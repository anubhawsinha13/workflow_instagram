"""Tests for the BrewIQ Reel Script Agent validator."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import date
from pathlib import Path

from research_agent import select_winner
from script_agent import to_visual_director, validate_script, word_count

RUNS = Path(__file__).with_name("research_runs")


def _load() -> tuple[dict, dict]:
    run = json.loads((RUNS / "2026-10-11.json").read_text(encoding="utf-8"))
    reach = {c["primary_source_url"]: c.get("accessible", False) for c in run["candidates"]}
    result = select_winner(run, date(2026, 10, 11), source_reachable=lambda u: reach.get(u, False))
    script = json.loads((RUNS / "2026-10-11.script.json").read_text(encoding="utf-8"))
    return script, result["brief"]


class ScriptValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script, self.brief = _load()

    def test_recorded_script_passes(self) -> None:
        self.assertEqual(validate_script(self.script, self.brief), [])
        self.assertTrue(45 <= word_count(self.script["voiceover"]) <= 65)

    def test_word_count_limits(self) -> None:
        bad = copy.deepcopy(self.script)
        bad["voiceover"] += " This extra sentence pushes the narration well past the limit for a short reel."
        self.assertTrue(any("words" in p for p in validate_script(bad, self.brief)))

    def test_long_static_shot_rejected(self) -> None:
        bad = copy.deepcopy(self.script)
        bad["shots"][0]["end"] = 5.0
        bad["shots"][1]["start"] = 5.0
        self.assertTrue(any("without a visual change" in p for p in validate_script(bad, self.brief)))

    def test_shots_must_be_labelled(self) -> None:
        bad = copy.deepcopy(self.script)
        bad["shots"][3]["kind"] = ""
        self.assertTrue(any("illustration or real_footage" in p for p in validate_script(bad, self.brief)))

    def test_dropped_qualification_rejected(self) -> None:
        bad = copy.deepcopy(self.script)
        bad["qualifications"] = bad["qualifications"][1:]
        self.assertTrue(any("Qualification not preserved" in p for p in validate_script(bad, self.brief)))

    def test_weak_hook_and_bait_rejected(self) -> None:
        bad = copy.deepcopy(self.script)
        bad["shots"][0]["on_screen_text"] = "WHY IT MATTERS"
        bad["voiceover"] = bad["voiceover"].replace("click wrong.", "click wrong. Follow for more.")
        problems = validate_script(bad, self.brief)
        self.assertTrue(any("weak opener" in p for p in problems))
        self.assertTrue(any("engagement bait" in p for p in problems))

    def test_unknown_source_and_beat_order(self) -> None:
        bad = copy.deepcopy(self.script)
        bad["sources"].append("https://example.com/not-in-brief")
        bad["beats"][1], bad["beats"][2] = bad["beats"][2], bad["beats"][1]
        problems = validate_script(bad, self.brief)
        self.assertTrue(any("not in the research brief" in p for p in problems))
        self.assertTrue(any("in order" in p for p in problems))

    def test_handoff(self) -> None:
        handoff = to_visual_director(self.script, self.brief)
        self.assertEqual(handoff["style"], "tech_storytelling")
        self.assertEqual(handoff["hook"], self.brief["winning_hook"]["text"])
        self.assertTrue(handoff["do_not_depict"])


if __name__ == "__main__":
    unittest.main()
