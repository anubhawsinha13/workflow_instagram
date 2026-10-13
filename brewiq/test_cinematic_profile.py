"""Tests for the cinematic ("miniature movie") profile and the household-robot remake run."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hook_agent import select_hook
from script_agent import validate_script
from visual_director import cinematic_problems, to_director_reel, validate_package

BASE = Path(__file__).parent
REFERENCE_DIR = BASE if (BASE / "brand/character-reference.png").is_file() else None
RUNS = BASE / "research_runs"
PREFIX = "2026-10-11-home-robots"


def _load(name: str) -> dict:
    return json.loads((RUNS / f"{PREFIX}.{name}.json").read_text(encoding="utf-8"))


class HomeRobotRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = _load("brief")
        self.script = _load("script")
        self.pkg = _load("visual_package")

    def _problems(self, pkg: dict) -> list[str]:
        return cinematic_problems(pkg, self.brief)

    def test_recorded_run_passes_every_stage(self) -> None:
        hooks = _load("hooks")
        selection = select_hook(hooks["evaluations"], self.brief)
        self.assertEqual(selection["winner"]["text"], "Would you leave THIS robot home alone?")
        self.assertEqual(validate_script(self.script, self.brief), [])
        self.assertEqual(validate_package(self.pkg, self.script, base_dir=REFERENCE_DIR), [])
        self.assertEqual(self._problems(self.pkg), [])

    def test_recorded_lock_matches_character_sheet(self) -> None:
        lock = self.pkg["character"]["lock_prompt"]
        for trait in ("wavy hair", "black quilted jacket", "no glasses"):
            self.assertIn(trait, lock)
        old = json.loads((RUNS / "2026-10-11.visual_package.json").read_text(encoding="utf-8"))
        self.assertEqual(old["character"]["lock_prompt"], lock)
        self.assertTrue(all(lock in s["prompt"] for s in old["scenes"]))

    def test_slow_opening_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][0]["events"][0]["t"] = 1.2
        self.assertTrue(any("motion by 0.5s" in p for p in self._problems(bad)))

    def test_title_slide_opening_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][0]["camera"] = "Push-in on a title card"
        self.assertTrue(any("title slide" in p for p in self._problems(bad)))

    def test_event_gap_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][3]["events"] = bad["scenes"][3]["events"][-1:]
        bad["scenes"][2]["events"] = bad["scenes"][2]["events"][:1]
        self.assertTrue(any("No new story event" in p for p in self._problems(bad)))

    def test_zoom_and_missing_moves_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        for scene in bad["scenes"]:
            scene["camera"] = "Slow zoom on the robot"
        problems = self._problems(bad)
        self.assertTrue(any("uses a zoom" in p for p in problems))
        self.assertTrue(any("No over-the-shoulder shot" in p for p in problems))

    def test_repeated_pointing_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        for index in (1, 2):
            bad["scenes"][index]["character_actions"] = "The host points at the robot."
        self.assertTrue(any("avoid repeated pointing" in p for p in self._problems(bad)))
        self.assertFalse(any("pointing" in p for p in self._problems(self.pkg)))

    def test_text_rules(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][1]["on_screen_text"][1]["start"] = 4.0
        bad["scenes"][2]["on_screen_text"][0]["placement"] = "bottom"
        bad["scenes"][3]["on_screen_text"][0]["layer"] = "behind_character"
        problems = self._problems(bad)
        self.assertTrue(any("one line at a time" in p for p in problems))
        self.assertTrue(any("must be placed" in p for p in problems))
        self.assertTrue(any("above the character layer" in p for p in problems))

    def test_fact_basis_required(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][3]["fact_basis"] = [42]
        bad["scenes"][5]["fact_basis"] = "a remote operator"
        problems = self._problems(bad)
        self.assertTrue(any("unknown verified fact" in p for p in problems))
        self.assertTrue(any("illustrative: <why>" in p for p in problems))

    def test_scene_length_runtime_and_locks(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][-1]["end"] = 31.0
        bad["scenes"][2]["prompt"] = bad["scenes"][2]["prompt"].replace(bad["environment"]["lock_prompt"], "")
        problems = self._problems(bad)
        self.assertTrue(any("clips must be 3–5s" in p for p in problems))
        self.assertTrue(any("Runtime 31.0s" in p for p in problems))
        self.assertTrue(any("environment lock" in p for p in problems))

    def test_thumbs_up_wave_and_stationary_host_rejected(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][1]["character_actions"] = "The host gives a thumbs-up to the robot."
        bad["scenes"][2]["character_actions"] = "The host stands still beside the table."
        problems = self._problems(bad)
        self.assertTrue(any("thumbs-up or wave" in p for p in problems))
        self.assertTrue(any("stationary presenter" in p for p in problems))

    def test_host_must_speak_to_camera(self) -> None:
        bad = copy.deepcopy(self.pkg)
        bad["scenes"][-1]["character_actions"] = "The host watches the robot."
        self.assertTrue(any("speaks to camera" in p for p in self._problems(bad)))

    def test_director_reel_export(self) -> None:
        reel = to_director_reel(self.pkg)
        self.assertEqual(len(reel["scenes"]), 7)
        self.assertAlmostEqual(sum(s["trim_to_seconds"] for s in reel["scenes"]), 24.0)
        self.assertTrue(all(3.0 <= s["trim_to_seconds"] <= 4.0 for s in reel["scenes"]))
        self.assertEqual(reel, _load("director_reel"))


if __name__ == "__main__":
    unittest.main()
