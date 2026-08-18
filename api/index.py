"""Vercel entrypoint — serves the FastAPI app as a Python function.

Vercel routes /api/* here (see vercel.json). The container's filesystem is
read-only apart from /tmp and thrown away between invocations, so the project
needs `GM2000_STORE=blob` set in the dashboard; `/api/store/status` reports
whether the save is actually durable.

THREE THINGS HERE EXIST BECAUSE THIS IS SERVERLESS.

1. `app` MUST BE BOUND AT MODULE LEVEL. Vercel decides whether a .py file in
   api/ is a function by looking for a top-level `app` or `handler`. An earlier
   version put the import inside `try:`, so the only bindings were indented —
   the file stopped being a function at all and the build failed with:

       Error: The pattern "api/index.py" defined in `functions` doesn't match
       any Serverless Functions inside the `api` directory.

   Which reads like a path typo and is nothing of the sort. All the fallible
   work happens inside `_build()`; the module-level line is a plain assignment.

2. `app` IS THE FASTAPI INSTANCE, not a wrapper function. The runtime inspects
   it to decide how to drive it, and a bare async function is a good way to get
   an opaque FUNCTION_INVOCATION_FAILED.

3. THE PATH HAS TO BE PUT BACK. Serving one ASGI app behind one function needs a
   rewrite, and a rewrite can replace the path: FastAPI must see `/api/health`,
   but after `/api/(.*) -> /api/index` it may be handed `/api/index` and would
   404 everything. The rewrite carries the real path in `__p`, which survives
   either behaviour, and the middleware restores it before routing. With no
   `__p` the request passes through untouched, so local runs are unaffected.
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


def _attach_path_fix(fastapi_app):
    """Undo the rewrite before routing sees the request."""

    @fastapi_app.middleware("http")
    async def _restore_path(request, call_next):
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

    return fastapi_app


def _error_app(tb: str):
    """Serve the import failure instead of letting the platform swallow it."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    broken = FastAPI()

    @broken.get("/{full_path:path}")
    @broken.post("/{full_path:path}")
    async def _boot_error(full_path: str = ""):
        return JSONResponse(status_code=500, content={
            "error": "the API failed to import",
            "traceback": tb.splitlines(),
            "sys_path": sys.path,
            "root_listing": sorted(p.name for p in ROOT.iterdir()) if ROOT.exists() else [],
        })

    return broken


def _build():
    try:
        from main import app as real
        return _attach_path_fix(real)
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(tb, flush=True)
        return _error_app(tb)


# Module level, and deliberately the last statement in the file: this binding is
# what makes Vercel treat the file as a Serverless Function at all.
app = _build()
