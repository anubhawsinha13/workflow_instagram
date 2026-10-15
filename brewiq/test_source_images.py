"""Checks for official-source screenshots. No network calls."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import source_images as si

PAGE = """
<img src="/img/nav/logo.svg" alt="Slack">
<img src="https://cdn.example.org/helpcenter/logo.png" alt="Help Center">
<img src="https://help.example.org/attachments/1" alt="Generating a summary with AI">
<img src="https://help.example.org/attachments/2" alt="A thread to keep discussion organized">
<img src="https://help.example.org/attachments/3" alt="">
<img src="https://help.example.org/attachments/tiny" alt="A tiny badge picture">
"""


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buffer, "PNG")
    return buffer.getvalue()


def _fetch(url: str) -> bytes:
    if url.endswith("/page"):
        return PAGE.encode()
    if url.endswith("tiny"):
        return _png(100, 60)
    return _png(1200, 800)


class SourceImageTests(unittest.TestCase):
    def test_keeps_described_content_images_and_skips_logos(self) -> None:
        found = si.candidates("https://help.example.org/page", PAGE)
        self.assertEqual([item["alt"] for item in found][:2], ["Generating a summary with AI", "A thread to keep discussion organized"])
        self.assertTrue(all("logo" not in item["src"] for item in found))

    def test_collect_downloads_large_images_with_their_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            images = si.collect(["https://help.example.org/page"], Path(directory), fetch=_fetch)
            self.assertEqual(len(images), 2, "the tiny badge is too small to show")
            self.assertEqual(images[0]["credit"], "help.example.org")
            self.assertTrue(Path(images[0]["path"]).is_file())

    def test_assign_matches_descriptions_and_ignores_the_product_name(self) -> None:
        images = [
            {"src": "a", "alt": "Static image of a cursor clicking the profile menu in the example app", "credit": "example.org"},
            {"src": "b", "alt": "Generating a summary with Example AI", "credit": "example.org"},
        ]
        beats = [
            {"voice": "Click Summarize first.", "on_screen": {}, "shot": {"mode": "graphics"}},
            {"voice": "A still beat.", "on_screen": {}, "shot": {"mode": "still"}},
        ]
        picks = si.assign(beats, images)
        self.assertEqual(picks[0]["src"], "b")
        self.assertIsNone(picks[1], "a beat with its own still keeps it")

    def test_rewrite_keeps_the_original_when_the_edit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "shot.img"
            path.write_bytes(_png(800, 600))
            image = {"src": "https://help.example.org/attachments/2", "path": str(path), "animated": False, "credit": "example.org"}
            screen = {"title": "#launch-plan", "lines": [{"who": "Priya", "text": "Move the review?"}]}
            failed = si.rewrite(image, screen, folder, edit=lambda source, prompt: {"ok": False})
            self.assertEqual(failed["path"], str(path))
            edited = si.rewrite(image, screen, folder, edit=lambda source, prompt: {"ok": True, "image": Image.new("RGB", (900, 700), "white")})
            self.assertTrue(edited["edited"])
            self.assertIn('"Priya"', si.rewrite_prompt(screen))
            self.assertIn("No photos of people", si.rewrite_prompt(screen))
            self.assertIn("Priya Shah", si.rewrite_prompt(None), "without a screen plan the people still change")
            animated = {**image, "animated": True}
            self.assertIs(si.rewrite(animated, None, folder, edit=lambda source, prompt: {"ok": True}), animated)

    def test_trim_crops_black_bands(self) -> None:
        canvas = Image.new("RGB", (400, 600), (0, 0, 0))
        canvas.paste(Image.new("RGB", (300, 200), (250, 250, 250)), (50, 200))
        self.assertEqual(si.trim(canvas).size, (300, 200))


if __name__ == "__main__":
    unittest.main()
