"""Unit tests for etsy_ops.py -- price/image parsing and pagination.
No network access, Etsy's HTTP layer is mocked.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import etsy_ops  # noqa: E402


class FormatPriceTests(unittest.TestCase):
    def test_usd_gets_dollar_sign(self):
        price = {"amount": 4200, "divisor": 100, "currency_code": "USD"}
        self.assertEqual(etsy_ops.format_price(price), "$42.00")

    def test_other_currency_gets_code_prefix(self):
        price = {"amount": 4200, "divisor": 100, "currency_code": "GBP"}
        self.assertEqual(etsy_ops.format_price(price), "GBP 42.00")

    def test_none_price_is_empty_string(self):
        self.assertEqual(etsy_ops.format_price(None), "")

    def test_missing_amount_is_empty_string(self):
        self.assertEqual(etsy_ops.format_price({"divisor": 100}), "")


class PrimaryImageUrlTests(unittest.TestCase):
    def test_picks_rank_one_even_if_not_first_in_list(self):
        images = [
            {"rank": 2, "url_fullxfull": "https://example.com/2.jpg"},
            {"rank": 1, "url_fullxfull": "https://example.com/1.jpg"},
        ]
        self.assertEqual(etsy_ops.primary_image_url(images), "https://example.com/1.jpg")

    def test_empty_list_is_empty_string(self):
        self.assertEqual(etsy_ops.primary_image_url([]), "")

    def test_missing_rank_falls_back_to_first(self):
        images = [{"url_fullxfull": "https://example.com/only.jpg"}]
        self.assertEqual(etsy_ops.primary_image_url(images), "https://example.com/only.jpg")


class HeadersTests(unittest.TestCase):
    def test_no_access_token_omits_authorization_header(self):
        headers = etsy_ops._headers("key", "secret")
        self.assertEqual(headers["x-api-key"], "key:secret")
        self.assertNotIn("Authorization", headers)

    def test_access_token_adds_bearer_authorization_header(self):
        headers = etsy_ops._headers("key", "secret", "token-abc")
        self.assertEqual(headers["Authorization"], "Bearer token-abc")


class FindShopIdTests(unittest.TestCase):
    def test_returns_first_result_shop_id(self):
        with mock.patch.object(etsy_ops, "_get", return_value={"results": [{"shop_id": 12345}]}):
            self.assertEqual(etsy_ops.find_shop_id("key", "secret", "MyShop"), "12345")

    def test_no_results_raises_etsy_error(self):
        with mock.patch.object(etsy_ops, "_get", return_value={"results": []}):
            with self.assertRaises(etsy_ops.EtsyError):
                etsy_ops.find_shop_id("key", "secret", "NoSuchShop")


def _raw_listing(listing_id: int) -> dict:
    return {
        "listing_id": listing_id, "title": f"Item {listing_id}", "description": "",
        "tags": [], "price": None, "url": f"https://etsy.com/listing/{listing_id}",
        "images": [],
    }


class ListActiveListingsTests(unittest.TestCase):
    def test_stops_once_a_page_comes_back_shorter_than_the_page_size(self):
        # A full first page (== PAGE_SIZE) means there might be more; a
        # shorter second page means that was the last one.
        page_one = {"results": [_raw_listing(1), _raw_listing(2)]}
        page_two = {"results": [_raw_listing(3)]}
        calls = []

        def fake_get(api_key, shared_secret, path, params, access_token=""):
            calls.append((params["offset"], access_token))
            return page_one if params["offset"] == 0 else page_two

        with mock.patch.object(etsy_ops, "_get", fake_get), \
             mock.patch.object(etsy_ops, "PAGE_SIZE", 2):
            listings = etsy_ops.list_active_listings("key", "secret", "999", "token-abc")

        self.assertEqual([l["listing_id"] for l in listings], [1, 2, 3])
        self.assertEqual(calls, [(0, "token-abc"), (2, "token-abc")])

    def test_full_first_page_only_stops_without_a_second_call(self):
        page_one = {"results": [_raw_listing(1), _raw_listing(2)]}
        calls = []

        def fake_get(api_key, shared_secret, path, params, access_token=""):
            calls.append(params["offset"])
            return page_one

        with mock.patch.object(etsy_ops, "_get", fake_get), \
             mock.patch.object(etsy_ops, "PAGE_SIZE", 5):
            listings = etsy_ops.list_active_listings("key", "secret", "999", "token-abc")

        self.assertEqual([l["listing_id"] for l in listings], [1, 2])
        self.assertEqual(calls, [0])

    def test_empty_shop_returns_empty_list(self):
        with mock.patch.object(etsy_ops, "_get", return_value={"results": []}):
            self.assertEqual(
                etsy_ops.list_active_listings("key", "secret", "999", "token-abc"), []
            )


if __name__ == "__main__":
    unittest.main()
