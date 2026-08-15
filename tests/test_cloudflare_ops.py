"""Unit tests for cloudflare_ops.py -- the parts that don't need a live
Cloudflare account: SQL escaping, wrangler-output parsing, and error
handling. All wrangler calls are mocked, no network access.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cloudflare_ops  # noqa: E402
from cloudflare_ops import D1_UUID_RE, R2_DEV_URL_RE, WranglerError, _sql_quote  # noqa: E402


class SqlQuoteTests(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(_sql_quote("hello"), "'hello'")

    def test_escapes_single_quotes(self):
        self.assertEqual(_sql_quote("Mom's Recipe"), "'Mom''s Recipe'")

    def test_none_becomes_null(self):
        self.assertEqual(_sql_quote(None), "NULL")

    def test_empty_string_becomes_null(self):
        self.assertEqual(_sql_quote(""), "NULL")

    def test_sql_injection_attempt_is_fully_escaped(self):
        malicious = "x'); DROP TABLE pin_queue; --"
        quoted = _sql_quote(malicious)
        # Every literal ' must be doubled, and the value must stay inside
        # one pair of outer quotes (no early close-and-reopen).
        self.assertTrue(quoted.startswith("'") and quoted.endswith("'"))
        inner = quoted[1:-1]
        self.assertEqual(inner.replace("''", ""), malicious.replace("'", ""))


class WranglerOutputRegexTests(unittest.TestCase):
    def test_d1_uuid_extracted_from_create_output(self):
        sample = (
            "Successfully created DB 'pin-publisher-db'\n\n"
            "[[d1_databases]]\n"
            'binding = "DB"\n'
            'database_name = "pin-publisher-db"\n'
            'database_id = "e259f6d1-7847-4b48-a78d-1e0465f3117d"\n'
        )
        match = D1_UUID_RE.search(sample)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "e259f6d1-7847-4b48-a78d-1e0465f3117d")

    def test_r2_dev_url_extracted_from_enable_output(self):
        sample = "Public access is enabled at https://pub-abc123def456.r2.dev"
        match = R2_DEV_URL_RE.search(sample)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(0), "https://pub-abc123def456.r2.dev")

    def test_r2_dev_url_absent_returns_no_match(self):
        self.assertIsNone(R2_DEV_URL_RE.search("bucket created, no public url yet"))


class InsertPinRowsTests(unittest.TestCase):
    def test_one_insert_statement_per_row_with_escaping_and_cleanup(self):
        captured = {}

        def fake_run_wrangler(args, input_text="", check=True):
            file_path = args[args.index("--file") + 1]
            captured["sql"] = Path(file_path).read_text()
            captured["path"] = file_path
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            cloudflare_ops.insert_pin_rows([
                {
                    "title": "Mom's Chili", "media_url": "https://x/1.png", "board_id": "1",
                    "description": "d", "link": "https://x/post",
                    "publish_at": "2026-01-01T09:00:00Z", "keywords": "chili,soup",
                },
                {
                    "title": "Second", "media_url": "https://x/2.png", "board_id": "1",
                    "description": "", "link": "",
                    "publish_at": "2026-01-02T09:00:00Z", "keywords": "",
                },
            ])

        self.assertEqual(captured["sql"].count("INSERT INTO pin_queue"), 2)
        self.assertIn("Mom''s Chili", captured["sql"])
        self.assertFalse(Path(captured["path"]).exists(), "temp SQL file should be deleted after use")


class EnsureImageBucketTests(unittest.TestCase):
    def test_r2_not_enabled_raises_friendly_error(self):
        def fake_run_wrangler(args, input_text="", check=True):
            if args[:3] == ["r2", "bucket", "create"]:
                return subprocess.CompletedProcess(
                    args, 1, stdout="",
                    stderr="Please enable R2 through the Cloudflare Dashboard. [code: 10042]",
                )
            raise AssertionError(f"unexpected wrangler call: {args}")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            with self.assertRaises(WranglerError) as ctx:
                cloudflare_ops.ensure_image_bucket()
        self.assertIn("R2 storage isn't turned on", str(ctx.exception))

    def test_existing_public_url_is_reused_without_enabling_again(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            if args[:3] == ["r2", "bucket", "create"]:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="already exists")
            if args[:4] == ["r2", "bucket", "dev-url", "get"]:
                return subprocess.CompletedProcess(
                    args, 0, stdout="https://pub-existing123.r2.dev is enabled", stderr="",
                )
            raise AssertionError(f"unexpected wrangler call: {args}")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            url = cloudflare_ops.ensure_image_bucket()

        self.assertEqual(url, "https://pub-existing123.r2.dev")
        self.assertFalse(any(a[:4] == ["r2", "bucket", "dev-url", "enable"] for a in calls))


if __name__ == "__main__":
    unittest.main()
