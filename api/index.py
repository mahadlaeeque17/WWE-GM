"""Vercel entrypoint — serves the FastAPI app as a Python function.

Vercel routes every /api/* request here (see vercel.json). The function's
filesystem is read-only apart from /tmp and is thrown away between invocations,
so two things have to be true and both are handled by env vars set on the
project, not by code changes:

    GM2000_DATA_DIR=/tmp/gm2000     the only writable place
    GM2000_STORE=blob               so the save survives the container

Without GM2000_STORE the app still runs, but every deploy — and every cold
start — begins again from the bundled roster. `/api/store/status` says which
of those two worlds you are in.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The backend imports its siblings by bare name (`import game`), and the harvest
# helpers live in their own folder, so both have to be importable.
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "harvester"))

# Only /tmp is writable here. Set it before importing the app: paths.py reads
# this at import time to decide where the database lives.
os.environ.setdefault("GM2000_DATA_DIR", "/tmp/gm2000")

from main import app  # noqa: E402,F401

# Vercel's Python runtime looks for `app` (ASGI) at module level.
