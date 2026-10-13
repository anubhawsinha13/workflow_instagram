"""Tests for BrewIQ post-production composition, cover and quality gates."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from composition import (
    BRAND,
    BRAND_LOOK,
    PRESENTER_ZONE,
    RENDER_CHECKS,
    brand_problems,
    build_composition,
    build_cover,
    composition_problems,
    contrast_ratio,
    cover_problems,
    fit_headline,
    icon_for_topic,
    phrase_subtitles,
    render_gate,
    voice_pacing,
    wrap_lines,
)

RUNS = Path(__file__).with_name("research_runs")


def _scenes() -> list[dict]:
    return [
        {"start": 0.0, "end": 4.0, "on_screen_text": [{"text": "Leave THIS robot home alone?", "start": 0.2, "end": 4.0}]},
        {"start": 4.0, "end": 8.0, "on_screen_text": []},
        {"start": 8.0, "end": 12.0, "on_screen_text": [{"text": "56% of tries", "start": 8.1, "end": 11.0}]},
    ]


VOICE = "Would you leave this robot home alone? It finished the job about half the time."


def _subs() -> list[dict]:
    return phrase_subtitles("Would you leave this robot home alone?", 0.05, 2.6) + phrase_subtitles(
        "It finished the job about half the time.", 8.05, 10.8
    )


class LayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.comp = build_composition(_scenes(), _subs(), icon=icon_for_topic("home robots"), icon_scene=3, label="Illustrative animation")

    def test_clean_layout_passes(self) -> None:
        self.assertEqual(composition_problems(self.comp, VOICE), [])
        types = [layer["type"] for layer in self.comp["layers"]]
        for kind in ("footage", "label", "headline", "subtitle", "icon", "brand"):
            self.assertIn(kind, types)
        self.assertEqual({a["type"] for a in self.comp["audio"]}, {"narration", "music", "sfx"})

    def test_text_in_presenter_zone_or_overlapping_is_rejected(self) -> None:
        bad = copy.deepcopy(self.comp)
        head = next(layer for layer in bad["layers"] if layer["type"] == "headline")
        head["box"] = [90, PRESENTER_ZONE[1] + 20, 690, 200]
        sub = next(layer for layer in bad["layers"] if layer["type"] == "subtitle")
        sub["box"] = list(head["box"])
        sub["start"], sub["end"] = head["start"], head["end"]
        problems = composition_problems(bad, VOICE)
        self.assertTrue(any("presenter area" in p for p in problems))
        self.assertTrue(any("overlap" in p for p in problems))

    def test_duplicate_caption_missing_brand_and_icon(self) -> None:
        bad = copy.deepcopy(self.comp)
        head = next(layer for layer in bad["layers"] if layer["type"] == "headline")
        head["text"] = next(layer for layer in bad["layers"] if layer["type"] == "subtitle")["text"]
        bad["layers"] = [layer for layer in bad["layers"] if layer["type"] not in ("brand", "icon")]
        problems = composition_problems(bad, VOICE)
        self.assertTrue(any("duplicates the headline" in p for p in problems))
        self.assertIn("Missing BrewIQ branding.", problems)
        self.assertIn("Missing topic icon.", problems)

    def test_blank_opening_out_of_sync_and_loud_music(self) -> None:
        bad = copy.deepcopy(self.comp)
        bad["layers"][0]["start"] = 0.5
        bad["audio"][1]["lufs"] = -18.0
        problems = composition_problems(bad, VOICE + " Extra words.")
        self.assertIn("Blank opening: footage must start at 0s.", problems)
        self.assertTrue(any("out of sync" in p for p in problems))
        self.assertTrue(any("dB under the voice" in p for p in problems))

    def test_repeated_narration_line_is_rejected(self) -> None:
        voice = "Study the gaps first. Then quiz yourself. Study the gaps first."
        subs = phrase_subtitles("Study the gaps first.", 0.05, 1.6) + phrase_subtitles("Then quiz yourself.", 4.05, 5.5)
        subs += phrase_subtitles("Study the gaps first.", 8.05, 9.6)
        comp = build_composition(_scenes(), subs, icon=icon_for_topic("notes"), icon_scene=3, label="Illustrative animation")
        self.assertTrue(any("repeats a line" in p for p in composition_problems(comp, voice)))

    def test_long_or_small_text_is_rejected(self) -> None:
        bad = copy.deepcopy(self.comp)
        head = next(layer for layer in bad["layers"] if layer["type"] == "headline")
        head["text"] = "This headline is far too long to read"
        head["size"] = 40
        problems = composition_problems(bad, VOICE)
        self.assertTrue(any("over 6 words" in p for p in problems))
        self.assertTrue(any("too small" in p for p in problems))


class TextTests(unittest.TestCase):
    def test_headline_fits_two_lines(self) -> None:
        size, lines = fit_headline("Leave THIS robot home alone?")
        self.assertGreaterEqual(size, 64)
        self.assertLessEqual(len(lines), 2)

    def test_separator_never_starts_or_ends_a_line(self) -> None:
        lines = wrap_lines("Towels · beds · toys", 84, 500)
        self.assertFalse(any(line.startswith("·") or line.endswith("·") for line in lines))

    def test_subtitles_are_short_and_cover_the_narration(self) -> None:
        subs = phrase_subtitles("Figure sent its humanoid into thirty homes it had never seen.", 0.0, 4.0)
        self.assertTrue(all(len(s["text"].split()) <= 6 for s in subs))
        self.assertEqual(subs[-1]["end"], 4.0)
        self.assertEqual(" ".join(s["text"] for s in subs), "Figure sent its humanoid into thirty homes it had never seen.")

    def test_brand_contrast_and_pacing(self) -> None:
        self.assertGreaterEqual(contrast_ratio(BRAND["clean_white"], BRAND["midnight_navy"]), 4.5)
        self.assertEqual(voice_pacing("one two three four five", [{"start": 0, "end": 2}])["wpm"], 150.0)
        self.assertEqual(voice_pacing("one two", [{"start": 0, "end": 2}])["note"], "slower than target")

    def test_topic_icons(self) -> None:
        self.assertEqual(icon_for_topic("Home robots fold towels")[0], "robotics")
        self.assertEqual(icon_for_topic("Deepfake scam calls")[0], "ai_security")
        self.assertEqual(icon_for_topic("Agents that run your workflow")[0], "ai_agents")
        self.assertEqual(icon_for_topic("Study notes with NotebookLM")[0], "productivity")
        self.assertEqual(icon_for_topic("OpenAI ships a new model")[0], "ai_news")


class CoverAndBrandTests(unittest.TestCase):
    def test_cover(self) -> None:
        cover = build_cover(visual="A robot mid-towel-snap", headline="Leave THIS robot home alone?", character_lock="HOST", environment_lock="SET")
        self.assertEqual(cover_problems(cover), [])
        self.assertNotIn("Leave THIS robot", cover["image_prompt"])
        bad = dict(cover, source="reel_frame", visual="", headline=dict(cover["headline"], text=""))
        problems = cover_problems(bad)
        self.assertTrue(any("never a frame" in p for p in problems))
        self.assertTrue(any("empty frame" in p for p in problems))
        self.assertTrue(any("curiosity headline" in p for p in problems))

    def test_brand_look(self) -> None:
        self.assertEqual(brand_problems([f"SET {BRAND_LOOK}"], "Navy studio"), [])
        problems = brand_problems(["SET only"], "A cream sofa on a beige rug")
        self.assertTrue(any("beige" in p for p in problems))
        self.assertTrue(any("brand look" in p for p in problems))


class RenderGateTests(unittest.TestCase):
    def _report(self, **failures: tuple[int | None, str]) -> list[dict]:
        return [
            {"check": key, "pass": key not in failures, "scene": failures.get(key, (None, ""))[0], "detail": failures.get(key, (None, ""))[1]}
            for key in RENDER_CHECKS
        ]

    def test_all_pass_is_approved(self) -> None:
        self.assertEqual(render_gate(self._report())["status"], "approved")

    def test_failures_reject_and_route(self) -> None:
        gate = render_gate(
            self._report(
                character_motion=(4, "feet slide"),
                text_hidden=(2, "headline behind host"),
                unsupported_claim=(None, "'every home' not in facts"),
            )
        )
        self.assertEqual(gate["status"], "rejected")
        self.assertEqual(gate["regenerate_scenes"], [4])
        self.assertTrue(any("scene 2" in f for f in gate["fix_in_post"]))
        self.assertTrue(any("unsupported_claim" in b for b in gate["blocked"]))
        self.assertTrue(gate["nothing_posted"])

    def test_missing_check_blocks(self) -> None:
        gate = render_gate(self._report()[1:])
        self.assertFalse(gate["ok"])
        self.assertTrue(any("not checked" in b for b in gate["blocked"]))


class RecordedRunTests(unittest.TestCase):
    def test_home_robot_package_passes_post_gates(self) -> None:
        pkg = json.loads((RUNS / "2026-10-11-home-robots.visual_package.json").read_text(encoding="utf-8"))
        voice = json.loads((RUNS / "2026-10-11-home-robots.script.json").read_text(encoding="utf-8"))["voiceover"]
        self.assertEqual(composition_problems(pkg["composition"], voice), [])
        self.assertEqual(cover_problems(pkg["cover"]), [])
        self.assertEqual(brand_problems([s["prompt"] for s in pkg["scenes"]], pkg["environment"]["lock_prompt"]), [])
        self.assertEqual(pkg["voice_pacing"]["note"], "")
        self.assertEqual(pkg["composition"]["layers"][-1]["type"], "brand")


if __name__ == "__main__":
    unittest.main()
