#!/usr/bin/env python3
"""
ai_image.py

Restyles an Etsy listing photo into a more eye-catching, Pinterest-ready
background using Google's Gemini 2.5 Flash Image model ("Nano Banana").
The AI only handles the visual styling (lighting, background, composition)
-- it's told not to add any text -- so pin_image.py still overlays the
exact title/price afterward, guaranteeing they're spelled and priced
correctly every time.
"""

from __future__ import annotations

import io

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image

MODEL = "gemini-2.5-flash-image"

BILLING_URL = "https://aistudio.google.com/"

PROMPT = (
    "Restyle this product photo into an eye-catching background for a "
    "Pinterest pin. Keep the product/design itself completely unchanged "
    "and clearly readable -- same shape, colors, and details (including "
    "any badges, stamps, or text baked into the photo), not redrawn. It "
    "must fill almost the entire frame edge-to-edge, at least 85% of the "
    "canvas -- do not shrink it down and surround it with large plain "
    "empty margins. Only improve the lighting, color, and contrast, and "
    "add a subtle, tasteful backdrop where the original photo doesn't "
    "already fill the frame. Do not add decorative props, sparkles, "
    "stars, or anything that wasn't in the original photo. Do not add "
    "any new text, letters, numbers, logos, or watermarks."
)


class AiImageError(RuntimeError):
    """Raised when the AI restyle step fails, with a message meant for a
    non-technical user rather than a raw stack trace."""


def restyle_photo(api_key: str, photo_bytes: bytes) -> bytes:
    """Sends a listing photo to Gemini and returns the restyled photo's
    image bytes (PNG)."""
    client = genai.Client(api_key=api_key)
    source_image = Image.open(io.BytesIO(photo_bytes))
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[PROMPT, source_image],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                # Matches pin_image.py's photo area (1000x940, nearly
                # square), not the full pin canvas, so nothing gets
                # cropped away when it's fit into place afterward.
                image_config=types.ImageConfig(aspect_ratio="1:1"),
            ),
        )
    except genai_errors.APIError as e:
        if e.code == 429 and "free_tier" in str(e.details).lower():
            raise AiImageError(
                "Gemini rejected the request because image generation isn't "
                f"available on the free tier. Enable billing on your Google "
                f"account at {BILLING_URL}, then try again."
            ) from e
        if e.code == 429:
            raise AiImageError(
                "Gemini's rate limit was hit. Wait a bit and try again, or "
                "process fewer listings at a time with --limit."
            ) from e
        raise AiImageError(f"Gemini image request failed ({e.code} {e.status}): {e.message}") from e
    except Exception as e:  # anything else (network error, bad image data, etc.)
        raise AiImageError(f"Gemini image request failed: {e}") from e

    for candidate in response.candidates or []:
        for part in (candidate.content.parts or []):
            if part.inline_data is not None:
                return part.inline_data.data

    block_reason = getattr(response.prompt_feedback, "block_reason", None) \
        if response.prompt_feedback else None
    if block_reason:
        raise AiImageError(f"Gemini declined to restyle this photo ({block_reason}).")
    raise AiImageError("Gemini did not return an image.")
