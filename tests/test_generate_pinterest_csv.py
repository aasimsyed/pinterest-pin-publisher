"""Unit tests for generate_pinterest_csv.py -- skipping images already
queued or published so re-running on a folder with old pictures still in
it doesn't re-upload/re-analyze/re-queue them. No network access.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_pinterest_csv as gen  # noqa: E402


class FilterNewImagesTests(unittest.TestCase):
    def test_splits_already_posted_from_new(self):
        images = [Path("a.png"), Path("b.png"), Path("c.png")]
        already_posted = {"a.png", "c.png"}

        new, skipped = gen.filter_new_images(images, already_posted)

        self.assertEqual(new, [Path("b.png")])
        self.assertEqual(skipped, [Path("a.png"), Path("c.png")])

    def test_nothing_already_posted_keeps_all_images(self):
        images = [Path("a.png"), Path("b.png")]

        new, skipped = gen.filter_new_images(images, set())

        self.assertEqual(new, images)
        self.assertEqual(skipped, [])

    def test_everything_already_posted_leaves_nothing_new(self):
        images = [Path("a.png"), Path("b.png")]
        already_posted = {"a.png", "b.png"}

        new, skipped = gen.filter_new_images(images, already_posted)

        self.assertEqual(new, [])
        self.assertEqual(skipped, images)


if __name__ == "__main__":
    unittest.main()
