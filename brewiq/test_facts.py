"""The research agent runs before a director receives facts."""

from __future__ import annotations

import unittest
from unittest import mock

import facts


class FactsTests(unittest.TestCase):
    def test_instagram_research_agent_supplies_the_facts(self):
        brief = {
            "ok": True,
            "summary": "A phone can forget one chat.",
            "limitations": "This does not cover every app.",
            "availability": "",
            "claims": [
                {
                    "text": "The control is in the app settings.",
                    "source_url": "https://openai.com/privacy",
                }
            ],
        }
        with mock.patch("facts._call_research_agent", return_value=brief) as agent:
            with mock.patch("facts._legacy_facts") as legacy:
                result = facts.verified_facts("chat memory")

        agent.assert_called_once()
        self.assertEqual(agent.call_args.args[0], "chat memory")
        legacy.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertIn("https://openai.com/privacy", result["facts"])
        self.assertEqual(result["sources"], ["https://openai.com/privacy"])

    def test_handoff_reaches_the_scriptwriter(self):
        brief = {
            "ok": True,
            "summary": "A long letter can become two tasks.",
            "situation": "This letter is three pages long.",
            "selected_hook": "What do you actually need to do?",
            "limitations": "",
            "availability": "",
            "demonstration": {
                "sample_input": "A three-page letter.",
                "instruction": "List the actions.",
                "result": "Pay the bill.",
                "result_kind": "illustrative",
                "visible_change": "The letter becomes two tasks.",
            },
            "opening_visual": "The letter is already on the table.",
            "claims": [{"text": "The help page shows the step.", "source_url": "https://help.openai.com/privacy"}],
        }
        with mock.patch("facts._call_research_agent", return_value=brief):
            result = facts.verified_facts("long letter")
        self.assertIn("Situation: This letter is three pages long.", result["facts"])
        self.assertIn("Result (illustrative): Pay the bill.", result["facts"])
        self.assertIn("Opening: The letter is already on the table.", result["facts"])

    def test_a_failed_brief_does_not_reach_the_old_researcher(self):
        with mock.patch("facts._call_research_agent", return_value={"ok": False, "error": "No primary source URL was returned."}):
            with mock.patch("facts._legacy_facts") as legacy:
                result = facts.verified_facts("chat memory")

        legacy.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("primary source", result["error"])

    def test_missing_package_uses_the_old_researcher(self):
        with mock.patch("facts._call_research_agent", return_value=None):
            with mock.patch("facts._legacy_facts", return_value={"ok": True, "facts": "Old fact.", "sources": ["https://example.org/doc"]}) as legacy:
                result = facts.verified_facts("chat memory")

        legacy.assert_called_once()
        self.assertEqual(result["facts"], "Old fact.")

    def test_research_agent_uses_the_instagram_profile(self):
        brief = mock.Mock(return_value={"ok": False, "error": "stopped"})
        package = mock.Mock(research_brief=brief)
        with mock.patch.dict("sys.modules", {"aegis_research": package}):
            facts._call_research_agent("chat memory", ["Old title"])

        brief.assert_called_once_with("chat memory", profile="instagram", avoid=["Old title"])
