"""Tiny localhost receiver for harvested JSON.

The harvest lives in browser memory on cagematch.net. Rather than shuttling ~95KB
through tool responses and retyping it, the page POSTs it straight here.

Chrome treats http://localhost as a trustworthy origin, so an https page is
allowed to POST to it without tripping mixed-content blocking. CORS still
applies, hence the explicit allow headers.

    python receiver.py <out.json> [port]
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("harvest.json")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8777


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        OUT.parent.mkdir(parents=True, exist_ok=True)
        # validate before writing so a truncated post cannot clobber good data
        parsed = json.loads(body.decode("utf-8"))
        OUT.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")

        n = len(parsed.get("wrestlers", []))
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "wrestlers": n, "bytes": len(body)}).encode())
        print(f"wrote {len(body)} bytes / {n} wrestlers -> {OUT}", flush=True)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"listening on http://localhost:{PORT} -> {OUT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
