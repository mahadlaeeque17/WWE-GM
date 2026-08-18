"""Where the game's state lives on disk.

Locally that is `data/` beside the code. On a host it has to be a MOUNTED DISK,
because everything the game owns is a file that gets written: the SQLite save on
every draft pick, contract, show and title change, and the portrait gallery on
every image sync. A container's own filesystem is wiped on each deploy, so state
kept there quietly disappears the first time the service restarts.

One env var moves the whole tree:

    GM2000_DATA_DIR=/var/data       # db + images + logos live here

`GM2000_DB` still overrides just the database file, which is what the test
harness uses to run against a throwaway save.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The copy that ships in the repo — the seeded 270-wrestler roster.
BUNDLED_DATA = ROOT / "data"
BUNDLED_DB = BUNDLED_DATA / "gm2000.db"

_dir = os.environ.get("GM2000_DATA_DIR")
DATA_DIR = Path(_dir) if _dir else BUNDLED_DATA

_db = os.environ.get("GM2000_DB")
DB_PATH = Path(_db) if _db else DATA_DIR / "gm2000.db"

IMAGES_ROOT = DATA_DIR / "images"
INBOX = IMAGES_ROOT / "inbox"
LOGOS_ROOT = DATA_DIR / "logos"

RELOCATED = DATA_DIR.resolve() != BUNDLED_DATA.resolve()


def seed_data_dir() -> str | None:
    """Put the bundled save on the mounted disk the first time it boots.

    A fresh disk is empty, and the API refuses to start without a database — so
    without this the first deploy comes up 503 and stays there. Copies ONCE:
    if a save already exists on the disk it is left completely alone, because
    that file is now the live game and the bundled one is just the seed.
    """
    if not RELOCATED:
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_ROOT.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    LOGOS_ROOT.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        return None
    if not BUNDLED_DB.exists():
        return None
    shutil.copy2(BUNDLED_DB, DB_PATH)
    return f"seeded {DB_PATH} from {BUNDLED_DB}"
