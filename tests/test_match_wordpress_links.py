"""Unit tests for match_wordpress_links.py -- chunking large batches so a
single Claude response can't get cut off mid-JSON. No network access.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import match_wordpress_links as mwl  # noqa: E402


class MatchAllLinksChunkingTests(unittest.TestCase):
    def test_splits_large_batch_into_chunks_of_chunk_size(self):
        titles = [f"Pin {i}" for i in range(60)]
        posts = [{"title": "Post", "slug": "post", "link": "https://example.com/post"}]
        seen_chunk_sizes = []

        def fake_ask(client, pin_titles, chunk_posts):
            seen_chunk_sizes.append(len(pin_titles))
            return {title: posts[0]["link"] for title in pin_titles}

        with mock.patch.object(mwl, "ask_claude_for_matches", fake_ask):
            assigned = mwl.match_all_links(None, titles, posts)

        self.assertEqual(seen_chunk_sizes, [mwl.CHUNK_SIZE, mwl.CHUNK_SIZE, 60 - 2 * mwl.CHUNK_SIZE])
        self.assertEqual(len(assigned), 60)

    def test_small_batch_is_a_single_chunk(self):
        titles = ["Only One Pin"]
        posts = [{"title": "Post", "slug": "post", "link": "https://example.com/post"}]
        calls = []

        def fake_ask(client, pin_titles, chunk_posts):
            calls.append(pin_titles)
            return {title: posts[0]["link"] for title in pin_titles}

        with mock.patch.object(mwl, "ask_claude_for_matches", fake_ask):
            assigned = mwl.match_all_links(None, titles, posts)

        self.assertEqual(calls, [titles])
        self.assertEqual(assigned, {"Only One Pin": "https://example.com/post"})

    def test_unmatched_pins_are_retried_in_chunks_with_leftover_posts(self):
        titles = ["Matched Pin", "Unmatched Pin"]
        posts = [
            {"title": "Post A", "slug": "post-a", "link": "https://example.com/a"},
            {"title": "Post B", "slug": "post-b", "link": "https://example.com/b"},
        ]

        def fake_ask(client, pin_titles, chunk_posts):
            if "Unmatched Pin" not in pin_titles:
                return {}
            if len(chunk_posts) == len(posts):
                # First pass: leave "Unmatched Pin" unmatched.
                return {t: posts[0]["link"] for t in pin_titles if t != "Unmatched Pin"}
            # Retry pass with leftover posts only.
            return {"Unmatched Pin": chunk_posts[0]["link"]}

        with mock.patch.object(mwl, "ask_claude_for_matches", fake_ask):
            assigned = mwl.match_all_links(None, titles, posts)

        self.assertEqual(assigned["Matched Pin"], "https://example.com/a")
        self.assertEqual(assigned["Unmatched Pin"], "https://example.com/b")


if __name__ == "__main__":
    unittest.main()
