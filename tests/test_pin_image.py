"""Unit tests for pin_image.py -- text wrapping and image generation.
No network access.
"""

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pin_image  # noqa: E402
from PIL import Image, ImageFont  # noqa: E402


class WrapTextTests(unittest.TestCase):
    def setUp(self):
        self.font = ImageFont.truetype(str(pin_image.TITLE_FONT_PATH), 40)

    def test_short_text_is_a_single_line(self):
        lines = pin_image.wrap_text("SHORT TITLE", self.font, max_width=900)
        self.assertEqual(lines, ["SHORT TITLE"])

    def test_long_text_wraps_to_multiple_lines(self):
        long_title = "HANDMADE WALNUT CUTTING BOARD WITH JUICE GROOVE AND HANDLE"
        lines = pin_image.wrap_text(long_title, self.font, max_width=400)
        self.assertGreater(len(lines), 1)
        # every word must survive the wrap, in order, none dropped or duplicated
        self.assertEqual(" ".join(lines).split(), long_title.split())

    def test_each_line_fits_within_max_width(self):
        long_title = "PERSONALIZED LEATHER JOURNAL FOR TRAVELERS AND WRITERS"
        max_width = 500
        lines = pin_image.wrap_text(long_title, self.font, max_width=max_width)
        for line in lines:
            self.assertLessEqual(self.font.getlength(line), max_width)

    def test_single_word_longer_than_max_width_is_not_dropped(self):
        lines = pin_image.wrap_text("Supercalifragilisticexpialidocious", self.font, max_width=10)
        self.assertEqual(lines, ["Supercalifragilisticexpialidocious"])


class BuildPinImageTests(unittest.TestCase):
    def _sample_photo_bytes(self) -> bytes:
        photo = Image.new("RGB", (800, 600), (100, 80, 60))
        buf = io.BytesIO()
        photo.save(buf, "PNG")
        return buf.getvalue()

    def test_output_is_canvas_sized_rgb_image(self):
        result = pin_image.build_pin_image(self._sample_photo_bytes(), "A Test Title", "$10.00")
        self.assertEqual(result.size, pin_image.CANVAS_SIZE)
        self.assertEqual(result.mode, "RGB")

    def test_works_without_a_price(self):
        result = pin_image.build_pin_image(self._sample_photo_bytes(), "No Price Listing")
        self.assertEqual(result.size, pin_image.CANVAS_SIZE)

    def test_save_pin_image_writes_a_png_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "nested" / "pin.png"
            pin_image.save_pin_image(self._sample_photo_bytes(), "Saved Title", "$5.00", output_path)
            self.assertTrue(output_path.exists())
            with Image.open(output_path) as saved:
                self.assertEqual(saved.size, pin_image.CANVAS_SIZE)


if __name__ == "__main__":
    unittest.main()
