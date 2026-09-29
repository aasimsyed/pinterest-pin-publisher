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
    _object_key,
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


class WranglerEnvTests(unittest.TestCase):
    def test_saved_account_id_is_added_to_env(self):
        with mock.patch.object(cloudflare_ops, "load_config", lambda: {"account_id": "abc123"}):
            env = cloudflare_ops._wrangler_env()
        self.assertEqual(env["CLOUDFLARE_ACCOUNT_ID"], "abc123")

    def test_no_saved_account_id_leaves_env_untouched(self):
        with mock.patch.object(cloudflare_ops, "load_config", lambda: {}):
            env = cloudflare_ops._wrangler_env()
        self.assertNotIn("CLOUDFLARE_ACCOUNT_ID", env)

    def test_run_wrangler_passes_env_to_subprocess(self):
        captured = {}

        def fake_run(cmd, cwd, input, capture_output, text, env):
            captured["env"] = env
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(cloudflare_ops, "load_config", lambda: {"account_id": "abc123"}), \
             mock.patch.object(cloudflare_ops.Path, "exists", return_value=True), \
             mock.patch.object(subprocess, "run", fake_run):
            cloudflare_ops.run_wrangler(["whoami"])

        self.assertEqual(captured["env"]["CLOUDFLARE_ACCOUNT_ID"], "abc123")


class InvokeWranglerTests(unittest.TestCase):
    def test_uses_the_pinned_local_binary_not_npx(self):
        captured = {}

        def fake_run(cmd, cwd, input, capture_output, text, env):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(cloudflare_ops, "load_config", lambda: {}), \
             mock.patch.object(cloudflare_ops.Path, "exists", return_value=True), \
             mock.patch.object(subprocess, "run", fake_run):
            cloudflare_ops._invoke_wrangler(["whoami"])

        self.assertEqual(captured["cmd"], [str(cloudflare_ops.WRANGLER_BIN), "whoami"])
        self.assertNotIn("npx", captured["cmd"])

    def test_missing_binary_raises_before_running_anything(self):
        with mock.patch.object(cloudflare_ops.Path, "exists", return_value=False), \
             mock.patch.object(subprocess, "run") as run:
            with self.assertRaises(cloudflare_ops.WranglerMissingError) as ctx:
                cloudflare_ops._invoke_wrangler(["whoami"])
        run.assert_not_called()
        self.assertIn("Setup", str(ctx.exception))

    def test_missing_binary_is_a_wrangler_error_too(self):
        self.assertTrue(issubclass(cloudflare_ops.WranglerMissingError, cloudflare_ops.WranglerError))


class RunWranglerAutoReloginTests(unittest.TestCase):
    def test_auth_error_triggers_relogin_then_retries_original_command(self):
        calls = []

        def fake_invoke(args, input_text=""):
            calls.append(list(args))
            if args == ["login"]:
                return subprocess.CompletedProcess(args, 0, stdout="Successfully logged in.", stderr="")
            if len([c for c in calls if c == args]) == 1:
                return subprocess.CompletedProcess(
                    args, 1, stdout="",
                    stderr="The given account is not authorized to access this service [code: 7403]",
                )
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        with mock.patch.object(cloudflare_ops, "_invoke_wrangler", fake_invoke), \
             mock.patch("builtins.print"):
            result = cloudflare_ops.run_wrangler(["whoami"])

        self.assertEqual(calls, [["whoami"], ["login"], ["whoami"]])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ok")

    def test_non_auth_error_does_not_trigger_relogin(self):
        calls = []

        def fake_invoke(args, input_text=""):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="Something else went wrong")

        with mock.patch.object(cloudflare_ops, "_invoke_wrangler", fake_invoke), \
             mock.patch("builtins.print"):
            with self.assertRaises(cloudflare_ops.WranglerError):
                cloudflare_ops.run_wrangler(["whoami"])

        self.assertEqual(calls, [["whoami"]])

    def test_relogin_is_not_attempted_for_the_login_command_itself(self):
        calls = []

        def fake_invoke(args, input_text=""):
            calls.append(list(args))
            return subprocess.CompletedProcess(
                args, 1, stdout="", stderr="You are not authorized to access this service",
            )

        with mock.patch.object(cloudflare_ops, "_invoke_wrangler", fake_invoke), \
             mock.patch("builtins.print"):
            with self.assertRaises(cloudflare_ops.WranglerError):
                cloudflare_ops.run_wrangler(["login"])

        self.assertEqual(calls, [["login"]])


class ListAccountsTests(unittest.TestCase):
    def test_parses_every_account_row_from_whoami_table(self):
        sample = (
            "You are logged in with an OAuth Token, associated with the email a@b.com.\n"
            "┌──────────────────────────────┬──────────────────────────────────┐\n"
            "│ Account Name                  │ Account ID                        │\n"
            "├──────────────────────────────┼──────────────────────────────────┤\n"
            "│ Aasim.ss@gmail.com's Account  │ 950035267d1186d83269e8b8eb50e572 │\n"
            "├──────────────────────────────┼──────────────────────────────────┤\n"
            "│ Yourfrugalfriendetsy's Account│ cd25873e37a0a29723d8fe179427d78d │\n"
            "└──────────────────────────────┴──────────────────────────────────┘\n"
        )

        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(args, 0, stdout=sample, stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            accounts = cloudflare_ops.list_accounts()

        self.assertEqual(
            accounts,
            [
                {"name": "Aasim.ss@gmail.com's Account", "id": "950035267d1186d83269e8b8eb50e572"},
                {"name": "Yourfrugalfriendetsy's Account", "id": "cd25873e37a0a29723d8fe179427d78d"},
            ],
        )

    def test_single_account_table_returns_one_row(self):
        sample = (
            "┌──────────────────────────────┬──────────────────────────────────┐\n"
            "│ Account Name                  │ Account ID                        │\n"
            "├──────────────────────────────┼──────────────────────────────────┤\n"
            "│ Solo Account                  │ 950035267d1186d83269e8b8eb50e572 │\n"
            "└──────────────────────────────┴──────────────────────────────────┘\n"
        )

        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(args, 0, stdout=sample, stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            accounts = cloudflare_ops.list_accounts()

        self.assertEqual(accounts, [{"name": "Solo Account", "id": "950035267d1186d83269e8b8eb50e572"}])

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

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler), \
             mock.patch.object(cloudflare_ops.webbrowser, "open") as mock_open:
            with self.assertRaises(WranglerError) as ctx:
                cloudflare_ops.ensure_image_bucket()
        self.assertIn("R2 storage isn't turned on", str(ctx.exception))
        mock_open.assert_called_once()

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


class ExistingMediaFilenamesTests(unittest.TestCase):
    def test_returns_filenames_from_media_urls_any_status(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0,
                stdout='[{"results": ['
                       '{"media_url": "https://pub-abc.r2.dev/chili.png"}, '
                       '{"media_url": "https://pub-abc.r2.dev/Mom%27s%20Chili.png"}'
                       '], "success": true}]',
                stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            filenames = cloudflare_ops.existing_media_filenames()

        self.assertEqual(filenames, {"chili.png", "Mom's Chili.png"})

    def test_empty_queue_returns_empty_set(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0, stdout='[{"results": [], "success": true}]', stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            self.assertEqual(cloudflare_ops.existing_media_filenames(), set())


class ListQueueTests(unittest.TestCase):
    def test_default_status_filters_to_pending(self):
        captured = {}

        def fake_run_wrangler(args, input_text="", check=True):
            captured["command"] = args[args.index("--command") + 1]
            return subprocess.CompletedProcess(args, 0, stdout='[{"results": [], "success": true}]', stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            cloudflare_ops.list_queue()

        self.assertIn("WHERE status = 'pending'", captured["command"])

    def test_empty_status_omits_where_clause(self):
        captured = {}

        def fake_run_wrangler(args, input_text="", check=True):
            captured["command"] = args[args.index("--command") + 1]
            return subprocess.CompletedProcess(args, 0, stdout='[{"results": [], "success": true}]', stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            cloudflare_ops.list_queue(status="")

        self.assertNotIn("WHERE", captured["command"])

    def test_returns_rows_from_query_results(self):
        def fake_run_wrangler(args, input_text="", check=True):
            return subprocess.CompletedProcess(
                args, 0,
                stdout='[{"results": [{"id": 1, "title": "Pin A", "status": "pending", '
                       '"publish_at": "2026-08-15T09:00:00Z", "pinterest_pin_url": null, "link": null}], '
                       '"success": true}]',
                stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            rows = cloudflare_ops.list_queue()

        self.assertEqual(rows, [{
            "id": 1, "title": "Pin A", "status": "pending",
            "publish_at": "2026-08-15T09:00:00Z", "pinterest_pin_url": None, "link": None,
        }])


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
        self.assertIn("pinterest_pin_url = NULL", update_call[-1])

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


class ObjectKeyTests(unittest.TestCase):
    def test_filename_from_public_url(self):
        self.assertEqual(
            _object_key("https://pub-abc.r2.dev/chili.png"),
            "chili.png",
        )

    def test_decodes_percent_encoding(self):
        self.assertEqual(_object_key("https://pub-abc.r2.dev/Mom%27s%20Chili.png"), "Mom's Chili.png")

    def test_empty_url_is_empty_key(self):
        self.assertEqual(_object_key(""), "")


class PrunePublishedImagesTests(unittest.TestCase):
    def test_deletes_published_only_and_skips_keys_still_in_use(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            if args[-1] == "--json":
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=(
                        '[{"results": ['
                        '{"status": "published", "media_url": "https://pub.r2.dev/done.png"},'
                        '{"status": "published", "media_url": "https://pub.r2.dev/shared.png"},'
                        '{"status": "pending", "media_url": "https://pub.r2.dev/shared.png"},'
                        '{"status": "failed", "media_url": "https://pub.r2.dev/retry.png"}'
                        '], "success": true}]'
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            result = cloudflare_ops.prune_published_images()

        self.assertEqual(result["deleted"], ["done.png"])
        self.assertEqual(result["skipped"], ["shared.png"])
        delete_calls = [c for c in calls if c[:3] == ["r2", "object", "delete"]]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(delete_calls[0][3], "pin-publisher-images/done.png")

    def test_no_published_images_does_not_call_r2_delete(self):
        calls = []

        def fake_run_wrangler(args, input_text="", check=True):
            calls.append(args)
            return subprocess.CompletedProcess(
                args, 0,
                stdout='[{"results": [{"status": "pending", "media_url": "https://pub.r2.dev/a.png"}], "success": true}]',
                stderr="",
            )

        with mock.patch.object(cloudflare_ops, "run_wrangler", fake_run_wrangler):
            result = cloudflare_ops.prune_published_images()

        self.assertEqual(result, {"deleted": [], "skipped": []})
        self.assertFalse(any(c[:3] == ["r2", "object", "delete"] for c in calls))


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

    def test_random_order_true_is_included_in_query_string(self):
        captured = {}

        def fake_urlopen(request, timeout=60):
            captured["url"] = request.full_url
            return io.BytesIO(b'{"results": []}')

        with mock.patch("cloudflare_ops.urllib.request.urlopen", fake_urlopen):
            cloudflare_ops.trigger_publish("https://x.workers.dev", "secret", limit=3, random_order=True)

        self.assertIn("random=true", captured["url"])

    def test_random_order_defaults_to_false_in_query_string(self):
        captured = {}

        def fake_urlopen(request, timeout=60):
            captured["url"] = request.full_url
            return io.BytesIO(b'{"results": []}')

        with mock.patch("cloudflare_ops.urllib.request.urlopen", fake_urlopen):
            cloudflare_ops.trigger_publish("https://x.workers.dev", "secret", limit=3)

        self.assertIn("random=false", captured["url"])


if __name__ == "__main__":
    unittest.main()
