"""Vercel entrypoint — serves the FastAPI app as a Python function.

Vercel routes every /api/* request here (see vercel.json). The function's
filesystem is read-only apart from /tmp and is thrown away between invocations,
so two things have to be true, both set as project env vars rather than in code:

    GM2000_DATA_DIR=/tmp/gm2000     the only writable place (defaulted below)
    GM2000_STORE=blob               so the save survives the container

Without GM2000_STORE the app still runs, but every deploy — and every cold
start — begins again from the bundled roster. `/api/store/status` says which of
those two worlds you are in.

ROUTING. Getting a whole ASGI app behind one function means a rewrite, and a
rewrite loses the path: FastAPI needs to see `/api/health`, but after
`/api/(.*) -> /api/index` the app can be handed `/api/index` instead and would
404 every route. Vercel's own build log warns that this behaviour changed:

    "Internal rewrites in backend framework projects now route requests using
     the rewritten destination path."

Rather than depend on which way that falls, the rewrite carries the original
path in a `__p` query parameter — which survives either behaviour — and the
shim below puts it back before FastAPI ever sees the request. If `__p` is
absent (running locally, or if Vercel preserved the path itself) the request is
passed through untouched.
"""

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent.parent

# The backend imports its siblings by bare name (`import game`), and the harvest
# helpers live in their own folder, so both have to be importable.
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "harvester"))

# Only /tmp is writable here. Set it before importing the app: paths.py reads
# this at import time to decide where the database lives.
os.environ.setdefault("GM2000_DATA_DIR", "/tmp/gm2000")

from main import app as _app  # noqa: E402

PATH_PARAM = "__p"


async def app(scope, receive, send):
    """Restore the original request path, then hand off to FastAPI."""
    if scope.get("type") == "http":
        raw = scope.get("query_string") or b""
        if PATH_PARAM.encode() in raw:
            params = parse_qsl(raw.decode("latin-1"), keep_blank_values=True)
            original = None
            kept = []
            for k, v in params:
                if k == PATH_PARAM and original is None:
                    original = v
                else:
                    kept.append((k, v))
            if original:
                # A rewrite can leave the trailing slash off the collapsed
                # match ("/api/" -> "/api"); normalise so routes still match.
                scope = {**scope,
                         "path": original if original.startswith("/") else "/" + original,
                         "raw_path": None,
                         "query_string": urlencode(kept).encode("latin-1")}
    await _app(scope, receive, send)
