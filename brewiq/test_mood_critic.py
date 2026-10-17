"""Checks for the picture editor. No network calls and no real image or vision models."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import mood_critic
import mood_reel
from test_mood_reel import fake_image, spec

PASS = {"pass": True, "issue": "", "fix": ""}


def review_with(shots: dict, score: int = 6):
    def review(_spec, frames):
        return {"score": score, "story": "The detail shot is weak.",
                "shots": {key: shots.get(key, PASS) for key in frames}}
    return review


class ParseReviewTests(unittest.TestCase):
    def test_reads_verdicts_and_treats_unmentioned_shots_as_passing(self) -> None:
        raw = json.dumps({"story": "ok", "score": 7, "shots": [
            {"id": "detail", "pass": False, "issue": "six fingers", "fix": "draw five fingers"}]})
        got = mood_critic.parse_review(raw, ["wide", "medium", "detail"])
        self.assertEqual(got["score"], 7)
        self.assertTrue(got["shots"]["wide"]["pass"])
        self.assertFalse(got["shots"]["detail"]["pass"])
        self.assertEqual(got["shots"]["detail"]["fix"], "draw five fingers")

    def test_a_failure_with_no_fix_is_not_acted_on_and_a_bad_score_is_zero(self) -> None:
        raw = json.dumps({"score": "high", "shots": [{"id": "wide", "pass": False, "issue": "dull", "fix": ""}]})
        got = mood_critic.parse_review(raw, ["wide"])
        self.assertTrue(got["shots"]["wide"]["pass"])
        self.assertEqual(got["score"], 0)
        with self.assertRaises(ValueError):
            mood_critic.parse_review("[]", ["wide"])


class EditPicturesTests(unittest.TestCase):
    def run_edit(self, review, **kwargs):
        drawn = []

        def edit(reference, prompt, **_):
            drawn.append(prompt)
            return fake_image()

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            frames = {}
            for shot_id in ("wide", "medium", "detail"):
                frames[shot_id] = str(folder / f"{shot_id}.png")
                Image.new("RGB", (576, 1024), (1, 2, 3)).save(frames[shot_id])
            report = mood_reel.edit_pictures(spec(), folder, frames, generate=lambda *_: fake_image(), edit=edit,
                                             sheet=folder / "sheet.png", review=review, **kwargs)
        return report, drawn

    def test_a_failed_shot_is_redrawn_once_with_the_fix(self) -> None:
        report, drawn = self.run_edit(review_with({"detail": {"pass": False, "issue": "six fingers", "fix": "five fingers"}}))
        self.assertEqual([item["shot"] for item in report["fixed"]], ["detail"])
        self.assertEqual(len(drawn), 1)
        self.assertIn("Fix: five fingers", drawn[0])
        self.assertEqual(report["score"], 6)

    def test_redrawing_the_opening_scene_redraws_the_rest_to_match(self) -> None:
        report, drawn = self.run_edit(review_with({"wide": {"pass": False, "issue": "extra person", "fix": "only two people"}}))
        self.assertEqual([item["shot"] for item in report["fixed"]], ["wide", "medium", "detail"])
        self.assertEqual(len(drawn), 3)

    def test_everything_passing_draws_nothing_and_a_broken_editor_never_blocks(self) -> None:
        report, drawn = self.run_edit(review_with({}, score=9))
        self.assertEqual((report["fixed"], drawn), ([], []))

        def broken(*_):
            raise RuntimeError("vision is down")

        report, drawn = self.run_edit(broken)
        self.assertIn("vision is down", report["error"])
        self.assertEqual(drawn, [])

    def test_a_redraw_that_fails_keeps_the_old_picture_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "detail.png"
            Image.new("RGB", (10, 10), (9, 9, 9)).save(path)
            frames = {"wide": str(folder / "wide.png"), "medium": str(folder / "m.png"), "detail": str(path)}
            report = mood_reel.edit_pictures(
                spec(), folder, frames, generate=lambda *_: fake_image(), edit=lambda *a, **k: {"ok": False, "error": "no"},
                sheet=None, review=review_with({"detail": {"pass": False, "issue": "x", "fix": "y"}}))
            self.assertEqual(report["left"][0]["shot"], "detail")
            self.assertEqual(Image.open(path).size, (10, 10))

    def test_build_runs_the_editor_when_given_one_and_skips_it_for_injected_drawing(self) -> None:
        calls = []

        def critic(_spec, frames):
            calls.append(list(frames))
            return {"score": 8, "story": "good", "shots": {key: PASS for key in frames}}

        for given, expected in ((critic, 1), (None, 1)):
            with tempfile.TemporaryDirectory() as directory, mock.patch.object(mood_reel, "CAST_DIR", Path(directory) / "cast"):
                result = mood_reel.build_mood_reel(
                    spec(), Path(directory) / "out", generate=fake_image, edit=fake_image, critic=given,
                    animate=lambda *a: {"ok": False, "error": "x"}, render=lambda p: {"ok": True, "path": "r.mp4", "seconds": 10})
                self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(calls), 1, "only the run that was given a critic used it")
        self.assertEqual(result["pictures"], {})


if __name__ == "__main__":
    unittest.main()
