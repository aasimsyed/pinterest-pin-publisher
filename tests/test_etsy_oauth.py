"""Unit tests for etsy_oauth.py's pure request-building/parsing pieces.
The browser/local-server consent flow (get_authorization_code) isn't
covered here, same as Pinterest's equivalent in oauth_setup.py -- it's an
interactive flow meant to be exercised by hand.
"""

import io
import json
import re
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import etsy_oauth  # noqa: E402

PKCE_CHARSET = re.compile(r"^[A-Za-z0-9._~-]+$")


class PkcePairTests(unittest.TestCase):
    def test_verifier_and_challenge_use_allowed_charset_and_length(self):
        verifier, challenge = etsy_oauth._pkce_pair()
        self.assertRegex(verifier, PKCE_CHARSET)
        self.assertRegex(challenge, PKCE_CHARSET)
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertTrue(43 <= len(challenge) <= 128)

    def test_each_call_produces_a_different_verifier(self):
        first, _ = etsy_oauth._pkce_pair()
        second, _ = etsy_oauth._pkce_pair()
        self.assertNotEqual(first, second)

    def test_challenge_is_deterministic_sha256_of_verifier(self):
        import base64
        import hashlib

        verifier, challenge = etsy_oauth._pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        self.assertEqual(challenge, expected)


def _fake_response(payload: dict):
    body = json.dumps(payload).encode()
    return mock.MagicMock(
        __enter__=mock.Mock(return_value=io.BytesIO(body)),
        __exit__=mock.Mock(return_value=False),
    )


class ExchangeCodeForTokensTests(unittest.TestCase):
    def test_returns_parsed_json_and_posts_expected_fields(self):
        captured = {}

        def fake_urlopen(request):
            captured["url"] = request.full_url
            captured["data"] = request.data.decode()
            return _fake_response({"access_token": "abc", "refresh_token": "def"})

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            result = etsy_oauth.exchange_code_for_tokens("client123", "auth-code", "verifier-xyz")

        self.assertEqual(result, {"access_token": "abc", "refresh_token": "def"})
        self.assertEqual(captured["url"], etsy_oauth.TOKEN_URL)
        self.assertIn("grant_type=authorization_code", captured["data"])
        self.assertIn("client_id=client123", captured["data"])
        self.assertIn("code=auth-code", captured["data"])
        self.assertIn("code_verifier=verifier-xyz", captured["data"])


class RefreshAccessTokenTests(unittest.TestCase):
    def test_returns_parsed_json_and_posts_expected_fields(self):
        captured = {}

        def fake_urlopen(request):
            captured["data"] = request.data.decode()
            return _fake_response({"access_token": "new-access", "refresh_token": "new-refresh"})

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            result = etsy_oauth.refresh_access_token("client123", "old-refresh")

        self.assertEqual(result, {"access_token": "new-access", "refresh_token": "new-refresh"})
        self.assertIn("grant_type=refresh_token", captured["data"])
        self.assertIn("refresh_token=old-refresh", captured["data"])

    def test_http_error_raises_runtime_error_with_message(self):
        def fake_urlopen(request):
            raise urllib.error.HTTPError(
                etsy_oauth.TOKEN_URL, 400, "Bad Request", {}, io.BytesIO(b'{"error":"invalid_grant"}')
            )

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(RuntimeError) as ctx:
                etsy_oauth.refresh_access_token("client123", "stale-refresh")
        self.assertIn("invalid_grant", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
