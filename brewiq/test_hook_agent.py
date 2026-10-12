"""Tests for the BrewIQ Hook Selection Agent."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from cinematic_director import rank_hooks
from hook_agent import (
    POOL_TECHNIQUES,
    apply_to_brief,
    best_hook_for_post,
    opening_visual_problems,
    pool_to_brief_hooks,
    score_hook,
    select_from_pool,
    select_hook,
)

RUNS = Path(__file__).with_name("research_runs")


class HookSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = json.loads((RUNS / "2026-10-11.result.json").read_text(encoding="utf-8"))["brief"]
        run = json.loads((RUNS / "2026-10-11.hooks.json").read_text(encoding="utf-8"))
        self.evaluations = run["evaluations"]
        self.opening = run["opening_visual"]

    def test_recorded_run_selects_supported_hook(self) -> None:
        result = select_hook(self.evaluations, self.brief)
        self.assertTrue(result["ok"])
        self.assertEqual(result["winner"]["text"], "An AI sent police a murder tip. It was invented.")
        partial = [r for r in result["ranked"] if r["accuracy"] == "partial"]
        self.assertEqual(len(partial), 2)
        self.assertTrue(all(not r["eligible"] for r in partial))

    def test_higher_score_cannot_beat_accuracy_gate(self) -> None:
        evals = copy.deepcopy(self.evaluations)
        everyday = next(e for e in evals if e["approach"] == "everyday_problem")
        everyday["scores"] = {k: 10 for k in everyday["scores"]}
        self.assertNotEqual(select_hook(evals, self.brief)["winner"]["approach"], "everyday_problem")

    def test_unsupported_citation_rejected(self) -> None:
        evals = copy.deepcopy(self.evaluations)
        for e in evals:
            e["supported_by"] = [99]
        result = select_hook(evals, self.brief)
        self.assertFalse(result["ok"])

    def test_requires_all_five_approaches(self) -> None:
        self.assertFalse(select_hook(self.evaluations[:4], self.brief)["ok"])

    def test_score_range(self) -> None:
        with self.assertRaises(ValueError):
            score_hook({"scores": {"curiosity": 0, "clarity": 5, "relatability": 5, "visual_potential": 5}})

    def test_opening_visual(self) -> None:
        self.assertEqual(opening_visual_problems(self.opening), [])
        bad = dict(self.opening, first_frame="BrewIQ logo reveal, then a title card")
        self.assertTrue(any("Start on action" in p for p in opening_visual_problems(bad)))
        bad = dict(self.opening, on_screen_text="WHY IT MATTERS")
        self.assertTrue(any("weak" in p.lower() for p in opening_visual_problems(bad)))
        bad = {k: v for k, v in self.opening.items() if k != "character_in_first_frame"}
        self.assertTrue(any("first frame" in p for p in opening_visual_problems(bad)))

    def test_apply_to_brief(self) -> None:
        result = select_hook(self.evaluations, self.brief)
        updated = apply_to_brief(self.brief, result, self.opening)
        self.assertEqual(updated["winning_hook"]["text"], result["winner"]["text"])
        self.assertFalse(updated["opening_visual"]["character_in_first_frame"])
        self.assertEqual(len(updated["hook_ranking"]), 5)
        self.assertNotIn("opening_visual", self.brief)


def _pool(n=20, techniques=POOL_TECHNIQUES):
    return [
        {
            "technique": techniques[i % len(techniques)],
            "text": f"This robot folded towels in home number {i} it had never seen",
            "scores": {"clarity": 6 + i % 4, "curiosity": 7, "relevance": 7, "keeps_right_viewer": 6},
            "accuracy": "supported",
            "supported_by": [0],
            "why": f"Hook {i}.",
        }
        for i in range(n)
    ]


POOL_BRIEF = {"verified_facts": ["Figure tested its robot in 30 homes."]}


class HookPoolTests(unittest.TestCase):

    def test_pool_ranks_top_five(self) -> None:
        result = select_from_pool(_pool(), POOL_BRIEF)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(len(result["top"]), 5)
        scores = [r["score"] for r in result["top"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreaterEqual(len(result["techniques_in_top"]), 2)

    def test_pool_needs_twenty_hooks_and_eight_techniques(self) -> None:
        self.assertIn("at least 20", select_from_pool(_pool(12), POOL_BRIEF)["error"])
        narrow = select_from_pool(_pool(20, POOL_TECHNIQUES[:3]), POOL_BRIEF)
        self.assertIn("8 different techniques", narrow["error"])

    def test_clickbait_duplicates_and_partial_accuracy_are_gated(self) -> None:
        pool = _pool()
        pool[0]["text"] = "This shocking robot secret changes how you do laundry"
        pool[0]["scores"] = dict.fromkeys(pool[0]["scores"], 10)
        pool[1]["text"] = pool[2]["text"]
        pool[3]["accuracy"] = "partial"
        result = select_from_pool(pool, POOL_BRIEF)
        rejected = {r["text"]: r["rejected"] for r in result["ranked"] if not r["eligible"]}
        self.assertTrue(any("Clickbait" in " ".join(v) for v in rejected.values()))
        self.assertTrue(any("Duplicate" in " ".join(v) for v in rejected.values()))
        self.assertTrue(any("Accuracy is partial" in " ".join(v) for v in rejected.values()))
        self.assertNotEqual(result["winner"]["text"], pool[0]["text"])

    def test_top_five_become_the_slack_hook_options(self) -> None:
        brief_hooks = pool_to_brief_hooks(select_from_pool(_pool(), POOL_BRIEF))
        hooks = rank_hooks("Home robots", {"brief_hooks": brief_hooks})
        self.assertEqual(len(hooks), 5)
        self.assertEqual(hooks[0]["text"], brief_hooks[0]["text"])


def _eval(technique: str, text: str, accuracy: str, score: int = 8) -> dict:
    return {
        "technique": technique,
        "text": text,
        "accuracy": accuracy,
        "supported_by": [0],
        "scores": {"clarity": score, "curiosity": score, "relevance": score, "keeps_right_viewer": score},
        "why": technique,
    }


class PostTypeHookTests(unittest.TestCase):
    def test_post_types_pick_different_approaches_from_the_same_hooks(self) -> None:
        research = {
            "brief_hooks": [
                {"approach": "everyday_problem", "text": "Your laundry pile never really shrinks", "score": 5},
                {"approach": "useful_promise", "text": "Save ten minutes every Sunday night", "score": 5},
                {"approach": "curiosity_gap", "text": "What is your home robot hiding", "score": 5},
                {"approach": "narrative_tension", "text": "The robot stalled halfway through the fold", "score": 5},
                {"approach": "surprising_contrast", "text": "A slow robot beat a rushed human folder", "score": 5},
                {"approach": "specific_mistake", "text": "One missed sensor ruins the whole fold", "score": 5},
                {"approach": "surprising_fact", "text": "This robot folded slower than a teenager", "score": 5},
            ]
        }
        expected = {
            "cinematic_3d": "surprising_contrast",
            "interactive_explainer": "everyday_problem",
            "tech_storytelling": "narrative_tension",
            "motion_graphics": "useful_promise",
            "utility_carousel": "useful_promise",
            "slides": "curiosity_gap",
        }
        for post_type, approach in expected.items():
            picked = best_hook_for_post(research, post_type)
            self.assertIsNotNone(picked)
            self.assertEqual(picked["approach"], approach, post_type)
            self.assertEqual(picked["source"], "research")

    def test_partial_and_unsupported_evaluations_are_skipped_when_facts_exist(self) -> None:
        facts = ["Figure tested its robot in thirty homes."]
        evaluations = [
            _eval("curiosity_gap", "Would you leave this robot home alone", "partial", 10),
            _eval("useful_promise", "Save ten minutes with this one retry", "unsupported", 10),
            _eval("everyday_problem", "Your laundry pile never really shrinks", "supported", 6),
        ]
        research = {"verified_facts": facts, "hook_evaluations": evaluations}
        picked = best_hook_for_post(research, "cinematic_3d")
        self.assertEqual(picked["approach"], "everyday_problem")
        self.assertIsNone(best_hook_for_post({"verified_facts": facts, "hook_evaluations": evaluations[:2]}, "slides"))
        kept = best_hook_for_post({"hook_evaluations": evaluations[:1]}, "slides")
        self.assertEqual(kept["text"], evaluations[0]["text"])

    def test_no_research_hook_returns_none(self) -> None:
        self.assertIsNone(best_hook_for_post(None, "cinematic_3d"))
        self.assertIsNone(best_hook_for_post({}, "interactive_explainer"))
        self.assertIsNone(best_hook_for_post({"hook": "WHY IT MATTERS", "headline": "Queue the render"}, "slides"))
        self.assertIsNone(best_hook_for_post({"brief_hooks": [{"approach": "curiosity_gap", "text": "Try this"}]}, "slides"))

    def test_learnings_only_break_ties(self) -> None:
        fit = {
            "brief_hooks": [
                {"approach": "useful_promise", "text": "Save ten minutes with this one retry", "score": 10},
                {"approach": "curiosity_gap", "text": "Would you leave this robot home", "score": 1},
            ]
        }
        bonus = {
            "reviewed_on": "2026-10-12",
            "technique_bonus": {"useful_promise": 5.0, "curiosity_gap": -0.5},
            "experiments": ["EXP-004"],
        }
        self.assertEqual(best_hook_for_post(fit, "cinematic_3d", bonus)["approach"], "curiosity_gap")

        scored = {
            "brief_hooks": [
                {"approach": "zeta_angle", "text": "Zeta robots fold towels at night", "score": 4},
                {"approach": "alpha_angle", "text": "Alpha robots fold towels at night", "score": 9},
            ]
        }
        score_bonus = {
            "reviewed_on": "2026-10-12",
            "technique_bonus": {"zeta_angle": 0.5, "alpha_angle": -0.5},
            "experiments": ["EXP-004"],
        }
        self.assertEqual(best_hook_for_post(scored, "cinematic_3d", score_bonus)["approach"], "alpha_angle")

        tied = {
            "brief_hooks": [
                {"approach": "zeta_angle", "text": "Zeta robots fold towels at night", "score": 5},
                {"approach": "alpha_angle", "text": "Alpha robots fold towels at night", "score": 5},
            ]
        }
        self.assertEqual(best_hook_for_post(tied, "slides")["approach"], "zeta_angle")
        tie_bonus = {
            "reviewed_on": "2026-10-12",
            "technique_bonus": {"alpha_angle": 0.5, "zeta_angle": -0.5},
            "experiments": ["EXP-004"],
        }
        self.assertEqual(best_hook_for_post(tied, "slides", tie_bonus)["approach"], "alpha_angle")


if __name__ == "__main__":
    unittest.main()
