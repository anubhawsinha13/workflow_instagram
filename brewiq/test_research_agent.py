"""Tests for the BrewIQ Reel-First Research Agent gates. Fixtures are synthetic, not news."""

from __future__ import annotations

import copy
import unittest
from datetime import date

from cinematic_director import plan_reel
from research_agent import (
    MIN_SCORE,
    brief_to_script_research,
    build_research_prompt,
    format_brief_for_slack,
    hook_problems,
    parse_research_response,
    select_winner,
    validate_candidate,
    weighted_score,
)
from slack_director import parse_operator_reply

TODAY = date(2026, 10, 11)


def _candidate(topic: str, scores: dict[str, int], **overrides) -> dict:
    base = {
        "topic": topic,
        "category": "robots",
        "region": "Japan",
        "primary_source_url": "https://lab.example.org/announcements/fixture",
        "event_date": "2026-10-09",
        "publication_date": "2026-10-09",
        "freshness": "last_72h",
        "verified_facts": ["Fixture fact one.", "Fixture fact two."],
        "can_do_today": "Folds towels in a lab kitchen.",
        "limitations": ["Teleoperated for some tasks."],
        "speculative": ["Home availability date."],
        "scores": scores,
        "human_story": {
            "surprise": "It folds laundry slower than a teen.",
            "who_is_affected": "Busy parents.",
            "why_care": "Chores eat hours every week.",
            "everyday_situation": "A pile of laundry on Sunday night.",
            "most_compelling_fact": "Fixture compelling fact.",
            "viewer_question": "Would I trust it alone at home?",
            "scroll_stop_visual": "Robot hand catching a falling mug.",
        },
        "hooks": [
            {"approach": "curiosity_gap", "text": "Would you trust a robot home alone?"},
            {"approach": "surprising_fact", "text": "This robot folds laundry slower than your teenager"},
            {"approach": "everyday_problem", "text": "Sunday laundry pile? A robot just tried it"},
            {"approach": "future_implication", "text": "Your next roommate might need a charging cable"},
            {"approach": "contrarian", "text": "The hardest chore for robots is not cooking"},
        ],
        "winning_hook_index": 0,
        "winning_hook_reason": "Personal question; answer needs the real limitation.",
        "everyday_angle": "Chores at home.",
        "key_visual_moment": "Robot hand catches a falling mug mid-air.",
        "suggested_style": "cinematic_3d",
        "share_reason": "Tag the friend who hates laundry.",
    }
    base.update(overrides)
    return base


HIGH = {"curiosity": 9, "relatability": 9, "visual_potential": 9, "surprise": 8, "shareability": 8, "timeliness": 8}
MID = {"curiosity": 8, "relatability": 8, "visual_potential": 8, "surprise": 8, "shareability": 8, "timeliness": 8}
LOW = {"curiosity": 6, "relatability": 7, "visual_potential": 7, "surprise": 6, "shareability": 6, "timeliness": 9}


class ScoringTests(unittest.TestCase):
    def test_weights_sum_to_one_and_score(self) -> None:
        self.assertAlmostEqual(weighted_score(MID), 8.0)
        self.assertAlmostEqual(weighted_score(HIGH), 8.65)
        self.assertLess(weighted_score(LOW), MIN_SCORE)

    def test_out_of_range_score_rejected(self) -> None:
        with self.assertRaises(ValueError):
            weighted_score({**MID, "curiosity": 11})


class VerificationTests(unittest.TestCase):
    def test_passing_candidate(self) -> None:
        self.assertEqual(validate_candidate(_candidate("Laundry robot", HIGH), TODAY), [])

    def test_rejects_missing_or_secondary_source(self) -> None:
        for url in ("", "https://news.google.com/x", "https://x.com/post/1", "notaurl"):
            reasons = validate_candidate(_candidate("t", HIGH, primary_source_url=url), TODAY)
            self.assertTrue(any("primary-source" in r for r in reasons), url)

    def test_rejects_unreachable_source(self) -> None:
        reasons = validate_candidate(_candidate("t", HIGH), TODAY, source_reachable=lambda _u: False)
        self.assertTrue(any("not accessible" in r for r in reasons))

    def test_dates_and_staleness(self) -> None:
        stale = _candidate("t", HIGH, publication_date="2026-09-01", event_date="2026-09-01", freshness="last_7d")
        self.assertTrue(any("without a new development" in r for r in validate_candidate(stale, TODAY)))
        mislabel = _candidate("t", HIGH, publication_date="2026-10-05", freshness="last_72h")
        self.assertTrue(any("last_72h" in r for r in validate_candidate(mislabel, TODAY)))
        no_date = _candidate("t", HIGH, event_date="")
        self.assertTrue(any("Event date" in r for r in validate_candidate(no_date, TODAY)))

    def test_old_story_cannot_be_breaking(self) -> None:
        old = _candidate("t", HIGH, publication_date="2026-10-05", freshness="last_7d")
        old["hooks"][0]["text"] = "Breaking: a robot folds your laundry now"
        self.assertTrue(any("breaking" in r for r in validate_candidate(old, TODAY)))

    def test_limitations_required(self) -> None:
        reasons = validate_candidate(_candidate("t", HIGH, limitations=[]), TODAY)
        self.assertIn("Limitations not recorded.", reasons)

    def test_low_score_rejected(self) -> None:
        reasons = validate_candidate(_candidate("t", LOW), TODAY)
        self.assertTrue(any("below 7.5" in r for r in reasons))


class HookTests(unittest.TestCase):
    def test_bad_hooks(self) -> None:
        self.assertTrue(hook_problems("AI is changing the world faster than ever before"))
        self.assertTrue(hook_problems("WHY IT MATTERS"))
        self.assertTrue(hook_problems("Acme unveils new robot for your kitchen today"))
        self.assertEqual(hook_problems("Would you trust a robot home alone?"), [])


class SelectionTests(unittest.TestCase):
    def _research(self) -> dict:
        return {
            "candidates": [
                _candidate("Laundry robot", MID),
                _candidate("Voice clone scam call", HIGH, key_visual_moment="Phone rings with mom's voice"),
                _candidate("Weak story", LOW),
                _candidate("No source", HIGH, primary_source_url=""),
            ]
        }

    def test_ranks_and_selects_highest_passing(self) -> None:
        result = select_winner(self._research(), TODAY)
        self.assertTrue(result["ok"])
        self.assertEqual(result["brief"]["selected_topic"], "Voice clone scam call")
        self.assertEqual([t["topic"] for t in result["top_three"]], ["Voice clone scam call", "Laundry robot"])
        self.assertIn("Only 4 candidates", result["warning"])
        brief = result["brief"]
        for key in (
            "selected_topic", "source", "verified_facts", "limitations", "reel_potential",
            "hooks", "winning_hook", "everyday_angle", "key_visual_moment", "suggested_style", "share_reason",
        ):
            self.assertIn(key, brief)
        self.assertEqual(len(brief["hooks"]), 5)
        self.assertNotIn("script", brief)

    def test_incomplete_hooks_cannot_win(self) -> None:
        research = self._research()
        research["candidates"][1]["hooks"] = research["candidates"][1]["hooks"][:3]
        result = select_winner(research, TODAY)
        self.assertEqual(result["brief"]["selected_topic"], "Laundry robot")

    def test_avoids_recent_repeat(self) -> None:
        recent = [{"topic": "Voice clone scam call", "key_visual_moment": "x"}]
        result = select_winner(self._research(), TODAY, recent=recent)
        self.assertEqual(result["brief"]["selected_topic"], "Laundry robot")

    def test_blocked_when_nothing_passes(self) -> None:
        result = select_winner({"candidates": [_candidate("Weak", LOW)]}, TODAY)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Nothing has been posted", format_brief_for_slack(result))


class HandoffTests(unittest.TestCase):
    def test_brief_feeds_director_with_five_hooks(self) -> None:
        result = select_winner({"candidates": [_candidate("Laundry robot", HIGH)]}, TODAY)
        research = brief_to_script_research(result["brief"])
        options = plan_reel(research["topic"], research=research)
        self.assertEqual(options["status"], "awaiting_choice")
        hooks = options["options"]["hooks"]
        self.assertEqual(len(hooks), 5)
        self.assertEqual(hooks[0]["text"], "Would you trust a robot home alone?")
        self.assertEqual(options["options"]["recommended_style"], "cinematic_3d")
        self.assertEqual(parse_operator_reply("style=cinematic_3d hook=hook_5")["hook_id"], "hook_5")
        planned = plan_reel(research["topic"], research=research, style="cinematic_3d", hook_id="hook_5")
        self.assertEqual(planned["hook"]["approach"], "contrarian")

    def test_slack_brief_message(self) -> None:
        result = select_winner({"candidates": [_candidate("Laundry robot", HIGH)]}, TODAY)
        body = format_brief_for_slack(result)
        self.assertIn("Winning hook", body)
        self.assertIn("https://lab.example.org/announcements/fixture", body)
        self.assertIn("script not written yet", body)


class PromptTests(unittest.TestCase):
    def test_prompt_and_parse(self) -> None:
        prompt = build_research_prompt(TODAY, [{"topic": "Old reel", "hook_approach": "contrarian"}])
        self.assertIn("2026-10-08", prompt)
        self.assertIn("Old reel", prompt)
        self.assertIn("Never invent links", prompt)
        parsed = parse_research_response('Here:\n```json\n{"candidates": [], "winner": ""}\n```')
        self.assertEqual(parsed["candidates"], [])
        original = copy.deepcopy(_candidate("x", HIGH))
        self.assertEqual(original["topic"], "x")


if __name__ == "__main__":
    unittest.main()
