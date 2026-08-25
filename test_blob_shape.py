"""Assert the SHAPE of every Vercel Blob request, with no token and no network.

WHY. The blob backend was wrong nine commits in a row, and every one of those
commits was "verified" by deploying it and reading an error banner. The failure
was never in the logic — it was in the URL: the pathname belongs in the query
string, and putting it in the path silently disabled the access header. A stub
server that records what was actually sent catches that in milliseconds.

Run:  python test_blob_shape.py

This talks to a throwaway HTTP server on localhost, so it needs no credentials
and touches nothing real. It is the fast half of the pair; `smoke_blob.py` is
the slow half that proves the real store accepts it.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

SEEN: list[dict] = []
PORT = 8733

FAKE_TOKEN = "vercel_blob_rw_STOREID123_secretsecretsecret"
STORE_ID = "STOREID123"


class Stub(BaseHTTPRequestHandler):
    """Records the request, then answers the way Vercel Blob does."""

    def log_message(self, *_a):  # silence the default stderr spam
        pass

    def _record(self, body: bytes = b"") -> dict:
        u = urlparse(self.path)
        rec = {"method": self.command, "path": u.path,
               "query": parse_qs(u.query),
               "headers": {k.lower(): v for k, v in self.headers.items()},
               "body": body}
        SEEN.append(rec)
        return rec

    def _json(self, payload: dict, code: int = 200) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._record()
        self._json({"blobs": [], "hasMore": False})

    def do_PUT(self):
        n = int(self.headers.get("content-length") or 0)
        self._record(self.rfile.read(n))
        self._json({"url": "https://x.blob.vercel-storage.com/gm2000.db",
                    "pathname": "gm2000.db"})


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"\n          {detail}" if not cond and detail else ""))
    return cond


def main() -> int:
    srv = HTTPServer(("127.0.0.1", PORT), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ["BLOB_READ_WRITE_TOKEN"] = FAKE_TOKEN
    os.environ["GM2000_STORE"] = "blob"
    os.environ["GM2000_BLOB_KEY"] = "gm2000.db"
    os.environ["GM2000_BLOB_API"] = f"http://127.0.0.1:{PORT}"
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from backend import store

    ok = True
    print("store id parsed from the token")
    ok &= check("id is the 4th underscore field", store._store_id() == STORE_ID,
                f"got {store._store_id()!r}, want {STORE_ID!r}")

    print("\nupload request")
    SEEN.clear()
    store._blob_put(b"hello-save")
    put = SEEN[-1]
    ok &= check("method is PUT", put["method"] == "PUT")
    # THE BUG. `/gm2000.db` is the legacy route that ignores the access header.
    ok &= check("pathname is in the QUERY, not the path",
                put["path"] == "/" and put["query"].get("pathname") == ["gm2000.db"],
                f"path={put['path']!r} query={put['query']!r}")
    h = put["headers"]
    ok &= check("x-api-version is 12", h.get("x-api-version") == "12",
                f"got {h.get('x-api-version')!r}")
    ok &= check("x-vercel-blob-access is private",
                h.get("x-vercel-blob-access") == "private",
                f"got {h.get('x-vercel-blob-access')!r}")
    ok &= check("x-vercel-blob-store-id is sent",
                h.get("x-vercel-blob-store-id") == STORE_ID,
                f"got {h.get('x-vercel-blob-store-id')!r}")
    ok &= check("x-allow-overwrite is 1 (the save reuses one key forever)",
                h.get("x-allow-overwrite") == "1")
    ok &= check("x-add-random-suffix is 0 (a suffix would orphan the save)",
                h.get("x-add-random-suffix") == "0")
    ok &= check("authorization carries the token",
                h.get("authorization") == f"Bearer {FAKE_TOKEN}")
    ok &= check("body is the bytes we passed", put["body"] == b"hello-save")

    print("\ndownload URL")
    priv = store._direct_url("private")
    pub = store._direct_url("public")
    ok &= check("private host is <storeId>.private.blob.vercel-storage.com",
                priv.startswith(f"https://{STORE_ID}.private.blob.vercel-storage.com/gm2000.db"),
                f"got {priv!r}")
    # Without cache=0 a cold boot can hydrate a CDN copy from an earlier write
    # and then persist it back over the newer save.
    ok &= check("private read is cache-busted", priv.endswith("?cache=0"),
                f"got {priv!r}")
    ok &= check("public host is <storeId>.public.blob.vercel-storage.com",
                pub == f"https://{STORE_ID}.public.blob.vercel-storage.com/gm2000.db",
                f"got {pub!r}")

    print("\nfallback list request")
    SEEN.clear()
    store._blob_url()
    lst = SEEN[-1]
    ok &= check("list is a GET with prefix + limit",
                lst["method"] == "GET"
                and lst["query"].get("prefix") == ["gm2000.db"]
                and lst["query"].get("limit") == ["1"],
                f"{lst['method']} {lst['query']}")
    ok &= check("list also carries the store id",
                lst["headers"].get("x-vercel-blob-store-id") == STORE_ID)

    srv.shutdown()
    print("\nPASS — every request matches @vercel/blob 2.8.0." if ok
          else "\nFAIL — see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
