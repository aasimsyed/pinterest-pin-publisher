#!/usr/bin/env python3
"""
push_to_d1.py

Takes the CSV produced by generate_pinterest_csv.py and inserts each row
into the Cloudflare D1 "pin_queue" table via Cloudflare's REST API, instead
of manually uploading the CSV through Pinterest's bulk-upload UI. The
pinterest-pin-publisher Worker (src/worker.js) then publishes each row on
its own once its publish_at time arrives.

Cloudflare credential resolution order (same pattern as the Anthropic key
in generate_pinterest_csv.py):
    1. --account-id / --api-token / --database-id flags
    2. CF_ACCOUNT_ID / CF_API_TOKEN / CF_DATABASE_ID environment variables
    3. ~/.config/cloudflare/config.json containing:
       {"account_id": "...", "api_token": "...", "database_id": "..."}
       If missing and running interactively, you'll be prompted once and
       it'll be saved there for next time.

The CSV's "Pinterest board" column is a display name, but Pinterest's API
needs a numeric board_id -- pass it explicitly with --board-id (find it by
calling GET /v5/boards with your access token, or from the board's URL in
Pinterest's UI).

Usage:
    python scripts/push_to_d1.py \
        --csv pinterest_bulk_upload.csv \
        --board-id 1234567890123456789
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

PRIMARY_CONFIG_PATH = Path.home() / ".config" / "cloudflare" / "config.json"
CONFIG_PATHS = [PRIMARY_CONFIG_PATH]


def save_cf_config(config: dict, path: Path = PRIMARY_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600


def first_run_setup() -> dict:
    print("No Cloudflare credentials found.")
    print(f"Let's set them up -- saved to {PRIMARY_CONFIG_PATH} "
          f"(readable only by your user account) so you won't be asked again.\n")
    print("Account ID: Cloudflare dashboard -> right sidebar of any domain overview")
    print("API token:  https://dash.cloudflare.com/profile/api-tokens "
          "(needs 'D1: Edit' permission)")
    print("Database ID: `wrangler d1 info pin-publisher-db` or the D1 dashboard\n")

    config = {
        "account_id": input("Cloudflare Account ID: ").strip(),
        "api_token": getpass.getpass("Cloudflare API Token (input hidden): ").strip(),
        "database_id": input("D1 Database ID: ").strip(),
    }
    save_cf_config(config)
    print(f"\nSaved to {PRIMARY_CONFIG_PATH}\n")
    return config


def load_cf_config(cli_account_id, cli_api_token, cli_database_id) -> dict:
    if cli_account_id and cli_api_token and cli_database_id:
        return {
            "account_id": cli_account_id,
            "api_token": cli_api_token,
            "database_id": cli_database_id,
        }

    env_account = os.environ.get("CF_ACCOUNT_ID")
    env_token = os.environ.get("CF_API_TOKEN")
    env_db = os.environ.get("CF_DATABASE_ID")
    if env_account and env_token and env_db:
        return {"account_id": env_account, "api_token": env_token, "database_id": env_db}

    for config_path in CONFIG_PATHS:
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                continue
            if all(k in data for k in ("account_id", "api_token", "database_id")):
                return data

    if sys.stdin.isatty():
        return first_run_setup()

    sys.exit(
        "No Cloudflare credentials found. Pass --account-id/--api-token/--database-id, "
        "set CF_ACCOUNT_ID/CF_API_TOKEN/CF_DATABASE_ID, or create "
        f"{PRIMARY_CONFIG_PATH}."
    )


def run_d1_query(config: dict, sql: str, params: list) -> dict:
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{config['account_id']}"
        f"/d1/database/{config['database_id']}/query"
    )
    body = json.dumps({"sql": sql, "params": params}).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Authorization", f"Bearer {config['api_token']}")
    request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"D1 query failed ({e.code}): {e.read().decode()}") from e


INSERT_SQL = """
INSERT INTO pin_queue (title, media_url, board_id, description, link, publish_at, keywords)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path,
                         help="CSV produced by generate_pinterest_csv.py")
    parser.add_argument("--board-id", required=True,
                         help="Numeric Pinterest board ID (not the display name)")
    parser.add_argument("--account-id", default=None)
    parser.add_argument("--api-token", default=None)
    parser.add_argument("--database-id", default=None)
    args = parser.parse_args()

    config = load_cf_config(args.account_id, args.api_token, args.database_id)

    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        sys.exit(f"No rows found in {args.csv}")

    print(f"Pushing {len(rows)} rows from {args.csv} to D1 database "
          f"{config['database_id']}...")

    inserted, failed = 0, 0
    for row in rows:
        publish_at = row["Publish date"]
        # Pinterest/D1 expect ISO-8601; the generator script already writes
        # e.g. 2026-07-22T09:00:00 -- treat naive datetimes as UTC.
        if publish_at and not publish_at.endswith("Z") and "+" not in publish_at:
            publish_at = publish_at + "Z"

        try:
            run_d1_query(
                config,
                INSERT_SQL,
                [
                    row["Title"],
                    row["Media URL"],
                    args.board_id,
                    row.get("Description", ""),
                    row.get("Link", ""),
                    publish_at,
                    row.get("Keywords", ""),
                ],
            )
            inserted += 1
        except RuntimeError as e:
            print(f"  ! Failed to insert \"{row['Title']}\": {e}")
            failed += 1

    print(f"\nDone. Inserted {inserted} rows, {failed} failed.")


if __name__ == "__main__":
    main()
