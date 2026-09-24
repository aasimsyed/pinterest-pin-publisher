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
             mock.patch.object(publish.Path, "exists", return_value=True), \
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
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_pipeline(shuffle=False)

        self.assertEqual(calls, [None, None, None])

    def test_force_requeue_only_forwarded_to_generate_step(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_pipeline(force_requeue=True)

        self.assertEqual(calls, [
            ("generate_pinterest_csv.py", ["--force-requeue"]),
            ("match_wordpress_links.py", None),
            ("push_to_d1.py", None),
        ])

    def test_stops_early_when_generate_step_finds_nothing_new(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append(script_name)

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=False), \
             mock.patch.object(publish, "summarize") as summarize, \
             mock.patch.object(publish, "print"):
            publish.run_pipeline()

        self.assertEqual(calls, ["generate_pinterest_csv.py"])
        summarize.assert_not_called()

    def test_board_override_forwarded_to_both_generate_and_push_steps(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_pipeline(board_name="Other Board", board_id="42")

        self.assertEqual(calls, [
            ("generate_pinterest_csv.py", ["--board", "Other Board"]),
            ("match_wordpress_links.py", None),
            ("push_to_d1.py", ["--board-id", "42"]),
        ])

    def test_no_board_override_leaves_scripts_to_use_their_own_default(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append(extra_args)

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_pipeline()

        self.assertEqual(calls, [None, None, None])

    def test_csv_only_skips_the_push_to_d1_step(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append(script_name)

        with mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize") as summarize, \
             mock.patch.object(publish, "print"):
            publish.run_pipeline(csv_only=True)

        self.assertEqual(calls, ["generate_pinterest_csv.py", "match_wordpress_links.py"])
        summarize.assert_not_called()


class RunEtsyPipelineTests(unittest.TestCase):
    def test_exits_when_etsy_not_configured(self):
        with mock.patch.object(publish, "load_config", return_value={}), \
             mock.patch.object(publish, "print"):
            with self.assertRaises(SystemExit):
                publish.run_etsy_pipeline()

    def test_shuffle_and_force_requeue_forwarded_to_generate_step_only(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "load_config", return_value={"etsy_board_id": "999"}), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_etsy_pipeline(shuffle=True, force_requeue=True)

        self.assertEqual(calls[0], ("generate_etsy_csv.py", ["--shuffle", "--force-requeue"]))
        self.assertEqual(calls[1][0], "push_to_d1.py")
        self.assertIn("999", calls[1][1])

    def test_stops_early_when_no_new_listings(self):
        with mock.patch.object(publish, "load_config", return_value={"etsy_board_id": "999"}), \
             mock.patch.object(publish, "run_step") as run_step, \
             mock.patch.object(publish.Path, "exists", return_value=False), \
             mock.patch.object(publish, "summarize") as summarize, \
             mock.patch.object(publish, "print"):
            publish.run_etsy_pipeline()

        run_step.assert_called_once()
        summarize.assert_not_called()

    def test_ai_images_forwarded_to_generate_step_only(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "load_config", return_value={"etsy_board_id": "999"}), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_etsy_pipeline(ai_images=True)

        self.assertEqual(calls[0], ("generate_etsy_csv.py", ["--ai-images"]))
        self.assertEqual(calls[1][0], "push_to_d1.py")

    def test_limit_forwarded_to_generate_step_only(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "load_config", return_value={"etsy_board_id": "999"}), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_etsy_pipeline(limit=20)

        self.assertEqual(calls[0], ("generate_etsy_csv.py", ["--limit", "20"]))
        self.assertEqual(calls[1][0], "push_to_d1.py")

    def test_csv_only_skips_the_push_to_d1_step(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append(script_name)

        with mock.patch.object(publish, "load_config", return_value={}), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize") as summarize, \
             mock.patch.object(publish, "print"):
            publish.run_etsy_pipeline(csv_only=True)

        self.assertEqual(calls, ["generate_etsy_csv.py"])
        summarize.assert_not_called()

    def test_board_override_wins_over_saved_etsy_default(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish, "load_config", return_value={"etsy_board_id": "999"}), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.run_etsy_pipeline(board_name="Shop Finds", board_id="42")

        self.assertEqual(calls[0], ("generate_etsy_csv.py", ["--board", "Shop Finds"]))
        self.assertEqual(calls[1], ("push_to_d1.py", ["--csv", str(publish.SCRIPTS_DIR.parent / "etsy_bulk_upload.csv"), "--board-id", "42"]))


class PublishCsvTests(unittest.TestCase):
    def test_missing_file_exits(self):
        with mock.patch.object(publish.Path, "exists", return_value=False), \
             mock.patch.object(publish, "print"):
            with self.assertRaises(SystemExit):
                publish.publish_csv(Path("missing.csv"), None)

    def test_runs_push_to_d1_with_the_given_csv_and_board(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append((script_name, extra_args))

        with mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.publish_csv(Path("pins.csv"), "42")

        self.assertEqual(calls, [("push_to_d1.py", ["--csv", "pins.csv", "--board-id", "42"])])

    def test_no_board_id_omits_the_board_flag(self):
        calls = []

        def fake_run_step(label, script_name, extra_args=None):
            calls.append(extra_args)

        with mock.patch.object(publish.Path, "exists", return_value=True), \
             mock.patch.object(publish, "run_step", fake_run_step), \
             mock.patch.object(publish, "summarize"), \
             mock.patch.object(publish, "print"):
            publish.publish_csv(Path("pins.csv"), None)

        self.assertEqual(calls, [["--csv", "pins.csv"]])


class MainPublishCsvBoardPromptTests(unittest.TestCase):
    """--publish-csv used to silently fall back to the default board (e.g.
    the regular board instead of the Etsy one) with no way to tell. It
    should now ask interactively, same as menu choice 9, whenever no
    --board was given and this is running in a real terminal."""

    def _run_main(self, argv):
        with mock.patch.object(sys, "argv", ["publish.py", *argv]):
            publish.main()

    def test_isatty_and_no_board_flag_prompts_for_board(self):
        with mock.patch.object(publish, "load_config", return_value={}), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(publish, "choose_board", return_value=("Etsy Finds", "42")) as choose, \
             mock.patch.object(publish, "publish_csv") as publish_csv:
            self._run_main(["--publish-csv", "etsy_bulk_upload.csv"])
        choose.assert_called_once()
        publish_csv.assert_called_once_with(Path("etsy_bulk_upload.csv"), "42")

    def test_not_a_tty_does_not_prompt(self):
        with mock.patch.object(publish, "load_config", return_value={}), \
             mock.patch.object(sys.stdin, "isatty", return_value=False), \
             mock.patch.object(publish, "choose_board") as choose, \
             mock.patch.object(publish, "publish_csv") as publish_csv:
            self._run_main(["--publish-csv", "etsy_bulk_upload.csv"])
        choose.assert_not_called()
        publish_csv.assert_called_once_with(Path("etsy_bulk_upload.csv"), None)

    def test_explicit_board_flag_skips_the_prompt(self):
        boards = [{"name": "Etsy Finds", "id": "42"}]
        with mock.patch.object(publish, "load_config", return_value={"pinterest_boards": boards}), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(publish, "choose_board") as choose, \
             mock.patch.object(publish, "publish_csv") as publish_csv:
            self._run_main(["--publish-csv", "etsy_bulk_upload.csv", "--board", "Etsy Finds"])
        choose.assert_not_called()
        publish_csv.assert_called_once_with(Path("etsy_bulk_upload.csv"), "42")


class CachedBoardsTests(unittest.TestCase):
    def test_returns_the_list_when_present(self):
        boards = [{"name": "A", "id": "1"}]
        self.assertEqual(publish.cached_boards({"pinterest_boards": boards}), boards)

    def test_missing_key_is_empty_list(self):
        self.assertEqual(publish.cached_boards({}), [])

    def test_empty_list_is_empty_list(self):
        self.assertEqual(publish.cached_boards({"pinterest_boards": []}), [])

    def test_non_list_value_is_empty_list(self):
        self.assertEqual(publish.cached_boards({"pinterest_boards": "not a list"}), [])


class ChooseBoardTests(unittest.TestCase):
    BOARDS = [{"name": "Blog Pins", "id": "1"}, {"name": "Shop Finds", "id": "2"}]

    def test_no_cached_boards_returns_none_none_without_prompting(self):
        with mock.patch.object(publish, "input") as prompt, \
             mock.patch.object(publish, "print"):
            result = publish.choose_board({}, "1", "these pins")
        self.assertEqual(result, (None, None))
        prompt.assert_not_called()

    def test_pressing_enter_keeps_the_saved_default(self):
        saved = {"pinterest_boards": self.BOARDS}
        with mock.patch.object(publish, "input", return_value=""), \
             mock.patch.object(publish, "print"):
            name, board_id = publish.choose_board(saved, "2", "these pins")
        self.assertEqual((name, board_id), ("Shop Finds", "2"))

    def test_picking_a_different_number_overrides_the_default(self):
        saved = {"pinterest_boards": self.BOARDS}
        with mock.patch.object(publish, "input", return_value="1"), \
             mock.patch.object(publish, "print"):
            name, board_id = publish.choose_board(saved, "2", "these pins")
        self.assertEqual((name, board_id), ("Blog Pins", "1"))

    def test_invalid_number_exits(self):
        saved = {"pinterest_boards": self.BOARDS}
        with mock.patch.object(publish, "input", return_value="9"), \
             mock.patch.object(publish, "print"):
            with self.assertRaises(SystemExit):
                publish.choose_board(saved, "1", "these pins")


class ResolveBoardFlagTests(unittest.TestCase):
    BOARDS = [{"name": "Blog Pins", "id": "1"}, {"name": "Shop Finds", "id": "2"}]

    def test_no_flag_returns_none_none(self):
        self.assertEqual(publish.resolve_board_flag({"pinterest_boards": self.BOARDS}, None), (None, None))

    def test_matches_by_number(self):
        saved = {"pinterest_boards": self.BOARDS}
        self.assertEqual(publish.resolve_board_flag(saved, "2"), ("Shop Finds", "2"))

    def test_matches_by_name_case_insensitively(self):
        saved = {"pinterest_boards": self.BOARDS}
        self.assertEqual(publish.resolve_board_flag(saved, "blog pins"), ("Blog Pins", "1"))

    def test_unknown_value_exits(self):
        saved = {"pinterest_boards": self.BOARDS}
        with self.assertRaises(SystemExit):
            publish.resolve_board_flag(saved, "Nonexistent Board")


class ListBoardsCommandTests(unittest.TestCase):
    def test_prints_each_cached_board(self):
        boards = [{"name": "Blog Pins", "id": "1"}, {"name": "Shop Finds", "id": "2"}]
        with mock.patch.object(publish, "load_config", return_value={"pinterest_boards": boards}), \
             mock.patch.object(publish, "print") as printed:
            publish.list_boards_command()
        output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("Blog Pins", output)
        self.assertIn("Shop Finds", output)

    def test_no_cached_boards_tells_user_to_run_setup(self):
        with mock.patch.object(publish, "load_config", return_value={}), \
             mock.patch.object(publish, "print") as printed:
            publish.list_boards_command()
        output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("setup.py", output)


class MenuTests(unittest.TestCase):
    def setUp(self):
        self._patch(publish, "print")
        self._patch(publish, "load_config", return_value={})

    def _patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enter_defaults_to_pipeline(self):
        with mock.patch.object(publish, "input", side_effect=["", "n", "n"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=False, board_name=None, board_id=None, csv_only=False)

    def test_choice_1_runs_pipeline(self):
        with mock.patch.object(publish, "input", side_effect=["1", "n", "n"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=False, board_name=None, board_id=None, csv_only=False)

    def test_choice_1_shuffle_yes_passes_shuffle_true(self):
        with mock.patch.object(publish, "input", side_effect=["1", "y", "n"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=True, board_name=None, board_id=None, csv_only=False)

    def test_choice_1_csv_only_yes_passes_csv_only_true(self):
        with mock.patch.object(publish, "input", side_effect=["1", "n", "y"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(shuffle=False, board_name=None, board_id=None, csv_only=True)

    def test_choice_1_prompts_for_board_when_boards_are_cached(self):
        boards = [{"name": "Blog Pins", "id": "1"}, {"name": "Other Board", "id": "2"}]
        self._patch(publish, "load_config", return_value={"pinterest_boards": boards, "board_id": "1"})
        with mock.patch.object(publish, "input", side_effect=["1", "n", "n", "2"]):
            with mock.patch.object(publish, "run_pipeline") as pipeline:
                publish.menu()
        pipeline.assert_called_once_with(
            shuffle=False, board_name="Other Board", board_id="2", csv_only=False
        )

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
        with mock.patch.object(publish, "input", return_value="99"):
            with self.assertRaises(SystemExit):
                publish.menu()

    def test_choice_8_not_available_when_etsy_not_configured(self):
        with mock.patch.object(publish, "input", return_value="8"):
            with self.assertRaises(SystemExit):
                publish.menu()

    def test_choice_8_runs_etsy_pipeline_when_configured(self):
        self._patch(publish, "load_config", return_value={"etsy_api_key": "key123"})
        with mock.patch.object(publish, "input", side_effect=["8", "n", "", "n", "n"]):
            with mock.patch.object(publish, "run_etsy_pipeline") as etsy:
                publish.menu()
        etsy.assert_called_once_with(
            shuffle=False, board_name=None, board_id=None, limit=None,
            csv_only=False, ai_images=False,
        )

    def test_choice_8_shuffle_yes_passes_shuffle_true(self):
        self._patch(publish, "load_config", return_value={"etsy_api_key": "key123"})
        with mock.patch.object(publish, "input", side_effect=["8", "y", "", "n", "n"]):
            with mock.patch.object(publish, "run_etsy_pipeline") as etsy:
                publish.menu()
        etsy.assert_called_once_with(
            shuffle=True, board_name=None, board_id=None, limit=None,
            csv_only=False, ai_images=False,
        )

    def test_choice_8_limit_number_forwarded(self):
        self._patch(publish, "load_config", return_value={"etsy_api_key": "key123"})
        with mock.patch.object(publish, "input", side_effect=["8", "n", "20", "n", "n"]):
            with mock.patch.object(publish, "run_etsy_pipeline") as etsy:
                publish.menu()
        etsy.assert_called_once_with(
            shuffle=False, board_name=None, board_id=None, limit=20,
            csv_only=False, ai_images=False,
        )

    def test_choice_8_limit_not_a_number_exits(self):
        self._patch(publish, "load_config", return_value={"etsy_api_key": "key123"})
        with mock.patch.object(publish, "input", side_effect=["8", "n", "abc"]):
            with self.assertRaises(SystemExit):
                publish.menu()

    def test_choice_8_ai_images_yes_passes_ai_images_true(self):
        self._patch(publish, "load_config", return_value={"etsy_api_key": "key123"})
        with mock.patch.object(publish, "input", side_effect=["8", "n", "", "y", "n"]):
            with mock.patch.object(publish, "run_etsy_pipeline") as etsy:
                publish.menu()
        etsy.assert_called_once_with(
            shuffle=False, board_name=None, board_id=None, limit=None,
            csv_only=False, ai_images=True,
        )

    def test_choice_8_csv_only_yes_passes_csv_only_true(self):
        self._patch(publish, "load_config", return_value={"etsy_api_key": "key123"})
        with mock.patch.object(publish, "input", side_effect=["8", "n", "", "n", "y"]):
            with mock.patch.object(publish, "run_etsy_pipeline") as etsy:
                publish.menu()
        etsy.assert_called_once_with(
            shuffle=False, board_name=None, board_id=None, limit=None,
            csv_only=True, ai_images=False,
        )

    def test_choice_9_publishes_csv_file(self):
        with mock.patch.object(publish, "input", side_effect=["9", "my_pins.csv"]):
            with mock.patch.object(publish, "publish_csv") as publish_csv:
                publish.menu()
        publish_csv.assert_called_once_with(publish.Path("my_pins.csv"), None)

    def test_choice_9_no_path_exits(self):
        with mock.patch.object(publish, "input", side_effect=["9", ""]):
            with self.assertRaises(SystemExit):
                publish.menu()


if __name__ == "__main__":
    unittest.main()
