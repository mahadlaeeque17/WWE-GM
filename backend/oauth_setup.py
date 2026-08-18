"""One-time Google OAuth consent for Drive image sync.

    python oauth_setup.py

Why OAuth and not a service account: this Google account has an org policy
(`iam.disableServiceAccountKeyCreation`) that blocks service-account JSON keys,
and even with that overridden a Google-managed `KeyExposureResponse` policy
re-blocks it. There is no user-facing way around either. OAuth Desktop clients
are not subject to those restrictions — the same conclusion the NBA Alternate
Universe build reached.

Reuses the OAuth Desktop client already created for that project unless this
project has its own. An OAuth client is not tied to a scope, so the same client
can be authorised for Drive; only the consent screen differs.

Opens a browser once, you click Allow, and a refresh token is cached to
backend/drive_token.json. Re-run it if the token is ever revoked.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN_PATH = HERE / "drive_token.json"
CLIENT_PATH = HERE / "drive_oauth_client.json"

# Falls back to the OAuth Desktop client already set up for the NBA app.
NBA_ENV = Path(r"C:\Users\Hp\Desktop\NBA Alternate Universe\.env.local")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def client_config() -> tuple[dict, str]:
    """Return (client_config, where_it_came_from). Never prints the secret."""
    # 1. a client JSON downloaded straight from the console
    if CLIENT_PATH.exists():
        data = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
        return data, str(CLIENT_PATH.name)

    # 2. env vars, or this project's own .env
    env = {**read_env_file(HERE.parent / ".env"), **os.environ}
    cid = env.get("GOOGLE_OAUTH_CLIENT_ID")
    csec = env.get("GOOGLE_OAUTH_CLIENT_SECRET")
    source = "environment / .env"

    # 3. the NBA project's client
    if not (cid and csec):
        nba = read_env_file(NBA_ENV)
        cid = nba.get("GOOGLE_OAUTH_CLIENT_ID")
        csec = nba.get("GOOGLE_OAUTH_CLIENT_SECRET")
        source = "NBA Alternate Universe .env.local (reused)"

    if not (cid and csec):
        sys.exit(
            "No OAuth client found.\n\n"
            "Create one: Google Cloud console -> APIs & Services -> Credentials\n"
            "  -> Create credentials -> OAuth client ID -> Desktop app\n"
            f"then save the downloaded JSON as {CLIENT_PATH}\n"
            "or set GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET."
        )

    return {
        "installed": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }, source


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    cfg, source = client_config()
    print(f"Using OAuth client from: {source}")
    print("Scope: drive.readonly (read-only — this can never modify your Drive)")
    print()
    print("A browser window is opening. Sign in as mahadlaeeque17@gmail.com and click Allow.")
    print("If a warning about an unverified app appears, choose Advanced -> Go to ... (unsafe);")
    print("that is expected for a personal Desktop client in Testing mode.")
    print()

    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print()
    print(f"Authorised. Refresh token cached to {TOKEN_PATH.name}")
    print("Drive sync is now live — hit 'Sync' on the Images tab.")


if __name__ == "__main__":
    main()
