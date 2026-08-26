"""Prove a save survives a stateless host.

Simulates what free hosting actually does: run the API, destroy its entire
filesystem, run it again, and check the game is still there. `dir` mode stands
in for Vercel Blob so the lifecycle is testable without a cloud account — the
blob backend is the same two calls behind an HTTP adapter.
"""
import atexit
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HERE = ROOT / ".smoke"
HERE.mkdir(exist_ok=True)
EPHEMERAL = HERE / "_container"      # wiped to simulate a redeploy
REMOTE = HERE / "_remote"            # stands in for Vercel Blob
PORT = "8021"
BASE = f"http://127.0.0.1:{PORT}"

def wipe(d: Path):
    """Delete a directory even if it holds read-only files.

    `rmtree(ignore_errors=True)` silently leaves read-only files behind on
    Windows, which is worse than failing: the next run then reads a stale save
    and the test appears to pass for the wrong reason.
    """
    def force(func, path, _exc):
        os.chmod(path, 0o666)
        func(path)
    shutil.rmtree(d, onexc=force) if d.exists() else None


for _d in (EPHEMERAL, REMOTE):
    wipe(_d)


def refuse_a_busy_port() -> None:
    """Fail loudly if something already owns PORT.

    A leaked uvicorn from an earlier run answers on this port perfectly happily,
    and its data directory has just been wiped by the lines above — so `boot()`
    talks to the wrong server and the test fails with "database missing", which
    points at the app instead of at the stale process. Cheap check, hours saved.
    """
    with socket.socket() as sk:
        sk.settimeout(0.4)
        if sk.connect_ex(("127.0.0.1", int(PORT))) == 0:
            raise SystemExit(
                f"something is already listening on port {PORT} — almost certainly a\n"
                f"leaked server from an earlier run. Stop it and try again:\n"
                f'  PowerShell: Get-NetTCPConnection -LocalPort {PORT} -State Listen | '
                f'%{{ Stop-Process -Id $_.OwningProcess -Force }}')


refuse_a_busy_port()

# How many wrestlers the bundled seed actually holds. NOT a literal: this used to
# be `== 270` and broke the moment a roster batch landed, which reads as the save
# system failing when nothing about it had changed.
with sqlite3.connect(f"file:{ROOT / 'data' / 'gm2000.db'}?mode=ro", uri=True) as _c:
    SEED_ROSTER = _c.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0]


def _md5(p: Path) -> str:
    import hashlib
    return hashlib.md5(p.read_bytes()).hexdigest()


# The seed the app ships. Nothing here may ever modify it.
BUNDLED = ROOT / "data" / "gm2000.db"
BUNDLED_MD5_BEFORE = _md5(BUNDLED)


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body or {}).encode() if method != "GET" else None,
        headers={"Content-Type": "application/json"} if method != "GET" else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def boot(label):
    """Start the API the way a fresh container would."""
    env = {**os.environ,
           "GM2000_DATA_DIR": str(EPHEMERAL),
           "GM2000_STORE": "dir",
           "GM2000_REMOTE_DIR": str(REMOTE)}
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", PORT, "--log-level", "warning"],
        cwd=ROOT / "backend", env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Reap it even if an assertion below blows up. Without this a failed run
    # leaves a server holding PORT, and the NEXT run talks to that stale process
    # against a wiped data directory — so one real failure produces a second,
    # unrelated-looking one that sends you hunting in the wrong place.
    atexit.register(lambda: p.poll() is None and p.kill())
    for _ in range(60):
        time.sleep(1)
        try:
            api("/api/health")
            print(f"  [{label}] up")
            return p
        except Exception:
            if p.poll() is not None:
                print(p.stdout.read())
                raise SystemExit(f"[{label}] server died")
    raise SystemExit(f"[{label}] never came up")


def kill(p):
    p.terminate()
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()


print("== boot 1: empty container, empty store ==")
srv = boot("boot1")
st = api("/api/store/status")
print("  store:", st["mode"], "| configured", st["configured"], "| err", st["error"])
assert st["configured"], st
h = api("/api/health")
print("  health:", h["ok"], h["wrestlers"], "wrestlers")
assert h["wrestlers"] == SEED_ROSTER, f"{h['wrestlers']} != seed {SEED_ROSTER}"
assert (REMOTE / "gm2000.db").exists(), "seed was never uploaded to the store"
print("  store seeded:", (REMOTE / "gm2000.db").stat().st_size, "bytes")

print("== write something the deploy must not lose ==")
api("/api/game/new", "POST", {"seed": 4242})
api("/api/power-rankings/generate", "POST", {})
before = api("/api/health")["save"]
print("  seed now", before["rng_seed"])
assert before["rng_seed"] == 4242
remote_after_write = (REMOTE / "gm2000.db").stat().st_mtime

kill(srv)

print("== DESTROY the container filesystem (what a redeploy does) ==")
wipe(EPHEMERAL)
assert not EPHEMERAL.exists()
print("  wiped", EPHEMERAL)

print("== boot 2: brand new container ==")
srv = boot("boot2")
st = api("/api/store/status")
print("  hydrated in", st["hydrated"], "s | db", st["db_bytes"], "bytes")
after = api("/api/health")["save"]
print("  seed now", after["rng_seed"])
assert after["rng_seed"] == 4242, f"THE SAVE WAS LOST — got {after['rng_seed']}"
assert after["created_at"] == before["created_at"], "different save came back"
print("  SAVE SURVIVED A FULL WIPE")

pr = api("/api/power-rankings")
assert pr["issue"], "power rankings issue did not survive"
print("  power issue survived:", pr["issue"]["week_of"])

print("== a GET must not trigger a write ==")
mt = (REMOTE / "gm2000.db").stat().st_mtime
api("/api/roster")
api("/api/contenders")
time.sleep(1)
assert (REMOTE / "gm2000.db").stat().st_mtime == mt, "a GET persisted — wasteful"
print("  GETs left the store alone")

print("== a POST does trigger a write ==")
api("/api/game/advance-month", "POST", {})
time.sleep(1)
assert (REMOTE / "gm2000.db").stat().st_mtime > mt, "a POST did NOT persist"
print("  POST persisted")

print("== a FAILED write must not persist ==")
mt = (REMOTE / "gm2000.db").stat().st_mtime
try:
    api("/api/contenders/999999/lock", "POST", {"wrestler_id": 1})
except Exception as e:
    print("  rejected as expected:", type(e).__name__)
time.sleep(1)
assert (REMOTE / "gm2000.db").stat().st_mtime == mt, "a failed request persisted"
print("  failed request left the store alone")

kill(srv)

print("== local dev must be completely unaffected ==")
out = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); import store, paths;"
     "print('mode', store.MODE, '| enabled', store.enabled(), '| db', paths.DB_PATH)"],
    cwd=ROOT, capture_output=True, text=True)
print(" ", out.stdout.strip() or out.stderr.strip())
assert "enabled False" in out.stdout, "store is on by default — it must not be"

print("== the bundled seed must be untouched ==")
after_md5 = _md5(BUNDLED)
print("  data/gm2000.db", BUNDLED_MD5_BEFORE[:12], "->", after_md5[:12])
assert after_md5 == BUNDLED_MD5_BEFORE, "the test modified data/gm2000.db"
print("  bundled roster untouched")

print("\nALL STORE CHECKS PASSED")
