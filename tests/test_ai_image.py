"""Unit tests for ai_image.py -- Gemini response parsing. No network
access, google.genai's client is mocked.
"""

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

from google.genai import errors as genai_errors
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ai_image  # noqa: E402


def _api_error(code: int, message: str, status: str = "RESOURCE_EXHAUSTED") -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"message": message, "status": status})


def _sample_photo_bytes() -> bytes:
    photo = Image.new("RGB", (400, 300), (10, 20, 30))
    buf = io.BytesIO()
    photo.save(buf, "PNG")
    return buf.getvalue()


def _fake_client_with_response(response):
    client = mock.Mock()
    client.models.generate_content.return_value = response
    return client


def _response_with_image(data: bytes):
    part = mock.Mock(inline_data=mock.Mock(data=data))
    content = mock.Mock(parts=[part])
    candidate = mock.Mock(content=content)
    return mock.Mock(candidates=[candidate], prompt_feedback=None)


def _response_with_no_image(block_reason=None):
    part = mock.Mock(inline_data=None)
    content = mock.Mock(parts=[part])
    candidate = mock.Mock(content=content)
    feedback = mock.Mock(block_reason=block_reason) if block_reason else None
    return mock.Mock(candidates=[candidate], prompt_feedback=feedback)


class RestylePhotoTests(unittest.TestCase):
    def test_returns_the_first_inline_image_bytes(self):
        expected = b"restyled-png-bytes"
        response = _response_with_image(expected)
        with mock.patch.object(ai_image.genai, "Client", return_value=_fake_client_with_response(response)):
            result = ai_image.restyle_photo("api-key", _sample_photo_bytes())
        self.assertEqual(result, expected)

    def test_no_image_in_response_raises_ai_image_error(self):
        response = _response_with_no_image()
        with mock.patch.object(ai_image.genai, "Client", return_value=_fake_client_with_response(response)):
            with self.assertRaises(ai_image.AiImageError):
                ai_image.restyle_photo("api-key", _sample_photo_bytes())

    def test_blocked_response_error_mentions_the_reason(self):
        response = _response_with_no_image(block_reason="SAFETY")
        with mock.patch.object(ai_image.genai, "Client", return_value=_fake_client_with_response(response)):
            with self.assertRaises(ai_image.AiImageError) as ctx:
                ai_image.restyle_photo("api-key", _sample_photo_bytes())
        self.assertIn("SAFETY", str(ctx.exception))

    def test_api_exception_is_wrapped_in_ai_image_error(self):
        client = mock.Mock()
        client.models.generate_content.side_effect = RuntimeError("boom")
        with mock.patch.object(ai_image.genai, "Client", return_value=client):
            with self.assertRaises(ai_image.AiImageError) as ctx:
                ai_image.restyle_photo("api-key", _sample_photo_bytes())
        self.assertIn("boom", str(ctx.exception))

    def test_free_tier_quota_error_suggests_enabling_billing(self):
        client = mock.Mock()
        client.models.generate_content.side_effect = _api_error(
            429, "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0"
        )
        with mock.patch.object(ai_image.genai, "Client", return_value=client):
            with self.assertRaises(ai_image.AiImageError) as ctx:
                ai_image.restyle_photo("api-key", _sample_photo_bytes())
        self.assertIn("billing", str(ctx.exception).lower())

    def test_generic_429_suggests_waiting_and_retrying(self):
        client = mock.Mock()
        client.models.generate_content.side_effect = _api_error(429, "Rate limit exceeded")
        with mock.patch.object(ai_image.genai, "Client", return_value=client):
            with self.assertRaises(ai_image.AiImageError) as ctx:
                ai_image.restyle_photo("api-key", _sample_photo_bytes())
        message = str(ctx.exception).lower()
        self.assertIn("rate limit", message)
        self.assertNotIn("billing", message)

    def test_other_api_error_includes_code_and_message(self):
        client = mock.Mock()
        client.models.generate_content.side_effect = _api_error(
            400, "Invalid API key", status="INVALID_ARGUMENT"
        )
        with mock.patch.object(ai_image.genai, "Client", return_value=client):
            with self.assertRaises(ai_image.AiImageError) as ctx:
                ai_image.restyle_photo("api-key", _sample_photo_bytes())
        message = str(ctx.exception)
        self.assertIn("400", message)
        self.assertIn("Invalid API key", message)


if __name__ == "__main__":
    unittest.main()
