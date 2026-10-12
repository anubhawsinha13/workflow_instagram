"""Tests for the BrewIQ Slides Director (six-slide carousel fallback)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from cinematic_director import rank_hooks
from composition import BRAND_LOOK
from research_agent import brief_to_script_research
from slides_director import plan_slides, slides_problems

RUNS = Path(__file__).with_name("research_runs")


class SlidesDirectorTests(unittest.TestCase):
    def setUp(self) -> None:
        brief = json.loads((RUNS / "2026-10-11-home-robots.brief.json").read_text(encoding="utf-8"))
        self.topic = brief["selected_topic"]
        self.research = brief_to_script_research(brief)
        self.recorded = json.loads((RUNS / "2026-10-11-home-robots.slides.json").read_text(encoding="utf-8"))
        self.plan = plan_slides(self.topic, self.research, headlines=self.recorded["headlines"])
        self.facts = self.research["verified_facts"] + self.research["limitations"]

    def test_recorded_run_passes(self) -> None:
        self.assertEqual(self.plan["slide_problems"], [])
        self.assertEqual(self.plan, self.recorded["plan"])
        self.assertEqual(self.plan["aspect_ratio"], "4:5")
        self.assertEqual(self.plan["slides"][0]["headline"]["text"], "Leave THIS robot home alone?")
        self.assertTrue(all(BRAND_LOOK in s["image_prompt"] for s in self.plan["slides"]))
        self.assertTrue(all(len(s["headline"]["lines"]) <= 2 for s in self.plan["slides"]))
        for limitation in self.research["limitations"]:
            self.assertIn(limitation, self.plan["caption"])

    def test_fitting_research_hook_is_the_slide_hook(self) -> None:
        research = {
            "brief_hooks": [
                {"approach": "useful_promise", "text": "Save ten minutes every Sunday night"},
                {"approach": "curiosity_gap", "text": "What is your robot hiding now"},
            ],
            "verified_facts": ["A robot folded towels in a lab kitchen."],
        }
        plan = plan_slides("Home robots", research)
        self.assertEqual(plan["hook"], "What is your robot hiding now")

    def test_long_research_hook_keeps_the_template_overlay(self) -> None:
        research = {"hook": "Would you leave this folding robot completely alone in the house tonight"}
        plan = plan_slides("Home robots", research)
        self.assertEqual(plan["hook"], rank_hooks("Home robots", research)[0]["on_screen_text"])
        self.assertNotEqual(plan["hook"], research["hook"])

    def test_long_lines_need_written_headlines(self) -> None:
        plan = plan_slides(self.topic, self.research)
        self.assertTrue(any("needs a written headline" in p for p in plan["slide_problems"]))
        self.assertFalse(plan["ok"])
        self.assertFalse(any(s["headline"]["text"].endswith(("own", "who")) for s in plan["slides"]))

    def test_title_card_opening_rejected(self) -> None:
        bad = copy.deepcopy(self.plan)
        bad["slides"][0]["frame"] = "Title card on a gradient"
        self.assertTrue(any("title card" in p for p in slides_problems(bad, self.facts)))

    def test_repeated_framing_and_missing_close_up_rejected(self) -> None:
        bad = copy.deepcopy(self.plan)
        for slide in bad["slides"]:
            slide["frame"] = "Wide shot"
        problems = slides_problems(bad, self.facts)
        self.assertTrue(any("same framing" in p for p in problems))
        self.assertTrue(any("No close-up slide" in p for p in problems))

    def test_text_layer_and_model_text_rules(self) -> None:
        bad = copy.deepcopy(self.plan)
        bad["slides"][1]["headline"]["layer"] = "behind_character"
        bad["slides"][2]["headline"]["placement"] = "over_face"
        bad["slides"][3]["image_prompt"] += " Big words read: Figure's own test: 56% success"
        problems = slides_problems(bad, self.facts)
        self.assertTrue(any("above the character layer" in p for p in problems))
        self.assertTrue(any("must be placed" in p for p in problems))
        self.assertTrue(any("render the headline" in p for p in problems))

    def test_pointing_locks_and_facts(self) -> None:
        bad = copy.deepcopy(self.plan)
        for slide in bad["slides"][:2]:
            slide["character_action"] = "The host points at the robot."
        bad["slides"][4]["image_prompt"] = bad["slides"][4]["image_prompt"].replace(bad["environment_lock"], "")
        bad["slides"][5]["fact_basis"] = "a question"
        bad["slides"][5]["character_action"] = "The host looks away."
        problems = slides_problems(bad, self.facts)
        self.assertTrue(any("avoid repeated pointing" in p for p in problems))
        self.assertTrue(any("environment lock" in p for p in problems))
        self.assertTrue(any("illustrative: <why>" in p for p in problems))
        self.assertTrue(any("address the reader" in p for p in problems))

    def test_premium_rules(self) -> None:
        bad = copy.deepcopy(self.plan)
        bad["slides"][0]["headline"]["text"] = "Would you really leave this robot alone?"
        bad["slides"][1]["image_prompt"] = bad["slides"][1]["image_prompt"].replace(BRAND_LOOK, "")
        bad["slides"][2]["headline"]["lines"] = ["Towels", "beds", "toys"]
        bad["slides"][3]["character_action"] = "The host gives a thumbs-up."
        problems = slides_problems(bad, self.facts)
        self.assertTrue(any("over 6 words" in p for p in problems))
        self.assertTrue(any("brand look" in p for p in problems))
        self.assertTrue(any("2 lines" in p for p in problems))
        self.assertTrue(any("thumbs-up" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
