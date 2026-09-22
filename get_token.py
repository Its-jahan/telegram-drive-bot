#!/usr/bin/env python3
"""Get a Google Drive OAuth token.

On a machine with a browser:
    GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python3 get_token.py

On a headless server, forward the callback port from your laptop first:
    ssh -L 8899:localhost:8899 root@SERVER
then run the same command there and open the printed URL in your own browser.
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")     or "YOUR_GOOGLE_CLIENT_ID"
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET") or "YOUR_GOOGLE_CLIENT_SECRET"
PORT          = int(os.environ.get("OAUTH_LOCAL_PORT", "8899"))
OUT           = os.environ.get("TOKEN_FILE", "/opt/dlbot/gdrive_token.json")
SCOPES        = ["https://www.googleapis.com/auth/drive.file"]

if CLIENT_ID.startswith("YOUR_"):
    raise SystemExit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first.")

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [f"http://localhost:{PORT}"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(
    port=PORT,
    open_browser=False,
    bind_addr="0.0.0.0",
    access_type="offline",
    prompt="consent",
    authorization_prompt_message="Open this URL in your browser:\n\n{url}\n",
)

with open(OUT, "w") as f:
    f.write(creds.to_json())

print(f"\nToken saved to {OUT}")
