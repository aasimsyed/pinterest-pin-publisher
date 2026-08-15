#!/usr/bin/env python3
"""
oauth_setup.py

Run this ONCE to complete Pinterest's OAuth 2.0 authorization-code flow and
get a refresh token. The refresh token is what you save as a Cloudflare
Worker secret (PINTEREST_REFRESH_TOKEN) -- the Worker uses it to mint fresh
access tokens on its own from then on, so you never have to do this again
unless you revoke access.

Before running:
    1. Create an app at https://developers.pinterest.com/apps/
    2. Add a redirect URI. For this script, use: http://localhost:8765/callback
    3. Note your App ID (client_id) and App secret (client_secret)

Usage:
    python scripts/oauth_setup.py --client-id YOUR_APP_ID --client-secret YOUR_APP_SECRET
    python scripts/oauth_setup.py --client-id YOUR_APP_ID --client-secret YOUR_APP_SECRET --sandbox

This will open your browser, ask you to approve the app on Pinterest, then
print the access token, refresh token, and expiry to your terminal.
"""

import argparse
import base64
import http.server
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL = "https://www.pinterest.com/oauth/"
PROD_API_BASE = "https://api.pinterest.com/v5"
SANDBOX_API_BASE = "https://api-sandbox.pinterest.com/v5"


def api_base(sandbox: bool = False) -> str:
    return SANDBOX_API_BASE if sandbox else PROD_API_BASE

# Create Pin needs write access on the board plus read/write on pins.
SCOPES = "boards:read,boards:write,pins:read,pins:write"

_auth_code = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            _auth_code["code"] = code
            body = b"Authorization received. You can close this tab and return to your terminal."
        else:
            body = b"No authorization code received. Check your terminal for details."

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence default request logging


def get_authorization_code(client_id: str) -> str:
    server = http.server.HTTPServer(("localhost", 8765), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print(f"Opening browser for Pinterest authorization:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for you to approve the app in your browser...")
    while "code" not in _auth_code:
        pass  # simple blocking wait; fine for a one-time local setup script

    server.shutdown()
    return _auth_code["code"]


def list_boards(access_token: str, sandbox: bool = False) -> list[dict]:
    request = urllib.request.Request(
        f"{api_base(sandbox)}/boards?page_size=100",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read())
    return data.get("items") or []


def exchange_code_for_tokens(
    client_id: str,
    client_secret: str,
    code: str,
    sandbox: bool = False,
) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()

    request = urllib.request.Request(
        f"{api_base(sandbox)}/oauth/token",
        data=data,
        method="POST",
    )
    request.add_header("Authorization", f"Basic {basic}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use api-sandbox.pinterest.com (Trial can create pins here)",
    )
    args = parser.parse_args()

    code = get_authorization_code(args.client_id)
    tokens = exchange_code_for_tokens(
        args.client_id, args.client_secret, code, sandbox=args.sandbox
    )
    access_token = tokens.get("access_token") or ""

    env_name = "sandbox" if args.sandbox else "production"
    print(f"\nSuccess ({env_name}). Save these as Cloudflare Worker secrets:\n")
    print(f"  wrangler secret put PINTEREST_CLIENT_ID       # {args.client_id}")
    print(f"  wrangler secret put PINTEREST_CLIENT_SECRET   # (paste your secret)")
    print(f"  wrangler secret put PINTEREST_REFRESH_TOKEN   # {tokens.get('refresh_token')}")
    if args.sandbox:
        print("\nSandbox tokens do not work on production. In wrangler.toml set:")
        print('  PINTEREST_SANDBOX = "true"')
        print("  PINTEREST_BOARD_ID = \"<sandbox board id below>\"")
        print("Then wrangler deploy.")
        print("\nSandbox boards (IDs differ from production):")
        try:
            boards = list_boards(access_token, sandbox=True)
        except urllib.error.URLError as e:
            boards = []
            print(f"  Could not list boards: {e}")
        if boards:
            for board in boards:
                print(f"  {board.get('name', '(no name)')}  {board.get('id', '')}")
            sandbox_board_id = boards[0].get("id") or ""
            if sandbox_board_id:
                print("\nD1 still has your production board id until you update it:")
                print(
                    "  wrangler d1 execute pin-publisher-db --remote --command "
                    f"\"UPDATE pin_queue SET board_id = '{sandbox_board_id}';\""
                )
        else:
            print("  None yet. Create one, then copy its id into PINTEREST_BOARD_ID:")
            print(f"  curl -sS -X POST {api_base(True)}/boards \\")
            print('    -H "Authorization: Bearer $PINTEREST_ACCESS_TOKEN" \\')
            print('    -H "Content-Type: application/json" \\')
            print('    -d \'{"name":"Sandbox pins","privacy":"PUBLIC"}\'')
    print("\nIf the Worker already ran with the old token, clear the cached one:")
    print('  wrangler d1 execute pin-publisher-db --remote --command "DELETE FROM oauth_tokens;"')
    print("  wrangler d1 execute pin-publisher-db --remote --command \"UPDATE pin_queue SET status = 'pending', error_message = NULL WHERE status = 'failed';\"")
    print(f"\n(Access token, for reference -- expires in {tokens.get('expires_in')}s "
          f"and the Worker will refresh it automatically, so you don't need to save this):")
    print(f"  {access_token}")


if __name__ == "__main__":
    main()
