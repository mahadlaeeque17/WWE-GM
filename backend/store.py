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

MODE = (os.environ.get("GM2000_STORE") or "disk").strip().lower()

# Vercel injects BLOB_READ_WRITE_TOKEN when a Blob store is linked to the project.
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_KEY = os.environ.get("GM2000_BLOB_KEY", "gm2000.db")
BLOB_API = "https://blob.vercel-storage.com"
BLOB_API_VERSION = "7"

# Where `dir` mode keeps its copy.
REMOTE_DIR = os.environ.get("GM2000_REMOTE_DIR", "")

TIMEOUT = 30.0

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


def status() -> dict:
    return {
        "mode": MODE,
        "enabled": enabled(),
        "key": BLOB_KEY if MODE == "blob" else REMOTE_DIR,
        "configured": _configured()[0],
        "detail": _configured()[1],
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
        if not BLOB_TOKEN:
            return False, ("BLOB_READ_WRITE_TOKEN is not set — link a Blob store "
                           "to the Vercel project")
        return True, f"Vercel Blob key {BLOB_KEY}"
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

def _blob_headers() -> dict:
    return {"authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": BLOB_API_VERSION}


def _blob_url() -> str | None:
    """Find the save's URL by listing the store.

    The URL is not derivable from the key alone — Vercel prefixes it with the
    store id — and a fresh container has no memory of the last upload, so it has
    to be looked up rather than cached. `downloadUrl` is preferred where the API
    returns one, since that is the form a private store expects.
    """
    r = httpx.get(BLOB_API, headers=_blob_headers(), timeout=TIMEOUT,
                  params={"prefix": BLOB_KEY, "limit": "1"})
    r.raise_for_status()
    blobs = r.json().get("blobs") or []
    match = next((b for b in blobs if b.get("pathname") == BLOB_KEY), None)
    match = match or (blobs[0] if blobs else None)
    if not match:
        return None
    return match.get("downloadUrl") or match.get("url")


def _blob_get() -> bytes | None:
    """Download the save, working with either a PRIVATE or a PUBLIC store.

    A public blob is readable by plain GET; a private one requires the store
    token. Rather than making the deploy depend on the operator having picked
    the option this code happens to assume, try authenticated first and fall
    back — the token only ever goes to Vercel's own storage domain.
    """
    url = _blob_url()
    if not url:
        return None

    attempts = [_blob_headers(), {}] if _is_blob_host(url) else [{}]
    last = None
    for headers in attempts:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=headers)
        if r.status_code == 404:
            return None
        if r.status_code < 400:
            return r.content
        last = r
    if last is not None:
        last.raise_for_status()
    return None


def _is_blob_host(url: str) -> bool:
    """Only ever attach the token to Vercel's own storage domains."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("vercel-storage.com") or host.endswith("vercel.app")


def _blob_put(data: bytes) -> None:
    r = httpx.put(
        f"{BLOB_API}/{BLOB_KEY}",
        headers={
            **_blob_headers(),
            "x-content-type": "application/octet-stream",
            # Same key every time, and never cached — this is the live save, not
            # an asset. With a random suffix each write would orphan the last.
            "x-add-random-suffix": "0",
            "x-cache-control-max-age": "0",
        },
        content=data, timeout=TIMEOUT,
    )
    r.raise_for_status()


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
