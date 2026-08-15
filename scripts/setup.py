#!/usr/bin/env python3
"""
One-time guided setup. Saves keys on this computer so the other scripts
can run with almost no flags.

    python scripts/setup.py
"""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
import urllib.error
from pathlib import Path

from anthropic_auth import load_api_key
from app_config import config_value, load_config, save_config
from oauth_setup import (
    exchange_code_for_tokens,
    get_authorization_code,
    list_boards,
)
from push_to_d1 import load_cf_config, save_cf_config

ROOT = Path(__file__).resolve().parent.parent
WRANGLER_TOML = ROOT / "wrangler.toml"


def ask(label: str, default: str = "", hidden: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    prompt = f"{label}{suffix}: "
    if hidden:
        value = getpass.getpass(prompt).strip()
    else:
        value = input(prompt).strip()
    return value or default


def install_packages() -> None:
    print("Installing Python packages (this may take a minute)...\n")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
    )
    print()


def write_wrangler_database_id(database_id: str) -> None:
    text = WRANGLER_TOML.read_text()
    needle = 'database_id = "'
    start = text.find(needle)
    if start < 0:
        return
    start += len(needle)
    end = text.find('"', start)
    WRANGLER_TOML.write_text(text[:start] + database_id + text[end:])


def pick_board(access_token: str, saved_id: str, sandbox: bool = False) -> tuple[str, str]:
    try:
        boards = list_boards(access_token, sandbox=sandbox)
    except urllib.error.HTTPError as e:
        print(f"Could not list boards automatically ({e.code}).")
        boards = []
    if not boards:
        board_id = ask("Pinterest board ID (from the board URL)", saved_id)
        return "", board_id
    print("Your Pinterest boards:\n")
    for i, board in enumerate(boards, 1):
        print(f"  {i}. {board.get('name', '(no name)')}  (id {board.get('id', '')})")
    print()
    choice = ask("Number of the board to publish to", "1")
    try:
        index = int(choice) - 1
        board = boards[index]
    except (ValueError, IndexError):
        sys.exit("That was not a valid board number.")
    return str(board.get("name") or ""), str(board.get("id") or "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Authorize against Pinterest sandbox (Trial can create pins there)",
    )
    args = parser.parse_args()

    print("Pinterest Pin Publisher setup")
    print("You will paste a few keys. They stay on this computer.\n")

    install_packages()

    print("1) Anthropic (Claude) key")
    print("   Open https://console.anthropic.com/settings/keys")
    print("   Sign in, click Create Key, copy it.\n")
    load_api_key(None)
    print("Anthropic key saved.\n")

    saved = load_config()

    print("2) Your website")
    print("   Example: https://yourfrugalmom.com")
    print("   No slash at the end.\n")
    site_url = ask("Website URL", config_value(saved, "site_url")).rstrip("/")

    print("\n3) Pin image folder")
    print("   Put the pin graphics in a folder in this project.")
    print("   Default is a folder named images.\n")
    images_dir = ask("Image folder", config_value(saved, "images_dir", "images"))
    (ROOT / images_dir).mkdir(parents=True, exist_ok=True)

    print("\n4) Public image URL prefix")
    print("   Upload the same images to WordPress: Media -> Add New.")
    print("   Open one image and copy its link, then delete the filename.")
    print("   Example image: https://yoursite.com/wp-content/uploads/2026/08/tuna.png")
    print("   Prefix to paste:  https://yoursite.com/wp-content/uploads/2026/08")
    print()
    url_prefix = ask("Image URL prefix", config_value(saved, "url_prefix")).rstrip("/")

    print("\n5) Pinterest app")
    print("   Open https://developers.pinterest.com/apps/")
    print("   Create an app (or open an existing one).")
    print("   Add this redirect URL exactly:")
    print("     http://localhost:8765/callback")
    print("   Copy the App ID and App secret.\n")
    client_id = ask("Pinterest App ID", config_value(saved, "pinterest_client_id"))
    client_secret = ask("Pinterest App secret", hidden=True)
    if not client_id or not client_secret:
        sys.exit("App ID and App secret are required.")

    print("\nA browser window will open. Click Allow, then come back here.\n")
    code = get_authorization_code(client_id)
    tokens = exchange_code_for_tokens(
        client_id, client_secret, code, sandbox=args.sandbox
    )
    refresh_token = tokens.get("refresh_token") or ""
    access_token = tokens.get("access_token") or ""
    if not refresh_token:
        sys.exit("Pinterest did not return a refresh token. Check the app scopes.")

    print("\n6) Which board should pins go on?")
    board_name, board_id = pick_board(
        access_token, config_value(saved, "board_id"), sandbox=args.sandbox
    )
    if not board_name:
        board_name = ask("Board name", config_value(saved, "board_name"))
    if not board_id:
        sys.exit("Could not get a board ID.")

    print("\n7) Cloudflare (for scheduled publishing)")
    print("   Account ID: dash.cloudflare.com, right sidebar of a domain.")
    print("   API token:  https://dash.cloudflare.com/profile/api-tokens")
    print("               Create token with D1 Edit permission.")
    print("   Database ID: after you create the D1 database (see the README).\n")
    cf = load_cf_config(None, None, None)
    write_wrangler_database_id(cf["database_id"])
    save_cf_config(cf)

    save_config({
        "site_url": site_url,
        "images_dir": images_dir,
        "url_prefix": url_prefix,
        "board_name": (
            (config_value(saved, "board_name") or board_name)
            if args.sandbox
            else board_name
        ),
        "board_id": (
            (config_value(saved, "board_id") or board_id)
            if args.sandbox
            else board_id
        ),
        "pinterest_client_id": client_id,
    })

    print("\nLocal settings saved.")
    print("Put these Worker secrets on Cloudflare (run in this folder):\n")
    print("  wrangler secret put PINTEREST_CLIENT_ID")
    print(f"    paste: {client_id}")
    print("  wrangler secret put PINTEREST_CLIENT_SECRET")
    print("    paste: your App secret")
    print("  wrangler secret put PINTEREST_REFRESH_TOKEN")
    print(f"    paste: {refresh_token}")
    if args.sandbox:
        print("\nSandbox mode: in wrangler.toml set PINTEREST_SANDBOX = \"true\"")
        print(f"and PINTEREST_BOARD_ID = \"{board_id}\" then wrangler deploy.")
        print("Clear oauth_tokens after you switch environments.")
    print("\nThen finish the README section: Deploy the publisher (one time).")
    print("Each time you have new pins:\n")
    print("  python scripts/generate_pinterest_csv.py")
    print("  python scripts/match_wordpress_links.py")
    print("  python scripts/push_to_d1.py")


if __name__ == "__main__":
    main()
