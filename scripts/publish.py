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
    python scripts/publish.py --shuffle         # randomize post order instead
                                                 # of filename order
    python scripts/publish.py --images-dir images/summer
                                                 # publish pictures from this
                                                 # folder instead of images
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
    python scripts/publish.py --list-queue      # show pins waiting to be
                                                 # published (add --all-statuses
                                                 # to include posted/failed too)
    python scripts/publish.py --run-now         # publish the next 3 pending
                                                 # pins right away instead of
                                                 # waiting for their scheduled
                                                 # time
    python scripts/publish.py --run-now --shuffle  # same, but pick which
                                                 # pending pins randomly
                                                 # instead of earliest-first
    python scripts/publish.py --force-requeue   # re-process every image even
                                                 # if its filename is already
                                                 # queued or published
    python scripts/publish.py --etsy            # build pins from your Etsy
                                                 # shop's active listings
                                                 # instead of the images folder
                                                 # (requires Etsy setup)
    python scripts/publish.py --etsy --limit 20 # only process 20 new Etsy
                                                 # listings this run, leaving
                                                 # the rest for later runs
    python scripts/publish.py --csv-only        # build the CSV (and, with
                                                 # --etsy, the pin graphics)
                                                 # but don't schedule it yet
    python scripts/publish.py --publish-csv pinterest_bulk_upload.csv
                                                 # schedule an already-built
                                                 # CSV instead of building
                                                 # a new one
    python scripts/publish.py --etsy --ai-images
                                                 # restyle each Etsy listing
                                                 # photo with AI before adding
                                                 # the title/price text
    python scripts/publish.py --list-boards     # show your Pinterest boards
                                                 # and their numbers
    python scripts/publish.py --board 2         # post to board #2 for just
                                                 # this run (name also works),
                                                 # instead of the saved default
    python scripts/publish.py --menu            # numbered list of every option
                                                 # (Publish Pins.command / .bat
                                                 #  opens this)
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
    list_queue,
    prune_published_images,
    reset_queue,
    set_worker_secrets,
    trigger_publish,
    worker_url_from_wrangler,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
STEPS = [
    ("Reading your pin images and writing titles/descriptions", "generate_pinterest_csv.py"),
    ("Matching each pin to a blog post link", "match_wordpress_links.py"),
    ("Scheduling your pins", "push_to_d1.py"),
]


def run_step(label: str, script_name: str, extra_args: list[str] | None = None) -> None:
    print(f"\n=== {label} ===")
    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / script_name), *(extra_args or [])])
    if result.returncode != 0:
        sys.exit(f"\nStopped: \"{label}\" did not finish. See the message above for what to fix.")


def summarize(csv_path: Path | None = None) -> None:
    csv_path = csv_path or SCRIPTS_DIR.parent / "pinterest_bulk_upload_with_links.csv"
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


def show_queue(all_statuses: bool) -> None:
    status = "" if all_statuses else "pending"
    label = "every pin in the queue" if all_statuses else "pins waiting to be published"
    print(f"\n=== {label.capitalize()} ===")
    try:
        rows = list_queue(status)
    except WranglerError as e:
        sys.exit(f"Could not read the queue: {e}")
    if not rows:
        print("Nothing to show.")
        return
    for row in rows:
        when = row.get("publish_at") or "(no date)"
        marker = f" [{row['status']}]" if all_statuses else ""
        print(f"  #{row['id']}  {when}{marker}  \"{row['title']}\"")
        if row.get("pinterest_pin_url"):
            print(f"      -> {row['pinterest_pin_url']}")
    print(f"\n{len(rows)} pin(s).")


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


def run_now(limit: int, shuffle: bool = False) -> None:
    order_note = "random" if shuffle else "earliest-scheduled"
    print(f"\n=== Publishing {limit} pending pin(s) now ({order_note} order) ===")
    worker_url, secret = resolve_trigger_credentials()
    try:
        result = trigger_publish(worker_url, secret, limit=limit, force=True, random_order=shuffle)
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


def cached_boards(saved: dict) -> list[dict]:
    boards = saved.get("pinterest_boards")
    return boards if isinstance(boards, list) and boards else []


def _pick_index(raw: str, count: int, what: str) -> int:
    """Turn a 1-based menu answer into a 0-based index, or exit if it is out of range."""
    try:
        index = int(raw) - 1
    except ValueError:
        sys.exit(f"That was not a valid {what} number.")
    if not 0 <= index < count:
        sys.exit(f"That was not a valid {what} number.")
    return index


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def count_images(folder: Path) -> int:
    return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def _count_label(n: int) -> str:
    if n == 0:
        return "no pictures yet"
    return f"{n} picture" if n == 1 else f"{n} pictures"


def resolve_images_dir(saved: dict, images_dir: Path | None) -> Path:
    """Explicit --images-dir wins, used as typed. Otherwise the setup folder
    (or images), relative to the project so it works from any directory."""
    if images_dir is not None:
        return images_dir
    return ROOT / config_value(saved, "images_dir", "images")


def list_image_subdirs(images_dir: Path) -> list[Path]:
    """Immediate subfolders, skipping hidden and generated ones (names starting with . or _)."""
    if not images_dir.is_dir():
        return []
    return sorted(
        (p for p in images_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))),
        key=lambda p: p.name.lower(),
    )


def choose_images_dir(images_dir: Path) -> Path:
    """Ask which folder to publish from when images_dir has subfolders.

    The folder itself stays the default, so pressing Enter keeps using it.
    """
    subdirs = list_image_subdirs(images_dir)
    if not subdirs:
        return images_dir
    options = [images_dir, *subdirs]
    print("\nWhich image folder should these pins come from?\n")
    for i, folder in enumerate(options, 1):
        label = _count_label(count_images(folder))
        if folder == images_dir:
            label = f"{label}, default"
        print(f"  {i}. {_display_path(folder)}  ({label})")
    choice = input("Number of the folder [1]: ").strip() or "1"
    return options[_pick_index(choice, len(options), "folder")]


def choose_board(saved: dict, default_id: str, prompt_label: str) -> tuple[str | None, str | None]:
    """Ask which board this one run should post to, defaulting to whatever
    was picked last (in setup or a previous run). Nothing is saved back --
    each run can go to a different board without changing anyone else's
    default. Returns (None, None) if no board list is cached yet (e.g.
    setup ran before this existed), so the caller just falls back to each
    script's own saved default."""
    boards = cached_boards(saved)
    if not boards:
        return None, None
    default_index = next(
        (i for i, b in enumerate(boards) if b.get("id") == default_id), 0
    )
    print(f"\nWhich board should {prompt_label} go to?\n")
    for i, board in enumerate(boards, 1):
        marker = "  (default)" if i - 1 == default_index else ""
        print(f"  {i}. {board.get('name', '(no name)')}{marker}")
    choice = input(f"Number of the board [{default_index + 1}]: ").strip() or str(default_index + 1)
    board = boards[_pick_index(choice, len(boards), "board")]
    return str(board.get("name") or ""), str(board.get("id") or "")


def resolve_board_flag(saved: dict, board_arg: str | None) -> tuple[str | None, str | None]:
    """Resolve --board (a board number from --list-boards, or an exact,
    case-insensitive board name) for non-interactive use. Returns
    (None, None) when no override was given, so the caller falls back to
    each script's own saved default."""
    if not board_arg:
        return None, None
    boards = cached_boards(saved)
    for i, board in enumerate(boards, 1):
        name = str(board.get("name") or "")
        if board_arg == str(i) or board_arg.strip().lower() == name.strip().lower():
            return name, str(board.get("id") or "")
    sys.exit(f"Could not find a board matching \"{board_arg}\". Run "
              f"--list-boards to see your options, or re-run setup.py to "
              f"refresh the list.")


def list_boards_command() -> None:
    boards = cached_boards(load_config())
    if not boards:
        print("No cached board list yet. Run python scripts/setup.py to fetch your boards.")
        return
    print("\nYour Pinterest boards:\n")
    for i, board in enumerate(boards, 1):
        print(f"  {i}. {board.get('name', '(no name)')}  (id {board.get('id', '')})")


def publish_csv(csv_path: Path, board_id: str | None) -> None:
    """Schedule an already-built CSV (e.g. one made earlier with
    --csv-only) instead of generating a new one."""
    if not csv_path.exists():
        sys.exit(f"Could not find {csv_path}.")
    extra_args = ["--csv", str(csv_path)]
    if board_id:
        extra_args += ["--board-id", board_id]
    run_step(f"Scheduling pins from {csv_path.name}", "push_to_d1.py", extra_args)
    summarize(csv_path)
    print("\nAll done. You can close this window.")


def run_pipeline(
    shuffle: bool = False, force_requeue: bool = False,
    board_name: str | None = None, board_id: str | None = None,
    csv_only: bool = False, images_dir: Path | None = None,
) -> None:
    csv_path = SCRIPTS_DIR.parent / "pinterest_bulk_upload.csv"
    steps = STEPS[:-1] if csv_only else STEPS
    for label, script_name in steps:
        extra_args = None
        if script_name == "generate_pinterest_csv.py":
            extra_args = []
            if images_dir is not None:
                extra_args += ["--images-dir", str(images_dir)]
            if shuffle:
                extra_args.append("--shuffle")
            if force_requeue:
                extra_args.append("--force-requeue")
            if board_name:
                extra_args += ["--board", board_name]
            extra_args = extra_args or None
        elif script_name == "push_to_d1.py" and board_id:
            extra_args = ["--board-id", board_id]
        run_step(label, script_name, extra_args)
        if script_name == "generate_pinterest_csv.py" and not csv_path.exists():
            print("\nNothing to do -- add new pictures to the images folder "
                  "and run this again.")
            return
    if csv_only:
        linked_csv = SCRIPTS_DIR.parent / "pinterest_bulk_upload_with_links.csv"
        final_csv = linked_csv if linked_csv.exists() else csv_path
        print(f"\nWrote {final_csv.name}. Nothing has been scheduled yet.")
        print(f"When you're ready: python scripts/publish.py --publish-csv {final_csv.name}")
        return
    summarize()
    print("\nAll done. You can close this window.")


def run_etsy_pipeline(
    shuffle: bool = False, force_requeue: bool = False,
    board_name: str | None = None, board_id: str | None = None,
    limit: int | None = None, csv_only: bool = False, ai_images: bool = False,
) -> None:
    saved = load_config()
    board_id = board_id or config_value(saved, "etsy_board_id")
    if not csv_only and not board_id:
        sys.exit("Etsy isn't set up yet. Run python scripts/setup.py and choose to set up Etsy.")

    csv_path = SCRIPTS_DIR.parent / "etsy_bulk_upload.csv"
    extra_args = []
    if shuffle:
        extra_args.append("--shuffle")
    if force_requeue:
        extra_args.append("--force-requeue")
    if board_name:
        extra_args += ["--board", board_name]
    if limit is not None:
        extra_args += ["--limit", str(limit)]
    if ai_images:
        extra_args.append("--ai-images")
    run_step("Building pins from your Etsy listings", "generate_etsy_csv.py", extra_args or None)
    if not csv_path.exists():
        print("\nNothing to do -- every active Etsy listing is already queued or posted.")
        return
    if csv_only:
        print(f"\nWrote {csv_path.name}. Nothing has been scheduled yet.")
        print(f"When you're ready: python scripts/publish.py --publish-csv {csv_path.name}")
        return
    run_step(
        "Scheduling your Etsy pins", "push_to_d1.py",
        ["--csv", str(csv_path), "--board-id", board_id],
    )
    summarize(csv_path)
    print("\nAll done. You can close this window.")


def _ask_yes_no(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("y", "yes")


def menu(images_dir: Path | None = None) -> None:
    etsy_configured = bool(config_value(load_config(), "etsy_api_key"))
    print("What do you want to do?\n")
    print("  1. Publish new pins (the usual)")
    print("  2. Publish waiting pins right now")
    print("  3. Remove duplicate titles from the queue")
    print("  4. Reset the queue (posted pins wait again)")
    print("  5. Empty the queue completely")
    print("  6. Delete pictures for pins that already posted")
    print("  7. Show pins waiting to be published")
    if etsy_configured:
        print("  8. Publish new Etsy pins")
    print("  9. Schedule pins from a CSV file you already have")
    print("  0. Nothing, close this window\n")
    choice = input("Type a number, then press Enter [1]: ").strip() or "1"
    if choice == "0":
        print("Nothing to do.")
        return
    if choice == "1":
        saved = load_config()
        if images_dir is None:
            images_dir = choose_images_dir(resolve_images_dir(saved, None))
        board_name, board_id = choose_board(saved, config_value(saved, "board_id"), "these new pins")
        shuffle = _ask_yes_no("Shuffle the post order instead of posting them in filename order? [y/N] ")
        csv_only = _ask_yes_no("Only build the CSV without scheduling it yet? [y/N] ")
        run_pipeline(
            shuffle=shuffle, board_name=board_name, board_id=board_id,
            csv_only=csv_only, images_dir=images_dir,
        )
        return
    if choice == "2":
        raw = input("How many pins? [3]: ").strip() or "3"
        try:
            limit = int(raw)
        except ValueError:
            sys.exit("That was not a number.")
        if limit < 1:
            sys.exit("Need at least 1 pin.")
        shuffle = _ask_yes_no("Pick which ones randomly instead of earliest-scheduled first? [y/N] ")
        run_now(limit, shuffle=shuffle)
        return
    if choice == "3":
        dedupe(all_statuses=False)
        return
    if choice == "4":
        reset(skip_confirm=False)
        return
    if choice == "5":
        clear(skip_confirm=False)
        return
    if choice == "6":
        prune_images(skip_confirm=False)
        return
    if choice == "7":
        show_queue(all_statuses=False)
        return
    if choice == "8" and etsy_configured:
        shuffle = _ask_yes_no("Shuffle the post order instead of listing order? [y/N] ")
        raw_limit = input("How many listings to process? [all]: ").strip()
        limit = None
        if raw_limit:
            try:
                limit = int(raw_limit)
            except ValueError:
                sys.exit("That was not a number.")
            if limit < 1:
                sys.exit("Need at least 1 listing.")
        ai_images = _ask_yes_no(
            "Restyle photos with AI before adding text? Costs about $0.04/pin extra. [y/N] "
        )
        csv_only = _ask_yes_no("Only build the CSV without scheduling it yet? [y/N] ")
        saved = load_config()
        board_name, board_id = choose_board(saved, config_value(saved, "etsy_board_id"), "your Etsy pins")
        run_etsy_pipeline(
            shuffle=shuffle, board_name=board_name, board_id=board_id,
            limit=limit, csv_only=csv_only, ai_images=ai_images,
        )
        return
    if choice == "9":
        raw_path = input("Path to the CSV file: ").strip()
        if not raw_path:
            sys.exit("Need a file path.")
        saved = load_config()
        _, board_id = choose_board(saved, config_value(saved, "board_id"), "these pins")
        publish_csv(Path(raw_path), board_id)
        return
    sys.exit("That was not a choice on the list.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dedupe-queue", action="store_true",
        help="Remove duplicate-titled rows already in the queue instead of publishing new pins.",
    )
    parser.add_argument(
        "--all-statuses", action="store_true",
        help="With --dedupe-queue or --list-queue, also include published/failed rows, "
             "not just pending ones.",
    )
    parser.add_argument(
        "--list-queue", action="store_true",
        help="Show pins waiting to be published instead of publishing new ones.",
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
        help="Publish N pending pins immediately instead of waiting for their scheduled "
             "time (default 3). Combine with --shuffle to pick which N randomly instead "
             "of earliest-scheduled first.",
    )
    parser.add_argument(
        "--menu", action="store_true",
        help="Show a numbered list of every publish option.",
    )
    parser.add_argument(
        "--images-dir", default=None, type=Path,
        help="Folder of pin images to publish. Default: images (or the folder saved in setup), "
             "relative to this project. With --menu, giving this skips the subfolder question. "
             "Not used with --etsy.",
    )
    parser.add_argument(
        "--shuffle", action="store_true",
        help="Randomize the post order instead of scheduling pins in filename order. "
             "With --run-now, picks which pending pins to post randomly instead of "
             "earliest-scheduled first.",
    )
    parser.add_argument(
        "--force-requeue", action="store_true",
        help="Process every image in the folder even if its filename is already "
             "queued or published, instead of skipping already-processed ones.",
    )
    parser.add_argument(
        "--etsy", action="store_true",
        help="Build pins from your Etsy shop's active listings instead of the "
             "images folder (requires Etsy setup in scripts/setup.py).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="With --etsy, only process this many new listings, useful for a "
             "first small batch out of a large shop.",
    )
    parser.add_argument(
        "--board", default=None,
        help="Post to this board just for this run (by name, or the number "
             "shown by --list-boards), instead of the saved default.",
    )
    parser.add_argument(
        "--list-boards", action="store_true",
        help="Show your cached Pinterest boards and their numbers for --board.",
    )
    parser.add_argument(
        "--csv-only", action="store_true",
        help="Build the pin CSV (and Etsy pin graphics, with --etsy) but don't "
             "schedule it yet. Schedule it later with --publish-csv.",
    )
    parser.add_argument(
        "--publish-csv", default=None, type=Path, metavar="PATH",
        help="Schedule pins from an existing CSV file instead of building a new one.",
    )
    parser.add_argument(
        "--ai-images", action="store_true",
        help="With --etsy, restyle each listing photo with Google Gemini "
             "(better lighting/background) before adding the title/price "
             "text. Costs about $0.04/pin extra and needs a Gemini API key.",
    )
    args = parser.parse_args()

    if args.etsy and args.images_dir is not None:
        parser.error("--images-dir does not apply to --etsy. Etsy pins are built from "
                     "your listing photos, not the images folder.")

    if args.menu:
        menu(images_dir=args.images_dir)
        return
    if args.list_boards:
        list_boards_command()
        return
    if args.list_queue:
        show_queue(args.all_statuses)
        return
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
        run_now(args.run_now, shuffle=args.shuffle)
        return

    saved = load_config()
    board_name, board_id = resolve_board_flag(saved, args.board)
    if args.publish_csv is not None:
        if board_id is None and sys.stdin.isatty():
            _, board_id = choose_board(saved, config_value(saved, "board_id"), "these pins")
        publish_csv(args.publish_csv, board_id)
        return
    if args.etsy:
        run_etsy_pipeline(
            shuffle=args.shuffle, force_requeue=args.force_requeue,
            board_name=board_name, board_id=board_id, limit=args.limit,
            csv_only=args.csv_only, ai_images=args.ai_images,
        )
        return

    run_pipeline(
        shuffle=args.shuffle, force_requeue=args.force_requeue,
        board_name=board_name, board_id=board_id, csv_only=args.csv_only,
        images_dir=resolve_images_dir(saved, args.images_dir),
    )


if __name__ == "__main__":
    main()
