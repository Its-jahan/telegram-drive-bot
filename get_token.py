#!/usr/bin/env python3
"""
Run this script ONCE on your local machine (with a browser) to authorise
Google Drive access. It saves a token file that you then copy to the server.

Usage:
    pip install google-auth-oauthlib
    python3 get_token.py
    # Browser opens → sign in → approve
    # Token saved to gdrive_token.json
    # Copy it to your server: scp gdrive_token.json root@YOUR_SERVER:/opt/dlbot/gdrive_token.json
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SCOPES        = ["https://www.googleapis.com/auth/drive.file"]

if not CLIENT_ID or not CLIENT_SECRET:
    print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables first.")
    raise SystemExit(1)

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow  = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0, open_browser=True)

with open("gdrive_token.json", "w") as f:
    f.write(creds.to_json())

print("\n✅ Token saved to gdrive_token.json")
print("Copy it to your server:")
print("  scp gdrive_token.json root@YOUR_SERVER:/opt/dlbot/gdrive_token.json")
