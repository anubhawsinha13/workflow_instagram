"""Tests for the BrewIQ utility (prompt pack) carousel."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from composition import BRAND_LOOK
from slack_director import format_slack_message, start_or_continue
from utility_carousel import carousel_problems, plan_utility_carousel, similarity

RUN = Path(__file__).with_name("research_runs") / "2026-10-11-prompt-pack-check-ai.utility_carousel.json"


class RecordedPackTests(unittest.TestCase):
    def setUp(self):
        self.recorded = json.loads(RUN.read_text(encoding="utf-8"))
        spec = copy.deepcopy(self.recorded["spec"])
        self.plan = plan_utility_carousel("checking an AI answer before you trust it", spec.pop("items"), **spec)

    def test_recorded_pack_passes(self):
        self.assertEqual(self.plan["problems"], [])
        self.assertEqual(self.plan, self.recorded["plan"])
        roles = [s["role"] for s in self.plan["slides"]]
        self.assertEqual(roles, ["cover"] + ["prompt"] * 6 + ["closing"])
        self.assertIn(BRAND_LOOK, self.plan["slides"][0]["image_prompt"])
        self.assertTrue(self.plan["nothing_posted"])

    def test_prompts_are_laid_out_to_fit(self):
        for slide in self.plan["slides"][1:-1]:
            prompt = next(layer for layer in slide["layers"] if layer["type"] == "prompt")
            self.assertGreaterEqual(prompt["size"], 30)
            self.assertTrue(slide["placeholders"])

    def _problems(self, mutate):
        bad = copy.deepcopy(self.plan)
        mutate(bad)
        return carousel_problems(bad)

    def test_too_long_prompt_and_missing_placeholder(self):
        def mutate(plan):
            slide = plan["slides"][1]
            slide["prompt"] = "word " * 80
            slide["placeholders"] = []
        problems = self._problems(mutate)
        self.assertTrue(any("over 70 words" in p for p in problems))
        self.assertTrue(any("[PLACEHOLDER]" in p for p in problems))

    def test_begging_cta_and_generic_reasons(self):
        def mutate(plan):
            plan["slides"][-1]["layers"][0]["text"] = "Share this with 3 friends and follow for more!"
            plan["share_reason"] = "It's useful."
        problems = self._problems(mutate)
        self.assertTrue(any("begs for engagement" in p for p in problems))
        self.assertTrue(any("share this (share_reason)" in p for p in problems))

    def test_overclaim_and_low_contrast(self):
        def mutate(plan):
            plan["slides"][2]["benefit"] = "Guaranteed to go viral"
            plan["slides"][2]["layers"][2]["color"] = "#1A2238"
        problems = self._problems(mutate)
        self.assertTrue(any("overclaims" in p for p in problems))
        self.assertTrue(any("contrast is below" in p for p in problems))


class OriginalityTests(unittest.TestCase):
    def test_near_copy_of_a_reference_prompt_is_rejected(self):
        recorded = json.loads(RUN.read_text(encoding="utf-8"))
        spec = copy.deepcopy(recorded["spec"])
        items = spec.pop("items")
        reference = items[0]["prompt"].replace("Here is", "This is")
        plan = plan_utility_carousel("checking an AI answer", items, reference_prompts=[reference], **spec)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("near-copy" in p for p in plan["problems"]))
        self.assertLess(similarity(items[0]["prompt"], items[1]["prompt"]), 0.6)


class SlackRouteTests(unittest.TestCase):
    def test_prompt_pack_keyword_waits_for_items_then_plans(self):
        first = start_or_continue("", operator_reply="#prompts checking AI answers")
        self.assertEqual(first["status"], "awaiting_content")
        self.assertEqual(first["topic"], "checking AI answers")
        self.assertIn("[PLACEHOLDERS]", format_slack_message(first))

        spec = json.loads(RUN.read_text(encoding="utf-8"))["spec"]
        second = start_or_continue("", research={"utility_carousel": spec}, thread=["#prompts checking AI answers"], operator_reply="here")
        self.assertEqual(second["status"], "planned", second.get("problems"))
        body = format_slack_message(second)
        self.assertIn("Find the weak spots", body)
        self.assertIn("Nothing has been posted", body)

    def test_research_hook_becomes_the_cover_when_headline_is_omitted(self):
        spec = copy.deepcopy(json.loads(RUN.read_text(encoding="utf-8"))["spec"])
        spec.pop("cover_headline")
        research = {
            "utility_carousel": spec,
            "brief_hooks": [
                {"approach": "curiosity_gap", "text": "What is your chatbot leaving out", "score": 9},
                {"approach": "useful_promise", "text": "Save these five prompts", "score": 4, "why": "A clear payoff."},
            ],
        }
        result = start_or_continue("", research=research, operator_reply="#prompts checking AI answers")
        self.assertEqual(result["status"], "planned", result.get("problems"))
        headline = next(layer for layer in result["slides"][0]["layers"] if layer["type"] == "headline")
        self.assertEqual(headline["text"], "Save these five prompts")
        self.assertEqual(result["hook"]["approach"], "useful_promise")
        self.assertEqual(result["hook"]["source"], "research")
        self.assertIn("chosen from research", format_slack_message(result))
        self.assertIn("Nothing has been posted", format_slack_message(result))

    def test_awaiting_prompt_names_the_research_hook(self):
        research = {"brief_hooks": [{"approach": "useful_promise", "text": "Save these five prompts"}]}
        first = start_or_continue("", research=research, operator_reply="#prompts checking AI answers")
        self.assertEqual(first["status"], "awaiting_content")
        self.assertIn("Save these five prompts", first["prompt"])
        self.assertIn("Nothing has been posted", format_slack_message(first))

    def test_existing_cover_is_kept_when_research_has_a_hook(self):
        spec = copy.deepcopy(json.loads(RUN.read_text(encoding="utf-8"))["spec"])
        research = {
            "utility_carousel": spec,
            "brief_hooks": [{"approach": "useful_promise", "text": "Save these five prompts"}],
        }
        result = start_or_continue("", research=research, thread=["#prompts checking AI answers"], operator_reply="here")
        self.assertEqual(result["status"], "planned", result.get("problems"))
        headline = next(layer for layer in result["slides"][0]["layers"] if layer["type"] == "headline")
        self.assertEqual(headline["text"], spec["cover_headline"])
        self.assertEqual(result["hook"]["text"], "Save these five prompts")


if __name__ == "__main__":
    unittest.main()
