"""Unit tests for generate_etsy_csv.py -- filtering already-posted
listings and Claude metadata parsing. No network access.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_etsy_csv as gen  # noqa: E402


def _listing(listing_id: int, **overrides) -> dict:
    base = {
        "listing_id": listing_id,
        "title": f"Listing {listing_id}",
        "description": "A handmade item.",
        "tags": ["handmade", "gift"],
        "price": "$20.00",
        "url": f"https://etsy.com/listing/{listing_id}",
        "image_url": f"https://example.com/{listing_id}.jpg",
    }
    base.update(overrides)
    return base


class FilterNewListingsTests(unittest.TestCase):
    def test_splits_already_posted_from_new(self):
        listings = [_listing(1), _listing(2), _listing(3)]
        already_posted = {"etsy-1.png", "etsy-3.png"}

        new, skipped = gen.filter_new_listings(listings, already_posted)

        self.assertEqual([l["listing_id"] for l in new], [2])
        self.assertEqual([l["listing_id"] for l in skipped], [1, 3])

    def test_nothing_already_posted_keeps_all_listings(self):
        listings = [_listing(1), _listing(2)]

        new, skipped = gen.filter_new_listings(listings, set())

        self.assertEqual(new, listings)
        self.assertEqual(skipped, [])

    def test_everything_already_posted_leaves_nothing_new(self):
        listings = [_listing(1), _listing(2)]
        already_posted = {"etsy-1.png", "etsy-2.png"}

        new, skipped = gen.filter_new_listings(listings, already_posted)

        self.assertEqual(new, [])
        self.assertEqual(skipped, listings)


class LimitListingsTests(unittest.TestCase):
    def test_no_limit_returns_all_listings(self):
        listings = [_listing(1), _listing(2), _listing(3)]
        self.assertEqual(gen.limit_listings(listings, None), listings)

    def test_limit_smaller_than_count_keeps_first_n(self):
        listings = [_listing(1), _listing(2), _listing(3)]
        result = gen.limit_listings(listings, 2)
        self.assertEqual([l["listing_id"] for l in result], [1, 2])

    def test_limit_larger_than_count_returns_all(self):
        listings = [_listing(1), _listing(2)]
        self.assertEqual(gen.limit_listings(listings, 50), listings)

    def test_limit_of_zero_returns_empty_list(self):
        listings = [_listing(1), _listing(2)]
        self.assertEqual(gen.limit_listings(listings, 0), [])


class GetAccessTokenTests(unittest.TestCase):
    def test_exits_when_no_refresh_token_saved(self):
        with mock.patch.object(gen, "save_config"), \
             mock.patch.object(gen, "print"):
            with self.assertRaises(SystemExit):
                gen.get_access_token("key123", {})

    def test_returns_access_token_and_persists_rotated_refresh_token(self):
        saved = {"etsy_refresh_token": "old-refresh"}
        with mock.patch.object(
            gen, "refresh_access_token",
            return_value={"access_token": "fresh-access", "refresh_token": "new-refresh"},
        ), mock.patch.object(gen, "save_config") as save_config, \
             mock.patch.object(gen, "print"):
            token = gen.get_access_token("key123", saved)

        self.assertEqual(token, "fresh-access")
        save_config.assert_called_once_with({"etsy_refresh_token": "new-refresh"})

    def test_refresh_error_exits_with_reconnect_message(self):
        saved = {"etsy_refresh_token": "old-refresh"}
        with mock.patch.object(gen, "refresh_access_token", side_effect=RuntimeError("boom")), \
             mock.patch.object(gen, "save_config"), \
             mock.patch.object(gen, "print"):
            with self.assertRaises(SystemExit):
                gen.get_access_token("key123", saved)

    def test_missing_access_token_in_response_exits(self):
        saved = {"etsy_refresh_token": "old-refresh"}
        with mock.patch.object(
            gen, "refresh_access_token", return_value={"refresh_token": "new-refresh"},
        ), mock.patch.object(gen, "save_config"), \
             mock.patch.object(gen, "print"):
            with self.assertRaises(SystemExit):
                gen.get_access_token("key123", saved)


class WritePinMetadataTests(unittest.TestCase):
    def _fake_client(self, raw_text: str):
        text_block = mock.Mock(type="text", text=raw_text)
        response = mock.Mock(content=[text_block])
        client = mock.Mock()
        client.messages.create.return_value = response
        return client

    def test_parses_valid_json_response(self):
        client = self._fake_client(
            '{"title": "Cute Mug", "description": "A great mug.", "keywords": "mug, gift"}'
        )
        result = gen.write_pin_metadata(client, _listing(1))
        self.assertEqual(result["title"], "Cute Mug")
        self.assertEqual(result["keywords"], "mug, gift")

    def test_strips_markdown_code_fences(self):
        client = self._fake_client('```json\n{"title": "Fenced", "description": "d", "keywords": "k"}\n```')
        result = gen.write_pin_metadata(client, _listing(1))
        self.assertEqual(result["title"], "Fenced")

    def test_invalid_json_falls_back_to_listing_text(self):
        client = self._fake_client("not json at all")
        listing = _listing(1, title="Original Title", description="Original description text.")
        result = gen.write_pin_metadata(client, listing)
        self.assertEqual(result["title"], "Original Title")
        self.assertEqual(result["description"], "Original description text.")
        self.assertEqual(result["keywords"], "")


if __name__ == "__main__":
    unittest.main()
