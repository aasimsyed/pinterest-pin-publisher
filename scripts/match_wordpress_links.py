#!/usr/bin/env python3
"""
match_wordpress_links.py

Fetches published posts from your WordPress REST API and asks Claude to
match each pin title to the best permalink, then writes those into the
CSV Link column. Matching is by meaning, so it works across categories
(recipes, travel, etc.) without a synonym list.

WordPress post data is public at /wp-json/wp/v2/posts for published posts.

Usage:
    python scripts/match_wordpress_links.py
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import anthropic
from anthropic.types import MessageParam

from anthropic_auth import load_api_key
from app_config import config_value, load_config

WP_POSTS_ENDPOINT = "/wp-json/wp/v2/posts"
PER_PAGE = 100
REVIEW_COLUMNS = ("Suggested Link", "Match Confidence", "Match Post Title")
MODEL = "claude-sonnet-4-6"

MATCH_SYSTEM = """\
You match Pinterest pin titles to WordPress posts.

Return ONLY valid JSON:
{"matches": [{"title": "<exact pin title>", "link": "<exact post link>"}]}

Rules:
- Copy each pin title exactly as given.
- Choose link only from the provided posts. Never invent a URL.
- Match by meaning, not wording. Titles may use synonyms, extra adjectives,
  or a different category vocabulary (food, travel, holidays, etc.).
- Use title and slug as evidence.
- Prefer a unique post per pin. Reuse a link only if two pins are clearly
  about that same article.
- Include every pin exactly once.
"""


def fetch_all_posts(site_url: str) -> list[dict]:
    """Paginate through /wp-json/wp/v2/posts and return title/slug/link."""
    posts = []
    page = 1
    base = site_url.rstrip("/") + WP_POSTS_ENDPOINT

    while True:
        url = f"{base}?per_page={PER_PAGE}&page={page}&_fields=id,link,title,slug"
        request = urllib.request.Request(url, headers={"User-Agent": "pin-publisher/1.0"})
        try:
            with urllib.request.urlopen(request) as response:
                batch = json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code == 400 and page > 1:
                break
            raise RuntimeError(f"WordPress API request failed ({e.code}): {e.read().decode()}") from e

        if not batch:
            break

        for post in batch:
            posts.append({
                "title": html.unescape(post["title"]["rendered"]),
                "slug": post["slug"],
                "link": post["link"],
            })

        page += 1

    return posts


def parse_json_object(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.split("\n", 1)[-1] if "\n" in raw_text else raw_text
    return json.loads(raw_text)


def title_key(title: str) -> str:
    return " ".join(title.casefold().split())


def apply_matches(
    pin_titles: list[str],
    allowed_links: set[str],
    payload: dict,
) -> dict[str, str]:
    """Map pin titles to catalog links. Ignore invented URLs or unknown titles."""
    by_key = {title_key(title): title for title in pin_titles}
    assigned: dict[str, str] = {}
    for item in payload.get("matches", []):
        if not isinstance(item, dict):
            continue
        raw_title = item.get("title")
        link = item.get("link")
        if not isinstance(raw_title, str) or not isinstance(link, str):
            continue
        title = by_key.get(title_key(raw_title))
        if title is None or link not in allowed_links or title in assigned:
            continue
        assigned[title] = link
    return assigned


def ask_claude_for_matches(
    client: anthropic.Anthropic,
    pin_titles: list[str],
    posts: list[dict],
) -> dict[str, str]:
    allowed_links = {post["link"] for post in posts}
    user_payload = json.dumps(
        {"pins": pin_titles, "posts": posts},
        ensure_ascii=False,
    )
    messages: list[MessageParam] = [{"role": "user", "content": user_payload}]
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=MATCH_SYSTEM,
        messages=messages,
    )
    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    try:
        payload = parse_json_object(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude did not return valid JSON: {raw_text}") from e
    if not isinstance(payload, dict):
        raise RuntimeError(f"Claude JSON must be an object, got {type(payload).__name__}")
    return apply_matches(pin_titles, allowed_links, payload)


def match_all_links(
    client: anthropic.Anthropic,
    pin_titles: list[str],
    posts: list[dict],
) -> dict[str, str]:
    """Match every pin. Retry once with leftover pins and unused posts."""
    assigned = ask_claude_for_matches(client, pin_titles, posts)
    missing = [title for title in pin_titles if title not in assigned]
    if not missing:
        return assigned

    used_links = set(assigned.values())
    leftover_posts = [post for post in posts if post["link"] not in used_links] or posts
    print(f"Retrying {len(missing)} unmatched pin(s)...")
    assigned.update(ask_claude_for_matches(client, missing, leftover_posts))
    return assigned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=Path("pinterest_bulk_upload.csv"), type=Path,
                         help="CSV produced by generate_pinterest_csv.py")
    parser.add_argument("--site-url", default=None,
                         help="e.g. https://yourfrugalmom.com")
    parser.add_argument("--output", default=Path("pinterest_bulk_upload_with_links.csv"),
                         type=Path)
    parser.add_argument("--api-key", default=None,
                         help="Anthropic API key. Same resolution as "
                              "generate_pinterest_csv.py if omitted.")
    args = parser.parse_args()
    site_url = args.site_url or config_value(load_config(), "site_url")
    if not site_url:
        sys.exit("No website URL. Run python scripts/setup.py or pass --site-url.")

    print(f"Fetching published posts from {site_url}...")
    posts = fetch_all_posts(site_url)
    if not posts:
        sys.exit(f"No published posts found at {site_url}")
    print(f"Found {len(posts)} published posts.\n")

    with open(args.csv, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            sys.exit(f"No header row in {args.csv}")
        fieldnames = [name for name in reader.fieldnames if name not in REVIEW_COLUMNS]
        rows = list(reader)

    if not rows:
        sys.exit(f"No rows found in {args.csv}")

    pin_titles = [row["Title"] for row in rows]
    client = anthropic.Anthropic(api_key=load_api_key(args.api_key))
    print(f"Matching {len(pin_titles)} pin titles with Claude...")
    links_by_title = match_all_links(client, pin_titles, posts)

    filled = 0
    for row in rows:
        for extra in REVIEW_COLUMNS:
            row.pop(extra, None)
        link = links_by_title.get(row["Title"])
        if link:
            row["Link"] = link
            filled += 1
            print(f"  LINK  \"{row['Title']}\" -> {link}")
        else:
            print(f"  MISS  \"{row['Title']}\"")

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    missing = len(rows) - filled
    print(f"\nDone. {filled}/{len(rows)} links filled.")
    if missing:
        sys.exit(f"{missing} pin(s) had no valid match. Re-run or set Link by hand.")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
