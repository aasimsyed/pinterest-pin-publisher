#!/usr/bin/env python3
"""
push_to_d1.py

Takes the CSV produced by generate_pinterest_csv.py and queues each row in
the Cloudflare D1 "pin_queue" table via `wrangler` (the same login used for
setup and deploy -- no separate Cloudflare credential needed). The
pinterest-pin-publisher Worker (src/worker.js) then publishes each row on
its own once its publish_at time arrives.

The CSV's "Pinterest board" column is a display name, but Pinterest's API
needs a numeric board_id -- pass it explicitly with --board-id (setup.py
saves this for you) or find it by calling GET /v5/boards with your access
token.

Usage:
    python scripts/push_to_d1.py \
        --csv pinterest_bulk_upload.csv \
        --board-id 1234567890123456789
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app_config import config_value, load_config
from cloudflare_ops import WranglerError, insert_pin_rows


def normalize_publish_at(value: str) -> str:
    # Pinterest/D1 expect ISO-8601; the generator script already writes
    # e.g. 2026-07-22T09:00:00 -- treat naive datetimes as UTC.
    if value and not value.endswith("Z") and "+" not in value:
        return value + "Z"
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=None, type=Path,
                         help="CSV to queue. Default: pinterest_bulk_upload_with_links.csv")
    parser.add_argument("--board-id", default=None,
                         help="Numeric Pinterest board ID (not the display name)")
    args = parser.parse_args()

    saved = load_config()
    board_id = args.board_id or config_value(saved, "board_id")
    if not board_id:
        sys.exit("No board ID. Run python scripts/setup.py or pass --board-id.")

    csv_path = args.csv
    if csv_path is None:
        matched = Path("pinterest_bulk_upload_with_links.csv")
        csv_path = matched if matched.exists() else Path("pinterest_bulk_upload.csv")

    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"No rows found in {csv_path}")

    queue_rows = [
        {
            "title": row["Title"],
            "media_url": row["Media URL"],
            "board_id": board_id,
            "description": row.get("Description", ""),
            "link": row.get("Link", ""),
            "publish_at": normalize_publish_at(row["Publish date"]),
            "keywords": row.get("Keywords", ""),
        }
        for row in rows
    ]

    print(f"Queuing {len(queue_rows)} pins from {csv_path}...")
    try:
        insert_pin_rows(queue_rows)
    except WranglerError as e:
        sys.exit(f"Could not queue pins: {e}")

    print(f"\nDone. Queued {len(queue_rows)} pins. The Worker posts each one "
          f"within about 15 minutes of its scheduled time.")


if __name__ == "__main__":
    main()
