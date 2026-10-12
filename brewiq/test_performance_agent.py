"""Tests for the BrewIQ Performance Agent. All metrics here are synthetic test data."""

from __future__ import annotations

import unittest

from hook_agent import select_from_pool
from performance_agent import (
    experiment_record,
    from_graph_insights,
    learnings,
    post_rates,
    priority_changes,
    review_posts,
)


def _post(post_id, *, fmt="reel", technique="curiosity_gap", style="cinematic_3d", reach=2000, saves=20, sends=20,
          comments=4, follows=4, hold=0.5, watch=10.0, duration=24.0, experiment="EXP-001", layout=None):
    return {
        "post_id": post_id,
        "experiment": experiment,
        "format": fmt,
        "style": style,
        "hook_technique": technique,
        **({"layout": layout} if layout else {}),
        "duration_seconds": duration,
        "metrics": {"reach": reach, "saves": saves, "sends": sends, "comments": comments, "follows": follows,
                    "hold_3s": hold, "avg_watch_seconds": watch},
    }


def _sample():
    return [
        _post("r1", technique="curiosity_gap", hold=0.62, sends=24),
        _post("r2", technique="curiosity_gap", hold=0.58, sends=22),
        _post("r3", technique="useful_promise", hold=0.35, sends=18, watch=6.0),
        _post("r4", technique="useful_promise", hold=0.38, sends=16, watch=6.5),
        _post("c1", fmt="utility_carousel", style=None, technique="useful_promise", hold=None, watch=None,
              saves=90, sends=120, duration=0, experiment="EXP-003"),
        _post("c2", fmt="utility_carousel", style=None, technique="useful_promise", hold=None, watch=None,
              saves=80, sends=100, duration=0, experiment="EXP-003"),
        _post("tiny", reach=120, sends=30),
    ]


class RecordTests(unittest.TestCase):
    def test_graph_insights_mapping(self):
        post = from_graph_insights(
            {"id": "179", "timestamp": "2026-10-09T18:00:00+0000", "media_product_type": "REELS"},
            {"reach": 1500, "saved": 30, "shares": 45, "comments": 6, "ig_reels_avg_watch_time": 9400},
            experiment="EXP-001", hook_technique="curiosity_gap", duration_seconds=24, hold_3s=0.55,
        )
        self.assertEqual(post["format"], "reel")
        self.assertEqual(post["published"], "2026-10-09")
        self.assertEqual(post["metrics"]["sends"], 45)
        self.assertEqual(post["metrics"]["avg_watch_seconds"], 9.4)
        rates = post_rates(post)
        self.assertEqual(rates["send_rate"], 0.03)
        self.assertEqual(rates["hold_3s"], 0.55)
        self.assertAlmostEqual(rates["watch_ratio"], 0.3917, places=4)

    def test_every_post_needs_an_experiment_and_reach(self):
        bad = _sample()
        bad[0]["experiment"] = ""
        del bad[1]["metrics"]["reach"]
        review = review_posts(bad)
        self.assertEqual(review["status"], "blocked")
        self.assertTrue(any("experiment ID" in p for p in review["problems"]))
        self.assertTrue(any("missing reach" in p for p in review["problems"]))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.review = review_posts(_sample())

    def test_low_reach_posts_are_excluded(self):
        tiny = next(p for p in self.review["posts"] if p["post_id"] == "tiny")
        self.assertFalse(tiny["reliable"])
        self.assertEqual(tiny["strengths"], [])
        self.assertTrue(any("tiny" in u for u in self.review["unknowns"]))

    def test_techniques_are_only_compared_within_a_format(self):
        self.assertIn("reel/curiosity_gap", self.review["groups"]["hook_technique"])
        self.assertIn("utility_carousel/useful_promise", self.review["groups"]["hook_technique"])
        technique_claims = [c for c in self.review["conclusions"] if "hook_technique" in c]
        self.assertTrue(technique_claims)
        self.assertTrue(all("utility_carousel" not in c for c in technique_claims))

    def test_directional_conclusions_are_labelled(self):
        self.assertTrue(any("utility_carousel" in c and "sends per reach" in c for c in self.review["conclusions"]))
        self.assertTrue(all(c.startswith("Directional:") for c in self.review["conclusions"]))
        self.assertTrue(any("can't be separated" in u for u in self.review["unknowns"]))

    def test_three_priority_changes(self):
        changes = priority_changes(self.review)
        self.assertLessEqual(len(changes), 3)
        self.assertEqual([c["area"] for c in changes], ["opening", "pacing", "share value"])
        self.assertTrue(all("Below median on 2" in c["evidence"] for c in changes))

    def test_learnings_feed_hook_ranking(self):
        found = learnings(self.review)
        self.assertEqual(found["preferred_format"], "utility_carousel")
        self.assertGreater(found["technique_bonus"]["curiosity_gap"], 0)
        self.assertLess(found["technique_bonus"]["useful_promise"], 0)
        self.assertTrue(all(abs(v) <= 0.5 for v in found["technique_bonus"].values()))
        self.assertIsNone(found["preferred_layout"])

    def test_layout_with_more_saves_loses_when_viewers_leave(self):
        posts = [
            _post("a1", layout="split", hold=0.30, saves=80, sends=10),
            _post("a2", layout="split", hold=0.32, saves=70, sends=12),
            _post("b1", layout="rail", hold=0.60, saves=20, sends=18),
            _post("b2", layout="rail", hold=0.62, saves=22, sends=16),
        ]
        found = learnings(review_posts(posts))
        self.assertEqual(found["preferred_layout"], "rail")

    def test_too_few_posts_draws_no_conclusions(self):
        review = review_posts(_sample()[:2])
        self.assertEqual(review["conclusions"], [])
        self.assertEqual(review["learnings"]["technique_bonus"], {})

    def test_experiment_record(self):
        record = experiment_record(self.review, "EXP-003")
        self.assertEqual(record["posts"], ["c1", "c2"])
        self.assertEqual(record["reliable_posts"], 2)
        self.assertIn("Continue", record["decision"])


class FeedbackIntoHooksTests(unittest.TestCase):
    def test_bonus_breaks_ties_but_cannot_rescue_a_weak_hook(self):
        brief = {"verified_facts": ["Fact zero.", "Fact one."]}
        techniques = ("curiosity_gap", "surprising_fact", "surprising_contrast", "everyday_problem", "specific_mistake",
                      "transformation", "bold_opinion", "narrative_tension", "useful_promise", "future_implication")
        pool = []
        for i in range(20):
            technique = techniques[i % len(techniques)]
            score = 8 if i < 2 else 6
            pool.append({"technique": technique, "text": f"Would you trust robot number {i} with your laundry?",
                         "scores": dict.fromkeys(("clarity", "curiosity", "relevance", "keeps_right_viewer"), score),
                         "accuracy": "supported", "supported_by": [0]})
        pool[1]["technique"] = "useful_promise"
        result = select_from_pool(pool, brief, technique_bonus={"useful_promise": 0.4, "curiosity_gap": -2})
        self.assertEqual(result["winner"]["technique"], "useful_promise")
        self.assertEqual(result["ranked"][1]["technique_bonus"], -0.5)
        self.assertEqual(result["ranked"][1]["score"], 7.5)
        self.assertGreater(result["ranked"][1]["score"], result["ranked"][2]["score"])


if __name__ == "__main__":
    unittest.main()
