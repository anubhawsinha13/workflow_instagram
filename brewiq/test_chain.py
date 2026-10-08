"""Budget and publish guards. These tests do not call paid APIs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from art import _fail, _ok, _skip, generate_illustrations
from character import character_reference, with_character
from brand import category_style
from host import to_jpeg, upload_jpegs
from image import CONTENT_WIDTH, DISPLAY, _font, paint_poster, poster_lines
from instagram_publish import publish_carousel
from reel import render_reel
from rights import copyright_problems
from slides import build_slides


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


class PosterTests(unittest.TestCase):
    TAKEAWAY = "Blooming mainly improves wetting; thirty seconds is a practical test, not a guarantee."

    def test_long_headline_stays_inside_the_safe_width(self):
        lines = [text for text, _color in poster_lines(self.TAKEAWAY, "#35D5F4")]
        draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
        font = _font(DISPLAY, 68)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(draw.textlength(line, font=font), CONTENT_WIDTH)

    def test_close_slide_uses_a_short_poster_line(self):
        slides = build_slides(
            {
                "category": "ai_research",
                "headline": "Why Coffee Blooms First",
                "why_it_matters": "A bloom can improve wetting.",
                "point": "Gas escapes before the main pour.",
                "try_it": "Wait 30 seconds.",
                "limitations": "The exact benefit is not proven.",
                "takeaway": self.TAKEAWAY,
                "timeliness": "evergreen",
            }
        )
        close = slides[-1]
        self.assertEqual(close["headline"], "Blooming mainly improves wetting")
        self.assertIn("thirty seconds is a practical test, not a guarantee.", close["body"])
        style = category_style("ai_research")
        _image, _text, margins_ok = paint_poster(
            Image.new("RGB", (64, 64), "black"),
            number=6,
            label=style["label"],
            accent=style["accent"],
            lines=poster_lines(close["headline"], style["accent"]),
            footers=["AI-generated concept illustration", "Follow @_brewiq"],
        )
        self.assertTrue(margins_ok)


class RightsTests(unittest.TestCase):
    def test_a_logo_or_screenshot_request_is_refused(self):
        problems = copyright_problems({"visual_idea": "a screenshot of the Nike logo", "claims": []})
        self.assertTrue(problems)

    def test_saying_no_logos_is_not_a_request_for_a_logo(self):
        problems = copyright_problems(
            {
                "visual_idea": (
                    "A blank paper sheet on a table, warm natural light, "
                    "no text, letters, logos, screens, or recognizable branding."
                ),
                "claims": [],
            }
        )
        self.assertEqual(problems, [])

    def test_an_original_scene_can_continue(self):
        problems = copyright_problems(
            {
                "visual_idea": "coffee grounds blooming in a glass server",
                "hook": "Thirty seconds lets the grounds wet evenly.",
                "claims": [
                    {
                        "text": "A study measured mixing in a pour-over bed and did not isolate bloom time.",
                    }
                ],
            }
        )
        self.assertEqual(problems, [])

    def test_a_long_copied_passage_is_refused(self):
        passage = "the water jet caused an avalanche of grounds during the pour and changed the measured extraction"
        problems = copyright_problems(
            {
                "visual_idea": "water moving through dark coffee grounds",
                "point": passage,
                "claims": [{"text": passage}],
            }
        )
        self.assertTrue(any("paraphrase" in item for item in problems))


class CharacterTests(unittest.TestCase):
    def test_reel_reference_is_the_face_crop(self):
        reference = character_reference()
        self.assertIsNotNone(reference)
        with Image.open(reference) as image:
            self.assertLess(image.width, 400)
            self.assertLess(image.height, 400)

    def test_reel_prompts_keep_the_same_face(self):
        prompts = with_character(["A quiet coffee bar."])
        self.assertIn("same face", prompts[0])
        self.assertIn("no logo", prompts[0])


class ReelTests(unittest.TestCase):
    def test_slide_images_become_a_vertical_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in ("slide-01.png", "slide-02.png"):
                Image.new("RGB", (1080, 1350), "#10141C").save(folder / name)
            result = render_reel(folder, seconds=0.4)
            self.assertTrue(result["ok"], result.get("error"))
            video = Path(result["path"])
            self.assertEqual(video.suffix, ".mp4")
            self.assertGreater(video.stat().st_size, 1000)


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
