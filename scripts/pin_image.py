#!/usr/bin/env python3
"""
pin_image.py

Builds a Pinterest-style pin graphic: a product photo with a title (and
optional price) overlaid in a legible text band, matching the look of a
baked-in-text pin design instead of a bare product photo.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
TITLE_FONT_PATH = FONT_DIR / "Anton-Regular.ttf"
PRICE_FONT_PATH = FONT_DIR / "Poppins-Bold.ttf"

CANVAS_SIZE = (1000, 1500)
BAND_HEIGHT = 560
MARGIN = 60
TITLE_FONT_SIZE = 72
PRICE_FONT_SIZE = 44
MAX_TITLE_LINES = 4


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit max_width, measured with the given font."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or font.getlength(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_pin_image(photo_bytes: bytes, title: str, price: str = "") -> Image.Image:
    """Product photo on top with a solid dark caption band below it holding
    the title (plus price if given) -- Pinterest text-on-image pins
    consistently outperform bare product photos. The band sits below the
    photo instead of over it, so it never covers a seller's own badge or
    watermark baked into the listing photo."""
    band_top = CANVAS_SIZE[1] - BAND_HEIGHT
    photo_area = (CANVAS_SIZE[0], band_top)

    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    photo = ImageOps.fit(photo, photo_area, method=Image.LANCZOS)

    canvas = Image.new("RGB", CANVAS_SIZE, (0, 0, 0))
    canvas.paste(photo, (0, 0))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, band_top, CANVAS_SIZE[0], CANVAS_SIZE[1]], fill=(0, 0, 0))
    title_font = ImageFont.truetype(str(TITLE_FONT_PATH), TITLE_FONT_SIZE)
    max_text_width = CANVAS_SIZE[0] - MARGIN * 2
    lines = wrap_text(title.upper(), title_font, max_text_width)[:MAX_TITLE_LINES]

    line_height = title_font.getbbox("Ag")[3] + 14
    price_font = ImageFont.truetype(str(PRICE_FONT_PATH), PRICE_FONT_SIZE) if price else None
    price_height = (price_font.getbbox("Ag")[3] + 24) if price_font else 0

    text_block_height = len(lines) * line_height + price_height
    y = CANVAS_SIZE[1] - MARGIN - text_block_height
    for line in lines:
        draw.text((MARGIN, y), line, font=title_font, fill="white")
        y += line_height

    if price_font:
        draw.text((MARGIN, y + 10), f"{price} on Etsy", font=price_font, fill="#F1641E")

    return canvas


def save_pin_image(photo_bytes: bytes, title: str, price: str, output_path: Path) -> None:
    image = build_pin_image(photo_bytes, title, price)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
