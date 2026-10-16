"""Checks for the Animated Music Reel. No network calls and no real image or video models."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import mood_reel
import story


def spec(**changes) -> dict:
    base = {
        "pillar": "soft_romance", "characters": "couple", "mood": "tender, unspoken first love",
        "setting": "a golden-hour street under a balcony with flowers",
        "text": "Some feelings don't need words", "stress": "words",
        "caption": "Some feelings don't need words.\n\nSave this for someone you miss.\n\n#animatedstories",
        "songs": ["Pehla Nasha — Udit Narayan, Sadhana Sargam", "Until I Found You — Stephen Sanchez"],
        "shots": [{"id": "wide", "prompt": "A boy on the street looks up at a girl reading on a balcony."},
                  {"id": "medium", "prompt": "She glances down and smiles, hair moving in the breeze."},
                  {"id": "detail", "prompt": "Her hand turns a page; a petal drifts past."}],
    }
    base.update(changes)
    return base


def fake_image(*args, **kwargs) -> dict:
    return {"ok": True, "image": Image.new("RGB", (576, 1024), (200, 140, 90))}


class MoodReelTests(unittest.TestCase):
    def test_a_good_spec_has_no_problems_and_a_bad_one_names_each_gap(self) -> None:
        self.assertEqual(mood_reel.problems(spec()), [])
        bad = mood_reel.problems(spec(pillar="comedy", characters="trio", text="one two three four five six seven eight nine ten",
                                      shots=[{"id": "wide", "prompt": "x"}]))
        joined = " ".join(bad)
        for word in ("pillar", "characters", "longer than", "medium", "detail"):
            self.assertIn(word, joined)

    def test_prompts_use_the_anime_look_the_cast_and_leave_room_for_text(self) -> None:
        wide = mood_reel.shot_prompt(spec(), "wide")
        self.assertIn("painterly", wide)
        self.assertIn("Meera", wide)
        self.assertIn("Aarav", wide)
        self.assertIn("lower third of the scene itself be calm", wide)
        self.assertIn("one continuous picture", wide)
        self.assertIn("No text", wide)
        self.assertIn("No people", mood_reel.shot_prompt(spec(characters="none"), "wide"))
        self.assertTrue(mood_reel.shot_prompt(spec(), "medium").startswith(mood_reel.SAME))
        self.assertIn("only the characters named", mood_reel.shot_prompt(spec(), "detail"))
        self.assertIn("no faces visible", mood_reel.shot_prompt(spec(), "detail"))
        self.assertNotIn("no faces visible", mood_reel.shot_prompt(spec(), "medium"))
        self.assertEqual(story.STYLES["anime_painterly"]["keyable"], False)

    def test_the_timeline_loops_back_to_the_opening_and_fits_ten_seconds(self) -> None:
        frames = {"wide": "w.png", "medium": "m.png", "detail": "d.png"}
        shots, total = mood_reel.timeline(frames)
        self.assertEqual([shot["role"] for shot in shots], ["wide", "medium", "detail", "wide"])
        self.assertEqual(shots[0]["path"], shots[-1]["path"])
        self.assertTrue(9.5 <= total <= 10.0, "ten seconds or less")
        self.assertEqual(shots[1]["start"], shots[0]["duration"])

    def test_a_poem_shows_one_stanza_at_a_time_and_needs_no_single_line(self) -> None:
        poem = ["Some days the road is only fog.\nWalk by the light you carry.", "Small steps still count as miles.",
                "Every sunset you survived\nwas proof you'd see the dawn.", "So keep going, softly."]
        with_poem = spec(poem=poem, text="")
        self.assertEqual(mood_reel.problems(with_poem), [], "a poem replaces the single line")
        self.assertTrue(any("poem" in p for p in mood_reel.problems(spec(poem=["only one"]))), "too few stanzas")
        self.assertTrue(any("longer than" in p for p in mood_reel.problems(spec(poem=["word " * 20, "ok"]))))
        renderer = mood_reel.layout(with_poem, 20.0, [{"start": 0.0, "color": "#F7B95B"}])
        scenes = renderer["scenes"]
        self.assertEqual(len(scenes), 4)
        starts = [scene["start_seconds"] for scene in scenes]
        self.assertEqual(starts, sorted(starts))
        self.assertGreaterEqual(starts[0], 0.5, "a short lead-in before the first stanza")
        for before, after in zip(scenes, scenes[1:]):
            self.assertLessEqual(before["start_seconds"] + before["duration_seconds"], after["start_seconds"], "stanzas never overlap")
        self.assertLessEqual(scenes[-1]["start_seconds"] + scenes[-1]["duration_seconds"], 20.0)
        self.assertEqual(mood_reel.layout_problems(renderer), [])
        self.assertEqual([s["elements"][0]["label"] for s in scenes], poem)

    def test_the_text_sits_inside_the_safe_zone(self) -> None:
        renderer = mood_reel.layout(spec(), 10.6, [{"start": 0.0, "color": "#F2B33D"}])
        self.assertEqual(mood_reel.layout_problems(renderer), [])
        element = renderer["scenes"][0]["elements"][0]
        self.assertEqual((element["type"], element["label"]), ("kinetic", "Some feelings don't need words"))
        self.assertEqual(element["keywords"], ["words"])

    def test_the_reel_is_silent_carries_the_account_mark_and_returns_the_song_ideas(self) -> None:
        payloads = []
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mood_reel, "CAST_DIR", Path(directory) / "cast"):
            result = mood_reel.build_mood_reel(
                spec(), Path(directory) / "out", generate=fake_image, edit=fake_image,
                animate=lambda start, prompt, dest: {"ok": False, "error": "Veo is out of credits."},
                render=lambda payload: payloads.append(payload) or {"ok": True, "path": "reel.mp4", "seconds": 10.6})
            self.assertTrue(result["ok"], result.get("error"))
            self.assertTrue((Path(directory) / "cast" / "a48" / "couple.png").is_file(), "the cast sheet is saved for the next episode")
        payload = payloads[0]
        self.assertNotIn("voiceover", payload, "the song is added in Instagram, so the file is silent")
        self.assertEqual(payload["backdrop"]["mark"], "logo:a48")
        self.assertEqual(payload["backdrop"]["mark_fallback"], "A48 STUDIO")
        self.assertEqual(payload["backdrop"]["accents"][0]["color"], mood_reel.BRAND_ACCENT, "the key word is always the brand gold")
        self.assertEqual(len(payload["backdrop"]["shots"]), 4)
        self.assertEqual(result["motion"], "stills")
        self.assertIn("Veo is out of credits.", result["notes"][0])
        self.assertEqual(len(result["songs"]), 2)

    def test_a_solo_scene_uses_the_same_cast_sheet_as_the_couple(self) -> None:
        sheets = []
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mood_reel, "CAST_DIR", Path(directory) / "cast"):
            mood_reel.cast_sheet(spec(characters="meera"), generate=lambda prompt: sheets.append(prompt) or fake_image())
            again = mood_reel.cast_sheet(spec(characters="aarav"), generate=lambda prompt: sheets.append(prompt) or fake_image())
            self.assertEqual(again.name, "couple.png")
            self.assertEqual(len(sheets), 1, "the sheet is drawn once and reused")
            self.assertIn("Meera", sheets[0])
            self.assertIn("Aarav", sheets[0])
            self.assertIsNone(mood_reel.cast_sheet(spec(characters="none")))
        self.assertIn("Meera", mood_reel.shot_prompt(spec(characters="meera"), "wide"))
        self.assertNotIn("Aarav", mood_reel.shot_prompt(spec(characters="meera"), "wide"))

    def test_a_working_video_model_replaces_the_stills(self) -> None:
        payloads = []

        def animate(start, prompt, dest):
            Path(dest).write_bytes(b"clip")
            return {"ok": True}

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mood_reel, "CAST_DIR", Path(directory) / "cast"):
            result = mood_reel.build_mood_reel(spec(), Path(directory) / "out", generate=fake_image, edit=fake_image, animate=animate,
                                               render=lambda payload: payloads.append(payload) or {"ok": True, "path": "r.mp4"})
        self.assertEqual(result["motion"], "video")
        self.assertIn("video", payloads[0]["backdrop"])
        self.assertNotIn("shots", payloads[0]["backdrop"])

    def test_the_corner_mark_is_the_a48_logo_with_a_text_fallback(self) -> None:
        import explainer_render

        def corner(mark: str, fallback: str | None = None) -> int:
            frame = Image.new("RGBA", (1080, 1920), (40, 30, 60, 255))
            explainer_render._corner_mark(frame, (247, 185, 91), mark, fallback)
            box = frame.crop((700, 0, 1080, 260))
            return sum(1 for pixel in box.getdata() if pixel[:3] != (40, 30, 60))

        self.assertTrue(explainer_render.LOGO_FILES["a48"].is_file(), "the A48 logo is saved with the brand files")
        self.assertGreater(corner("logo:a48"), 2000, "the logo is drawn in the top-right corner")
        self.assertGreater(corner("logo:missing", "A48 STUDIO"), 200, "a missing logo falls back to the name in type")
        self.assertEqual(corner("logo:missing"), 0, "no logo and no fallback draws nothing")
        self.assertEqual(corner("none"), 0)

    def test_lyrics_mode_has_no_text_and_keeps_the_lower_third_clear(self) -> None:
        payloads = []
        with_lyrics = spec(lyrics=True, text="", stress="")
        self.assertEqual(mood_reel.problems(with_lyrics), [], "no text is needed when the Lyrics sticker will carry the words")
        self.assertTrue(any("one line" in problem for problem in mood_reel.problems(spec(text=""))), "normal mode still needs its line")
        renderer = mood_reel.layout(with_lyrics, 10.6, [])
        self.assertEqual(renderer["scenes"][0]["elements"], [])
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mood_reel, "CAST_DIR", Path(directory) / "cast"):
            result = mood_reel.build_mood_reel(
                with_lyrics, Path(directory) / "out", generate=fake_image, edit=fake_image,
                animate=lambda start, prompt, dest: {"ok": False, "error": "no credits"},
                render=lambda payload: payloads.append(payload) or {"ok": True, "path": "r.mp4", "seconds": 10.6})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["lyrics"])
        self.assertEqual(payloads[0]["renderer"]["scenes"][0]["elements"], [])
        self.assertEqual(payloads[0]["backdrop"]["mark"], "logo:a48", "the account mark stays")

    def test_an_invalid_spec_is_refused_before_anything_is_drawn(self) -> None:
        drawn = []
        with tempfile.TemporaryDirectory() as directory:
            result = mood_reel.build_mood_reel(spec(text=""), Path(directory), generate=lambda *a, **k: drawn.append(1) or fake_image(),
                                               edit=fake_image)
        self.assertFalse(result["ok"])
        self.assertEqual(drawn, [])


if __name__ == "__main__":
    unittest.main()
