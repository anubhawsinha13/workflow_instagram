#!/usr/bin/env python3
"""Tests for the BrewIQ cinematic video director planner."""

from __future__ import annotations

import unittest

from cinematic_director import (
    STYLES,
    apply_recovery,
    is_weak_opener,
    list_styles,
    opening_frame_problems,
    plan_reel,
    rank_hooks,
    recommend_style,
    recovery_options,
)
from composition import BRAND_LOOK
from slack_director import (
    STYLE_KEYWORDS,
    format_slack_message,
    parse_operator_reply,
    start_or_continue,
    topic_from_request,
)


class StyleTests(unittest.TestCase):
    def test_four_styles_are_listed(self):
        styles = list_styles()
        self.assertEqual(len(styles), 4)
        self.assertEqual({s["id"] for s in styles}, set(STYLES))

    def test_recommend_motion_graphics_for_api_topics(self):
        self.assertEqual(
            recommend_style("Prevent duplicate orders with Stripe idempotency keys"),
            "motion_graphics",
        )

    def test_recommend_explainer_for_product_ui(self):
        self.assertEqual(
            recommend_style("GPT-6 Intelligent UI in ChatGPT"),
            "interactive_explainer",
        )


class HookTests(unittest.TestCase):
    def test_three_ranked_hooks(self):
        hooks = rank_hooks(
            "AI Memory Has Two Layers",
            {"hook": "AI memory is short-term and long-term", "takeaway": "Store preferences separately"},
        )
        self.assertEqual(len(hooks), 3)
        self.assertEqual([h["rank"] for h in hooks], [1, 2, 3])
        self.assertTrue(all(h["id"].startswith("hook_") for h in hooks))
        self.assertTrue(all(h["text"] and h["why"] and h["on_screen_text"] for h in hooks))
        self.assertFalse(any(is_weak_opener(h["text"]) for h in hooks))
        self.assertFalse(any(is_weak_opener(h["on_screen_text"]) for h in hooks))

    def test_sentence_seeds_get_sentence_safe_templates(self):
        texts = [h["text"] for h in rank_hooks("Gemini study notebooks", {"hook": "Your notes hide the gaps"})]
        self.assertFalse(any("doing Your" in t or "ruins Your" in t or "backwards" in t for t in texts))
        self.assertIn("Most people miss this: your notes hide the gaps", texts)
        self.assertIn("Watch closely: NotebookLM quizzes you", [h["text"] for h in rank_hooks("NotebookLM quizzes you")])
        self.assertIn("You're doing API retries and idempotency backwards", [h["text"] for h in rank_hooks("API retries and idempotency")])

    def test_why_it_matters_is_rejected_as_opener(self):
        self.assertTrue(is_weak_opener("WHY IT MATTERS"))
        self.assertTrue(is_weak_opener("Why it matters"))
        hooks = rank_hooks(
            "Gemini Can Now Describe Your Surroundings",
            {"hook": "WHY IT MATTERS", "headline": "Gemini describes your surroundings"},
        )
        for hook in hooks:
            self.assertNotIn("why it matters", hook["text"].lower())
            self.assertNotIn("why it matters", hook["on_screen_text"].lower())
            self.assertNotEqual(hook["on_screen_text"].upper(), "WHY IT MATTERS")

    def test_opening_frame_problems_catch_label_overlay(self):
        problems = opening_frame_problems(
            "WHY IT MATTERS",
            {"narration": "Why it matters", "prompt": "Character smiling at camera holding a mug"},
        )
        self.assertGreaterEqual(len(problems), 1)
        self.assertTrue(any("0:02" in p or "WHY IT MATTERS" in p for p in problems))


class PlanTests(unittest.TestCase):
    def test_missing_style_and_hook_asks_for_options(self):
        result = plan_reel("Why AI Video Needs a Queue", research={"headline": "Queue the render"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "awaiting_choice")
        self.assertTrue(result["nothing_posted"])
        self.assertEqual(len(result["options"]["styles"]), 4)
        self.assertEqual(len(result["options"]["hooks"]), 3)
        self.assertIn("style=", result["prompt"])

    def test_planned_reel_includes_storyboard_and_director_payload(self):
        result = plan_reel(
            "Gemini study notebooks",
            research={
                "headline": "Find Study Gaps Faster",
                "hook": "Your notes hide the gaps",
                "point": "Ask the model what you still do not understand",
                "try_it": "Paste class notes and ask for missing topics",
                "takeaway": "Study the gaps, not the highlights",
                "keywords": ["Gemini", "NotebookLM"],
            },
            style="tech_storytelling",
            hook_id="hook_1",
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["nothing_posted"])
        self.assertGreaterEqual(len(result["scenes"]), 5)
        self.assertLessEqual(len(result["scenes"]), 8)
        self.assertTrue(result["voiceover"])
        self.assertEqual(result["style"]["id"], "tech_storytelling")
        self.assertIsNotNone(result["director_reel"])
        self.assertGreaterEqual(len(result["director_reel"]["scenes"]), 5)
        self.assertTrue(all(s["use_character"] for s in result["director_reel"]["scenes"]))
        self.assertEqual(len(result["hashtags"]), 5)
        self.assertEqual(result["cover_headline"], result["hook"]["on_screen_text"])
        self.assertFalse(is_weak_opener(result["cover_headline"]))
        self.assertEqual(result["scenes"][0]["role"], "Hook")
        self.assertTrue(result["scenes"][0]["timing"].startswith("0"))
        self.assertNotIn("why it matters", result["scenes"][0]["on_screen_text"].lower())
        self.assertIn("mid-action", result["scenes"][0]["character_action"].lower())

    def test_character_styles_follow_cinematic_profile(self):
        research = {
            "hook": "Your notes hide the gaps",
            "verified_facts": ["Gemini can list topics missing from pasted notes."],
            "limitations": ["It only sees what you paste."],
            "point": "Ask the model what you still do not understand",
            "try_it": "Paste notes, ask for gaps",
            "takeaway": "Study the gaps first",
            "viewer_question": "What are you missing?",
        }
        for style in ("interactive_explainer", "cinematic_3d", "tech_storytelling"):
            with self.subTest(style=style):
                result = plan_reel("Gemini study notebooks", research=research, style=style, hook_id="hook_1")
                self.assertEqual(result["status"], "planned", result.get("waiting_on"))
                self.assertEqual(result["cinematic_problems"], [])
                scenes = result["scenes"]
                self.assertEqual(len(scenes), 7)
                self.assertTrue(20.0 <= scenes[-1]["end"] <= 30.0)
                self.assertTrue(all(3.0 <= s["end"] - s["start"] <= 5.0 for s in scenes))
                self.assertEqual(result["icon"]["category"], "productivity")
                layers = {layer["type"] for layer in result["composition"]["layers"]}
                # The research hook is spoken, so it is a subtitle rather than a second headline.
                self.assertTrue({"footage", "subtitle", "icon", "brand", "label"} <= layers)
                self.assertEqual(result["hook"]["source"], "research")
                self.assertEqual(result["hook"]["text"], research["hook"])
                self.assertEqual(result["cover"]["headline"]["text"], research["hook"])
                self.assertEqual(result["cover"]["source"], "generated")
                self.assertTrue(all(BRAND_LOOK in s["prompt"] for s in scenes))
                self.assertFalse(any("beige" in s["environment"].lower() for s in scenes))
                self.assertFalse(any("zoom" in s["camera"].lower() for s in scenes))
                self.assertFalse(any("Dark studio" in s["environment"] for s in scenes))
                self.assertEqual(scenes[3]["fact_basis"], [1])
                self.assertIn("It only sees what you paste.", result["voiceover"])
                self.assertNotIn("?.", result["voiceover"])

        explainer = plan_reel("Gemini study notebooks", research=research, style="interactive_explainer", hook_id="hook_1")
        self.assertIsNone(explainer["director_reel"])
        self.assertIn("holographic", explainer["scenes"][2]["character_action"])
        self.assertIn("premium", explainer["scenes"][0]["environment"].lower())
        veo = plan_reel("Gemini study notebooks", research=research, style="cinematic_3d", hook_id="hook_1")
        jobs = veo["director_reel"]["scenes"]
        self.assertTrue(all(job["duration_seconds"] in (4, 6) for job in jobs))
        self.assertTrue(all(job["trim_to_seconds"] <= job["duration_seconds"] for job in jobs))

    def test_hook_built_from_the_point_is_not_spoken_twice(self):
        research = {
            "verified_facts": ["Gemini can list topics missing from pasted notes."],
            "limitations": ["It only sees what you paste."],
            "point": "Ask the model what you still do not understand",
            "try_it": "Paste notes, ask for gaps",
            "takeaway": "Study the gaps first",
            "viewer_question": "What are you missing?",
            "cover_headline": "Your notes hide the gaps",
        }
        result = plan_reel("Gemini study notebooks", research=research, style="interactive_explainer", hook_id="hook_1")
        self.assertEqual(result["status"], "planned", result.get("waiting_on"))
        self.assertEqual(result["voiceover"].lower().count("ask the model what you still do not understand"), 1)

    def test_long_lines_are_not_cut_into_overlays(self):
        research = {
            "hook": "Your notes hide the gaps",
            "verified_facts": ["Gemini can list topics missing from pasted notes."],
            "limitations": ["It only sees the notes you paste, not your textbook or lectures."],
        }
        result = plan_reel("Gemini study notebooks", research=research, style="cinematic_3d", hook_id="hook_1")
        self.assertEqual(result["scenes"][3]["on_screen_text"], "")
        self.assertIsNone(result["scenes"][3]["text_overlay"])

    def test_character_style_without_facts_is_blocked(self):
        result = plan_reel("Gemini study notebooks", research={}, style="interactive_explainer", hook_id="hook_1")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("No scene is grounded in a verified fact.", result["waiting_on"])
        self.assertIn("switch_slides", {o["id"] for o in result["options"]["recovery"]})

    def test_motion_graphics_has_no_veo_payload(self):
        result = plan_reel(
            "API idempotency keys",
            research={"hook": "Retries are not double charges"},
            style="motion_graphics",
            hook_id="hook_1",
        )
        self.assertTrue(result["ok"])
        self.assertIsNone(result["director_reel"])
        self.assertEqual(result["style"]["pipeline"], "motion_graphics")

    def test_unknown_style_asks_again(self):
        result = plan_reel("Topic", style="neon_vapor", hook_id="hook_1")
        self.assertEqual(result["status"], "awaiting_choice")
        self.assertIn("Unknown style", result["error"])


class RecoveryTests(unittest.TestCase):
    def test_veo_quota_offers_motion_graphics_and_slides(self):
        result = recovery_options(
            "The reel file is not ready yet.",
            "Google Veo rejected the clip because the Gemini quota or billing limit is exhausted.",
            "The post repeats a long passage from the source notes. It needs a shorter paraphrase before it can be posted.",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["nothing_posted"])
        self.assertEqual(len(result["waiting_on"]), 3)
        ids = {item["id"] for item in result["options"]["recovery"]}
        self.assertIn("retry_later", ids)
        self.assertIn("switch_motion_graphics", ids)
        self.assertIn("switch_slides", ids)
        self.assertIn("shorten_copy", ids)
        self.assertIn("recovery=", result["prompt"])

    def test_apply_switch_motion_graphics_plans_without_veo(self):
        result = apply_recovery(
            "switch_motion_graphics",
            "GPT-6 Intelligent UI",
            {"hook": "ChatGPT can draw the answer", "takeaway": "Ask for a visual"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["style"]["id"], "motion_graphics")
        self.assertIsNone(result["director_reel"])

    def test_apply_switch_slides_redirects(self):
        research = {
            "hook": "Your notes hide the gaps",
            "verified_facts": ["Gemini can list topics missing from pasted notes."],
            "limitations": ["It only sees what you paste."],
            "point": "Ask what you still miss",
            "try_it": "Paste notes, ask for gaps",
            "takeaway": "Study the gaps first",
        }
        result = apply_recovery("switch_slides", "Gemini study notebooks", research)
        self.assertTrue(result["ok"], result["waiting_on"])
        self.assertEqual(result["status"], "redirect")
        self.assertEqual(result["format"], "slides")
        self.assertEqual(len(result["slides"]["slides"]), 6)
        body = format_slack_message(result)
        self.assertIn("1. *Hook* (Low-angle action close-up)", body)
        self.assertNotIn("Needs fix", body)

    def test_switch_slides_without_facts_waits(self):
        result = apply_recovery("switch_slides", "Any topic")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "redirect")
        self.assertTrue(any("research fact" in p for p in result["waiting_on"]))
        self.assertIn("Needs fix", format_slack_message(result))


class SlackBridgeTests(unittest.TestCase):
    def test_parse_style_and_hook(self):
        picks = parse_operator_reply("style=interactive_explainer hook=hook_2 please")
        self.assertEqual(picks["style"], "interactive_explainer")
        self.assertEqual(picks["hook_id"], "hook_2")

    def test_start_asks_then_continues(self):
        first = start_or_continue("API retries and idempotency")
        self.assertEqual(first["status"], "awaiting_choice")
        body = format_slack_message(first)
        self.assertIn("pick options", body.lower())
        self.assertIn("motion_graphics", body)

        second = start_or_continue(
            "API retries and idempotency",
            operator_reply="style=motion_graphics hook=hook_1",
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second["status"], "planned")

    def test_prior_errors_surface_recovery_options(self):
        result = start_or_continue(
            "GPT-6 Intelligent UI",
            prior_errors=[
                "Google Veo rejected the clip because the Gemini quota or billing limit is exhausted."
            ],
        )
        self.assertEqual(result["status"], "blocked")
        body = format_slack_message(result)
        self.assertIn("Options:", body)
        self.assertIn("switch_motion_graphics", body)


KEYWORD_RESEARCH = {
    "hook": "Your notes hide the gaps",
    "cover_headline": "Your notes hide the gaps",
    "verified_facts": ["NotebookLM answers from uploaded sources."],
    "limitations": ["It only knows what you upload."],
    "point": "Upload notes",
    "try_it": "Ask for a quiz",
    "takeaway": "Notes become a tutor",
    "viewer_question": "What first?",
}


class KeywordTriggerTests(unittest.TestCase):
    def test_every_style_has_a_keyword(self):
        cases = {
            "explainer: NotebookLM quizzes you": ("interactive_explainer", "NotebookLM quizzes you"),
            "make a #cinematic reel about home robots": ("cinematic_3d", "home robots"),
            "tech storytelling about AI agents": ("tech_storytelling", "AI agents"),
            "motion graphics on API idempotency": ("motion_graphics", "API idempotency"),
        }
        for message, (style, topic) in cases.items():
            with self.subTest(message=message):
                self.assertEqual(parse_operator_reply(message), {"style": style})
                self.assertEqual(topic_from_request(message), topic)
        self.assertEqual(set(STYLE_KEYWORDS), set(STYLES))

    def test_numbers_and_short_hook_replies(self):
        self.assertEqual(parse_operator_reply("style 2 hook 3"), {"style": "interactive_explainer", "hook_id": "hook_3"})
        self.assertEqual(parse_operator_reply("option 4"), {"style": "motion_graphics"})
        self.assertEqual(parse_operator_reply("hook=hook_1"), {"hook_id": "hook_1"})
        self.assertEqual(parse_operator_reply("NotebookLM"), {})

    def test_keyword_without_a_research_hook_still_waits(self):
        research = {key: value for key, value in KEYWORD_RESEARCH.items() if key != "hook"}
        for message, style in (("explainer: NotebookLM quizzes you", "interactive_explainer"), ("#motion API retries", "motion_graphics")):
            with self.subTest(message=message):
                first = start_or_continue("", research=research, operator_reply=message)
                self.assertEqual(first["status"], "awaiting_choice")
                self.assertEqual(first["chosen_style"], style)
                self.assertTrue(first["nothing_posted"])
                self.assertFalse(first["options"].get("hook_from_research"))
                body = format_slack_message(first)
                self.assertIn("from your message", body)
                self.assertIn("hook_1", body)
                self.assertNotIn("*Styles:*", body)

    def test_keyword_uses_the_research_hook_for_that_post_type(self):
        research = {
            key: value for key, value in KEYWORD_RESEARCH.items() if key != "hook"
        }
        research["brief_hooks"] = [
            {"approach": "everyday_problem", "text": "Your laundry pile never really shrinks", "why": "Daily chore."},
            {"approach": "useful_promise", "text": "Save ten minutes every Sunday night", "why": "Clear payoff."},
            {"approach": "curiosity_gap", "text": "What is your home robot hiding", "why": "Open question."},
        ]
        cases = (
            ("explainer: NotebookLM quizzes you", "interactive_explainer", "everyday_problem"),
            ("#motion API retries", "motion_graphics", "useful_promise"),
            ("tech storytelling about AI agents", "tech_storytelling", "curiosity_gap"),
        )
        for message, style, approach in cases:
            with self.subTest(message=message):
                result = start_or_continue("", research=research, operator_reply=message)
                self.assertEqual(result["status"], "planned", result.get("waiting_on") or result.get("error"))
                self.assertEqual(result["style"]["id"], style)
                self.assertEqual(result["hook"]["approach"], approach)
                self.assertEqual(result["hook"]["source"], "research")
                self.assertTrue(result["nothing_posted"])
                body = format_slack_message(result)
                self.assertIn("chosen from research for this style", body)
                self.assertIn("post it", body)

        overridden = start_or_continue(
            "",
            research=research,
            operator_reply="explainer: NotebookLM quizzes you hook 2",
        )
        self.assertEqual(overridden["status"], "planned", overridden.get("waiting_on"))
        self.assertEqual(overridden["hook"]["approach"], "useful_promise")
        self.assertEqual(overridden["hook"]["id"], "hook_2")

    def test_thread_keeps_the_keyword_style_and_runs_every_gate(self):
        thread = ["explainer: NotebookLM quizzes you"]
        result = start_or_continue("", research=KEYWORD_RESEARCH, thread=thread, operator_reply="hook 1")
        self.assertEqual(result["status"], "planned", result.get("waiting_on"))
        self.assertEqual(result["style"]["id"], "interactive_explainer")
        self.assertEqual(result["topic"], "NotebookLM quizzes you")
        self.assertEqual(result["cinematic_problems"], [])
        self.assertIn("composition", result)
        self.assertIn("cover", result)

        blocked = start_or_continue("", research={}, thread=thread, operator_reply="hook 1")
        self.assertEqual(blocked["status"], "blocked")

    def test_later_reply_can_change_the_style(self):
        result = start_or_continue("", research=KEYWORD_RESEARCH, thread=["explainer: NotebookLM"], operator_reply="style=motion_graphics")
        self.assertEqual(result["status"], "planned", result.get("waiting_on") or result.get("error"))
        self.assertEqual(result["style"]["id"], "motion_graphics")
        self.assertEqual(result["hook"]["text"], KEYWORD_RESEARCH["hook"])
        self.assertEqual(result["hook"]["source"], "research")


if __name__ == "__main__":
    unittest.main()
