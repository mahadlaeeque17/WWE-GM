"""Vercel entrypoint — serves the FastAPI app as a Python function.

Vercel routes /api/* here (see vercel.json). The container's filesystem is
read-only apart from /tmp and is thrown away between invocations, so the project
needs two env vars — `GM2000_STORE=blob` (set in the dashboard) and
`GM2000_DATA_DIR` (defaulted below). `/api/store/status` reports whether the
save is actually durable.

Two things here exist specifically because this is serverless:

WHAT `app` IS. It is the FastAPI instance itself, not a wrapper. The runtime
inspects this attribute to decide how to drive it, and handing it a bare async
function is a good way to get an opaque FUNCTION_INVOCATION_FAILED. The path
fix-up is therefore installed as middleware on the real app instead.

WHY THE PATH NEEDS FIXING. Serving one ASGI app behind one function needs a
rewrite, and a rewrite can replace the path: FastAPI must see `/api/health`, but
after `/api/(.*) -> /api/index` it may be handed `/api/index` and would 404
every route. Vercel's build log warns about exactly this ("Internal rewrites in
backend framework projects now route requests using the rewritten destination
path"). The rewrite carries the real path in `__p`, which survives either
behaviour, and the middleware restores it before routing. With no `__p` the
request passes through untouched, so local runs are unaffected.
"""

import os
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent.parent

# The backend imports its siblings by bare name (`import game`), and the harvest
# helpers live in their own folder, so both have to be importable.
for _p in (ROOT / "backend", ROOT / "harvester"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Only /tmp is writable here. Set it before importing the app: paths.py reads
# this at import time to decide where the database lives.
os.environ.setdefault("GM2000_DATA_DIR", "/tmp/gm2000")

PATH_PARAM = "__p"

try:
    from main import app

    @app.middleware("http")
    async def _restore_path(request, call_next):
        """Undo the rewrite before routing sees the request."""
        raw = request.scope.get("query_string") or b""
        if PATH_PARAM.encode() in raw:
            original, kept = None, []
            for k, v in parse_qsl(raw.decode("latin-1"), keep_blank_values=True):
                if k == PATH_PARAM and original is None:
                    original = v
                else:
                    kept.append((k, v))
            if original:
                if not original.startswith("/"):
                    original = "/" + original
                # Mutated in place: `call_next` passes this same scope down to
                # the router, so the corrected path is what gets matched.
                request.scope["path"] = original
                request.scope["raw_path"] = original.encode("latin-1")
                request.scope["query_string"] = urlencode(kept).encode("latin-1")
        return await call_next(request)

except Exception:  # noqa: BLE001
    # An import-time failure on a serverless host is otherwise invisible — the
    # platform reports FUNCTION_INVOCATION_FAILED and nothing else. Serve the
    # traceback instead so the next deploy can be diagnosed from the browser.
    _TB = traceback.format_exc()
    print(_TB, flush=True)

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/{full_path:path}")
    @app.post("/{full_path:path}")
    async def _boot_error(full_path: str = ""):
        return JSONResponse(
            status_code=500,
            content={"error": "the API failed to import",
                     "traceback": _TB.splitlines(),
                     "sys_path": sys.path,
                     "cwd": os.getcwd(),
                     "root_listing": sorted(p.name for p in ROOT.iterdir())
                     if ROOT.exists() else []},
        )
