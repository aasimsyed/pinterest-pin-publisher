"""Unit tests for gemini_auth.py's key-resolution order. The interactive
first_run_setup() (opens a browser, prompts for input) isn't covered here,
same as anthropic_auth.py's equivalent -- it's meant to be exercised by hand.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gemini_auth  # noqa: E402


class LoadApiKeyTests(unittest.TestCase):
    def test_cli_key_wins_over_everything(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "env-key"}), \
             mock.patch.object(gemini_auth, "load_config", return_value={"gemini_api_key": "saved-key"}):
            self.assertEqual(gemini_auth.load_api_key("cli-key"), "cli-key")

    def test_env_key_wins_over_saved_config(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "env-key"}), \
             mock.patch.object(gemini_auth, "load_config", return_value={"gemini_api_key": "saved-key"}):
            self.assertEqual(gemini_auth.load_api_key(None), "env-key")

    def test_saved_config_used_when_no_cli_or_env_key(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(gemini_auth, "load_config", return_value={"gemini_api_key": "saved-key"}):
            self.assertEqual(gemini_auth.load_api_key(None), "saved-key")

    def test_non_interactive_with_no_key_anywhere_exits(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(gemini_auth, "load_config", return_value={}), \
             mock.patch.object(gemini_auth.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(SystemExit):
                gemini_auth.load_api_key(None)

    def test_interactive_with_no_key_anywhere_runs_first_run_setup(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(gemini_auth, "load_config", return_value={}), \
             mock.patch.object(gemini_auth.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(gemini_auth, "first_run_setup", return_value="fresh-key") as setup:
            self.assertEqual(gemini_auth.load_api_key(None), "fresh-key")
        setup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
