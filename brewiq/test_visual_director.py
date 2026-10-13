"""Tests for the BrewIQ Cinematic Video Director package validator."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from visual_director import to_director_reel, validate_package

RUNS = Path(__file__).with_name("research_runs")


class VisualPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pkg = json.loads((RUNS / "2026-10-11.visual_package.json").read_text(encoding="utf-8"))
        self.script = json.loads((RUNS / "2026-10-11.script.json").read_text(encoding="utf-8"))

    def _problems(self, pkg: dict) -> list[str]:
        return validate_package(pkg, self.script)

    def test_recorded_package_passes(self) -> None:
        self.assertEqual(self._problems(self.pkg), [])

    def test_scene_count(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"] = bad["scenes"][:4]
        self.assertTrue(any("5–7 scenes" in p for p in self._problems(bad)))

    def test_static_camera_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][1]["camera"] = "Static shot with a Ken Burns zoom"
        self.assertTrue(any("static" in p for p in self._problems(bad)))

    def test_missing_character_lock_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][2]["prompt"] = "A monitor rises. No readable text."
        self.assertTrue(any("character lock" in p for p in self._problems(bad)))

    def test_model_rendered_text_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][0]["prompt"] += " Big title reads: An AI sent police a murder tip."
        self.assertTrue(any("render on-screen text" in p for p in self._problems(bad)))

    def test_clip_too_short_and_bad_length(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][2]["generation"]["clip_seconds"] = 6
        bad["scenes"][3]["generation"]["clip_seconds"] = 5
        problems = self._problems(bad)
        self.assertTrue(any("shorter than the scene" in p for p in problems))
        self.assertTrue(any("must be one of" in p for p in problems))

    def test_voiceover_and_subtitles_must_match_script(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][4]["voiceover"] = "It went to spam."
        bad["subtitles"][0]["text"] = "A robot sent police"
        problems = self._problems(bad)
        self.assertTrue(any("add up to the approved script" in p for p in problems))
        self.assertTrue(any("Subtitles do not match" in p for p in problems))

    def test_label_required(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["label"] = ""
        self.assertTrue(any("Illustrative animation" in p for p in self._problems(bad)))

    def test_character_references_exist(self) -> None:
        base = Path(__file__).parent
        if not (base / "brand/character-reference.png").is_file():
            self.skipTest("The character reference lives in a workflow_instagram checkout.")
        self.assertEqual(validate_package(self.pkg, self.script, base_dir=base), [])
        self.assertIn("BrewIQ host", self.pkg["character"]["lock_prompt"])
        bad = copy.deepcopy(self.pkg)
        bad["character"]["reference_assets"] = ["assets/character/missing.jpg"]
        self.assertTrue(any("not found" in p for p in validate_package(bad, self.script, base_dir=base)))

    def test_director_reel_export(self) -> None:
        reel = to_director_reel(self.pkg)
        self.assertEqual(reel["aspect_ratio"], "9:16")
        self.assertEqual(len(reel["scenes"]), 7)
        self.assertAlmostEqual(sum(s["trim_to_seconds"] for s in reel["scenes"]), 28.5)
        self.assertTrue(all(s["use_character"] and s["reference_assets"] for s in reel["scenes"]))


if __name__ == "__main__":
    unittest.main()
