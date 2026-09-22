#!/usr/bin/env python3
"""Get a Google Drive OAuth token on a machine with no browser.

    GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python3 get_token.py

Prints an authorisation URL. Open it in any browser, approve, then paste the
URL your browser lands on back here — it will fail to load, which is fine; the
authorisation code is in its address bar and that is all this needs.

Requires an OAuth client of type "Desktop app".
"""

import os
import sys
import urllib.parse

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from google_auth_oauthlib.flow import Flow

CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
OUT           = os.environ.get("TOKEN_FILE", "/opt/dlbot/gdrive_token.json")
REDIRECT_URI  = "http://localhost:8899/"
SCOPES        = ["https://www.googleapis.com/auth/drive.file"]

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first.")

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [REDIRECT_URI],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

print(f"\n1. Open this URL in a browser:\n\n{auth_url}\n")
print("2. Approve, then copy the URL your browser lands on (it will show")
print("   'site can't be reached' — that is expected) and paste it below.\n")

pasted = input("Redirected URL (or just the code): ").strip()

code = pasted
if "://" in pasted or "code=" in pasted:
    params = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
    if "code" not in params:
        sys.exit("No 'code' parameter found in that URL.")
    code = params["code"][0]

flow.fetch_token(code=code)

with open(OUT, "w") as f:
    f.write(flow.credentials.to_json())

print(f"\nToken saved to {OUT}")
