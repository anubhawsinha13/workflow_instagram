"""Budget and publish guards. These tests do not call paid APIs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from art import _fail, _ok, _skip, generate_illustrations, openai_edit_image
from director_reel import render_director_reel
from character import character_reference, with_character
from brand import category_style
from host import to_jpeg, upload_jpegs
from image import CONTENT_WIDTH, DISPLAY, _font, paint_poster, poster_lines
from instagram_publish import publish_carousel
from reel import motion_changes, render_reel
from rights import copyright_problems, omit_long_quotations, prepare_post_copy
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
        self.assertEqual(" ".join(close["body"]), "thirty seconds is a practical test, not a guarantee.")
        style = category_style("ai_research")
        _image, _text, margins_ok = paint_poster(
            Image.new("RGB", (64, 64), "black"),
            number=6,
            label=style["label"],
            accent=style["accent"],
            lines=poster_lines(close["headline"], style["accent"]),
            footers=["AI-generated concept illustration"],
            body=close["body"],
        )
        self.assertTrue(margins_ok)

    def test_cover_puts_the_stat_in_cyan_under_the_headline(self):
        slides = build_slides(
            {
                "category": "ai_news",
                "headline": "10,000 engineers to deploy AI",
                "stat": "$100M training commitment",
                "why_title": "Scale meets training",
                "why_it_matters": "Companies need people who can ship AI safely.",
                "point_title": "Headcount plus budget",
                "point": "A large hiring plan is paired with a training fund.",
                "try_title": "Ask for the plan",
                "try_it": "Ask how training is measured.",
                "limit_title": "Plans can slip",
                "limitations": "Announced numbers can change.",
                "takeaway": "Check the source before you share.",
                "timeliness": "timely",
                "publication_date": "Oct 2, 2026",
            }
        )
        cover, why = slides[0], slides[1]
        self.assertEqual(cover["accent_line"], "$100M training commitment")
        self.assertEqual(why["headline"], "Scale meets training")
        style = category_style("ai_news")
        lines = poster_lines(cover["headline"], style["accent"], cover["accent_line"])
        self.assertEqual(lines[-1], ("$100M TRAINING COMMITMENT", style["accent"]))
        self.assertTrue(all(color == "#FFFFFF" for _text, color in lines[:-1]))
        image, on_image, margins_ok = paint_poster(
            Image.new("RGB", (64, 64), "#152033"),
            number=1,
            label=style["label"],
            accent=style["accent"],
            lines=lines,
            footers=["Source: Anthropic • Oct 2, 2026", "AI-generated concept illustration"],
        )
        self.assertTrue(margins_ok)
        self.assertIn("@_brewiq", on_image)
        self.assertIn("BrewIQ", on_image)
        self.assertIn("$100M TRAINING COMMITMENT", on_image)
        self.assertEqual(image.size, (1080, 1350))


class ArtDirectorTests(unittest.TestCase):
    RESEARCH = {
        "category": "try_this",
        "topic": "Turn meeting notes into actions",
        "headline": "Turn meeting notes into clear actions",
        "why_it_matters": "Action items get lost in long notes.",
        "point": "Ask the assistant to list owners and due dates.",
        "try_it": "Paste notes and ask for a checklist with owners.",
        "limitations": "It can miss context that was only said aloud.",
        "takeaway": "Review the list before you send it.",
        "timeliness": "evergreen",
        "claims": [],
    }

    def _answer(self, accent="gold", use_character=True):
        return json.dumps({
            "accent": accent,
            "images": [
                {
                    "number": index + 1,
                    "message": "Messy notes become one clear checklist",
                    "scene": "Scattered paper pages stream into a single glowing checklist card on a dark table",
                    "prompt": "Scattered torn paper pages fly from the left in a luminous stream into one clean "
                              "checklist card standing on a dark reflective table",
                    "exclusions": "readable text, logos",
                    "use_character": use_character,
                    "character_action": "pulling one clean page out of the stream",
                }
                for index in range(6)
            ],
        })

    def test_direction_becomes_six_prompts_with_one_accent_and_at_most_two_character_slides(self):
        from art_director import direct_slides

        slides = build_slides(self.RESEARCH)
        calls = []

        def complete(system, user):
            calls.append((system, user))
            return self._answer()

        result = direct_slides(slides, self.RESEARCH, character_available=True, complete=complete)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["accent_hex"], "#FFC76A")
        self.assertEqual(len(result["images"]), 6)
        self.assertEqual(sum(item["use_character"] for item in result["images"]), 2)
        self.assertIn("#FFC76A", result["images"][0]["prompt"])
        self.assertIn("lower third stays dark", result["images"][0]["prompt"])
        self.assertIn("BREWIQ IMAGE ART DIRECTION", calls[0][0])
        self.assertIn("CHARACTER_AVAILABLE: yes", calls[0][1])

    def test_a_broken_answer_falls_back_to_plain_scene_prompts(self):
        from art_director import direct_slides

        slides = build_slides(self.RESEARCH)
        result = direct_slides(slides, self.RESEARCH, complete=lambda _system, _user: "{\"images\": []}")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["images"]), 6)
        self.assertEqual(result["accent_hex"], "#FFC76A")
        self.assertIn("art director was unavailable", result["error"])

    def test_character_slides_use_the_reference_caller(self):
        from art_director import directed_illustrations

        slides = build_slides(self.RESEARCH)
        seen = []

        def caller(prompt):
            seen.append(prompt.startswith("Use the same face"))
            return {"image": Image.new("RGB", (8, 8)), "provider": "test", "model": "test", "ok": True,
                    "skipped": False, "error": ""}

        with tempfile.TemporaryDirectory() as tmp, mock.patch("art_director.character_reference",
                                                               return_value=Path(tmp)):
            generated, direction = directed_illustrations(
                slides, self.RESEARCH, Path(tmp), complete=lambda _s, _u: self._answer(), callers=[caller]
            )
            self.assertTrue((Path(tmp) / "art-direction.json").is_file())
        self.assertTrue(generated["ok"])
        self.assertEqual(seen, [True, True, False, False, False, False])
        self.assertEqual(direction["accent"], "gold")


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

    def test_a_long_quotation_is_removed_before_the_facts_are_used(self):
        quoted = (
            '"Gemini study notebooks use a diagnostic quiz to establish a baseline and identify knowledge gaps."'
        )
        cleaned = omit_long_quotations({"point": f"Google describes the feature. {quoted}", "claims": []})
        self.assertNotIn('"', cleaned["point"])
        self.assertEqual(copyright_problems(cleaned), [])

    def test_a_repeated_source_passage_is_shortened_so_the_post_can_continue(self):
        passage = "the water jet caused an avalanche of grounds during the pour and changed the measured extraction"
        cleaned = prepare_post_copy(
            {
                "visual_idea": "water moving through dark coffee grounds",
                "point": passage,
                "claims": [{"text": passage, "source_url": "https://example.com/study"}],
            }
        )
        self.assertEqual(copyright_problems(cleaned), [])
        self.assertLess(len(cleaned["point"].split()), 10)

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

    def test_a_moving_shot_changes_more_than_a_zoomed_still(self):
        ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            still = folder / "still.png"
            Image.new("RGB", (320, 180), "#10141C").save(still)
            zoomed = folder / "zoom.mp4"
            moving = folder / "move.mp4"
            zoom = subprocess.run(
                [
                    ffmpeg, "-y", "-loop", "1", "-i", str(still),
                    "-vf", "zoompan=z='min(zoom+0.0015,1.10)':d=24:s=320x180:fps=12",
                    "-frames:v", "24", "-pix_fmt", "yuv420p", str(zoomed),
                ],
                capture_output=True, text=True, check=False,
            )
            moved = subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:d=2",
                    "-f", "lavfi", "-i", "color=c=white:s=40x40:d=2",
                    "-filter_complex", "[0][1]overlay=x='10+120*t':y=60",
                    "-pix_fmt", "yuv420p", str(moving),
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(zoom.returncode, 0, zoom.stderr[-200:])
            self.assertEqual(moved.returncode, 0, moved.stderr[-200:])
            self.assertGreater(motion_changes(moving), motion_changes(zoomed) + 5)


class DirectorReelTests(unittest.TestCase):
    def test_two_scenes_are_required(self):
        result = render_director_reel({"folder": ".", "scenes": [{"prompt": "One scene."}]})
        self.assertFalse(result["ok"])
        self.assertIn("two scenes", result["error"])

    def test_a_ready_storyboard_joins_moving_clips(self):
        starts = []

        def start_frame(_reference, _prompt, dest):
            Image.new("RGB", (72, 128), "#C08040").save(dest)
            return {"ok": True, "error": ""}

        def generate(start, _prompt, dest):
            starts.append(Path(start).name)
            ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
            completed = subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1",
                    "-f", "lavfi", "-i", "color=c=white:s=40x40:d=1",
                    "-filter_complex", "[0][1]overlay=x='10+80*t':y=40",
                    "-pix_fmt", "yuv420p", str(dest),
                ],
                capture_output=True, text=True, check=False,
            )
            return {
                "ok": completed.returncode == 0 and dest.is_file(),
                "provider": "veo-3.1-generate-preview",
                "error": completed.stderr[-120:],
            }

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "face.png"
            Image.new("RGB", (64, 64), "#10141C").save(reference)
            result = render_director_reel(
                {
                    "folder": tmp,
                    "reference": str(reference),
                    "scenes": [
                        {"prompt": "The host pours coffee in a quiet kitchen.", "use_character": True},
                        {"prompt": "The same host checks a calendar.", "use_character": True},
                    ],
                },
                generate_clip=generate,
                make_start_frame=start_frame,
                model="veo-3.1-lite-generate-preview",
            )
            self.assertTrue(result["ok"], result.get("error"))
            self.assertTrue((Path(tmp) / "joined.mp4").is_file())
            self.assertEqual(result["provider"], "veo-3.1-generate-preview")
            self.assertEqual(starts, ["start-frame.png", "clip-01-last.png"])

    def test_standard_veo_uses_the_character_reference_for_every_clip(self):
        starts = []

        def generate(start, _prompt, dest):
            starts.append(Path(start).name)
            return {"ok": False, "error": "stop after the first clip"}

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "face.png"
            Image.new("RGB", (64, 64), "#10141C").save(reference)
            result = render_director_reel(
                {
                    "folder": tmp,
                    "reference": str(reference),
                    "scenes": [
                        {"prompt": "The host pours coffee.", "use_character": True},
                        {"prompt": "The host checks a calendar.", "use_character": True},
                    ],
                },
                generate_clip=generate,
                model="veo-3.1-generate-preview",
            )
            self.assertFalse(result["ok"])
            self.assertEqual(starts, ["face.png"])
            self.assertFalse((Path(tmp) / "start-frame.png").exists())

    def test_a_frozen_clip_is_not_posted(self):
        def generate(_reference, _prompt, dest):
            ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
            completed = subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1", "-pix_fmt", "yuv420p", str(dest)],
                capture_output=True, text=True, check=False,
            )
            return {"ok": completed.returncode == 0, "provider": "veo-3.1-generate-preview", "error": ""}

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "face.png"
            Image.new("RGB", (64, 64), "#10141C").save(reference)
            result = render_director_reel(
                {
                    "folder": tmp,
                    "reference": str(reference),
                    "scenes": [
                        {"prompt": "The host pours coffee.", "use_character": True},
                        {"prompt": "The host checks a calendar.", "use_character": True},
                    ],
                },
                generate_clip=generate,
                model="veo-3.1-generate-preview",
            )
            self.assertFalse(result["ok"])
            self.assertIn("continuous motion", result["error"])
            self.assertFalse((Path(tmp) / "joined.mp4").exists())

    def test_missing_gemini_key_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "face.png"
            Image.new("RGB", (32, 32), "#10141C").save(reference)
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
                result = render_director_reel(
                    {
                        "folder": tmp,
                        "reference": str(reference),
                        "scenes": [
                            {"prompt": "The host pours coffee.", "use_character": True},
                            {"prompt": "The host checks a calendar.", "use_character": True},
                        ],
                    }
                )
            self.assertFalse(result["ok"])
            self.assertIn("GEMINI_API_KEY", result["error"])

    def test_missing_reference_does_not_invent_a_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = render_director_reel(
                {
                    "folder": tmp,
                    "reference": str(Path(tmp) / "missing.png"),
                    "scenes": [
                        {"prompt": "A person pours coffee.", "use_character": True},
                        {"prompt": "The same person checks a calendar.", "use_character": True},
                    ],
                }
            )
            self.assertFalse(result["ok"])
            self.assertIn("character reference", result["error"])

    def test_a_scene_without_the_character_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "face.png"
            Image.new("RGB", (32, 32), "#10141C").save(reference)
            result = render_director_reel(
                {
                    "folder": tmp,
                    "reference": str(reference),
                    "scenes": [
                        {"prompt": "The host pours coffee.", "use_character": True},
                        {"prompt": "A calendar opens.", "use_character": False},
                    ],
                }
            )
            self.assertFalse(result["ok"])
            self.assertIn("approved BrewIQ character", result["error"])


class ExplainerRenderTests(unittest.TestCase):
    def test_scene_data_becomes_a_vertical_video(self):
        from explainer_render import render_explainer

        element = {
            "id": "s1-card", "type": "card", "label": "Agents pick tools",
            "box": {"x": 120, "y": 640, "w": 760, "h": 360},
            "enter_at": 0.1, "enter_duration": 0.3, "enter_motion": "slide_up",
            "hold_until": 1.2, "exit_motion": "fade_out", "exit_duration": 0.2,
        }
        bar = dict(element, id="s2-bar", type="progress", label="", enter_motion="fill",
                   box={"x": 120, "y": 900, "w": 760, "h": 40})
        renderer = {
            "canvas": {"width": 360, "height": 640, "fps": 10},
            "scenes": [
                {"start_seconds": 0, "duration_seconds": 1.5, "elements": [element]},
                {"start_seconds": 1.5, "duration_seconds": 1.5, "elements": [bar]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "explainer.mp4"
            result = render_explainer({"renderer": renderer, "output": str(out)})
            self.assertTrue(result["ok"], result.get("error"))
            self.assertTrue(out.is_file())
            self.assertEqual(result["seconds"], 3.0)

    def test_host_props_metaphors_and_camera_render(self):
        from explainer_render import load_pose_library, render_explainer

        library = load_pose_library()
        self.assertIn("magnify", library)
        self.assertIn("lens", library["magnify"][1], "the magnifier lens is located for the prop label")

        def element(**extra):
            base = {
                "box": {"x": 120, "y": 300, "w": 760, "h": 360}, "label": "",
                "enter_at": 0.1, "enter_duration": 0.3, "enter_motion": "snap",
                "hold_until": 1.0, "exit_motion": "crack", "exit_duration": 0.4,
            }
            base.update(extra)
            return base

        scenes = [
            {"start_seconds": 0, "duration_seconds": 1.5, "camera": "push_in", "elements": [
                element(id="claim", type="bubble", label="Sounds sure", tone="warning"),
                element(id="host", type="character", box={"x": 64, "y": 900, "w": 540, "h": 580},
                        enter_motion="walk_in", exit_motion="hold", hold_until=1.5, pose="magnify",
                        prop_label="Source?", beats=[{"at": 0.8, "pose": "pinch", "prop_label": "1899"}]),
            ]},
            {"start_seconds": 1.5, "duration_seconds": 1.5, "camera": "pull_out", "elements": [
                element(id="reel", type="slots", label="a | b | c", exit_motion="fade_out"),
                element(id="word", type="token", label="1899", box={"x": 400, "y": 700, "w": 260, "h": 110},
                        exit_motion="toss"),
            ]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "explainer.mp4"
            result = render_explainer({"renderer": {"canvas": {"fps": 6}, "scenes": scenes}, "output": str(out)})
            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["seconds"], 3.0)


class CharacterEditTests(unittest.TestCase):
    def test_edit_retries_when_the_model_rejects_input_fidelity(self):
        import base64
        import io

        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "#10141C").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        calls = []

        class Images:
            def edit(self, **kwargs):
                calls.append(kwargs.get("input_fidelity", ""))
                if kwargs.get("input_fidelity"):
                    raise RuntimeError("The model does not support the 'input_fidelity' parameter.")

                class Data:
                    b64_json = encoded

                class Response:
                    data = [Data()]

                return Response()

        class Client:
            def __init__(self, *_args, **_kwargs):
                self.images = Images()

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "face.png"
            Image.new("RGB", (8, 8), "#10141C").save(reference)
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False), mock.patch(
                "openai.OpenAI", Client
            ):
                result = openai_edit_image(reference, "Pour coffee.", require_reference=True)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(calls, ["high", ""])
        self.assertEqual(result["model"], "gpt-image-2.5-sunburst")


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
