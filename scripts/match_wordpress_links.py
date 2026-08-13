#!/usr/bin/env python3
"""
match_wordpress_links.py

Fetches every published post from your WordPress site's REST API and
fuzzy-matches each pin's title against your post titles, to suggest a
"Link" value for the Pinterest bulk-upload CSV -- instead of typing each
one in by hand.

WordPress exposes post data (including the permalink) publicly at
/wp-json/wp/v2/posts with no authentication needed, as long as the posts
are published (not draft/private).

This does NOT silently overwrite your CSV's Link column. It adds three new
columns so you can review before trusting the match:
    Suggested Link       -- the best-matching post's permalink
    Match Confidence      -- 0-100, how sure the match is
    Match Post Title       -- the WordPress post title it matched against

Only matches at or above --auto-fill-threshold get copied into the actual
Link column automatically; everything else is left for you to check the
suggestion and copy it over yourself (or fix it).

Usage:
    python scripts/match_wordpress_links.py \
        --csv pinterest_bulk_upload.csv \
        --site-url https://yourfrugalmom.com \
        --output pinterest_bulk_upload_with_links.csv \
        --auto-fill-threshold 85
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

WP_POSTS_ENDPOINT = "/wp-json/wp/v2/posts"
PER_PAGE = 100

# Strip a leading pin-style count ("25+", "10", "12 ") and common filler
# words before comparing titles -- WordPress post titles usually won't
# repeat the Pinterest-style "10 Easy ..." framing verbatim.
LEADING_NUMBER_RE = re.compile(r"^\s*\d+\+?\s*", re.IGNORECASE)
FILLER_WORDS = {
    "easy", "cheap", "budget", "budget-friendly", "low-cost", "quick",
    "simple", "the", "for", "a", "an", "and", "to", "of", "you", "can",
}


def normalize_title(title: str) -> str:
    title = LEADING_NUMBER_RE.sub("", title)
    title = re.sub(r"[^\w\s]", " ", title.lower())
    words = [w for w in title.split() if w not in FILLER_WORDS]
    return " ".join(words)


def fetch_all_posts(site_url: str) -> list[dict]:
    """Paginate through /wp-json/wp/v2/posts and return id/title/link for each."""
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
                break  # WP returns 400 "invalid page number" past the last page
            raise RuntimeError(f"WordPress API request failed ({e.code}): {e.read().decode()}") from e

        if not batch:
            break

        for post in batch:
            posts.append({
                "id": post["id"],
                "link": post["link"],
                "title": html.unescape(post["title"]["rendered"]),
                "slug": post["slug"],
            })

        page += 1

    return posts


def best_match(pin_title: str, posts: list[dict]) -> tuple[dict | None, float]:
    """Return (best_matching_post, confidence_0_to_100)."""
    target = normalize_title(pin_title)
    if not target:
        return None, 0.0

    best_post, best_score = None, 0.0
    for post in posts:
        candidate = normalize_title(post["title"])
        score = difflib.SequenceMatcher(None, target, candidate).ratio()
        # Also check against the slug (dashes -> spaces), since some posts'
        # slugs are more stable/keyword-focused than the display title.
        slug_candidate = normalize_title(post["slug"].replace("-", " "))
        slug_score = difflib.SequenceMatcher(None, target, slug_candidate).ratio()
        score = max(score, slug_score)

        if score > best_score:
            best_post, best_score = post, score

    return best_post, round(best_score * 100, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path,
                         help="CSV produced by generate_pinterest_csv.py")
    parser.add_argument("--site-url", required=True,
                         help="e.g. https://yourfrugalmom.com")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--auto-fill-threshold", type=float, default=85.0,
                         help="Confidence (0-100) at or above which the Link "
                              "column is filled automatically. Below this, "
                              "Link is left as-is and only the Suggested "
                              "Link column is filled in for you to review.")
    args = parser.parse_args()

    print(f"Fetching published posts from {args.site_url}...")
    posts = fetch_all_posts(args.site_url)
    print(f"Found {len(posts)} published posts.\n")

    with open(args.csv, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + ["Suggested Link", "Match Confidence", "Match Post Title"]
        rows = list(reader)

    auto_filled, needs_review = 0, 0
    for row in rows:
        post, confidence = best_match(row["Title"], posts)
        if post:
            row["Suggested Link"] = post["link"]
            row["Match Confidence"] = confidence
            row["Match Post Title"] = post["title"]
            if confidence >= args.auto_fill_threshold and not row.get("Link", "").strip():
                row["Link"] = post["link"]
                auto_filled += 1
                print(f"  [{confidence:5.1f}%] AUTO-FILLED  \"{row['Title']}\" -> {post['link']}")
            else:
                needs_review += 1
                print(f"  [{confidence:5.1f}%] REVIEW       \"{row['Title']}\" -> {post['link']}")
        else:
            row["Suggested Link"] = ""
            row["Match Confidence"] = 0
            row["Match Post Title"] = ""
            needs_review += 1
            print(f"  [  0.0%] NO MATCH     \"{row['Title']}\"")

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {auto_filled} links auto-filled (>= {args.auto_fill_threshold}% "
          f"confidence), {needs_review} need your review.")
    print(f"Wrote {args.output}")
    print("\nOnce you've checked the 'Suggested Link' / 'Match Confidence' columns, "
          "delete those extra columns before uploading to Pinterest.")


if __name__ == "__main__":
    main()
