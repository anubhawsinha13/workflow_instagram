"""Reel spec, layout, stills, narration, and history tests. These do not call paid APIs."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops

import plates as plates_module
import reel_spec
import voice
from explainer_render import _fit_lines, _font, _swatch_ink, contrast_ratio, render_explainer
from history import append_history, load_history, withdraw_record
from reel import ffmpeg_bin

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def product_spec(reference: str) -> dict:
    still = {"mode": "still", "subject": "product",
             "prompt": "The same black car on a glossy studio floor with soft rim light and a clean dark backdrop."}
    beat = {"role": "intro", "voice": "Start from one clean photo of the product.",
            "lower_third": "Start from one clean product photo.",
            "on_screen": {"prompt_text": "Black coupe, studio floor, soft rim light."}, "shot": still}
    return {
        "format": "product_shot", "product_reference": reference,
        "disclosure": "Animated still made from a product photo, not filmed footage.",
        "beats": [dict(beat, id="one"), dict(beat, id="two", role="use_case"), dict(beat, id="three", role="cta")],
    }


def tile_workflow() -> dict:
    grid = load("reel_tile_grid.json")["beats"][0]["on_screen"]["tiles"]
    beat = lambda number, focus: {  # noqa: E731
        "id": f"scene{number}", "role": "use_case", "voice": "Pick one tile and write it as one sentence.",
        "lower_third": "One tile, one sentence.",
        "on_screen": {"tiles": grid, "tile_focus": focus, "prompt_text": "Make the bars grow from left to right."},
        "shot": {"mode": "graphics"},
    }
    return {"format": "workflow_reel", "beats": [beat(1, None), beat(2, 2), beat(3, 6)]}


def fake_plates(spec: dict, folder: Path) -> dict:
    result = {}
    for beat in spec["beats"]:
        if (beat.get("shot") or {}).get("mode") == "still":
            path = folder / f"plate-{beat['id']}.png"
            Image.new("RGB", (400, 500), "#445566").save(path)
            result[beat["id"]] = {"path": str(path), "source": "generated"}
    return result


def tone(dest: Path, seconds: float) -> None:
    subprocess.run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
         "-ar", "48000", "-ac", "1", str(dest)],
        check=True,
    )


class SpecValidationTests(unittest.TestCase):
    def test_the_shipped_examples_are_valid(self):
        for name in ("reel_chapter_build.json", "reel_beat_explainer.json", "reel_workflow.json", "reel_tile_grid.json",
                     "reel_color_pairs.json"):
            self.assertEqual(reel_spec.validate_spec(load(name)), [], name)

    def test_generated_video_is_refused(self):
        spec = load("reel_chapter_build.json")
        spec["beats"][1]["shot"] = {"mode": "generated", "prompt": "A car drives along a desert road at sunset."}
        problems = reel_spec.validate_spec(spec)
        self.assertTrue(any("Generated video clips are not available" in item for item in problems), problems)

    def test_a_continuous_shot_is_refused(self):
        spec = product_spec("photo.png")
        spec["beats"][0]["shot"]["continuous"] = True
        self.assertTrue(any("continuous shot" in item for item in reel_spec.validate_spec(spec)))

    def test_a_product_shot_needs_its_reference_and_an_animated_still_disclosure(self):
        spec = product_spec("photo.png")
        self.assertEqual(reel_spec.validate_spec(spec), [])
        spec["product_reference"] = ""
        self.assertTrue(any("product_reference" in item for item in reel_spec.validate_spec(spec)))
        spec = product_spec("photo.png")
        spec["disclosure"] = "AI generated."
        self.assertTrue(any("animated still" in item for item in reel_spec.validate_spec(spec)))

    def test_stills_need_a_disclosure(self):
        spec = load("reel_beat_explainer.json")
        spec["disclosure"] = ""
        self.assertTrue(any("disclosure" in item for item in reel_spec.validate_spec(spec)))

    def test_format_rules(self):
        spec = load("reel_beat_explainer.json")
        spec["beats"][1]["shot"] = {"mode": "pose"}
        self.assertTrue(any("does not allow the pose" in item for item in reel_spec.validate_spec(spec)))
        spec = load("reel_workflow.json")
        spec["beats"][1]["on_screen"] = {}
        self.assertTrue(any("prompt_text" in item for item in reel_spec.validate_spec(spec)))
        spec = load("reel_chapter_build.json")
        spec["beats"][0]["pose"] = "backflip"
        self.assertTrue(any("pose must be one of" in item for item in reel_spec.validate_spec(spec)))

    def test_length_limits(self):
        spec = load("reel_chapter_build.json")
        spec["hook"] = "one two three four five six seven eight nine"
        spec["beats"][0]["lower_third"] = "x" * 91
        spec["beats"][1]["chapter"] = "Much too long"
        spec["beats"][2]["id"] = spec["beats"][1]["id"]
        problems = " ".join(reel_spec.validate_spec(spec))
        for expected in ("hook", "lower_third", "chapter", "id is used twice"):
            self.assertIn(expected, problems)


class TileSpecTests(unittest.TestCase):
    def grid(self) -> dict:
        return load("reel_tile_grid.json")

    def problems(self, spec: dict) -> str:
        return " ".join(reel_spec.validate_spec(spec))

    def test_the_tile_rules(self):
        spec = self.grid()
        spec["beats"][0]["on_screen"]["tiles"] = spec["beats"][0]["on_screen"]["tiles"][:3]
        self.assertIn("4 to 16 entries", self.problems(spec))

        spec = self.grid()
        tiles = spec["beats"][0]["on_screen"]["tiles"]
        tiles[0]["label"] = "x" * 25
        tiles[1]["glyph"] = "rocket"
        tiles[2]["value"] = "123456789"
        problems = self.problems(spec)
        for expected in ("24 characters", "glyph must be one of", "8 characters"):
            self.assertIn(expected, problems)

        spec = self.grid()
        spec["beats"][1]["on_screen"]["tile_focus"] = 13
        self.assertIn("tile_focus must be a tile number from 1 to 12", self.problems(spec))

        spec = self.grid()
        spec["beats"][1]["on_screen"].pop("tiles")
        self.assertIn("tile_focus needs tiles", self.problems(spec))

    def test_tiles_belong_to_the_wide_formats_and_replace_a_still(self):
        spec = load("reel_chapter_build.json")
        spec["beats"][0]["on_screen"]["tiles"] = self.grid()["beats"][0]["on_screen"]["tiles"]
        self.assertIn("tiles can only be used in", self.problems(spec))

        spec = self.grid()
        spec["disclosure"] = "AI-generated pictures."
        spec["beats"][0]["shot"] = {"mode": "still", "subject": "scene",
                                    "prompt": "A friendly workbench with a calendar and a calculator in warm light."}
        self.assertIn("either a still or a tile grid", self.problems(spec))

    def test_the_grid_is_revealed_once_and_then_only_the_focus_moves(self):
        spec = self.grid()
        timing = reel_spec.beat_timing(spec["beats"], [4.0] * len(spec["beats"]))
        renderer = reel_spec.layout(spec, timing, {})
        grids = [element for scene in renderer["scenes"] for element in scene["elements"] if element["type"] == "tiles"]
        self.assertEqual(len(grids), 5)
        self.assertGreater(grids[0]["stagger"], 0)
        self.assertTrue(all(grid["stagger"] == 0 for grid in grids[1:]), "later beats keep the grid on screen")
        self.assertEqual([grid["focus"] for grid in grids], [None, 1, 5, 6, None])
        self.assertLess(grids[1]["focus_at"], grids[0]["focus_at"])
        self.assertEqual(len(grids[0]["tiles"]), 12)


class ColorPairTests(unittest.TestCase):
    def spec(self) -> dict:
        return load("reel_color_pairs.json")

    def problems(self, spec: dict) -> str:
        return " ".join(reel_spec.validate_spec(spec))

    def test_the_contrast_scale_runs_from_one_to_twenty_one(self):
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=2)
        self.assertAlmostEqual(contrast_ratio((120, 40, 40), (120, 40, 40)), 1.0, places=2)

    def test_a_pair_that_cannot_be_read_is_refused(self):
        spec = self.spec()
        spec["beats"][1]["on_screen"]["swatch"]["bottom"]["hex"] = "#7A3540"
        self.assertRegex(self.problems(spec), r"contrast of \d\.\d to 1")

    def test_the_swatch_rules(self):
        spec = self.spec()
        spec["beats"][1]["on_screen"]["swatch"]["top"]["hex"] = "red"
        spec["beats"][1]["on_screen"]["swatch"]["bottom"]["name"] = "N" * 21
        problems = self.problems(spec)
        self.assertIn("top hex must look like", problems)
        self.assertIn("bottom color needs a name", problems)

        spec = self.spec()
        spec["beats"][1]["on_screen"]["swatch"] = {"top": {"name": "Wine Red", "hex": "#722F37"}}
        self.assertIn("top and a bottom color", self.problems(spec))

        spec = load("reel_chapter_build.json")
        spec["beats"][0]["on_screen"]["swatch"] = self.spec()["beats"][1]["on_screen"]["swatch"]
        self.assertIn("color pair can only be used in", self.problems(spec))

        spec = self.spec()
        spec["beats"][1]["on_screen"]["tiles"] = load("reel_tile_grid.json")["beats"][0]["on_screen"]["tiles"]
        self.assertIn("one of a still, a tile grid, or a color pair", self.problems(spec))

    def test_the_text_takes_the_partner_color_unless_it_cannot_be_read(self):
        cream, wine = (246, 239, 230), (114, 47, 55)
        self.assertEqual(_swatch_ink(wine, cream), cream)
        self.assertEqual(_swatch_ink(cream, wine), wine)
        self.assertEqual(_swatch_ink((20, 20, 20), (30, 30, 30)), (255, 255, 255))
        self.assertEqual(_swatch_ink((240, 240, 240), (235, 235, 235)), (30, 30, 30))

    def test_each_half_is_its_own_color_and_the_pair_stays_in_the_safe_zone(self):
        spec = self.spec()
        timing = reel_spec.beat_timing(spec["beats"], [4.0] * len(spec["beats"]))
        renderer = reel_spec.layout(spec, timing, {})
        self.assertEqual(reel_spec.layout_problems(renderer), [])
        element = next(item for item in renderer["scenes"][1]["elements"] if item["type"] == "swatch")
        self.assertEqual([side["hex"] for side in element["swatch"]], ["#722F37", "#F6EFE6"])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            scene = {"start_seconds": 0, "duration_seconds": 1.0, "camera": "steady", "elements": [
                dict(element, box={"x": 20, "y": 40, "w": 320, "h": 400}, enter_motion="none")]}
            result = render_explainer({
                "renderer": {"canvas": {"width": 360, "height": 640, "fps": 6}, "scenes": [scene]},
                "output": str(folder / "out.mp4"), "preview": {"folder": str(folder), "times": [0.8]},
            })
            self.assertTrue(result["ok"], result.get("error"))
            frame = Image.open(result["previews"][0]).convert("RGB")
        self.assertEqual(frame.getpixel((40, 60)), (0x72, 0x2F, 0x37))
        self.assertEqual(frame.getpixel((40, 420)), (0xF6, 0xEF, 0xE6))


class LayoutTests(unittest.TestCase):
    def build(self, spec: dict, folder: Path) -> dict:
        voices = [4.0] * len(spec["beats"])
        timing = reel_spec.beat_timing(spec["beats"], voices)
        return reel_spec.layout(spec, timing, fake_plates(spec, folder))

    def test_every_format_stays_inside_the_safe_zones_without_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            Image.new("RGB", (400, 300), "#222").save(folder / "photo.png")
            specs = {
                "chapter_build": load("reel_chapter_build.json"),
                "beat_explainer": load("reel_beat_explainer.json"),
                "tile_grid": load("reel_tile_grid.json"),
                "color_pairs": load("reel_color_pairs.json"),
                "tile_workflow": tile_workflow(),
                "workflow_reel": load("reel_workflow.json"),
                "product_shot": product_spec(str(folder / "photo.png")),
            }
            for name, spec in specs.items():
                self.assertEqual(reel_spec.validate_spec(spec), [], name)
                self.assertEqual(reel_spec.layout_problems(self.build(spec, folder)), [], name)

    def test_longest_allowed_text_still_lays_out_and_fits(self):
        spec = load("reel_chapter_build.json")
        spec["title"] = "T" * 12 + " " + "word " * 9
        spec["title"] = spec["title"][:60]
        spec["beats"][1]["lower_third"] = ("Check the source before you share it " * 3)[:90]
        spec["beats"][2]["on_screen"] = {"card": "Claim", "prompt_text": ("Ask for sources. " * 14)[:220]}
        for beat, chapter in zip(spec["beats"], ["ONE", "TWO", "THREE", "FOUR", "FIVE"]):
            beat["chapter"] = chapter
        self.assertEqual(reel_spec.validate_spec(spec), [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(reel_spec.layout_problems(self.build(spec, Path(tmp))), [])
        font, lines, _height, _size = _fit_lines(
            spec["beats"][1]["lower_third"], reel_spec.LOWER["w"] - 86, reel_spec.LOWER["h"] - 32,
            lambda size: _font(size, "Bold"), 50, 28, max_lines=2, leading=1.16,
        )
        self.assertLessEqual(len(lines), 2)
        self.assertFalse(any("..." in line for line in lines), lines)

    def test_the_host_clears_the_text_column_for_every_pose(self):
        for pose in reel_spec.POSES:
            beats = [{"pose": pose}]
            left = reel_spec.host_left(beats)
            right = reel_spec._pose_right(pose, left)
            self.assertLessEqual(right, reel_spec.COLUMN["x"], f"{pose} reaches {right}")
            self.assertGreaterEqual(left, reel_spec.HOST_LEFT - reel_spec.MAX_HOST_SHIFT)

    def test_a_narrow_pose_set_keeps_the_host_in_place(self):
        self.assertEqual(reel_spec.host_left([{"pose": "neutral"}, {"pose": "reach"}]), reel_spec.HOST_LEFT)

    def test_the_host_is_always_a_library_pose(self):
        with tempfile.TemporaryDirectory() as tmp:
            renderer = self.build(load("reel_chapter_build.json"), Path(tmp))
        poses = set()
        for scene in renderer["scenes"]:
            for element in scene["elements"]:
                if element["type"] == "character":
                    poses.add(element["pose"])
                    self.assertNotIn("path", element)
        self.assertTrue(poses <= set(reel_spec.POSES))

    def test_beats_last_as_long_as_their_narration(self):
        beats = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        timing = reel_spec.beat_timing(beats, [1.0, 5.0, 3.0])
        self.assertEqual([item["duration"] for item in timing], [2.4, 5.35, 3.35])
        self.assertEqual([item["start"] for item in timing], [0.0, 2.4, 7.75])


class NarrationTests(unittest.TestCase):
    def test_the_track_fills_each_beat_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            tone(folder / "a.wav", 1.2)
            result = voice.build_track([(folder / "a.wav", 2.0), (None, 1.5)], folder / "track.wav")
            self.assertTrue(result["ok"], result.get("error"))
            self.assertAlmostEqual(voice.duration(folder / "track.wav"), 3.5, delta=0.1)

    def test_speak_trims_and_reuses_a_cached_file(self):
        class Speech:
            def __init__(self, path):
                self.path = path

            def read(self):
                return self.path.read_bytes()

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            tone(folder / "source.mp3", 2.0)
            calls = []

            class Client:
                class audio:
                    class speech:
                        @staticmethod
                        def create(**kwargs):
                            calls.append(kwargs["model"])
                            return Speech(folder / "source.mp3")

            first = voice.speak("Hello there.", folder / "line.wav", client=Client)
            second = voice.speak("Hello there.", folder / "line.wav", client=Client)
        self.assertTrue(first["ok"], first.get("error"))
        self.assertTrue(second["cached"])
        self.assertEqual(calls, [voice.MODEL])

    def test_speak_uses_the_characters_voice(self):
        voices = []

        class Client:
            class audio:
                class speech:
                    @staticmethod
                    def create(**kwargs):
                        voices.append((kwargs["voice"], kwargs["instructions"]))
                        raise RuntimeError("stop after the request")

        with tempfile.TemporaryDirectory() as tmp:
            for gender in ("female", "male", ""):
                voice.speak("Hello.", Path(tmp) / f"{gender or 'none'}.wav", client=Client, pace="quick", gender=gender)
        self.assertEqual([name for name, _ in voices], ["coral", voice.VOICE, voice.VOICE])
        self.assertIn("female", voices[0][1])
        self.assertTrue(all("Fast, punchy" in text for _, text in voices))

    def test_speak_reports_a_missing_key_without_inventing_audio(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(voice, "_secret", return_value=""):
            result = voice.speak("Hello.", Path(tmp) / "line.wav")
        self.assertFalse(result["ok"])
        self.assertIn("OPENAI_API_KEY", result["error"])


class PlateTests(unittest.TestCase):
    def beats(self, subject: str) -> list:
        return [{"id": "one", "pose": "think",
                 "shot": {"mode": "still", "subject": subject, "prompt": "A friendly scene in a bright studio with warm light."}}]

    def image(self, color="#335577") -> dict:
        return {"ok": True, "image": Image.new("RGB", (300, 400), color), "error": ""}

    def test_a_character_still_that_passes_the_check_is_kept_and_cached(self):
        calls = []

        def generate(reference, prompt):
            calls.append(prompt)
            return self.image()

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = plates_module.make_plates(self.beats("character"), folder, generate=generate,
                                               check=lambda ref, img: {"ok": True, "reason": ""})
            again = plates_module.make_plates(self.beats("character"), folder, generate=generate,
                                              check=lambda ref, img: {"ok": True, "reason": ""})
        self.assertEqual(result["plates"]["one"]["source"], "generated")
        self.assertEqual(again["plates"]["one"]["source"], "generated")
        self.assertEqual(len(calls), 1, "a good still is made once")
        self.assertIn("same person as in the reference image", calls[0])

    def test_a_character_still_that_drifts_is_replaced_by_the_approved_pose(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = plates_module.make_plates(
                self.beats("character"), folder, generate=lambda ref, prompt: self.image(),
                check=lambda ref, img: {"ok": False, "reason": "Different face."},
            )
            self.assertEqual(result["plates"]["one"]["source"], "pose_fallback")
            self.assertTrue(any("approved think pose" in note for note in result["notes"]), result["notes"])
            self.assertFalse((folder / "plate-one.json").exists(), "a fallback is retried next run")

    def test_an_unverified_character_still_is_never_used(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(plates_module, "_secret", return_value=""):
            result = plates_module.make_plates(self.beats("character"), Path(tmp),
                                               generate=lambda ref, prompt: self.image())
        self.assertEqual(result["plates"]["one"]["source"], "pose_fallback")

    def test_a_failed_generation_falls_back_without_a_different_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = plates_module.make_plates(
                self.beats("character"), Path(tmp),
                generate=lambda ref, prompt: {"ok": False, "image": None, "error": "no credits"},
                check=lambda ref, img: {"ok": True, "reason": ""},
            )
        self.assertEqual(result["plates"]["one"]["source"], "pose_fallback")
        self.assertTrue(any("no credits" in note for note in result["notes"]))

    def test_a_product_still_is_edited_from_the_reference_photo(self):
        seen = {}

        def generate(reference, prompt):
            seen["reference"], seen["prompt"] = reference, prompt
            return self.image()

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            photo = folder / "photo.png"
            Image.new("RGB", (200, 100), "#111").save(photo)
            result = plates_module.make_plates(self.beats("product"), folder, product_reference=str(photo), generate=generate)
        self.assertEqual(result["plates"]["one"]["source"], "generated")
        self.assertEqual(seen["reference"], photo)
        self.assertIn("only visual truth", seen["prompt"])

    def test_a_failed_product_still_uses_the_photo_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            photo = folder / "photo.png"
            Image.new("RGB", (200, 100), "#111").save(photo)
            result = plates_module.make_plates(
                self.beats("product"), folder, product_reference=str(photo),
                generate=lambda ref, prompt: {"ok": False, "image": None, "error": "timed out"},
            )
        self.assertEqual(result["plates"]["one"]["source"], "reference_photo")

    def test_a_product_still_without_a_photo_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = plates_module.make_plates(self.beats("product"), Path(tmp), product_reference=None,
                                               generate=lambda ref, prompt: self.image())
        self.assertFalse(result["ok"])
        self.assertIn("product reference", result["error"])

    def test_the_vision_check_needs_a_confident_yes(self):
        def client(reply: dict):
            class Message:
                content = json.dumps(reply)

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            class Completions:
                @staticmethod
                def create(**_kwargs):
                    return Response()

            class Chat:
                completions = Completions()

            class Client:
                chat = Chat()

            return Client()

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "ref.png"
            Image.new("RGB", (64, 64), "#222").save(reference)
            image = Image.new("RGB", (64, 64), "#333")
            yes = plates_module.vision_check(reference, image, client({"same_character": True, "confidence": 0.9}))
            unsure = plates_module.vision_check(reference, image, client({"same_character": True, "confidence": 0.4}))
            no = plates_module.vision_check(reference, image, client({"same_character": False, "confidence": 0.95}))
        self.assertTrue(yes["ok"])
        self.assertFalse(unsure["ok"])
        self.assertFalse(no["ok"])


class BuildTests(unittest.TestCase):
    def test_an_invalid_spec_is_not_built(self):
        spec = load("reel_chapter_build.json")
        spec["beats"][0]["shot"] = {"mode": "generated"}
        with tempfile.TemporaryDirectory() as tmp:
            result = reel_spec.build_reel(spec, Path(tmp), preview=True)
        self.assertFalse(result["ok"])
        self.assertIn("not valid", result["error"])

    def test_narration_failure_stops_the_build_instead_of_making_a_silent_reel(self):
        spec = load("reel_chapter_build.json")
        with tempfile.TemporaryDirectory() as tmp:
            result = reel_spec.build_reel(
                spec, Path(tmp), speak=lambda text, dest: {"ok": False, "error": "no credits"},
                plates={}, render=lambda payload: self.fail("must not render"),
            )
        self.assertFalse(result["ok"])
        self.assertIn("Narration was not created", result["error"])

    def test_a_full_build_passes_a_timed_narration_track_to_the_renderer(self):
        spec = load("reel_chapter_build.json")
        captured = {}

        def speak(text, dest):
            tone(dest, 1.5)
            return {"ok": True, "path": dest, "seconds": voice.duration(dest)}

        def render(payload):
            captured.update(payload)
            captured["track_seconds"] = voice.duration(Path(payload["voiceover"]))
            return {"ok": True, "path": payload["output"], "seconds": 12.0, "has_audio": True, "error": ""}

        with tempfile.TemporaryDirectory() as tmp:
            result = reel_spec.build_reel(spec, Path(tmp), speak=speak, plates={}, render=render)
            self.assertTrue((Path(tmp) / "renderer.json").is_file())
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["narrated"])
        total = sum(scene["duration_seconds"] for scene in captured["renderer"]["scenes"])
        self.assertAlmostEqual(captured["track_seconds"], total, delta=0.15)
        self.assertEqual(len(captured["renderer"]["scenes"]), 5)

    def test_a_preview_renders_stills_without_calling_any_provider(self):
        spec = load("reel_beat_explainer.json")
        with tempfile.TemporaryDirectory() as tmp:
            result = reel_spec.build_reel(spec, Path(tmp), preview=True)
            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(len(result["previews"]), 4)
            for path in result["previews"]:
                with Image.open(path) as picture:
                    self.assertEqual(picture.size, (1080, 1920))
        self.assertEqual(result["disclosure"], spec["disclosure"])


class RendererElementTests(unittest.TestCase):
    def test_the_new_elements_render_to_video_with_the_host_standing_on_foot_y(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            Image.new("RGB", (300, 400), "#5577aa").save(folder / "plate.png")

            def element(kind, box, **extra):
                base = {"id": kind, "type": kind, "box": box, "enter_at": 0.0, "enter_duration": 0.2,
                        "enter_motion": "slide_up", "exit_motion": "hold"}
                base.update(extra)
                return base

            scene = {"start_seconds": 0, "duration_seconds": 1.2, "camera": "push_in", "elements": [
                element("rail", {"x": 20, "y": 20, "w": 320, "h": 100}, enter_motion="none", label="Check",
                        chips=["Claim", "Source", "Fix"], active=1, timer="remaining", timeline=True),
                element("title", {"x": 20, "y": 140, "w": 320, "h": 200}, label="Is that right?",
                        stat={"value": "30", "unit": "seconds"}),
                element("image", {"x": 20, "y": 350, "w": 150, "h": 120}, path=str(folder / "plate.png"),
                        zoom=0.1, sweep=True, tag="Still"),
                element("prompt_card", {"x": 180, "y": 350, "w": 160, "h": 120}, label="Prompt", text="Ask for sources.",
                        meta="Scene 1"),
                element("sheet", {"x": 20, "y": 480, "w": 320, "h": 80}, label="Host", poses=["neutral", "present"]),
                element("character", {"x": 0, "y": 0, "w": 150, "h": 300}, pose="think", foot_y=600, enter_motion="none"),
                element("lower_third", {"x": 10, "y": 540, "w": 340, "h": 80}, label="Check the source."),
            ]}
            out = folder / "out.mp4"
            result = render_explainer({"renderer": {"canvas": {"width": 360, "height": 640, "fps": 6}, "scenes": [scene]},
                                       "output": str(out)})
            self.assertTrue(result["ok"], result.get("error"))
            self.assertGreater(out.stat().st_size, 1000)

    def test_tiles_pop_in_one_by_one_and_then_dim_all_but_the_focused_tile(self):
        tiles = [{"label": f"Item {n} → done", "glyph": glyph} for n, glyph in enumerate(
            ("bars", "ring", "arrow", "dots", "line", "check", "pin", "card", "toggle"), start=1)]
        grid = {"id": "grid", "type": "tiles", "box": {"x": 20, "y": 40, "w": 320, "h": 400}, "enter_at": 0.0,
                "enter_duration": 0.01, "enter_motion": "none", "exit_motion": "hold", "tiles": tiles,
                "stagger": 0.1, "focus": 5, "focus_at": 1.6}
        scene = {"start_seconds": 0, "duration_seconds": 2.6, "camera": "steady", "elements": [grid]}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = render_explainer({
                "renderer": {"canvas": {"width": 360, "height": 640, "fps": 6}, "scenes": [scene]},
                "output": str(folder / "out.mp4"),
                "preview": {"folder": str(folder), "times": [0.15, 1.5, 2.5]},
            })
            self.assertTrue(result["ok"], result.get("error"))
            early, settled, focused = (Image.open(path).convert("RGB") for path in result["previews"])
            # Early on, the last tile has not appeared, so its cell still shows the plain stage.
            last_cell = (240, 330, 340, 430)
            self.assertNotEqual(settled.crop(last_cell).tobytes(), early.crop(last_cell).tobytes())
            self.assertNotEqual(settled.tobytes(), focused.tobytes(), "the focus change must be visible")
            first_cell = (20, 40, 120, 140)
            self.assertNotEqual(settled.crop(first_cell).tobytes(), focused.crop(first_cell).tobytes(), "other tiles dim")

    def test_an_explainer_opens_with_the_host_on_the_left_and_words_on_the_right(self):
        scene = {
            "start_seconds": 0, "duration_seconds": 4.0, "camera": "steady", "purpose": "compare",
            "caption": "AI can sound sure and still be wrong.",
            "elements": [
                {"id": "left", "type": "card", "label": "AI checklist (illustration)",
                 "box": {"x": 80, "y": 520, "w": 420, "h": 360}, "enter_at": 0.2, "enter_duration": 0.4,
                 "enter_motion": "fade_in", "exit_motion": "hold"},
                {"id": "right", "type": "card", "label": "Official wording (illustration)",
                 "box": {"x": 540, "y": 520, "w": 420, "h": 360}, "enter_at": 0.2, "enter_duration": 0.4,
                 "enter_motion": "fade_in", "exit_motion": "hold"},
                {"id": "host", "type": "character", "label": "", "box": {"x": 64, "y": 900, "w": 540, "h": 580},
                 "enter_at": 0.0, "enter_duration": 0.8, "enter_motion": "walk_in", "exit_motion": "hold",
                 "pose": "think"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = render_explainer({
                "renderer": {"format": "brewiq-motion-explainer",
                             "canvas": {"width": 1080, "height": 1920, "fps": 6}, "scenes": [scene]},
                "output": str(folder / "out.mp4"),
                "preview": {"folder": str(folder), "times": [0.0, 1.5]},
            })
            self.assertTrue(result["ok"], result.get("error"))
            first = Image.open(result["previews"][0]).convert("RGB")
            later = Image.open(result["previews"][1]).convert("RGB")
        # The page is white, so a filled stage shows up as many dark ink pixels across the middle of the frame.
        ink = sum(1 for pixel in first.crop((0, 400, 1080, 1500)).resize((270, 275)).getdata() if max(pixel) < 80)
        self.assertGreater(ink, 500, "the first still must not be a blank stage")
        self.assertNotEqual(first.tobytes(), later.tobytes())

    def test_chrome_stays_still_while_the_camera_pushes_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)

            def box_scene(camera):
                return {"start_seconds": 0, "duration_seconds": 2.0, "camera": camera, "elements": [
                    {"id": "card", "type": "card", "label": "x", "box": {"x": 40, "y": 200, "w": 200, "h": 120},
                     "enter_motion": "none", "exit_motion": "hold"},
                    {"id": "bar", "type": "lower_third", "label": "Fixed", "box": {"x": 10, "y": 480, "w": 340, "h": 80},
                     "enter_motion": "none", "exit_motion": "hold"},
                ]}

            frames = {}
            for camera in ("steady", "push_in"):
                result = render_explainer({
                    "renderer": {"canvas": {"width": 360, "height": 640, "fps": 6}, "scenes": [box_scene(camera)]},
                    "output": str(folder / f"{camera}.mp4"),
                    "preview": {"folder": str(folder), "times": [1.9]},
                })
                self.assertTrue(result["ok"], result.get("error"))
                frames[camera] = Image.open(result["previews"][0]).copy()
                (folder / "preview-01.png").rename(folder / f"{camera}.png")
        bar = (40, 500, 320, 540)
        gap = ImageChops.difference(frames["steady"].crop(bar), frames["push_in"].crop(bar)).getextrema()
        self.assertLessEqual(max(high for _low, high in gap), 3, "the lower third must not zoom with the camera")
        self.assertNotEqual(frames["steady"].crop((40, 200, 240, 320)).tobytes(),
                            frames["push_in"].crop((40, 200, 240, 320)).tobytes())


class HistoryTests(unittest.TestCase):
    def test_a_withdrawn_record_stays_as_seen_but_is_no_longer_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_history(root, {"date": "2026-10-09", "title": "Why AI Video Needs a Queue", "carousel_status": "ready",
                                  "category": "ai_news", "keywords": [], "source_urls": [], "output": "x"})
            append_history(root, {"date": "2026-10-09", "title": "Other", "carousel_status": "ready",
                                  "category": "ai_research", "keywords": [], "source_urls": [], "output": "y"})
            self.assertTrue(withdraw_record(root, "2026-10-09", "Why AI Video Needs a Queue", "Not posted."))
            self.assertFalse(withdraw_record(root, "2026-10-09", "Why AI Video Needs a Queue", "Not posted."))
            records, available = load_history(root)
        self.assertTrue(available)
        self.assertEqual(records[0]["carousel_status"], "withdrawn")
        self.assertFalse(records[0]["posted_to_instagram"])
        self.assertEqual(records[0]["withdrawn_reason"], "Not posted.")
        self.assertEqual(records[1]["carousel_status"], "ready")

    def test_the_real_record_is_withdrawn(self):
        records, _ = load_history(HERE)
        match = [item for item in records if item.get("title") == "Why AI Video Needs a Queue"]
        self.assertEqual([item["carousel_status"] for item in match], ["withdrawn"])
        self.assertFalse(match[0]["posted_to_instagram"])


class RetiredModelTests(unittest.TestCase):
    def test_the_cover_image_uses_the_current_image_chain(self):
        import image

        with mock.patch("art.openai_image", return_value={"ok": True, "image": Image.new("RGB", (4, 4))}) as call:
            self.assertIsNotNone(image._openai_image("key", "prompt"))
        call.assert_called_once_with("prompt")
        with mock.patch("art.openai_image", return_value={"ok": False, "image": None}):
            self.assertIsNone(image._openai_image("key", "prompt"))



class QuickFixTests(unittest.TestCase):
    def _spec(self):
        beat = lambda role, words: {"id": role, "role": role, "voice": words, "lower_third": words,
                                    "on_screen": {"headline": words}, "shot": {"mode": "graphics"}}
        return {"format": "quick_fix", "beats": [beat("hook", "That toll text? Don't tap."),
                                                 beat("fix", "Check your toll account yourself."),
                                                 beat("cta", "Send this to someone who drives.")]}

    def test_quick_fix_needs_hook_fix_cta_in_order(self) -> None:
        self.assertEqual(reel_spec.validate_spec(self._spec()), [])
        spec = self._spec()
        spec["beats"][1]["role"] = "cta"
        self.assertTrue(any("hook, fix, cta" in problem for problem in reel_spec.validate_spec(spec)))

    def test_quick_fix_timing_is_tight_and_capped(self) -> None:
        timing = reel_spec.beat_timing(self._spec()["beats"], [1.6, 2.4, 1.9], "quick_fix")
        self.assertLessEqual(sum(item["duration"] for item in timing), reel_spec.QUICK_FIX_MAX_SECONDS)
        short = reel_spec.beat_timing(self._spec()["beats"], [1.2, 1.5, 1.4], "quick_fix")
        self.assertAlmostEqual(sum(item["duration"] for item in short), reel_spec.QUICK_FIX_MIN_SECONDS, places=2)
        with tempfile.TemporaryDirectory() as directory:
            slow = lambda text, dest: {"ok": True, "path": str(dest), "seconds": 4.0}
            result = reel_spec.build_reel(self._spec(), Path(directory), speak=slow, plates={}, render=lambda payload: {"ok": True})
        self.assertFalse(result["ok"])
        self.assertIn("7 to 8 seconds", result["error"])

    def test_quick_fix_lays_out_inside_the_safe_zones(self) -> None:
        spec = self._spec()
        timing = reel_spec.beat_timing(spec["beats"], [1.6, 2.4, 1.9], "quick_fix")
        renderer = reel_spec.layout(spec, timing, {})
        self.assertEqual(reel_spec.layout_problems(renderer), [])
        first = renderer["scenes"][0]["elements"]
        self.assertTrue(all(e["enter_at"] == 0.0 for e in first if e["type"] != "character"), "beat 1 is fully drawn at frame 0")
        self.assertFalse(any(e["type"] == "character" for scene in renderer["scenes"] for e in scene["elements"]), "faceless")

    def test_story_reel_puts_the_character_behind_the_words(self) -> None:
        spec = self._spec()
        spec["story"] = {"character": "a nurse in green scrubs", "setting": "a parked car", "alert": "Don't tap",
                         "moments": {"hook": "She frowns at a text.", "fix": "She checks.", "cta": "She smiles."}}
        spec["beats"][0]["on_screen"]["screen"] = {"app": "chat", "title": "Texts",
                                                   "lines": [{"who": "TOLL", "text": "Pay now", "mark": True}]}
        self.assertEqual(reel_spec.validate_spec(spec), [])
        payloads = []
        with tempfile.TemporaryDirectory() as directory:
            frames = {role: str(Path(directory) / f"{role}.png") for role in ("hook", "fix", "cta")}
            made = lambda story, folder, screens: {"ok": True, "kind": "stills", "frames": frames, "notes": ["Veo was out."],
                                                   "keyed": {"hook": str(Path(directory) / "keyed.png")},
                                                   "accents": {"hook": "#F2B33D", "insert": "#F2B33D", "fix": "#3D8BF2", "cta": "#F2B33D"}}
            quick = lambda text, dest: {"ok": True, "path": str(dest), "seconds": 1.8}
            result = reel_spec.build_reel(spec, Path(directory), speak=quick, make_story=made,
                                          render=lambda payload: payloads.append(payload) or {"ok": True},
                                          make_plates=lambda *a, **k: self.fail("a story reel draws no plates"))
            self.assertTrue(result["ok"], result.get("error"))
        payload = payloads[0]
        shots = payload["backdrop"]["shots"]
        self.assertEqual([shot["role"] for shot in shots], ["hook", "insert", "fix", "cta"], "the hook cuts to the phone close-up")
        self.assertEqual(shots[0]["start"], 0.0)
        self.assertEqual([item["color"] for item in payload["backdrop"]["accents"]], ["#F2B33D", "#3D8BF2", "#F2B33D"])
        scenes = payload["renderer"]["scenes"]
        self.assertEqual(reel_spec.layout_problems(payload["renderer"]), [])
        kinds = [e["type"] for scene in scenes for e in scene["elements"]]
        self.assertNotIn("lower_third", kinds, "the picture stays clear")
        self.assertNotIn("title", kinds, "story words are kinetic")
        self.assertNotIn("screen", [e["type"] for e in scenes[0]["elements"]], "a keyed hook needs no floating phone")
        self.assertIn("Veo was out.", result["notes"])
        self.assertIn("alert", kinds, "the thumb over the link gets the alert")
        broken = self._spec()
        broken["story"] = {"character": "x", "moments": {}}
        self.assertTrue(any("setting" in problem for problem in reel_spec.validate_spec(broken)))

if __name__ == "__main__":
    unittest.main()
