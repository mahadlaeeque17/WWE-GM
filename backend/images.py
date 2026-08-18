"""Wrestler images, one per year of career.

Two sources, same index:

  LOCAL  drop files into  data/images/<wrestler_id>/<year>.<ext>
         or               data/images/inbox/  using  <name> <year>.<ext>
  DRIVE  a Google Drive folder, mirrored down into the same local layout

Local works with no setup. Drive needs credentials — see DRIVE_SETUP below;
an API key alone will NOT work for Drive, which is a lesson already learned on
the AI Recruiter build.

Filenames are matched leniently because you will be dropping files in by hand:

    356.2000.jpg          explicit wrestler id and year
    Trish Stratus 2000.jpg
    trish-stratus_2000.png
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

IMAGES_ROOT = Path(__file__).resolve().parent.parent / "data" / "images"
INBOX = IMAGES_ROOT / "inbox"
VALID_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Optional user-supplied logo/belt art. Drop files here named by KEY (e.g.
# raw.png, world.svg, wrestlemania.png) to override the built-in SVG emblems.
# The app never ships or downloads copyrighted brand art — this is a slot for
# you to add your own if you want it.
LOGOS_ROOT = Path(__file__).resolve().parent.parent / "data" / "logos"
LOGO_EXT = [".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif"]


def _slug(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def logo_keys() -> list[str]:
    """Keys (filename stems, slugified) with a user-supplied logo present."""
    if not LOGOS_ROOT.exists():
        return []
    keys = []
    for p in LOGOS_ROOT.iterdir():
        if p.is_file() and p.suffix.lower() in LOGO_EXT:
            keys.append(_slug(p.stem))
    return sorted(set(keys))


def logo_path(key: str) -> Path | None:
    key = _slug(key)
    if not LOGOS_ROOT.exists():
        return None
    for p in LOGOS_ROOT.iterdir():
        if p.is_file() and p.suffix.lower() in LOGO_EXT and _slug(p.stem) == key:
            return p
    return None

DRIVE_SETUP = """\
Run this once, from the backend folder:

    python oauth_setup.py

It opens a browser, you click Allow, and a refresh token is cached to
backend/drive_token.json. It reuses the OAuth Desktop client already created for
the NBA Alternate Universe app, so there is no Google Cloud console work.

WHY NOT A SERVICE ACCOUNT: this account has an org policy
(iam.disableServiceAccountKeyCreation) blocking service-account JSON keys, and
even with that overridden a Google-managed KeyExposureResponse policy re-blocks
it. There is no user-facing way around either. OAuth Desktop clients are not
subject to those restrictions.

An API key is not an option either — it can only read PUBLIC files, and this
folder is not link-shared.

Requires: pip install google-api-python-client google-auth google-auth-oauthlib
"""

API_KEY_FILE = "drive_api_key.txt"

# Mahad's wrestler-image folder. Overridable via GM2000_DRIVE_FOLDER_ID or the
# folder box on the Images tab.
DEFAULT_FOLDER_ID = "1zGgyubKfJZ0QBtQABvH3l7E9XZIlD5Wl"


def slugify(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def build_name_index(con: sqlite3.Connection) -> dict[str, int]:
    """Every ring name maps to its wrestler, so `Miss Congeniality 1999.jpg`
    files correctly against Lita."""
    idx: dict[str, int] = {}
    for wid, nm in con.execute("SELECT wrestler_id, name FROM ring_name"):
        idx.setdefault(slugify(nm), wid)
    for wid, nm in con.execute("SELECT id, name FROM wrestler"):
        idx[slugify(nm)] = wid
    return idx


def parse_filename(stem: str, name_index: dict[str, int]) -> tuple[int | None, int | None]:
    """Pull (wrestler_id, year) out of a filename. Returns (None, None) if unsure."""
    # Photos can predate the 1980-2000 game window — Moolah debuted in the 1950s
    # and her Commons portrait is from 1970. A narrower range silently drops the
    # year and the file gets reported as unidentifiable rather than filed.
    years = re.findall(r"(19[3-9]\d|20[0-4]\d)", stem)
    year = int(years[-1]) if years else None

    m = re.match(r"^(\d{1,6})[._\-\s]", stem)
    if m:
        wid = int(m.group(1))
        return wid, year

    residue = stem
    if year:
        residue = residue.replace(str(year), " ")
    key = slugify(residue)
    if key in name_index:
        return name_index[key], year

    for k, wid in name_index.items():
        if k and (k in key or key in k) and len(k) >= 5:
            return wid, year
    return None, year


# A portrait with no year in its filename is filed under year 0, meaning
# "default" — used whenever there is no year-specific shot. This lets you drop
# `Trish Stratus.jpg` in and have it work; per-year images can come later and
# will take precedence automatically.
DEFAULT_YEAR = 0


def _safe(name: str) -> str:
    """Filesystem-safe but still recognisable — keeps the name you uploaded."""
    return re.sub(r"[^\w\s.\-'&()]", "_", name).strip()


def record_image(con: sqlite3.Connection, wid: int, filename: str, year: int | None,
                 source: str, original: str | None = None,
                 drive_file_id: str | None = None) -> None:
    """Index one image. The FIRST image a wrestler gets becomes her profile."""
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """INSERT INTO wrestler_image
             (wrestler_id, year, filename, original_name, drive_file_id, source, synced_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(wrestler_id, filename) DO UPDATE SET
             year=excluded.year, drive_file_id=excluded.drive_file_id,
             source=excluded.source, synced_at=excluded.synced_at""",
        (wid, year, filename, original or filename, drive_file_id, source, now),
    )
    has_profile = con.execute(
        "SELECT 1 FROM wrestler_image WHERE wrestler_id=? AND is_profile=1", (wid,)
    ).fetchone()
    if not has_profile:
        con.execute(
            "UPDATE wrestler_image SET is_profile=1 WHERE wrestler_id=? AND filename=?",
            (wid, filename),
        )


def index_local(con: sqlite3.Connection) -> dict:
    """Scan the images tree and record everything found.

    Files keep their ORIGINAL name under data/images/<wrestler_id>/. The old
    scheme renamed them to "<year>.jpg", which meant a second photo of the same
    wrestler from the same year silently overwrote the first — fine for one
    portrait, fatal for a gallery.
    """
    IMAGES_ROOT.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    name_index = build_name_index(con)

    filed, skipped = [], []

    for path in sorted(INBOX.iterdir()):
        if not path.is_file() or path.suffix.lower() not in VALID_EXT:
            continue
        wid, year = parse_filename(path.stem, name_index)
        if wid is None:
            skipped.append({"file": path.name, "why": "could not tell which wrestler"})
            continue
        dest_dir = IMAGES_ROOT / str(wid)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / _safe(path.name)
        if dest.exists():
            dest = dest_dir / f"{dest.stem}_{int(path.stat().st_size) % 9973}{dest.suffix}"
        shutil.move(str(path), str(dest))
        filed.append({"file": path.name, "wrestler_id": wid, "year": year})

    indexed, deduped = 0, []
    for wdir in sorted(IMAGES_ROOT.iterdir()):
        if not wdir.is_dir() or not wdir.name.isdigit():
            continue
        wid = int(wdir.name)

        # Dedupe by CONTENT, not filename. The same photo can arrive twice under
        # different names — an upload repeated to Drive, or a leftover from the
        # old "<year>.jpg" scheme sitting next to its renamed twin. Keeping both
        # puts the identical image in the gallery twice.
        seen: dict[str, Path] = {}
        for img in sorted(wdir.iterdir()):
            if img.suffix.lower() not in VALID_EXT:
                continue
            digest = hashlib.md5(img.read_bytes()).hexdigest()
            if digest in seen:
                # Keep whichever name is more descriptive — the longer one.
                keep, drop = (seen[digest], img) if len(seen[digest].name) >= len(img.name) else (img, seen[digest])
                seen[digest] = keep
                con.execute("DELETE FROM wrestler_image WHERE wrestler_id=? AND filename=?",
                            (wid, drop.name))
                drop.unlink(missing_ok=True)
                deduped.append({"wrestler_id": wid, "dropped": drop.name, "kept": keep.name})
                continue
            seen[digest] = img

        for img in seen.values():
            _, year = parse_filename(img.stem, name_index)
            record_image(con, wid, img.name, year, "local")
            indexed += 1

    # A wrestler can lose her profile image to dedupe; make sure one is always set.
    for (wid,) in con.execute(
        """SELECT DISTINCT wrestler_id FROM wrestler_image
           WHERE wrestler_id NOT IN (SELECT wrestler_id FROM wrestler_image WHERE is_profile=1)"""):
        nxt = con.execute("SELECT id FROM wrestler_image WHERE wrestler_id=? LIMIT 1", (wid,)).fetchone()
        if nxt:
            con.execute("UPDATE wrestler_image SET is_profile=1 WHERE id=?", (nxt[0],))

    con.commit()
    return {"indexed": indexed, "filed_from_inbox": filed,
            "duplicates_removed": deduped, "needs_attention": skipped}


# ------------------------------------------------------------------ drive

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def drive_available() -> tuple[bool, str]:
    try:
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError:
        return False, "google-api-python-client is not installed"

    here = Path(__file__).resolve().parent
    if (here / "drive_token.json").exists():
        return True, "oauth (authorised)"
    if (here / "drive_service_account.json").exists():
        return True, "service account"
    if (here / API_KEY_FILE).exists():
        return True, "api key (folder must be link-shared)"
    return False, "not authorised yet — run: python backend/oauth_setup.py"


def drive_client():
    """Build a Drive client from whichever credential exists.

    OAuth first: service-account keys are blocked by org policy on this account,
    so the cached OAuth token is the working path. The server NEVER launches a
    consent flow itself — that would hang a web request waiting on a browser.
    Authorising is an explicit, separate step (oauth_setup.py).
    """
    from googleapiclient.discovery import build

    here = Path(__file__).resolve().parent

    token = here / "drive_token.json"
    if token.exists():
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RuntimeError(
                    "Drive token is no longer valid — re-run: python backend/oauth_setup.py"
                )
        return build("drive", "v3", credentials=creds)

    sa = here / "drive_service_account.json"
    if sa.exists():
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(str(sa), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)

    key_file = here / API_KEY_FILE
    if key_file.exists():
        return build("drive", "v3", developerKey=key_file.read_text(encoding="utf-8").strip())

    raise RuntimeError(DRIVE_SETUP)


def sync_drive(con: sqlite3.Connection, folder_id: str | None = None) -> dict:
    """Mirror a Drive folder into the local tree, then index it.

    Only pulls files it does not already have, so repeat syncs are cheap.
    """
    folder_id = folder_id or os.environ.get("GM2000_DRIVE_FOLDER_ID") or DEFAULT_FOLDER_ID
    if not folder_id:
        return {"ok": False, "reason": "GM2000_DRIVE_FOLDER_ID is not set", "setup": DRIVE_SETUP}

    ok, why = drive_available()
    if not ok:
        return {"ok": False, "reason": why, "setup": DRIVE_SETUP}

    from googleapiclient.http import MediaIoBaseDownload

    service = drive_client()
    name_index = build_name_index(con)
    INBOX.mkdir(parents=True, exist_ok=True)

    known = {r[0] for r in con.execute(
        "SELECT drive_file_id FROM wrestler_image WHERE drive_file_id IS NOT NULL")}

    pulled, skipped, page = [], [], None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=200, pageToken=page,
        ).execute()

        for f in resp.get("files", []):
            if f["id"] in known or not f["mimeType"].startswith("image/"):
                continue
            stem = Path(f["name"]).stem
            wid, year = parse_filename(stem, name_index)
            if wid is None:
                skipped.append({"file": f["name"], "why": "could not tell which wrestler"})
                continue
            if year is None:
                year = DEFAULT_YEAR

            dest_dir = IMAGES_ROOT / str(wid)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / _safe(f["name"])

            with open(dest, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, service.files().get_media(fileId=f["id"]))
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            record_image(con, wid, dest.name, year, "drive",
                         original=f["name"], drive_file_id=f["id"])
            pulled.append({"file": f["name"], "wrestler_id": wid, "year": year})

        page = resp.get("nextPageToken")
        if not page:
            break

    con.commit()
    return {"ok": True, "pulled": len(pulled), "files": pulled, "needs_attention": skipped}
