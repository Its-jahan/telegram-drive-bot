#!/usr/bin/env python3
"""Run once locally to get a Google Drive OAuth token, then copy it to the server."""

from google_auth_oauthlib.flow import InstalledAppFlow
import json

CLIENT_ID     = "YOUR_GOOGLE_CLIENT_ID"
CLIENT_SECRET = "YOUR_GOOGLE_CLIENT_SECRET"
SCOPES        = ["https://www.googleapis.com/auth/drive.file"]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0, open_browser=True)

token_json = creds.to_json()
with open("/tmp/gdrive_token.json", "w") as f:
    f.write(token_json)

print("\n✅ Token saved to /tmp/gdrive_token.json")
print("Now copying to server...")
