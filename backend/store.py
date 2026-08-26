"""Durable storage for the save on a host that has no disk.

THE PROBLEM. Free hosting is stateless. Render's free tier, Vercel's Python
runtime and everything else that costs nothing give you a container whose
filesystem is thrown away — on every restart, on every deploy, and on Vercel
between individual requests. This game *is* a SQLite file that is written on
every draft pick, contract, show and title change, so on a free host that file
disappears and the save with it. Paying for a mounted disk solves it; this
module solves it without paying.

THE APPROACH. Keep SQLite. At boot, pull the whole database down into a local
file and let the app talk to it exactly as it always has — full local speed,
real transactions, and **not one line of SQL anywhere in the app changes**.
After any request that wrote something, push the file back up.

That last point is why this design was chosen over swapping the driver for a
hosted SQLite service. A driver swap touches every query in game.py, sim.py,
rankings.py and main.py, and the Python client for it ships as a compiled
extension with no wheel for this machine's interpreter — meaning the port could
not have been tested here at all. This module is ~150 lines, is exercised
end-to-end by the test suite, and leaves the 3,000 lines of working SQL alone.

THE TRADE-OFF, stated plainly: the whole database moves on every write. That is
fine at this size (the save is well under a megabyte) and for one player, which
is what this game is. It would be the wrong design for a multi-user app, where
two writers could overwrite each other.

BACKENDS
    disk   (default) the database file is already durable — local dev, or any
           host with a real mounted disk. Nothing is copied; this is a no-op.
    dir    the "remote" is another directory. Exists so the whole hydrate /
           persist lifecycle can be tested without a cloud account.
    blob   Vercel Blob over HTTPS. Free on a Hobby plan.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import httpx

# ------------------------------------------------------------- CREDENTIALS
#
# THERE ARE TWO WAYS TO AUTHENTICATE, and a modern store only offers the second.
#
#   read-write token   a long-lived `vercel_blob_rw_...` string in the
#                      environment. What every tutorial shows. Vercel calls it
#                      `BLOB_READ_WRITE_TOKEN` for a default-named store, and
#                      `WWEGM_READ_WRITE_TOKEN` for one named WWEGM.
#
#   OIDC               what a store connected through the dashboard uses NOW.
#                      Vercel injects only `WWEGM_STORE_ID` and a
#                      `WWEGM_WEBHOOK_PUBLIC_KEY`, and authenticates each request
#                      with a SHORT-LIVED OIDC token. There is no read-write
#                      token in the environment at all.
#
# This is what "I connected the blob and redeployed and it still does not save"
# turned out to be: the store was connected correctly, and the app was looking
# for a credential the platform had stopped issuing.
#
# TWO CONSEQUENCES WORTH SPELLING OUT.
#
# 1. The OIDC token arrives PER REQUEST, in the `x-vercel-oidc-token` header —
#    `VERCEL_OIDC_TOKEN` in the environment is the local-dev fallback. So the
#    credential cannot be read once at import: a token captured at cold start
#    expires while the container is still alive, and the save would start
#    failing part-way through a session. `main.py` feeds each request's header
#    to `use_request_token`, and everything here resolves credentials lazily.
#
# 2. Under OIDC the store id CANNOT be parsed out of the token — it comes from
#    the environment instead, which is why `*_STORE_ID` is discovered the same
#    forgiving way the token name is.
TOKEN_SUFFIX = "_READ_WRITE_TOKEN"
TOKEN_PREFIX = "vercel_blob_rw_"
STORE_ID_SUFFIX = "_STORE_ID"

# The current request's OIDC token. Set by the middleware, read by the next
# outbound blob call — never cached beyond the request that supplied it.
_request_oidc: str = ""


def use_request_token(token: str | None) -> None:
    """Hand this request's `x-vercel-oidc-token` to the store layer."""
    global _request_oidc
    _request_oidc = (token or "").strip()


def _find_rw_token() -> tuple[str, str]:
    """A long-lived read-write token, and which variable held it."""
    explicit = os.environ.get("GM2000_BLOB_TOKEN_VAR", "").strip()
    if explicit:
        return os.environ.get(explicit, ""), explicit
    if os.environ.get("BLOB_READ_WRITE_TOKEN"):
        return os.environ["BLOB_READ_WRITE_TOKEN"], "BLOB_READ_WRITE_TOKEN"
    # Sorted so the choice is deterministic when a project has two stores linked.
    for name in sorted(os.environ):
        if name.endswith(TOKEN_SUFFIX) and os.environ[name].startswith(TOKEN_PREFIX):
            return os.environ[name], name
    return "", ""


def _find_store_id() -> tuple[str, str]:
    """The store id from the environment, and which variable held it.

    Vercel writes it as `store_xxxxx`; the API wants it bare, so the prefix is
    stripped exactly as the official client does.
    """
    def clean(v: str) -> str:
        v = v.strip()
        return v[len("store_"):] if v.startswith("store_") else v

    explicit = os.environ.get("GM2000_BLOB_STORE_ID", "").strip()
    if explicit:
        return clean(explicit), "GM2000_BLOB_STORE_ID"
    if os.environ.get("BLOB_STORE_ID"):
        return clean(os.environ["BLOB_STORE_ID"]), "BLOB_STORE_ID"
    for name in sorted(os.environ):
        if name.endswith(STORE_ID_SUFFIX) and os.environ[name].strip():
            return clean(os.environ[name]), name
    return "", ""


def _oidc_token() -> str:
    """This request's OIDC token, else the environment's (local dev)."""
    return _request_oidc or os.environ.get("VERCEL_OIDC_TOKEN", "").strip()


def credentials() -> dict:
    """How this process can talk to the store, resolved fresh every time.

    Returns `kind` of "rw", "oidc" or "" — and the store id, which both paths
    need as a header.
    """
    rw, rw_var = _find_rw_token()
    env_id, id_var = _find_store_id()
    if rw:
        # vercel_blob_rw_<storeId>_<secret> — the id is the fourth field.
        parts = rw.split("_")
        parsed = parts[3] if len(parts) > 4 else ""
        return {"kind": "rw", "token": rw, "token_var": rw_var,
                "store_id": parsed or env_id, "store_id_var": id_var}
    oidc = _oidc_token()
    if oidc and env_id:
        return {"kind": "oidc", "token": oidc,
                "token_var": "x-vercel-oidc-token" if _request_oidc else "VERCEL_OIDC_TOKEN",
                "store_id": env_id, "store_id_var": id_var}
    return {"kind": "", "token": "", "token_var": "",
            "store_id": env_id, "store_id_var": id_var}


# Whether a blob credential is POSSIBLE, decided at import because it selects the
# backend. A read-write token is proof on its own; for OIDC the store id is the
# stable signal — the token itself only shows up once a request is in flight, so
# waiting for one would leave the app on the throwaway filesystem for the whole
# of the first request.
_RW_TOKEN, _RW_VAR = _find_rw_token()
_STORE_ID, _STORE_ID_VAR = _find_store_id()
BLOB_TOKEN = _RW_TOKEN
BLOB_TOKEN_VAR = _RW_VAR or (_STORE_ID_VAR if _STORE_ID else "")
BLOB_CREDENTIAL_POSSIBLE = bool(_RW_TOKEN or _STORE_ID)

# If a Blob store is linked, USE IT — do not also demand GM2000_STORE=blob.
#
# Requiring both meant the common half-configured state (store created and
# linked, second variable forgotten) ran silently on the throwaway filesystem:
# the game worked perfectly for one session and lost everything on the next cold
# start, with nothing on screen to say so. A token that is present is intent
# enough. Setting GM2000_STORE explicitly still wins, so `disk` remains a way to
# opt out on a host that has a real volume.
MODE = (os.environ.get("GM2000_STORE")
        or ("blob" if BLOB_CREDENTIAL_POSSIBLE else "disk")).strip().lower()
BLOB_KEY = os.environ.get("GM2000_BLOB_KEY", "gm2000.db")
# Overridable for the same reason the real client allows VERCEL_BLOB_API_URL:
# it lets the request SHAPE be asserted against a local stub, which is how the
# pathname-in-the-query bug is now caught without a token or a deploy.
BLOB_API = os.environ.get("GM2000_BLOB_API", "https://blob.vercel-storage.com")
# 12 is what @vercel/blob 2.8.0 sends. It matters: private stores did not exist
# when v7 was current, so asking for private access on v7 is a contradiction the
# server resolves by ignoring the request. Overridable without a code change, so
# a future bump can be corrected from the dashboard.
BLOB_API_VERSION = os.environ.get("GM2000_BLOB_API_VERSION", "12")

# Where `dir` mode keeps its copy.
REMOTE_DIR = os.environ.get("GM2000_REMOTE_DIR", "")

TIMEOUT = 30.0

# Vercel sets VERCEL=1 in every function. It is the difference between "mode is
# disk and that is correct" (a laptop, a real volume) and "mode is disk and the
# save is being written to a filesystem that is about to be deleted".
EPHEMERAL_HOST = bool(os.environ.get("VERCEL") or os.environ.get("GM2000_EPHEMERAL"))

_last: dict[str, object] = {"hydrated": None, "persisted": None, "error": None}


def _copy_writable(src: Path, dst: Path) -> None:
    """Copy the seed, then make sure the copy can actually be written to.

    NOT `shutil.copy2`. copy2 preserves the source's permission bits, and the
    bundled `data/gm2000.db` sits inside a deployment bundle that the host mounts
    READ-ONLY. Copying it faithfully produces a read-only save in /tmp, and every
    write then dies with "attempt to write a readonly database" — a failure that
    only appears once deployed, because the file is writable in a git checkout.
    """
    if dst.exists():
        # A previous copy could itself be read-only, and copyfile opens the
        # destination for writing — so clear it before overwriting.
        dst.chmod(0o644)
    shutil.copyfile(src, dst)
    dst.chmod(0o644)


def enabled() -> bool:
    """False means the database file is already durable and we stay out of it."""
    return MODE in ("dir", "blob")


def durable() -> tuple[bool, str]:
    """Will the save actually survive? The single question worth answering.

    `mode: disk` is the right answer on a laptop and a catastrophic one on a
    serverless host, so the mode alone cannot be reported as healthy — this is
    what the UI warns on.
    """
    ok, detail = _configured()
    if enabled():
        return ok, detail
    if EPHEMERAL_HOST:
        # Phrased as the next action, not as a restatement of the problem — the
        # banner already says what is wrong, and adding the token WITHOUT
        # redeploying is the step everyone misses, because env vars only reach
        # a function on its next build.
        return False, ("Link a Blob store to this project, then redeploy — "
                       "environment variables only reach the app on a new build.")
    return True, detail


def status() -> dict:
    ok, detail = _configured()
    dur, dur_detail = durable()
    return {
        "mode": MODE,
        "enabled": enabled(),
        "key": BLOB_KEY if MODE == "blob" else REMOTE_DIR,
        "configured": ok,
        "detail": detail,
        "durable": dur,
        "durable_detail": dur_detail,
        "ephemeral_host": EPHEMERAL_HOST,
        # The NAME of the variable the token came from, never the token. Which
        # variable was found is the single most useful thing when a correctly
        # created store still reports as missing.
        "auth": credentials()["kind"] or None,
        "token_var": credentials()["token_var"] or None,
        "store_id_var": _STORE_ID_VAR or None,
        "put_variant": put_variant(),
        **_last,
    }


def _configured() -> tuple[bool, str]:
    if MODE == "disk":
        return True, "local disk — the database file is already durable"
    if MODE == "dir":
        if not REMOTE_DIR:
            return False, "GM2000_REMOTE_DIR is not set"
        return True, f"directory {REMOTE_DIR}"
    if MODE == "blob":
        cred = credentials()
        if not cred["kind"]:
            if cred["store_id"]:
                # The store IS connected — this is the OIDC case with no token in
                # flight yet, which is normal outside a request.
                return True, (f"Vercel Blob key {BLOB_KEY} via OIDC "
                              f"(store id from {cred['store_id_var']})")
            return False, ("no blob credential — connect the Blob store to this "
                           "project, then redeploy. Looked for a "
                           "*_READ_WRITE_TOKEN, and for OIDC a *_STORE_ID plus "
                           "an x-vercel-oidc-token header")
        return True, (f"Vercel Blob key {BLOB_KEY} via {cred['kind']}"
                      f" ({cred['token_var']})")
    return False, f"unknown GM2000_STORE mode {MODE!r}"


# ---------------------------------------------------------------- dir backend

def _dir_path() -> Path:
    return Path(REMOTE_DIR) / BLOB_KEY


def _dir_get() -> bytes | None:
    p = _dir_path()
    return p.read_bytes() if p.exists() else None


def _dir_put(data: bytes) -> None:
    p = _dir_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target then move, so a crash mid-write cannot leave a
    # half-written save where a complete one used to be.
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(p)


# --------------------------------------------------------------- blob backend
#
# THE PROTOCOL, read out of the official @vercel/blob client (v2.8.0) rather
# than guessed. Every earlier attempt here failed on the same wrong assumption,
# so the shape is written down in full:
#
#   upload    PUT  https://blob.vercel-storage.com/?pathname=<urlencoded>
#   list      GET  https://blob.vercel-storage.com/?prefix=<p>&limit=<n>
#   download  GET  https://<storeId>.<access>.blob.vercel-storage.com/<pathname>
#
# The pathname goes in the QUERY STRING, not the path. That one detail was the
# whole bug. `PUT /gm2000.db` is an older route that never reads
# x-vercel-blob-access, so the server saw no access header at all, assumed
# public, and a private store refused it — reporting "cannot use public access
# on a private store" while the request had in fact asked for private. The
# message described the server's own default, not what was sent, which is why
# guessing header names could never fix it.
#
# Common headers on every API call:
#   authorization             Bearer <token>
#   x-api-version             12   (v7 predates private stores entirely)
#   x-vercel-blob-store-id    the store id, parsed out of the token
#
# Upload-only headers:
#   x-vercel-blob-access      private | public — must match the store
#   x-allow-overwrite         "1"; the save is rewritten at the same key forever
#   x-add-random-suffix       "0"; a suffix would orphan the previous save
#   x-content-type            application/octet-stream

from urllib.parse import quote

# Which access mode to TRY FIRST. The retry in _blob_put covers the other one, so
# this is only about not spending a guaranteed-failed request on every upload.
#
# PRIVATE, on evidence rather than on the badge. The dashboard labels this store
# "Public", so the default was set to public — and the live deploy then reported
# `put_variant: private`, meaning the public attempt was refused and the retry
# succeeded. Whatever that badge describes, it is not what the upload API accepts.
# One guaranteed-failed request per cold container is not free, and private is the
# better answer anyway: it is the only mode that supports the cache-busting read
# in _direct_url.
BLOB_ACCESS = os.environ.get("GM2000_BLOB_ACCESS", "private").strip().lower()

_good_variant: str | None = None


def _store_id() -> str:
    """The store id, which the API wants as its own header.

    From the read-write token where there is one (it is the fourth
    underscore-separated field of `vercel_blob_rw_<storeId>_<secret>`), and from
    the environment under OIDC, where the token carries no store id at all.
    """
    return credentials()["store_id"]


def _blob_headers() -> dict:
    cred = credentials()
    h = {"authorization": f"Bearer {cred['token']}", "x-api-version": BLOB_API_VERSION}
    # Required under OIDC — the store id is not in the token, so without this
    # header the API has no idea which store is being addressed.
    if cred["store_id"]:
        h["x-vercel-blob-store-id"] = cred["store_id"]
    return h


def _blob_raise(r: httpx.Response, what: str) -> None:
    """Fail with the RESPONSE BODY, not just the status line.

    Vercel Blob explains a rejection in the body — `{"error":{"code":...}}` —
    and httpx's raise_for_status throws that away. A bare "400 Bad Request" from
    a host you cannot attach a debugger to is close to useless. The token is
    never echoed back, so this is safe to surface on /api/store/status.
    """
    if r.status_code < 400:
        return
    body = ""
    try:
        body = " ".join(r.text[:400].split())
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(f"{what}: HTTP {r.status_code} — {body or '(empty body)'}")


def _direct_url(access: str) -> str | None:
    """The blob's own URL, built from the store id — no lookup needed.

    `https://<storeId>.<access>.blob.vercel-storage.com/<pathname>` is exactly
    what the client constructs, which means the list-then-fetch round trip this
    used to do on every cold boot was avoidable.

    `?cache=0` on a private store is not an optimisation, it is REQUIRED FOR
    CORRECTNESS. Blob reads are CDN-cached and this one key is overwritten after
    every single write, so a cached response means booting into a save that is
    minutes or hours stale and then persisting it back over the good one. Only
    private stores accept the parameter, which is the strongest reason to keep
    the store private rather than public.
    """
    sid = _store_id()
    if not sid:
        return None
    url = f"https://{sid}.{access}.blob.vercel-storage.com/{quote(BLOB_KEY)}"
    return f"{url}?cache=0" if access == "private" else url


def _blob_listing() -> dict | None:
    """Ask the store about the save: its url, and when it was last written.

    This is an API call, not a CDN read, so what it says is always current —
    which is what makes it usable as the freshness source for a public store.
    """
    r = httpx.get(BLOB_API, headers=_blob_headers(), timeout=TIMEOUT,
                  params={"prefix": BLOB_KEY, "limit": "1"})
    _blob_raise(r, "list")
    blobs = r.json().get("blobs") or []
    match = next((b for b in blobs if b.get("pathname") == BLOB_KEY), None)
    return match or (blobs[0] if blobs else None)


def _blob_url() -> str | None:
    """Fallback lookup: ask the store what the save's URL is.

    Only reached if the token could not be parsed for a store id, which should
    not happen — but a listing failure carries a readable error, whereas a bad
    guess at a hostname just times out.
    """
    match = _blob_listing()
    if not match:
        return None
    return match.get("downloadUrl") or match.get("url")


def _public_fresh_url() -> str | None:
    """A public blob URL that CANNOT serve a stale copy.

    THE PROBLEM WITH A PUBLIC STORE, and the reason this function is not
    optional. Public blobs are served through the CDN with a long cache lifetime,
    and `?cache=0` — the private-store escape hatch — is rejected on public ones.
    This app overwrites ONE key after every single write, so a cached read means a
    cold boot hydrates an old save and the next write pushes it back over the
    newer one. Silent, permanent, and it looks like the game forgetting a session
    at random rather than like a caching bug.

    So the freshness comes from the API instead: `list` reports `uploadedAt`,
    which changes on every upload, and hanging it on the URL as a query parameter
    makes each version a distinct cache entry. It costs one extra request per cold
    boot, which is the correct trade against losing a save.

    A private store needs none of this and keeps the direct, no-round-trip path.
    """
    match = _blob_listing()
    if not match:
        return None
    url = match.get("url") or match.get("downloadUrl")
    if not url:
        return None
    stamp = match.get("uploadedAt") or match.get("etag") or match.get("size")
    if stamp is None:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={quote(str(stamp), safe='')}"


def _blob_get() -> bytes | None:
    """Download the save, working with either a PRIVATE or a PUBLIC store.

    The store's access mode is picked in the dashboard and the app cannot read
    it, so both hostnames are tried — starting with whichever an upload has
    already been accepted under, if one has. A 404 from both means "no save in
    the store yet", which is a normal first boot rather than an error.
    """
    order = [_good_variant or BLOB_ACCESS]
    order.append("public" if order[0] == "private" else "private")

    last = None
    for access in order:
        # Private reads go direct and cache-busted. Public reads have to ask the
        # API when the save was last written, because there is no cache=0 for
        # them — see _public_fresh_url.
        url = _direct_url(access) if access == "private" else _public_fresh_url()
        if not url:
            continue
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                      headers={"authorization": f"Bearer {credentials()['token']}"})
        if r.status_code < 400:
            return r.content
        if r.status_code != 404:
            last = r

    url = _blob_url()
    if url:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                      headers={"authorization": f"Bearer {credentials()['token']}"})
        if r.status_code < 400:
            return r.content
        if r.status_code != 404:
            last = r

    if last is not None:
        _blob_raise(last, "download")
    return None


def _put_headers(access: str) -> dict:
    return {**_blob_headers(),
            "x-vercel-blob-access": access,
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-content-type": "application/octet-stream"}


def _blob_put(data: bytes) -> None:
    """Upload the save, matching the store's access mode.

    One request. The single retry exists because the store's access is chosen in
    the dashboard and the app cannot see it: if the store turns out to be the
    other kind, Vercel says so explicitly, so that one message — and nothing
    else — is worth a second attempt with the opposite value.
    """
    global _good_variant
    first = _good_variant or BLOB_ACCESS
    other = "public" if first == "private" else "private"
    url = f"{BLOB_API}/?pathname={quote(BLOB_KEY, safe='')}"

    for attempt, access in enumerate((first, other)):
        r = httpx.put(url, headers=_put_headers(access), content=data,
                      timeout=TIMEOUT)
        if r.status_code < 400:
            _good_variant = access
            return
        body = " ".join(r.text[:300].split())
        if attempt == 0 and "access" in body.lower():
            continue
        raise RuntimeError(f"upload rejected (access={access}): "
                           f"HTTP {r.status_code} {body or '(empty body)'}")


def put_variant() -> str | None:
    """Which access mode the store accepted, once an upload has worked."""
    return _good_variant


# ---------------------------------------------------------------- lifecycle

def _get() -> bytes | None:
    return _blob_get() if MODE == "blob" else _dir_get()


def _put(data: bytes) -> None:
    (_blob_put if MODE == "blob" else _dir_put)(data)


def hydrate(local: Path, seed: Path | None = None) -> str:
    """Bring the durable save down to `local` before anything opens it.

    If the remote has nothing yet — first ever boot — the bundled seed is
    uploaded so the remote becomes the source of truth from then on.
    """
    if not enabled():
        return "store disabled — using the local file directly"
    ok, why = _configured()
    if not ok:
        _last["error"] = why
        return f"store NOT configured: {why}"

    local.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        data = _get()
    except Exception as e:  # noqa: BLE001
        # Never take the service down over this — a readable error on
        # /api/store/status beats a container that will not boot.
        _last["error"] = f"hydrate failed: {e}"
        return _last["error"]

    if data:
        local.write_bytes(data)
        _last.update(hydrated=round(time.time() - t0, 2), error=None)
        return f"hydrated {len(data):,} bytes from {MODE} in {_last['hydrated']}s"

    src = seed if seed and seed.exists() else (local if local.exists() else None)
    if src is None:
        _last["error"] = "no save in the store and no seed to upload"
        return _last["error"]
    if src != local:
        _copy_writable(src, local)
    try:
        _put(local.read_bytes())
    except Exception as e:  # noqa: BLE001
        _last["error"] = f"seed upload failed: {e}"
        return _last["error"]
    _last.update(persisted=round(time.time() - t0, 2), error=None)
    return f"store was empty — seeded it from {src.name}"


def persist(local: Path) -> str:
    """Push the save back up. Called after a request that wrote something."""
    if not enabled():
        return "store disabled"
    ok, why = _configured()
    if not ok:
        return f"store NOT configured: {why}"
    if not local.exists():
        return "nothing to persist"
    t0 = time.time()
    try:
        _put(local.read_bytes())
    except Exception as e:  # noqa: BLE001
        _last["error"] = f"persist failed: {e}"
        return _last["error"]
    _last.update(persisted=round(time.time() - t0, 2), error=None)
    return f"persisted in {_last['persisted']}s"
