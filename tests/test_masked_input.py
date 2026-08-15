"""Unit tests for masked secret input (no live TTY required)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from masked_input import _handle_secret_char, read_secret  # noqa: E402


class HandleSecretCharTests(unittest.TestCase):
    def test_printable_char_appends_and_echoes_star(self):
        chars: list[str] = []
        self.assertEqual(_handle_secret_char(chars, "a"), "*")
        self.assertEqual(chars, ["a"])

    def test_enter_finishes(self):
        self.assertIsNone(_handle_secret_char(["x"], "\n"))
        self.assertIsNone(_handle_secret_char(["x"], "\r"))

    def test_backspace_removes_last_char(self):
        chars = ["a", "b"]
        self.assertEqual(_handle_secret_char(chars, "\x7f"), "\b \b")
        self.assertEqual(chars, ["a"])

    def test_backspace_on_empty_is_noop(self):
        chars: list[str] = []
        self.assertEqual(_handle_secret_char(chars, "\b"), "")
        self.assertEqual(chars, [])

    def test_ctrl_c_raises(self):
        with self.assertRaises(KeyboardInterrupt):
            _handle_secret_char([], "\x03")

    def test_control_chars_are_ignored(self):
        chars: list[str] = []
        self.assertEqual(_handle_secret_char(chars, "\x01"), "")
        self.assertEqual(chars, [])


class ReadSecretFallbackTests(unittest.TestCase):
    def test_non_tty_uses_getpass(self):
        with mock.patch("masked_input.sys.stdin.isatty", return_value=False):
            with mock.patch("masked_input.getpass.getpass", return_value="  secret  ") as gp:
                self.assertEqual(read_secret("Secret: "), "secret")
        gp.assert_called_once_with("Secret: ")


if __name__ == "__main__":
    unittest.main()
