import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from push_to_d1 import normalize_publish_at  # noqa: E402


class NormalizePublishAtTests(unittest.TestCase):
    def test_naive_datetime_gets_utc_z_suffix(self):
        self.assertEqual(normalize_publish_at("2026-08-16T09:00:00"), "2026-08-16T09:00:00Z")

    def test_already_utc_is_unchanged(self):
        self.assertEqual(normalize_publish_at("2026-08-16T09:00:00Z"), "2026-08-16T09:00:00Z")

    def test_explicit_offset_is_unchanged(self):
        self.assertEqual(normalize_publish_at("2026-08-16T09:00:00+02:00"), "2026-08-16T09:00:00+02:00")

    def test_empty_string_is_unchanged(self):
        self.assertEqual(normalize_publish_at(""), "")


if __name__ == "__main__":
    unittest.main()
