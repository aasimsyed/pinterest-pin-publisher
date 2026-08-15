"""Unit tests for cloudflare_ops.py -- the parts that don't need a live
Cloudflare account: SQL escaping, wrangler-output parsing, and error
handling. All wrangler calls are mocked, no network access.
"""

import io
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cloudflare_ops  # noqa: E402
from cloudflare_ops import (  # noqa: E402
    D1_UUID_RE,
    R2_DEV_URL_RE,
    WORKER_URL_RE,
    PublishTriggerError,
    WranglerError,
    _sql_quote,
)


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

    def test_worker_url_extracted_from_deploy_output(self):
        sample = (
            "Uploaded pinterest-pin-publisher (1.23 sec)\n"
            "Published pinterest-pin-publisher (2.34 sec)\n"
            "  https://pinterest-pin-publisher.myaccount.workers.dev\n"
            "Current Deployment ID: abc123\n"
        )
        match = WORKER_URL_RE.search(sample)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(0), "https://pinterest-pin-publisher.myaccount.workers.dev")


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


class ExistingTitlesTests(unittest.TestCase):
    def test_returns_lowercased_titles_from_query_results(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0,
                stdout='[{"results": [{"title": "Mom'"'"'s Chili"}, {"title": "Second Pin"}], "success": true}]',
                stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            titles = cloudflare_ops.existing_titles()

        self.assertEqual(titles, {"mom's chili", "second pin"})

    def test_empty_queue_returns_empty_set(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0, stdout='[{"results": [], "success": true}]', stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            self.assertEqual(cloudflare_ops.existing_titles(), set())


class DedupeQueueTests(unittest.TestCase):
    def test_keeps_oldest_row_and_deletes_newer_duplicates(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            if "SELECT" in args[-2]:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=(
                        '[{"results": ['
                        '{"id": 1, "title": "Chili Recipe", "status": "pending"},'
                        '{"id": 2, "title": "Other Pin", "status": "pending"},'
                        '{"id": 3, "title": "chili recipe", "status": "pending"},'
                        '{"id": 4, "title": "Chili Recipe ", "status": "pending"}'
                        '], "success": true}]'
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            removed = cloudflare_ops.dedupe_queue()

        self.assertEqual([row["id"] for row in removed], [3, 4])
        delete_call = calls[-1]
        self.assertIn("DELETE FROM pin_queue WHERE id IN (3, 4)", delete_call[-1])

    def test_no_duplicates_deletes_nothing(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            return subprocess.CompletedProcess(
                args, 0,
                stdout='[{"results": [{"id": 1, "title": "Unique", "status": "pending"}], "success": true}]',
                stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            removed = cloudflare_ops.dedupe_queue()

        self.assertEqual(removed, [])
        self.assertEqual(len(calls), 1, "should not issue a DELETE when nothing is duplicated")

    def test_pending_only_filters_query_by_status(self):
        def fake_run_wrangler(args, input_text="", check=True):
            self.assertIn("WHERE status = 'pending'", args[-2])
            return subprocess.CompletedProcess(args, 0, stdout='[{"results": [], "success": true}]', stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            cloudflare_ops.dedupe_queue(pending_only=True)

    def test_all_statuses_omits_status_filter(self):
        def fake_run_wrangler(args, input_text="", check=True):
            self.assertNotIn("WHERE", args[-2])
            return subprocess.CompletedProcess(args, 0, stdout='[{"results": [], "success": true}]', stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            cloudflare_ops.dedupe_queue(pending_only=False)


class DeployWorkerTests(unittest.TestCase):
    def test_returns_workers_dev_url_from_output(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0, stdout="Published foo\n  https://foo.bar.workers.dev\n", stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            self.assertEqual(cloudflare_ops.deploy_worker(), "https://foo.bar.workers.dev")

    def test_returns_none_when_url_not_found(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(args, 0, stdout="Published foo\n", stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            self.assertIsNone(cloudflare_ops.deploy_worker())


class ResetQueueTests(unittest.TestCase):
    def test_deletes_pending_and_failed_resets_published(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            if args[-1] == "--json":
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=(
                        '[{"results": ['
                        '{"id": 1, "status": "pending"},'
                        '{"id": 2, "status": "failed"},'
                        '{"id": 3, "status": "published"}'
                        '], "success": true}]'
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            counts = cloudflare_ops.reset_queue()

        self.assertEqual(counts, {"cleared": 2, "reset": 1})
        delete_call = next(c for c in calls if "DELETE" in c[-1])
        update_call = next(c for c in calls if "UPDATE" in c[-1])
        self.assertIn("DELETE FROM pin_queue WHERE id IN (1, 2)", delete_call[-1])
        self.assertIn("WHERE id IN (3)", update_call[-1])
        self.assertIn("status = 'pending'", update_call[-1])

    def test_empty_queue_issues_no_delete_or_update(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout='[{"results": [], "success": true}]', stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            counts = cloudflare_ops.reset_queue()

        self.assertEqual(counts, {"cleared": 0, "reset": 0})
        self.assertEqual(len(calls), 1)


class ClearQueueTests(unittest.TestCase):
    def test_deletes_every_row_and_returns_count(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            if args[-1] == "--json":
                return subprocess.CompletedProcess(
                    args, 0, stdout='[{"results": [{"n": 4}], "success": true}]', stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            n = cloudflare_ops.clear_queue()

        self.assertEqual(n, 4)
        self.assertIn("DELETE FROM pin_queue;", calls[-1][-1])

    def test_empty_queue_issues_no_delete(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            return subprocess.CompletedProcess(
                args, 0, stdout='[{"results": [{"n": 0}], "success": true}]', stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            n = cloudflare_ops.clear_queue()

        self.assertEqual(n, 0)
        self.assertEqual(len(calls), 1)


class WorkerUrlFromWranglerTests(unittest.TestCase):
    def test_extracts_url_from_deployments_list(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0,
                stdout="https://pinterest-pin-publisher.acct.workers.dev\nCreated: 2026-08-01\n",
                stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            self.assertEqual(
                cloudflare_ops.worker_url_from_wrangler(),
                "https://pinterest-pin-publisher.acct.workers.dev",
            )

    def test_returns_none_when_url_absent(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(args, 0, stdout="No deployments", stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            self.assertIsNone(cloudflare_ops.worker_url_from_wrangler())


class TriggerPublishTests(unittest.TestCase):
    def test_success_returns_parsed_json(self):
        fake_response = io.BytesIO(b'{"published": 1, "results": []}')

        with mock.patch("cloudflare_ops.urllib.request.urlopen", return_value=fake_response):
            result = cloudflare_ops.trigger_publish("https://x.workers.dev", "secret", limit=3)

        self.assertEqual(result, {"published": 1, "results": []})

    def test_http_error_raises_publish_trigger_error(self):
        error = urllib.error.HTTPError(
            "https://x.workers.dev/run", 401, "Unauthorized", {}, io.BytesIO(b"bad secret"),
        )
        with mock.patch("cloudflare_ops.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(PublishTriggerError) as ctx:
                cloudflare_ops.trigger_publish("https://x.workers.dev", "secret", limit=3)
        self.assertIn("401", str(ctx.exception))

    def test_url_error_raises_publish_trigger_error(self):
        error = urllib.error.URLError("name resolution failed")
        with mock.patch("cloudflare_ops.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(PublishTriggerError) as ctx:
                cloudflare_ops.trigger_publish("https://x.workers.dev", "secret", limit=3)
        self.assertIn("Could not reach", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
