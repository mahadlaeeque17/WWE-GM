"""Dependency-free diagnostics for the deployed function. GET /api/diag

Uses ONLY the standard library and the plain `handler` interface, so it answers
even when the real app cannot start — which is exactly when it is needed. The
FastAPI entrypoint next door already reports its own import errors, but that
only works if FastAPI itself imported; if the dependency install did not happen,
that fallback dies with it and the platform shows nothing but
FUNCTION_INVOCATION_FAILED.

This file therefore imports nothing that is not built in, and answers four
questions that between them explain every failure seen so far:

  1. did pip install the requirements  (fastapi / pydantic / httpx present?)
  2. did includeFiles put backend/ and the seeded database in the bundle?
  3. is /tmp writable, and is the Blob token present?
  4. what does importing the app actually raise?

Vercel routes this by filesystem before rewrites are consulted, so it is
reachable at /api/diag without the /api/(.*) rewrite intercepting it.
"""

import importlib
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _probe_import(name):
    try:
        m = importlib.import_module(name)
        return {"ok": True, "version": getattr(m, "__version__", None),
                "file": getattr(m, "__file__", None)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _listing(p, limit=40):
    try:
        return sorted(x.name for x in p.iterdir())[:limit]
    except Exception as e:  # noqa: BLE001
        return f"unreadable: {type(e).__name__}: {e}"


def _tmp_writable():
    try:
        d = Path("/tmp/gm2000_diag")
        d.mkdir(parents=True, exist_ok=True)
        f = d / "probe"
        f.write_text("ok")
        got = f.read_text()
        f.unlink()
        return {"ok": got == "ok", "path": str(d)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _app_import():
    for p in (ROOT / "backend", ROOT / "harvester"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    os.environ.setdefault("GM2000_DATA_DIR", "/tmp/gm2000")
    try:
        import main  # noqa: F401
        return {"ok": True, "routes": len(getattr(main.app, "routes", []))}
    except Exception:  # noqa: BLE001
        return {"ok": False, "traceback": traceback.format_exc().splitlines()[-25:]}


def report():
    return {
        "python": sys.version,
        "cwd": os.getcwd(),
        "function_dir": str(Path(__file__).resolve().parent),
        "root": str(ROOT),
        "packages": {n: _probe_import(n)
                     for n in ("fastapi", "pydantic", "httpx", "dotenv", "starlette")},
        "bundle": {
            "root_listing": _listing(ROOT),
            "backend_present": (ROOT / "backend").is_dir(),
            "backend_listing": _listing(ROOT / "backend"),
            "harvester_present": (ROOT / "harvester").is_dir(),
            "seed_db_present": (ROOT / "data" / "gm2000.db").exists(),
            "seed_db_bytes": (ROOT / "data" / "gm2000.db").stat().st_size
            if (ROOT / "data" / "gm2000.db").exists() else 0,
        },
        "env": {
            "GM2000_STORE": os.environ.get("GM2000_STORE"),
            "GM2000_DATA_DIR": os.environ.get("GM2000_DATA_DIR"),
            "BLOB_TOKEN_SET": bool(os.environ.get("BLOB_READ_WRITE_TOKEN")),
            "GROQ_KEY_SET": bool(os.environ.get("GROQ_API_KEY")),
        },
        "tmp": _tmp_writable(),
        "app_import": _app_import(),
        "sys_path": sys.path,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        try:
            body = json.dumps(report(), indent=1, default=str).encode()
            code = 200
        except Exception:  # noqa: BLE001
            body = json.dumps({"diag_itself_failed":
                               traceback.format_exc().splitlines()}).encode()
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
