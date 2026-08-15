#!/usr/bin/env python3
"""
publish.py

The one command for "I have new pins." Runs the whole pipeline in order:

    1. generate_pinterest_csv.py  -- uploads images, asks Claude for
       titles/descriptions/keywords, and schedules them
    2. match_wordpress_links.py   -- finds the right blog post link for
       each pin
    3. push_to_d1.py              -- queues everything for the Worker to
       post on schedule

If a step fails, this stops right there and explains what to fix -- it
will not push half-finished pins.

Usage:
    python scripts/publish.py
    python scripts/publish.py --dedupe-queue   # remove duplicate-titled
                                                # rows already queued,
                                                # keeping the oldest of
                                                # each and deleting the
                                                # more recent copies
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from cloudflare_ops import WranglerError, dedupe_queue

SCRIPTS_DIR = Path(__file__).resolve().parent
STEPS = [
    ("Reading your pin images and writing titles/descriptions", "generate_pinterest_csv.py"),
    ("Matching each pin to a blog post link", "match_wordpress_links.py"),
    ("Scheduling your pins", "push_to_d1.py"),
]


def run_step(label: str, script_name: str) -> None:
    print(f"\n=== {label} ===")
    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / script_name)])
    if result.returncode != 0:
        sys.exit(f"\nStopped: \"{label}\" did not finish. See the message above for what to fix.")


def summarize() -> None:
    csv_path = SCRIPTS_DIR.parent / "pinterest_bulk_upload_with_links.csv"
    if not csv_path.exists():
        return
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    first_time = rows[0].get("Publish date", "")
    print(f"\n{len(rows)} pin(s) queued. The first one posts around {first_time} "
          f"(the Worker checks every 15 minutes).")


def dedupe(all_statuses: bool) -> None:
    print("\n=== Cleaning up duplicate titles already in the queue ===")
    try:
        removed = dedupe_queue(pending_only=not all_statuses)
    except WranglerError as e:
        sys.exit(f"Could not clean up the queue: {e}")
    if not removed:
        print("No duplicate titles found.")
        return
    print(f"Removed {len(removed)} duplicate row(s), keeping the oldest of each title:")
    for row in removed:
        print(f"  - #{row['id']} ({row['status']}): \"{row['title']}\"")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dedupe-queue", action="store_true",
        help="Remove duplicate-titled rows already in the queue instead of publishing new pins.",
    )
    parser.add_argument(
        "--all-statuses", action="store_true",
        help="With --dedupe-queue, also clean up published/failed rows, not just pending ones.",
    )
    args = parser.parse_args()

    if args.dedupe_queue:
        dedupe(args.all_statuses)
        return

    for label, script_name in STEPS:
        run_step(label, script_name)
    summarize()
    print("\nAll done. You can close this window.")


if __name__ == "__main__":
    main()
