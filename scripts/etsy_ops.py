#!/usr/bin/env python3
"""
etsy_ops.py

Talks to Etsy's Open API v3 (https://api.etsy.com/v3/application) to read a
shop's active listings. Finding a shop by name works with just an API key,
but reading its listings needs an OAuth access token too (see
etsy_oauth.py) -- Etsy requires the listings_r scope even for a shop's own
active listings.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.etsy.com/v3/application"
PAGE_SIZE = 100


class EtsyError(RuntimeError):
    """Raised when an Etsy API call fails, with a message meant for a
    non-technical user rather than a raw stack trace."""


def _headers(api_key: str, shared_secret: str, access_token: str = "") -> dict:
    headers = {
        "x-api-key": f"{api_key}:{shared_secret}",
        "Accept": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _get(
    api_key: str, shared_secret: str, path: str, params: dict, access_token: str = "",
) -> dict:
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(url, headers=_headers(api_key, shared_secret, access_token))
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise EtsyError(f"Etsy API request failed ({e.code}): {body[:300]}") from e
    except urllib.error.URLError as e:
        raise EtsyError(f"Could not reach Etsy: {e.reason}") from e


def find_shop_id(api_key: str, shared_secret: str, shop_name: str) -> str:
    """Look up a shop's numeric ID from its name."""
    data = _get(api_key, shared_secret, "/shops", {"shop_name": shop_name, "limit": 1})
    results = data.get("results") or []
    if not results:
        raise EtsyError(f"No Etsy shop found named '{shop_name}'.")
    return str(results[0]["shop_id"])


def format_price(price: dict | None) -> str:
    """Turn Etsy's {amount, divisor, currency_code} into e.g. '$24.99'."""
    if not price:
        return ""
    amount = price.get("amount")
    divisor = price.get("divisor") or 1
    currency = price.get("currency_code", "")
    if amount is None:
        return ""
    value = amount / divisor
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.2f}"


def _unescape(text: str) -> str:
    """Etsy's title/description text comes back HTML-entity-escaped (e.g.
    "Galentine&#39;s" for "Galentine's") -- decode it so it reads right in
    the pin's title, description, and baked-in image text."""
    return html.unescape(text)


def primary_image_url(images: list[dict]) -> str:
    """The listing's main photo -- rank 1 if present, else the first one."""
    if not images:
        return ""
    ranked = sorted(images, key=lambda img: img.get("rank") or 999)
    return ranked[0].get("url_fullxfull", "")


def list_active_listings(
    api_key: str, shared_secret: str, shop_id: str, access_token: str,
) -> list[dict]:
    """Every active listing in the shop, simplified to just what this app
    needs: id, title, description, tags, price, link, and photo URL."""
    listings = []
    offset = 0
    while True:
        data = _get(
            api_key, shared_secret, f"/shops/{shop_id}/listings",
            {"state": "active", "limit": PAGE_SIZE, "offset": offset, "includes": "Images"},
            access_token,
        )
        batch = data.get("results") or []

        for listing in batch:
            listings.append({
                "listing_id": listing["listing_id"],
                "title": _unescape(listing.get("title") or ""),
                "description": _unescape(listing.get("description") or ""),
                "tags": [_unescape(tag) for tag in (listing.get("tags") or [])],
                "price": format_price(listing.get("price")),
                "url": listing.get("url") or "",
                "image_url": primary_image_url(listing.get("images") or []),
            })

        # A page shorter than what we asked for means there's nothing left.
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return listings
