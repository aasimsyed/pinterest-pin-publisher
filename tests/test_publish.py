"""Menu routing tests for publish.py. Action functions are mocked."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402


class RunPipelineTests(unittest.TestCase):
    def test_shuffle_flag_only_forwarded_to_generate_step(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_pipeline(shuffle=True)

        self.assertEqual(calls, [
            ("generate_pinterest_csv.py", ["--shuffle"]),
            ("match_wordpress_links.py", None),
            ("push_to_d1.py", None),
        ])

    def test_no_shuffle_forwards_no_extra_args(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append(extra_args)

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_pipeline(shuffle=False)

        self.assertEqual(calls, [None, None, None])


class MenuTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(publish, "print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enter_defaults_to_pipeline(self):
        with mock.patch.object(publish, "input", side_effect=["", "n"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=False)

    def test_choice_1_runs_pipeline(self):
        with mock.patch.object(publish, "input", side_effect=["1", "n"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=False)

    def test_choice_1_shuffle_yes_passes_shuffle_true(self):
        with mock.patch.object(publish, "input", side_effect=["1", "y"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=True)

    def test_choice_2_asks_how_many_then_run_now(self):
        with mock.patch.object(publish, "input", side_effect=["2", "1", "n"]):
            with mock.patch.object(publish, "run_now") as run_now:
                publish.menu()
        run_now.assert_called_once_with(1, shuffle=False)

    def test_choice_2_defaults_to_three(self):
        with mock.patch.object(publish, "input", side_effect=["2", "", "n"]):
            with mock.patch.object(publish, "run_now") as run_now:
                publish.menu()
        run_now.assert_called_once_with(3, shuffle=False)

    def test_choice_2_shuffle_yes_passes_shuffle_true(self):
        with mock.patch.object(publish, "input", side_effect=["2", "2", "y"]):
            with mock.patch.object(publish, "run_now") as run_now:
                publish.menu()
        run_now.assert_called_once_with(2, shuffle=True)

    def test_choice_3_dedupes_pending_only(self):
        with mock.patch.object(publish, "input", return_value="3"):
            with mock.patch.object(publish, "dedupe") as dedupe:
                publish.menu()
        dedupe.assert_called_once_with(all_statuses=False)

    def test_choice_4_resets_with_confirm(self):
        with mock.patch.object(publish, "input", return_value="4"):
            with mock.patch.object(publish, "reset") as reset:
                publish.menu()
        reset.assert_called_once_with(skip_confirm=False)

    def test_choice_5_clears_with_confirm(self):
        with mock.patch.object(publish, "input", return_value="5"):
            with mock.patch.object(publish, "clear") as clear:
                publish.menu()
        clear.assert_called_once_with(skip_confirm=False)

    def test_choice_6_prunes_with_confirm(self):
        with mock.patch.object(publish, "input", return_value="6"):
            with mock.patch.object(publish, "prune_images") as prune:
                publish.menu()
        prune.assert_called_once_with(skip_confirm=False)

    def test_choice_7_shows_queue(self):
        with mock.patch.object(publish, "input", return_value="7"):
            with mock.patch.object(publish, "show_queue") as show:
                publish.menu()
        show.assert_called_once_with(all_statuses=False)

    def test_choice_0_does_nothing(self):
        with mock.patch.object(publish, "input", return_value="0"):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_not_called()

    def test_bad_choice_exits(self):
        with mock.patch.object(publish, "input", return_value="9"):
            with self.assertRaises(SystemExit):
                publish.menu()


if __name__ == "__main__":
    unittest.main()
