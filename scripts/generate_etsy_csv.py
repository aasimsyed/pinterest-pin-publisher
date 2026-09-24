#!/usr/bin/env python3
"""
generate_etsy_csv.py

Reads active listings from your Etsy shop via the Etsy API, builds a
Pinterest-style pin graphic for each one (product photo + title/price
overlay), asks Claude to write an SEO-optimized Pinterest title,
description, and keywords from the listing's own text, and assembles
everything into a bulk-upload CSV in the same format
generate_pinterest_csv.py produces, so it feeds straight into
push_to_d1.py.

Unlike the blog-image pipeline, the Link column is already known (the
Etsy listing's own URL), so there's no separate link-matching step.

Usage:
    python scripts/generate_etsy_csv.py
    python scripts/generate_etsy_csv.py --shuffle
    python scripts/generate_etsy_csv.py --force-requeue
    python scripts/generate_etsy_csv.py --ai-images

Requires:
    pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

import anthropic
from anthropic.types import MessageParam

from ai_image import AiImageError, restyle_photo
from anthropic_auth import load_api_key
from app_config import config_value, load_config, save_config
from cloudflare_ops import (
    WranglerError,
    ensure_image_bucket,
    existing_media_filenames,
    existing_titles,
    upload_image,
)
from etsy_oauth import refresh_access_token
from etsy_ops import EtsyError, find_shop_id, list_active_listings
from gemini_auth import load_api_key as load_gemini_api_key
from generate_pinterest_csv import FIELDNAMES, build_schedule, dedupe_titles
from pin_image import save_pin_image

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "images" / "_etsy_generated"

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a Pinterest SEO specialist for a handmade/vintage \
Etsy shop. You will be given one Etsy listing's own title, description, \
tags, and price. Use that to write pin metadata optimized to rank in \
Pinterest search and drive clicks through to the listing.

Respond with ONLY a JSON object (no markdown fences, no preamble) with these \
exact keys:

  "title": a Pinterest pin title, Title Case, max 100 characters. Lead \
with the primary keyword phrase a shopper would actually type into \
Pinterest search (the product type, e.g. "Personalized Leather Journal"), \
not a generic word. Do not just copy the Etsy title verbatim, rewrite it \
to read like a Pinterest search query.

  "description": a Pinterest description, 300-500 characters, that puts \
the main keyword phrase in the first sentence, naturally works in 2-4 \
secondary keywords (material, occasion, who it's a gift for), reads like \
a human wrote it (not a keyword list), and ends with a soft \
call-to-action (e.g. "Shop this and more in our Etsy shop," "Tap to see \
more photos"). Do not use hashtags.

  "keywords": a comma-separated string of 6-10 relevant Pinterest search \
terms (lowercase, no hashtags, no duplicates), mixing short broad terms \
with longer long-tail phrases.
"""


def write_pin_metadata(client: anthropic.Anthropic, listing: dict) -> dict:
    """Ask Claude to turn one Etsy listing's own text into Pinterest metadata."""
    payload = json.dumps({
        "title": listing["title"],
        "description": listing["description"][:1000],
        "tags": listing["tags"],
        "price": listing["price"],
    }, ensure_ascii=False)
    messages: list[MessageParam] = [{"role": "user", "content": payload}]
    response = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.split("\n", 1)[-1] if "\n" in raw_text else raw_text
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"  ! Could not parse JSON for listing {listing['listing_id']}, "
              f"raw response:\n{raw_text}")
        return {
            "title": listing["title"][:100],
            "description": listing["description"][:500],
            "keywords": "",
        }


def download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pin-publisher/1.0"})
    with urllib.request.urlopen(request) as response:
        return response.read()


def get_access_token(api_key: str, saved: dict) -> str:
    """Trade the saved refresh token for a fresh access token, immediately
    persisting the rotated refresh token Etsy returns -- the old one stops
    working the moment a new one is issued, so this must be saved right
    away or the next run's refresh will fail."""
    refresh_token = config_value(saved, "etsy_refresh_token")
    if not refresh_token:
        sys.exit("Etsy isn't connected yet. Run python scripts/setup.py, choose "
                  "to set up Etsy, and click Allow when Etsy's login page opens.")
    try:
        tokens = refresh_access_token(api_key, refresh_token)
    except RuntimeError as e:
        sys.exit(f"Could not connect to Etsy ({e}). Run python scripts/setup.py "
                  f"again to reconnect Etsy.")
    save_config({"etsy_refresh_token": tokens.get("refresh_token") or refresh_token})
    access_token = tokens.get("access_token") or ""
    if not access_token:
        sys.exit("Etsy did not return an access token. Run python scripts/setup.py "
                  "again to reconnect Etsy.")
    return access_token


def limit_listings(listings: list[dict], limit: int | None) -> list[dict]:
    """Cap how many listings get processed this run, leaving the rest for
    a later run (useful when a shop has hundreds of listings)."""
    if limit is None or limit >= len(listings):
        return listings
    return listings[:limit]


def filter_new_listings(listings: list[dict], already_posted: set[str]) -> tuple[list[dict], list[dict]]:
    """Split listings into (new, already queued/posted), keyed by the
    deterministic filename their pin graphic would upload as."""
    def key(listing: dict) -> str:
        return f"etsy-{listing['listing_id']}.png"

    new = [l for l in listings if key(l) not in already_posted]
    skipped = [l for l in listings if key(l) in already_posted]
    return new, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=None,
                         help="Etsy API key (keystring). Default: saved config.")
    parser.add_argument("--shared-secret", default=None,
                         help="Etsy shared secret. Default: saved config.")
    parser.add_argument("--shop-id", default=None,
                         help="Etsy shop ID. Default: saved config.")
    parser.add_argument("--shop-name", default=None,
                         help="Etsy shop name, used to look up the shop ID if not saved.")
    parser.add_argument("--board", default=None,
                         help="Pinterest board for Etsy pins. Default: value from setup.")
    parser.add_argument("--posts-per-day", type=int, default=3)
    parser.add_argument("--start-date", default=datetime.date.today().isoformat(),
                         help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--output", default="etsy_bulk_upload.csv", type=Path)
    parser.add_argument("--anthropic-api-key", default=None,
                         help="Anthropic API key. Same resolution as "
                              "generate_pinterest_csv.py if omitted.")
    parser.add_argument("--allow-duplicate-titles", action="store_true")
    parser.add_argument("--shuffle", action="store_true",
                         help="Randomize which listing gets which publish date.")
    parser.add_argument("--force-requeue", action="store_true",
                         help="Regenerate pins for listings already queued or published.")
    parser.add_argument("--limit", type=int, default=None,
                         help="Only process this many new listings, useful for a "
                              "first small batch out of a large shop.")
    parser.add_argument("--ai-images", action="store_true",
                         help="Restyle each listing photo with Google Gemini "
                              "(better lighting/background) before adding the "
                              "title/price text. Costs about $0.04/pin extra "
                              "and needs a Gemini API key.")
    parser.add_argument("--gemini-api-key", default=None,
                         help="Gemini API key, only used with --ai-images. "
                              "Default: saved config.")
    args = parser.parse_args()

    saved = load_config()
    api_key = args.api_key or config_value(saved, "etsy_api_key")
    shared_secret = args.shared_secret or config_value(saved, "etsy_shared_secret")
    if not api_key or not shared_secret:
        sys.exit("No Etsy API credentials. Run python scripts/setup.py to set up Etsy.")

    shop_id = args.shop_id or config_value(saved, "etsy_shop_id")
    if not shop_id:
        shop_name = args.shop_name or config_value(saved, "etsy_shop_name")
        if not shop_name:
            sys.exit("No Etsy shop configured. Run python scripts/setup.py or pass --shop-name.")
        try:
            shop_id = find_shop_id(api_key, shared_secret, shop_name)
        except EtsyError as e:
            sys.exit(f"Could not find your Etsy shop: {e}")

    board = args.board or config_value(saved, "etsy_board_name")
    if not board:
        sys.exit("No Etsy board name. Run python scripts/setup.py or pass --board.")

    print("Connecting to Etsy...")
    access_token = get_access_token(api_key, saved)

    print("Fetching active listings from your Etsy shop...")
    try:
        listings = list_active_listings(api_key, shared_secret, shop_id, access_token)
    except EtsyError as e:
        sys.exit(f"Could not fetch Etsy listings: {e}")
    if not listings:
        sys.exit("No active listings found in your Etsy shop.")
    print(f"Found {len(listings)} active listing(s).\n")

    if not args.force_requeue:
        try:
            already_posted = existing_media_filenames()
        except WranglerError as e:
            print(f"  ! Could not check already-queued images ({e}); "
                  f"processing every listing.")
            already_posted = set()
        listings, skipped = filter_new_listings(listings, already_posted)
        if skipped:
            print(f"Skipping {len(skipped)} listing(s) already queued or posted "
                  f"(pass --force-requeue to process them anyway):")
            for l in skipped:
                print(f"  - {l['title']}")

    if not listings:
        print("\nNo new listings to process -- every active listing is "
              "already queued or posted.")
        if args.output.exists():
            args.output.unlink()
        return

    if args.shuffle:
        random.shuffle(listings)

    if args.limit is not None and args.limit < len(listings):
        print(f"Processing {args.limit} of {len(listings)} new listing(s) "
              f"(--limit), the rest are left for a later run.\n")
    listings = limit_listings(listings, args.limit)

    start_date = datetime.date.fromisoformat(args.start_date)
    anthropic_key = load_api_key(args.anthropic_api_key)
    client = anthropic.Anthropic(api_key=anthropic_key)

    print("Making sure your pin images have a public web address...")
    try:
        public_base_url = ensure_image_bucket()
    except WranglerError as e:
        sys.exit(f"Could not set up image hosting: {e}")

    gemini_key = load_gemini_api_key(args.gemini_api_key) if args.ai_images else ""

    rows = []
    print(f"\nBuilding pin graphics and writing metadata for {len(listings)} listing(s)...")
    for i, listing in enumerate(listings, 1):
        print(f"[{i}/{len(listings)}] {listing['title']}")
        if not listing["image_url"]:
            print("  ! No photo on this listing, skipping.")
            continue
        try:
            photo_bytes = download_bytes(listing["image_url"])
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"  ! Could not download photo, skipping ({e}).")
            continue

        if args.ai_images:
            try:
                photo_bytes = restyle_photo(gemini_key, photo_bytes)
            except AiImageError as e:
                print(f"  ! Gemini restyle failed ({e}); using the original photo instead.")

        # Claude's title first -- it's short and Pinterest-optimized, unlike
        # the listing's own title, which is often a long comma-separated
        # dump of SEO keyword phrases that looks terrible baked into the pin.
        meta = write_pin_metadata(client, listing)
        pin_title = meta.get("title", listing["title"])[:100]

        local_path = GENERATED_DIR / f"etsy-{listing['listing_id']}.png"
        save_pin_image(photo_bytes, pin_title, listing["price"], local_path)

        try:
            media_url = upload_image(local_path, public_base_url)
        except WranglerError as e:
            sys.exit(f"Could not upload pin image for listing {listing['listing_id']}: {e}")

        description = meta.get("description", "")[:500]
        rows.append({
            "Title": pin_title,
            "Media URL": media_url,
            "Pinterest board": board,
            "Thumbnail": "",
            "Description": description,
            "Link": listing["url"],
            "Publish date": "",  # filled in below
            "Keywords": meta.get("keywords", ""),
        })

    if not rows:
        sys.exit("No pins were built (every listing was missing a photo or "
                  "failed to download).")

    if not args.allow_duplicate_titles:
        print("\nChecking for duplicate titles (Pinterest's bulk CSV upload "
              "rejects these)...")
        try:
            already_queued = existing_titles()
        except WranglerError as e:
            print(f"  ! Could not check already-queued titles ({e}); only "
                  f"checking this batch.")
            already_queued = set()
        rows = dedupe_titles(client, rows, already_queued)

    schedule = list(build_schedule(len(rows), start_date, args.posts_per_day))
    for row, publish_date in zip(rows, schedule):
        row["Publish date"] = publish_date

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
