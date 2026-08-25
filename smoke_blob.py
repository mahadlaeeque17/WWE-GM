"""Prove the Vercel Blob backend works — against the real store, from here.

WHY THIS EXISTS. Every previous fix to the blob backend was verified by pushing
a commit and reading a banner in the deployed app. That loop is slow, it burns a
deploy per guess, and it tells you only that something failed, not which request
was wrong. Nine commits went that way. This script closes the loop locally: one
command, real HTTPS, real store, full round trip.

    # PowerShell
    $env:BLOB_READ_WRITE_TOKEN = "vercel_blob_rw_..."
    python smoke_blob.py

    # bash
    BLOB_READ_WRITE_TOKEN="vercel_blob_rw_..." python smoke_blob.py

The token is read from the environment only — it is never written to a file and
never printed. Get it from the Vercel dashboard under Storage -> your Blob store
-> the `.env.local` snippet, or with `vercel env pull`.

WHAT IT CHECKS, in order, stopping at the first failure:

    1. the token parses into a store id
    2. list   — the store answers at all, and the credentials are good
    3. upload — a throwaway key, which is where the 400 was
    4. download — and the bytes come back byte-identical
    5. re-upload to the SAME key — proves x-allow-overwrite, the case that
       matters, because the real save is rewritten after every single request
    6. delete the throwaway key, so the store is left as it was found

It writes to `gm2000.smoketest` and NEVER to the real save key, so it is safe to
run against the live store while a game is in progress.
"""
from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

TEST_KEY = "gm2000.smoketest"
PAYLOAD = b"SQLite format 3\x00" + bytes(range(256)) * 8   # ~2KB, binary-safe


def main() -> int:
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        print("BLOB_READ_WRITE_TOKEN is not set.\n"
              "  PowerShell: $env:BLOB_READ_WRITE_TOKEN = \"vercel_blob_rw_...\"\n"
              "  bash:       export BLOB_READ_WRITE_TOKEN=vercel_blob_rw_...")
        return 2

    # Point the module at the throwaway key BEFORE importing it — the key is read
    # at import time, and the real save must not be touched.
    os.environ["GM2000_BLOB_KEY"] = TEST_KEY
    os.environ["GM2000_STORE"] = "blob"
    from backend import store

    def step(n: str) -> None:
        print(f"  {n} ... ", end="", flush=True)

    print(f"store mode {store.MODE}, key {store.BLOB_KEY}, "
          f"api v{store.BLOB_API_VERSION}, access {store.BLOB_ACCESS}")

    step("token parses to a store id")
    sid = store._store_id()
    if not sid:
        print("FAIL — token is not in vercel_blob_rw_<storeId>_<secret> form")
        return 1
    print(f"ok ({len(sid)} chars)")

    step("list")
    try:
        store._blob_url()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL\n    {e}")
        return 1
    print("ok")

    step("upload")
    try:
        store._blob_put(PAYLOAD)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL\n    {e}")
        return 1
    print(f"ok (access={store.put_variant()})")

    step("download")
    try:
        got = store._blob_get()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL\n    {e}")
        return 1
    if got != PAYLOAD:
        n = 0 if got is None else len(got)
        print(f"FAIL — sent {len(PAYLOAD)} bytes, got back {n}")
        return 1
    print(f"ok ({len(got)} bytes, identical)")

    step("overwrite the same key")
    try:
        store._blob_put(PAYLOAD + b"second write")
        again = store._blob_get()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL\n    {e}")
        return 1
    if again != PAYLOAD + b"second write":
        print("FAIL — the second write did not come back; a cached or stale "
              "read here would silently roll the save back")
        return 1
    print("ok (fresh bytes, not a cached copy)")

    step("clean up")
    try:
        r = httpx.post(f"{store.BLOB_API}/delete",
                       headers={**store._blob_headers(),
                                "content-type": "application/json"},
                       json={"urls": [TEST_KEY]}, timeout=store.TIMEOUT)
        print("ok" if r.status_code < 400 else
              f"left {TEST_KEY} behind (HTTP {r.status_code}) — harmless")
    except Exception as e:  # noqa: BLE001
        print(f"left {TEST_KEY} behind ({e}) — harmless")

    print("\nPASS — the save will survive on this store.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
