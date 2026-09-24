#!/usr/bin/env python3
"""
etsy_oauth.py

Etsy's Open API v3 requires OAuth 2.0 (Authorization Code + PKCE) to read
shop listings -- an API key alone isn't enough, even for a shop's own
active listings. This runs that one-time browser consent flow and gets a
refresh token; generate_etsy_csv.py then uses it to mint short-lived
access tokens on its own from then on, refreshing again each run.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://localhost:8766/callback"
AUTH_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

# listings_r covers reading a shop's listings; Etsy requires it even for a
# shop's own active (already-public) listings.
SCOPES = "listings_r"

_auth_response: dict = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        _auth_response["code"] = params.get("code", [None])[0]
        _auth_response["state"] = params.get("state", [None])[0]
        _auth_response["error"] = params.get("error", [None])[0]
        if _auth_response["code"]:
            body = b"Authorization received. You can close this tab and return to your terminal."
        else:
            body = b"No authorization code received. Check your terminal for details."

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence default request logging


def _pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) per RFC 7636 -- Etsy requires PKCE
    on every authorization request."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def get_authorization_code(client_id: str) -> tuple[str, str]:
    """Opens the browser for the user to approve access, waits for the
    redirect, and returns (code, code_verifier)."""
    server = http.server.HTTPServer(("localhost", 8766), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print(f"Opening browser for Etsy authorization:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for you to approve the app in your browser...")
    while "code" not in _auth_response:
        pass  # simple blocking wait; fine for a one-time local setup script

    server.shutdown()
    if _auth_response.get("error") or not _auth_response.get("code"):
        raise RuntimeError(
            f"Etsy authorization failed: {_auth_response.get('error') or 'no code returned'}"
        )
    if _auth_response.get("state") != state:
        raise RuntimeError("Etsy's response didn't match the request. Please try again.")
    return _auth_response["code"], verifier


def exchange_code_for_tokens(client_id: str, code: str, code_verifier: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code": code,
        "code_verifier": code_verifier,
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def refresh_access_token(client_id: str, refresh_token: str) -> dict:
    """Trades a refresh token for a new (access_token, refresh_token)
    pair. Etsy rotates the refresh token on every use -- the caller must
    save the new one, or the next refresh will fail."""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Could not refresh your Etsy access token ({e.code}): {body[:300]}") from e
