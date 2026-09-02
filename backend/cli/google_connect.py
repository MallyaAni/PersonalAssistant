"""Connect a Google account, read-only, for the Drive document source.

    python -m backend.cli.google_connect

Prints the consent URL for the configured OAuth client (Drive read-only
scope), takes the code Google shows after consent, exchanges it for a
refresh token, and writes GOOGLE_TOKEN_PATH (mode 600). Run it where a
browser is at hand; the token file is what the Spark's backend reads. The
redirect is the loopback address, so the code is read from the URL the
browser lands on (paste the whole URL or just the code).
"""
from __future__ import annotations

import sys
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from backend.config.settings import settings
from backend.services.google_drive_source import SCOPES, TOKEN_URL, save_token

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT = "http://127.0.0.1:8765/"


def main() -> int:
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        print("Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env first (a Desktop OAuth client in Google Cloud).")
        return 2
    url = AUTH_URL + "?" + urlencode(
        {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print("Open this URL, consent, then paste the URL you land on (or the code):\n\n" + url + "\n")
    raw = input("code or URL: ").strip()
    code = parse_qs(urlparse(raw).query).get("code", [raw])[0] if raw.startswith("http") else raw
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT,
        },
        timeout=30,
    )
    if response.status_code != 200:
        print("Google refused the code:", response.text[:300])
        return 1
    token = response.json()
    if "refresh_token" not in token:
        print("No refresh token came back; revoke the app's access in your Google account and run this again.")
        return 1
    save_token(token)
    print(f"Token written to {settings.GOOGLE_TOKEN_PATH}. Set GOOGLE_DRIVE_FOLDER_ID and restart the backend; the folder syncs every {settings.GOOGLE_DRIVE_SYNC_INTERVAL_SECONDS} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
