"""Budget and publish guards. These tests do not call paid APIs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from art import _fail, _ok, _skip, generate_illustrations
from host import to_jpeg, upload_jpegs
from instagram_publish import publish_carousel


class ChainTests(unittest.TestCase):
    def test_first_success_is_the_only_provider_used(self):
        calls = []

        def first(_prompt):
            calls.append("first")
            return _ok("openai", "gpt-image-2.5-sunburst", Image.new("RGB", (8, 8), "black"))

        def second(_prompt):
            calls.append("second")
            return _ok("gemini", "gemini-3.1-flash-image", Image.new("RGB", (8, 8), "white"))

        result = generate_illustrations(["one", "two", "three"], callers=[first, second])
        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["first", "first", "first"])
        self.assertEqual(result["model"], "gpt-image-2.5-sunburst")

    def test_a_failed_winner_does_not_switch_provider(self):
        calls = []
        seen = {"n": 0}

        def first(_prompt):
            calls.append("first")
            seen["n"] += 1
            if seen["n"] == 1:
                return _ok("openai", "gpt-image-2.5-sunburst", Image.new("RGB", (8, 8)))
            return _fail("openai", "gpt-image-2.5-sunburst", "timed out")

        def second(_prompt):
            calls.append("second")
            return _ok("gemini", "gemini-3.1-flash-image", Image.new("RGB", (8, 8)))

        result = generate_illustrations(["one", "two"], callers=[first, second])
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["first", "first"])

    def test_skip_does_not_count_as_a_paid_call(self):
        calls = []

        def first(_prompt):
            calls.append("first")
            return _skip("openai", "gpt-image-2.5-sunburst", "OPENAI_API_KEY is not set.")

        def second(_prompt):
            calls.append("second")
            return _ok("gemini", "gemini-3.1-flash-image", Image.new("RGB", (8, 8)))

        result = generate_illustrations(["one"], callers=[first, second])
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "gemini-3.1-flash-image")
        self.assertEqual(calls, ["first", "second"])


class HostTests(unittest.TestCase):
    def test_png_becomes_jpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            Image.new("RGB", (12, 12), "#10141C").save(folder / "slide.png")
            to_jpeg(folder / "slide.png", folder / "slide.jpg")
            self.assertEqual(Image.open(folder / "slide.jpg").format, "JPEG")

    def test_missing_bucket_does_not_invent_a_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            Image.new("RGB", (12, 12)).save(folder / "slide-01.png")
            Image.new("RGB", (12, 12)).save(folder / "slide-02.png")
            with mock.patch.dict(os.environ, {"GCS_BUCKET_NAME": ""}, clear=False):
                result = upload_jpegs(folder, "2026-10-02")
        self.assertFalse(result["ok"])
        self.assertEqual(result["urls"], [])


class PublishTests(unittest.TestCase):
    def test_missing_token_posts_nothing(self):
        with mock.patch.dict(os.environ, {"IG_ACCESS_TOKEN": "", "IG_USER_ID": ""}, clear=False):
            result = publish_carousel(["https://example.com/a.jpg", "https://example.com/b.jpg"], "caption")
        self.assertFalse(result["ok"])
        self.assertIn("Nothing was posted", result["error"])

    def test_publish_sends_children_then_one_publish_call(self):
        class Response:
            def __init__(self, payload):
                self.status_code = 200
                self.content = json.dumps(payload).encode()
                self.text = self.content.decode()

            def json(self):
                return json.loads(self.content)

        class Http:
            def __init__(self):
                self.posts = []

            def post(self, url, data, params, timeout):
                self.posts.append((url, dict(data)))
                if url.endswith("/media_publish"):
                    return Response({"id": "media-1"})
                return Response({"id": f"container-{len(self.posts)}"})

            def get(self, url, params, timeout):
                return Response({"status_code": "FINISHED"})

        http = Http()
        with mock.patch.dict(
            os.environ,
            {"IG_ACCESS_TOKEN": "test-token", "IG_USER_ID": "1789"},
            clear=False,
        ):
            result = publish_carousel(
                ["https://storage.googleapis.com/bucket/a.jpg", "https://storage.googleapis.com/bucket/b.jpg"],
                "caption",
                http=http,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["media_id"], "media-1")
        self.assertEqual(http.posts[-1][1]["creation_id"], "container-3")
        self.assertEqual(http.posts[2][1]["media_type"], "CAROUSEL")
        self.assertIn("container-1", http.posts[2][1]["children"])


if __name__ == "__main__":
    unittest.main()
