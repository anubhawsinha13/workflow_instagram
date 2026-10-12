"""Tests for the BrewIQ learning loop. All metrics are synthetic test data."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cinematic_director import plan_reel, recommend_style
from hook_agent import select_from_pool
from learning_loop import (
    LEARNINGS_FILE,
    PROMOTE_AFTER,
    applied_summary,
    empty_learnings,
    hook_bonus,
    instructions_block,
    load_learnings,
    set_rule_status,
    update_learnings,
    weekly_review,
)
from performance_agent import review_posts
from research_agent import build_research_prompt
from slack_director import format_slack_message, parse_rule_reply, start_or_continue
from test_hook_agent import POOL_BRIEF as BRIEF
from test_hook_agent import _pool
from test_performance_agent import _sample


def _learned(**overrides):
    learned = weekly_review(_sample(), reviewed_on="2026-10-12", previous=empty_learnings())["learnings"]
    return {**learned, **overrides}


class MemoryTests(unittest.TestCase):
    def test_committed_file_starts_empty(self):
        stored = load_learnings(LEARNINGS_FILE)
        self.assertIsNone(stored["reviewed_on"])
        self.assertEqual(applied_summary(stored), [])
        self.assertEqual(instructions_block(stored), "")

    def test_missing_file_is_empty(self):
        self.assertEqual(load_learnings(Path(tempfile.gettempdir()) / "no-such-learnings.json"), empty_learnings())

    def test_weekly_review_writes_learnings_and_experiment_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.json"
            result = weekly_review(_sample(), reviewed_on="2026-10-12", learnings_path=path, runs_dir=tmp)
            self.assertTrue(result["ok"])
            self.assertEqual(load_learnings(path)["technique_bonus"], {"curiosity_gap": 0.49, "useful_promise": -0.49})
            record = json.loads((Path(tmp) / "2026-10-12.performance.json").read_text(encoding="utf-8"))
            self.assertEqual(set(record["records"]), {"EXP-001", "EXP-003"})
            self.assertIn("Applied automatically to the next plans", result["slack"])
            self.assertIn("Nothing has been posted", result["slack"])

    def test_blocked_review_changes_nothing(self):
        bad = _sample()
        bad[0]["experiment"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.json"
            result = weekly_review(bad, reviewed_on="2026-10-12", learnings_path=path)
            self.assertFalse(result["ok"])
            self.assertFalse(path.exists())
            self.assertIn("Nothing has been changed", result["slack"])

    def test_review_without_measurements_keeps_previous_values(self):
        previous = _learned()
        thin = review_posts([p for p in _sample() if p["post_id"] in ("r1", "r3")])
        updated = update_learnings(previous, thin, reviewed_on="2026-10-19", experiments=["EXP-001"])
        self.assertEqual(updated["technique_bonus"], previous["technique_bonus"])
        self.assertEqual(updated["preferred_format"], "utility_carousel")
        self.assertEqual(len(updated["history"]), 2)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.learned = _learned(preferred_style="interactive_explainer")

    def test_research_prompt_carries_the_learnings(self):
        prompt = build_research_prompt(date(2026, 10, 12), learnings=self.learned)
        self.assertIn("LEARNINGS FROM THE LAST PERFORMANCE REVIEW", prompt)
        self.assertIn("Fix opening", prompt)
        self.assertIn("never override accuracy", prompt)
        self.assertNotIn("LEARNINGS FROM", build_research_prompt(date(2026, 10, 12)))

    def test_hook_pool_uses_stored_bonus(self):
        pool = _pool()
        direct = select_from_pool(pool, BRIEF, technique_bonus=hook_bonus(self.learned))
        loaded = select_from_pool(pool, BRIEF, learnings=self.learned)
        self.assertEqual([h["text"] for h in direct["top"]], [h["text"] for h in loaded["top"]])
        bonuses = {h["technique"]: h["technique_bonus"] for h in loaded["ranked"]}
        self.assertEqual(bonuses["curiosity_gap"], 0.49)
        self.assertEqual(bonuses["useful_promise"], -0.49)
        explicit = select_from_pool(pool, BRIEF, technique_bonus={}, learnings=self.learned)
        self.assertTrue(all(h["technique_bonus"] == 0.0 for h in explicit["ranked"]))

    def test_learned_style_is_recommended_but_architecture_still_gets_motion_graphics(self):
        self.assertEqual(recommend_style("Home robots fold towels", learnings=self.learned), "interactive_explainer")
        self.assertEqual(recommend_style("API idempotency keys", learnings=self.learned), "motion_graphics")
        self.assertEqual(recommend_style("Home robots fold towels"), "cinematic_3d")

    def test_plan_and_slack_show_what_was_applied(self):
        result = start_or_continue("Home robots fold towels", learnings=self.learned)
        self.assertEqual(result["status"], "awaiting_choice")
        self.assertEqual(result["options"]["recommended_style"], "interactive_explainer")
        self.assertTrue(result["learnings_applied"])
        body = format_slack_message(result)
        self.assertIn("Applied from the last review", body)
        self.assertIn("directional", body)
        self.assertEqual(plan_reel("Home robots fold towels")["learnings_applied"], [])


class RuleProposalTests(unittest.TestCase):
    def _three_reviews(self):
        learned = empty_learnings()
        review = review_posts(_sample())
        for day in ("2026-10-12", "2026-10-19", "2026-10-26")[:PROMOTE_AFTER]:
            learned = update_learnings(learned, review, reviewed_on=day, experiments=["EXP-001", "EXP-003"])
        return learned

    def test_same_signal_three_reviews_in_a_row_becomes_a_proposal(self):
        once = update_learnings(empty_learnings(), review_posts(_sample()), reviewed_on="2026-10-12", experiments=["EXP-001"])
        self.assertEqual(once["rule_proposals"], [])
        ids = {p["id"] for p in self._three_reviews()["rule_proposals"]}
        self.assertIn("technique:curiosity_gap", ids)
        self.assertIn("priority:opening", ids)
        self.assertIn("format:utility_carousel", ids)

    def test_approval_is_recorded_and_kept(self):
        learned = set_rule_status(self._three_reviews(), "technique:curiosity_gap", "approved")
        later = update_learnings(learned, review_posts(_sample()), reviewed_on="2026-11-02", experiments=["EXP-001"])
        statuses = {p["id"]: p["status"] for p in later["rule_proposals"]}
        self.assertEqual(statuses["technique:curiosity_gap"], "approved")
        self.assertEqual(statuses["priority:opening"], "proposed")
        with self.assertRaises(KeyError):
            set_rule_status(learned, "style:nope", "approved")

    def test_slack_rule_reply(self):
        self.assertEqual(parse_rule_reply("approve rule technique:curiosity_gap"), ("approved", "technique:curiosity_gap"))
        self.assertEqual(parse_rule_reply("Reject rule priority:opening please"), ("rejected", "priority:opening"))
        self.assertIsNone(parse_rule_reply("approve the plan"))


if __name__ == "__main__":
    unittest.main()
