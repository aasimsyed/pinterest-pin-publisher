#!/usr/bin/env python3
"""
One-time guided setup. Saves keys on this computer, connects Pinterest, and
builds the whole Cloudflare side (database, image storage, scheduler) for
you, so the other scripts run with almost no flags.

    python scripts/setup.py
"""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
import urllib.error
from pathlib import Path

from anthropic_auth import load_api_key
from app_config import config_value, load_config, save_config
from masked_input import read_secret
from cloudflare_ops import (
    WranglerError,
    apply_migrations,
    deploy_worker,
    ensure_d1_database,
    ensure_image_bucket,
    ensure_login,
    list_accounts,
    reset_after_reauth,
    set_worker_secrets,
    write_database_id,
    write_pinterest_vars,
)
from oauth_setup import (
    create_board,
    exchange_code_for_tokens,
    get_authorization_code,
    list_boards,
)

ROOT = Path(__file__).resolve().parent.parent


def ask(label: str, default: str = "", hidden: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    prompt = f"{label}{suffix}: "
    if hidden:
        value = read_secret(prompt)
    else:
        value = input(prompt).strip()
    return value or default


def install_packages() -> None:
    print("Installing Python packages (this may take a minute)...\n")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
    )
    print()


def pick_account(saved_id: str) -> str:
    """Pick which Cloudflare account wrangler should use. Silent unless
    the login has more than one account and the one already saved (if
    any) isn't one of them."""
    accounts = list_accounts()
    if not accounts:
        return ""
    if any(account["id"] == saved_id for account in accounts):
        return saved_id
    if len(accounts) == 1:
        return accounts[0]["id"]

    print("\nYour Cloudflare login has more than one account:\n")
    for i, account in enumerate(accounts, 1):
        print(f"  {i}. {account['name']}  (id {account['id']})")
    print()
    choice = ask("Number of the account to use", "1")
    try:
        return accounts[int(choice) - 1]["id"]
    except (ValueError, IndexError):
        sys.exit("That was not a valid account number.")


def pick_board(access_token: str, saved_id: str, sandbox: bool) -> tuple[str, str]:
    try:
        boards = list_boards(access_token, sandbox=sandbox)
    except urllib.error.HTTPError as e:
        print(f"Could not list boards automatically ({e.code}).")
        boards = []

    if not boards and sandbox:
        print("No sandbox boards yet -- creating one for testing...")
        board = create_board(access_token, "Sandbox pins", sandbox=True)
        return str(board.get("name") or "Sandbox pins"), str(board.get("id") or "")

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
    parser.parse_args()

    print("Pinterest Pin Publisher setup")
    print("You will paste a few keys and click Allow twice. Everything stays "
          "on this computer or in your own Cloudflare/Pinterest accounts.\n")

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

    print("\n4) Pinterest app")
    print("   Open https://developers.pinterest.com/apps/")
    print("   Create an app (or open an existing one).")
    print("   Add this redirect URL exactly:")
    print("     http://localhost:8765/callback")
    print("   Copy the App ID and App secret.\n")
    client_id = ask("Pinterest App ID", config_value(saved, "pinterest_client_id"))
    client_secret = ask("Pinterest App secret", hidden=True)
    if not client_id or not client_secret:
        sys.exit("App ID and App secret are required.")

    print("\n   Trial apps can only create pins in Pinterest's private sandbox,")
    print("   visible only to you, until Pinterest approves Standard access.")
    has_standard = ask(
        "Do you already have Pinterest Standard access? (y/n)", "n"
    ).lower().startswith("y")
    sandbox = not has_standard
    if sandbox:
        print("   Using sandbox for now -- switch to Standard later by "
              "re-running this after you're approved.\n")

    print("\nA browser window will open. Click Allow, then come back here.\n")
    code = get_authorization_code(client_id)
    tokens = exchange_code_for_tokens(client_id, client_secret, code, sandbox=sandbox)
    refresh_token = tokens.get("refresh_token") or ""
    access_token = tokens.get("access_token") or ""
    if not refresh_token:
        sys.exit("Pinterest did not return a refresh token. Check the app scopes.")

    print("\n5) Which board should pins go on?")
    board_name, board_id = pick_board(access_token, config_value(saved, "board_id"), sandbox)
    if not board_name:
        board_name = ask("Board name", config_value(saved, "board_name"))
    if not board_id:
        sys.exit("Could not get a board ID.")

    print("\n6) Cloudflare (hosts the scheduler and your pin images)")
    print("   A browser window may open so you can log into Cloudflare.\n")
    try:
        ensure_login()
        account_id = pick_account(config_value(saved, "account_id"))
        if account_id:
            save_config({"account_id": account_id})
        print("Setting up the pin queue database...")
        database_id = ensure_d1_database()
        write_database_id(database_id)
        apply_migrations()
        write_pinterest_vars(sandbox, board_id)
        print("Setting up image storage...")
        ensure_image_bucket()
        print("Saving Pinterest credentials to your Cloudflare Worker...")
        manual_trigger_secret = secrets.token_urlsafe(24)
        set_worker_secrets({
            "PINTEREST_CLIENT_ID": client_id,
            "PINTEREST_CLIENT_SECRET": client_secret,
            "PINTEREST_REFRESH_TOKEN": refresh_token,
            "MANUAL_TRIGGER_SECRET": manual_trigger_secret,
        })
        reset_after_reauth()
        print("Deploying the publisher...")
        worker_url = deploy_worker()
    except WranglerError as e:
        sys.exit(f"\nCloudflare setup failed: {e}")

    save_config({
        "site_url": site_url,
        "images_dir": images_dir,
        "board_name": board_name,
        "board_id": board_id,
        "pinterest_client_id": client_id,
        "worker_url": worker_url,
        "manual_trigger_secret": manual_trigger_secret,
    })

    print("\nAll set" + (" (sandbox mode -- pins are private until you have "
                          "Standard access)" if sandbox else "") + ". Each time you have new pins:")
    print("  1. Put the image files in the images folder")
    print("  2. Double-click \"Publish Pins\" (or run: python scripts/publish.py)")
    if worker_url:
        print(f"\nYour scheduler is live at {worker_url}")
        print("Run pins immediately instead of waiting for their scheduled time with: "
              "python scripts/publish.py --run-now")


if __name__ == "__main__":
    main()
