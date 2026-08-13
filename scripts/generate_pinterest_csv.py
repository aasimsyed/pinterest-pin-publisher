#!/usr/bin/env python3
"""
generate_pinterest_csv.py

Reads a folder of Pinterest pin images, uses Claude (vision) to read the
title text baked into each graphic and write an SEO-optimized description
and keyword list, then assembles everything into a Pinterest bulk-upload CSV.

API key resolution order:
    1. --api-key flag
    2. ANTHROPIC_API_KEY environment variable
    3. ~/.config/anthropic/config.json  (or legacy ~/.anthropic/config.json)
       containing: {"api_key": "sk-ant-..."}
    4. If none found and running interactively, prompts once and saves the
       key to ~/.config/anthropic/config.json (chmod 600) for next time.

Usage:
    python scripts/generate_pinterest_csv.py

Requires:
    pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime
import json
import mimetypes
import sys
from pathlib import Path
from typing import Literal

import anthropic
from anthropic.types import (
    Base64ImageSourceParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)

from anthropic_auth import load_api_key
from app_config import config_value, load_config

# Pinterest bulk-upload column order (see Pinterest's help doc)
FIELDNAMES = [
    "Title",
    "Media URL",
    "Pinterest board",
    "Thumbnail",
    "Description",
    "Link",
    "Publish date",
    "Keywords",
]

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a Pinterest SEO specialist for a budget-recipe \
and frugal-living blog. You will be shown one Pinterest pin graphic. \
Read any text baked into the image exactly as printed -- including any \
leading number like "10", "25+", or "12" -- and use it to write pin metadata \
that is optimized to rank in Pinterest search.

Respond with ONLY a JSON object (no markdown fences, no preamble) with these \
exact keys:

  "title": the exact title text as printed on the image, cleaned up with \
normal capitalization (Title Case), including any leading number/count. \
Lead with the primary keyword phrase (what someone would actually type into \
Pinterest search), not a generic word. Max 100 characters -- use close to \
the full limit when it reads naturally, since longer keyword-rich titles \
perform better in Pinterest search than short generic ones.

  "description": a Pinterest description written to rank in Pinterest \
search AND get clicks. Follow these SEO rules:
    - Aim for 300-500 characters (Pinterest allows up to 500; use most of \
that space -- thin descriptions under ~150 characters under-perform in \
search).
    - Put the single most important keyword phrase in the first sentence, \
ideally in the first few words. Pinterest weights the opening of the \
description more heavily than the end.
    - Naturally work in 2-4 related secondary keywords or phrases a home \
cook would search (e.g. specific dish names, occasion, dietary tag, \
audience like "for busy weeknights" or "for a family of 4") -- but write \
full, natural sentences. Never comma-stack bare keywords or repeat the same \
phrase more than twice; keyword-stuffed text is downranked and reads like \
spam.
    - Write for a human first: warm, concrete, scannable. Mention a \
specific detail (an ingredient, a time-saver, a budget angle) so it doesn't \
read like a rewritten title.
    - End with a soft call-to-action (e.g. "Save this for later," "Tap for \
the full recipe," "Perfect for your next grocery list").
    - Do not use hashtags in the description field.

  "keywords": a comma-separated string of 6-10 relevant search terms a \
person might type into Pinterest to find this pin (lowercase, no hashtags, \
no duplicates of each other). Mix short broad terms (e.g. "budget dinners") \
with longer long-tail phrases (e.g. "cheap dinner ideas for a family of 4") \
since Pinterest search rewards long-tail keyword coverage.
"""


MediaType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
_MEDIA_TYPES: dict[str, MediaType] = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
}


def encode_image(path: Path) -> tuple[str, MediaType]:
    """Return (base64_data, media_type) for an image file."""
    guessed = mimetypes.guess_type(path.name)[0] or "image/png"
    media_type = _MEDIA_TYPES.get(guessed, "image/png")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return data, media_type


def analyze_image(client: anthropic.Anthropic, path: Path) -> dict:
    """Ask Claude to read the pin image and return title/description/keywords."""
    data, media_type = encode_image(path)
    source: Base64ImageSourceParam = {
        "type": "base64",
        "media_type": media_type,
        "data": data,
    }
    image_block: ImageBlockParam = {"type": "image", "source": source}
    text_block: TextBlockParam = {
        "type": "text",
        "text": f"Filename for context: {path.name}",
    }
    messages: list[MessageParam] = [
        {"role": "user", "content": [image_block, text_block]},
    ]

    response = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    # Strip accidental code fences just in case
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.split("\n", 1)[-1] if "\n" in raw_text else raw_text

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"  ! Could not parse JSON for {path.name}, raw response:\n{raw_text}")
        return {"title": path.stem, "description": "", "keywords": ""}


def rephrase_title(client: anthropic.Anthropic, title: str, used_titles: set[str]) -> str:
    """Ask Claude for an alternate phrasing of a title that collides with
    another title already in this batch. Pinterest's bulk CSV uploader
    rejects exact duplicate titles (even though duplicates are allowed when
    scheduling manually through the UI), so this keeps the same keyword and
    meaning while wording it differently enough to pass validation."""
    used_list = "\n".join(f"- {t}" for t in sorted(used_titles))
    prompt = f"""This Pinterest pin title collides with another title already \
used in the same bulk-upload batch, which Pinterest's CSV uploader will \
reject as a duplicate (manual scheduling allows duplicates, but bulk CSV \
upload does not):

"{title}"

Titles already used in this batch -- the new title must not exactly match \
any of these:
{used_list}

Write ONE alternate phrasing that:
- Keeps the same leading number/count if the original had one
- Keeps the same core keyword phrase and meaning -- this is a second pin \
design for the same topic/recipe roundup, so it still needs to rank for the \
same Pinterest search terms
- Is worded differently enough that it will not exactly match any title above
- Stays under 100 characters
- Reads naturally, like a genuinely different way to say it -- not the \
original with one word swapped

Respond with ONLY a JSON object: {{"title": "..."}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.split("\n", 1)[-1] if "\n" in raw_text else raw_text
    try:
        return json.loads(raw_text)["title"][:100]
    except (json.JSONDecodeError, KeyError):
        return title  # fall back to original if parsing fails


def dedupe_titles(client: anthropic.Anthropic, rows: list[dict], max_attempts: int = 3) -> list[dict]:
    """Reword any titles that exactly duplicate an earlier title in the batch
    (case-insensitive), since Pinterest's bulk CSV upload rejects duplicates."""
    used_titles: set[str] = set()
    for row in rows:
        title = row["Title"]
        key = title.strip().lower()
        if key in used_titles:
            print(f"  Duplicate title found, rewording: \"{title}\"")
            candidate = title
            for _ in range(max_attempts):
                candidate = rephrase_title(client, title, used_titles)
                if candidate.strip().lower() not in used_titles:
                    break
            title = candidate
            row["Title"] = title
            print(f"    -> \"{title}\"")
        used_titles.add(title.strip().lower())
    return rows


def build_schedule(n: int, start_date: datetime.date, posts_per_day: int):
    """Yield an ISO publish-date string for each of n items, evenly spaced."""
    # Spread evenly across the day if 4 or fewer/day; otherwise every 2 hours.
    day_start_hour = 9
    hour_step = max(1, 8 // max(posts_per_day - 1, 1)) if posts_per_day > 1 else 0

    for i in range(n):
        day_offset = i // posts_per_day
        slot = i % posts_per_day
        pub_date = start_date + datetime.timedelta(days=day_offset)
        hour = day_start_hour + slot * hour_step
        hour = min(hour, 23)
        yield f"{pub_date.isoformat()}T{hour:02d}:00:00"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-dir", default=None, type=Path,
                         help="Folder of pin images. Default: images/ or setup value.")
    parser.add_argument("--board", default=None,
                         help="Pinterest board name. Default: value from setup.")
    parser.add_argument("--url-prefix", default=None,
                         help="Public URL folder for those images. Default: setup value.")
    parser.add_argument("--link", default="",
                         help="Destination URL to fill into the Link column for every pin")
    parser.add_argument("--posts-per-day", type=int, default=3)
    parser.add_argument("--start-date", default=datetime.date.today().isoformat(),
                         help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--output", default="pinterest_bulk_upload.csv", type=Path)
    parser.add_argument("--extensions", default=".png,.jpg,.jpeg",
                         help="Comma-separated list of image extensions to include")
    parser.add_argument("--api-key", default=None,
                         help="Anthropic API key. If omitted, falls back to the "
                              "ANTHROPIC_API_KEY env var, then "
                              "~/.config/anthropic/config.json -- if none of those "
                              "exist you'll be prompted once and it'll be saved "
                              "for next time")
    parser.add_argument("--allow-duplicate-titles", action="store_true",
                         help="Skip the automatic title-dedup pass. Only use this "
                              "if you plan to schedule the rows manually in "
                              "Pinterest's UI instead of bulk-uploading the CSV -- "
                              "bulk upload rejects duplicate titles.")
    args = parser.parse_args()
    saved = load_config()
    images_dir = args.images_dir or Path(config_value(saved, "images_dir", "images"))
    board = args.board or config_value(saved, "board_name")
    url_prefix = args.url_prefix or config_value(saved, "url_prefix")
    if not board:
        sys.exit("No board name. Run python scripts/setup.py or pass --board.")
    if not url_prefix:
        sys.exit("No image URL prefix. Run python scripts/setup.py or pass --url-prefix.")

    exts = tuple(e.strip().lower() for e in args.extensions.split(","))
    if not images_dir.exists():
        sys.exit(f"Image folder not found: {images_dir}. Create it and add PNG/JPG files.")
    images = sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in exts and p.is_file()
    )
    if not images:
        sys.exit(f"No images found in {images_dir} with extensions {exts}")

    start_date = datetime.date.fromisoformat(args.start_date)
    api_key = load_api_key(args.api_key)
    client = anthropic.Anthropic(api_key=api_key)

    rows = []
    print(f"Analyzing {len(images)} images with Claude...")
    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {path.name}")
        meta = analyze_image(client, path)
        description = meta.get("description", "")[:500]
        if len(description) < 150:
            print(f"  ! Description is short ({len(description)} chars) -- "
                  f"may under-perform in Pinterest search")
        rows.append({
            "Title": meta.get("title", path.stem)[:100],
            "Media URL": url_prefix.rstrip("/") + "/" + path.name,
            "Pinterest board": board,
            "Thumbnail": "",
            "Description": description,
            "Link": args.link,
            "Publish date": "",  # filled in below
            "Keywords": meta.get("keywords", ""),
        })

    if not args.allow_duplicate_titles:
        print("\nChecking for duplicate titles (Pinterest's bulk CSV upload "
              "rejects these)...")
        rows = dedupe_titles(client, rows)

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
