"""Tests for the BrewIQ weekly test planner. All metrics are synthetic test data."""

from __future__ import annotations

import copy
import unittest
from datetime import date

from learning_loop import empty_learnings, weekly_review
from performance_agent import from_graph_insights, record_problems
from test_performance_agent import _sample
from weekly_planner import (
    EXPERIMENTS,
    format_week_for_slack,
    plan_week,
    post_labels,
    week_problems,
)

TOPICS = [
    "NotebookLM quizzes",
    "Home robots",
    "Gemini in Gmail",
    "AI agents book travel",
    "Deepfake voice scams",
    "Claude projects",
    "ChatGPT memory",
]
WEEK = date(2026, 10, 13)


def _learned():
    return weekly_review(_sample(), reviewed_on="2026-10-12", previous=empty_learnings())["learnings"]


class BaselineWeekTests(unittest.TestCase):
    def test_every_slot_is_a_labelled_test(self):
        for posts in (5, 6, 7):
            with self.subTest(posts=posts):
                plan = plan_week(TOPICS, week_of=WEEK, posts=posts)
                self.assertTrue(plan["ok"], plan["problems"])
                self.assertFalse(plan["uses_learnings"])
                self.assertEqual(len(plan["slots"]), posts)
                for slot in plan["slots"]:
                    self.assertEqual(slot["role"], "baseline")
                    self.assertEqual(slot["hypothesis"], EXPERIMENTS[slot["experiment"]][0])
                    self.assertIn("beat the account median", slot["test"])
                self.assertEqual({s["format"] for s in plan["slots"]}, {"reel", "utility_carousel"})
                self.assertGreaterEqual(len({s["hook_technique"] for s in plan["slots"]}), 3)

    def test_too_few_topics_is_flagged(self):
        plan = plan_week(TOPICS[:3], week_of=WEEK)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("needs a topic" in p for p in plan["problems"]))


class LearnedWeekTests(unittest.TestCase):
    def setUp(self):
        self.learned = _learned()

    def test_exploits_and_explores(self):
        for posts in (5, 6, 7):
            with self.subTest(posts=posts):
                plan = plan_week(TOPICS, week_of=WEEK, learnings=self.learned, posts=posts)
                self.assertTrue(plan["ok"], plan["problems"])
                self.assertEqual(plan["learned_from"], "2026-10-12")
                roles = [s["role"] for s in plan["slots"]]
                self.assertGreaterEqual(roles.count("explore"), 2)
                exploit_reels = [s for s in plan["slots"] if s["role"] == "exploit" and s["format"] == "reel"]
                self.assertTrue(exploit_reels)
                for slot in exploit_reels:
                    self.assertEqual(slot["experiment"], "EXP-006")
                    self.assertEqual(slot["hook_technique"], "curiosity_gap")
                explore_reels = [s for s in plan["slots"] if s["role"] == "explore" and s["format"] == "reel"]
                self.assertTrue(all(s["experiment"] == "EXP-004" for s in explore_reels))
                self.assertTrue(all(s["hook_technique"] != "curiosity_gap" for s in explore_reels))
                self.assertEqual(len({s["style"] for s in explore_reels}), len(explore_reels))
                self.assertEqual(len({s["hook_technique"] for s in explore_reels}), len(explore_reels))

    def test_exploit_carousel_says_it_repeats_the_format(self):
        plan = plan_week(TOPICS, week_of=WEEK, learnings=self.learned, posts=5)
        carousels = [s for s in plan["slots"] if s["format"] == "utility_carousel"]
        self.assertTrue(carousels)
        for slot in carousels:
            self.assertEqual(slot["role"], "exploit")
            self.assertIn("repeats the format", slot["test"])

    def test_carousels_lead_so_three_are_planned(self):
        plan = plan_week(TOPICS, week_of=WEEK, learnings=self.learned, posts=7)
        self.assertEqual(sum(s["format"] == "utility_carousel" for s in plan["slots"]), 3)
        other = dict(self.learned, preferred_format="reel")
        plan = plan_week(TOPICS, week_of=WEEK, learnings=other, posts=7)
        self.assertEqual(sum(s["format"] == "utility_carousel" for s in plan["slots"]), 2)

    def test_learned_style_leads_exploit_reels(self):
        learned = dict(self.learned, preferred_style="tech_storytelling")
        plan = plan_week(TOPICS, week_of=WEEK, learnings=learned, posts=7)
        styles = {s["style"] for s in plan["slots"] if s["role"] == "exploit" and s["format"] == "reel"}
        self.assertEqual(styles, {"tech_storytelling"})


class GateAndLabelTests(unittest.TestCase):
    def test_week_problems(self):
        plan = plan_week(TOPICS, week_of=WEEK, learnings=_learned(), posts=5)
        bad = copy.deepcopy(plan)
        for slot in bad["slots"]:
            slot.update(format="reel", style="cinematic_3d", hook_technique="curiosity_gap", role="exploit")
        bad["slots"][0]["experiment"] = "EXP-999"
        bad["slots"][1]["primary_metric"] = "likes"
        bad["slots"][2]["topic"] = bad["slots"][3]["topic"]
        problems = week_problems(bad)
        for text in ("known experiment", "primary metric", "same topic", "Vary the format", "Vary the hook technique",
                     "explore slots", "same thing twice"):
            self.assertTrue(any(text in p for p in problems), text)

    def test_labels_flow_into_the_performance_record(self):
        plan = plan_week(TOPICS, week_of=WEEK, learnings=_learned(), posts=5)
        slot = next(s for s in plan["slots"] if s["format"] == "reel")
        record = from_graph_insights(
            {"id": "179", "timestamp": "2026-10-13T18:00:00+0000", "media_product_type": "REELS"},
            {"reach": 1500, "saved": 30, "shares": 45},
            **post_labels(slot),
        )
        self.assertEqual(record_problems([record]), [])
        self.assertEqual(record["experiment"], slot["experiment"])
        self.assertEqual(record["style"], slot["style"])

    def test_slack_message_keeps_every_step(self):
        body = format_week_for_slack(plan_week(TOPICS, week_of=WEEK, learnings=_learned()))
        self.assertIn("learnings from 2026-10-12", body)
        self.assertIn("hook choice", body)
        self.assertIn("Nothing has been posted", body)


if __name__ == "__main__":
    unittest.main()
