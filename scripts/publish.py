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
    python scripts/publish.py --dedupe-queue    # remove duplicate-titled
                                                 # rows already queued,
                                                 # keeping the oldest of
                                                 # each and deleting the
                                                 # more recent copies
    python scripts/publish.py --reset-queue     # delete pending/failed rows
                                                 # and reset published rows
                                                 # back to pending
    python scripts/publish.py --clear-queue     # delete every row, any status
    python scripts/publish.py --prune-images    # delete R2 pictures for pins
                                                 # that already published
    python scripts/publish.py --run-now         # publish the next 3 pending
                                                 # pins right away instead of
                                                 # waiting for their scheduled
                                                 # time
"""

from __future__ import annotations

import argparse
import csv
import secrets
import subprocess
import sys
from pathlib import Path

from app_config import config_value, load_config, save_config
from cloudflare_ops import (
    PublishTriggerError,
    WranglerError,
    clear_queue,
    dedupe_queue,
    prune_published_images,
    reset_queue,
    set_worker_secrets,
    trigger_publish,
    worker_url_from_wrangler,
)

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


def reset(skip_confirm: bool) -> None:
    print("\n=== Resetting the queue ===")
    if not skip_confirm:
        answer = input(
            "This deletes every pending/failed pin and resets published pins "
            "back to pending so they'll be posted again. Continue? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled, nothing was changed.")
            return
    try:
        counts = reset_queue()
    except WranglerError as e:
        sys.exit(f"Could not reset the queue: {e}")
    print(f"Deleted {counts['cleared']} pending/failed row(s) and reset "
          f"{counts['reset']} published row(s) back to pending.")


def clear(skip_confirm: bool) -> None:
    print("\n=== Clearing the queue ===")
    if not skip_confirm:
        answer = input(
            "This permanently deletes every pin in the queue, including "
            "already-published ones. Continue? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled, nothing was changed.")
            return
    try:
        n = clear_queue()
    except WranglerError as e:
        sys.exit(f"Could not clear the queue: {e}")
    print(f"Deleted {n} row(s). The queue is empty.")


def prune_images(skip_confirm: bool) -> None:
    print("\n=== Removing pictures for pins that already posted ===")
    if not skip_confirm:
        answer = input(
            "This deletes stored pictures for pins that already posted. "
            "Pictures still needed by waiting or failed pins are kept. Continue? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled, nothing was changed.")
            return
    try:
        result = prune_published_images()
    except WranglerError as e:
        sys.exit(f"Could not prune pictures: {e}")
    deleted = result["deleted"]
    skipped = result["skipped"]
    if deleted:
        print(f"Deleted {len(deleted)} picture(s):")
        for name in deleted:
            print(f"  - {name}")
    else:
        print("No published pictures to delete.")
    if skipped:
        print(f"Kept {len(skipped)} picture(s) still used by a waiting or failed pin:")
        for name in skipped:
            print(f"  - {name}")


def resolve_trigger_credentials() -> tuple[str, str]:
    """Return (worker_url, secret), recovering either from wrangler if
    this computer's config was saved before those fields existed."""
    config = load_config()
    worker_url = config_value(config, "worker_url")
    secret = config_value(config, "manual_trigger_secret")
    updates = {}
    if not worker_url:
        try:
            worker_url = worker_url_from_wrangler() or ""
        except WranglerError as e:
            sys.exit(f"Could not look up your Worker URL: {e}")
        if worker_url:
            updates["worker_url"] = worker_url
    if not secret:
        secret = secrets.token_urlsafe(24)
        try:
            set_worker_secrets({"MANUAL_TRIGGER_SECRET": secret})
        except WranglerError as e:
            sys.exit(f"Could not set the manual-trigger secret: {e}")
        updates["manual_trigger_secret"] = secret
        print("Saved a new manual-trigger secret (the previous one, if any, no longer works).")
    if updates:
        save_config(updates)
    if not worker_url:
        sys.exit(
            "Could not find your Worker URL. Run scripts/setup.py again, "
            "then retry --run-now."
        )
    return worker_url, secret


def run_now(limit: int) -> None:
    print(f"\n=== Publishing the next {limit} pending pin(s) now ===")
    worker_url, secret = resolve_trigger_credentials()
    try:
        result = trigger_publish(worker_url, secret, limit=limit, force=True)
    except PublishTriggerError as e:
        sys.exit(f"Could not trigger the Worker: {e}")

    published = [r for r in result.get("results", []) if r.get("status") == "published"]
    failed = [r for r in result.get("results", []) if r.get("status") != "published"]
    if not result.get("results"):
        print("Nothing pending to publish.")
        return
    for row in published:
        print(f"  Published \"{row['title']}\" -> {row.get('pin_url', '(no link returned)')}")
    for row in failed:
        print(f"  ! Failed \"{row['title']}\": {row.get('error', 'unknown error')}")


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
    parser.add_argument(
        "--reset-queue", action="store_true",
        help="Delete pending/failed rows and reset published rows back to pending.",
    )
    parser.add_argument(
        "--clear-queue", action="store_true",
        help="Delete every row in the queue, including published ones.",
    )
    parser.add_argument(
        "--prune-images", action="store_true",
        help="Delete R2 pictures that belong only to already-published pins.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="With --reset-queue, --clear-queue, or --prune-images, skip the confirmation prompt.",
    )
    parser.add_argument(
        "--run-now", nargs="?", type=int, const=3, default=None, metavar="N",
        help="Publish the next N pending pins immediately instead of waiting for their "
             "scheduled time (default 3).",
    )
    args = parser.parse_args()

    if args.dedupe_queue:
        dedupe(args.all_statuses)
        return
    if args.reset_queue:
        reset(args.yes)
        return
    if args.clear_queue:
        clear(args.yes)
        return
    if args.prune_images:
        prune_images(args.yes)
        return
    if args.run_now is not None:
        run_now(args.run_now)
        return

    for label, script_name in STEPS:
        run_step(label, script_name)
    summarize()
    print("\nAll done. You can close this window.")


if __name__ == "__main__":
    main()
