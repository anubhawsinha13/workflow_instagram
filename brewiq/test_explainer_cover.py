"""The explainer cover still shows the hook, not the empty background."""

from __future__ import annotations

import unittest

from explainer_render import _hook_time, opening_still


class ExplainerCoverTests(unittest.TestCase):
    def test_hook_is_fully_drawn_before_its_entrance(self) -> None:
        element = {"enter_at": 0.8, "enter_duration": 0.4}
        self.assertAlmostEqual(_hook_time(element, 0.0), 1.2)
        self.assertAlmostEqual(_hook_time(element, 2.0), 2.0)

    def test_opening_still_is_not_a_blank_background(self) -> None:
        element = {
            "id": "s1-card",
            "type": "card",
            "label": "Your notes hide the gaps",
            "box": {"x": 40, "y": 180, "w": 300, "h": 220},
            "enter_at": 0.8,
            "enter_duration": 0.4,
            "enter_motion": "fade_in",
            "hold_until": 3,
            "exit_motion": "hold",
            "exit_duration": 0,
        }
        frame = opening_still({"width": 400, "height": 700, "background": "#F7F3EC"}, [element])
        pixels = list(frame.convert("RGB").resize((40, 70)).getdata())
        white = sum(1 for red, green, blue in pixels if red > 245 and green > 245 and blue > 245)
        self.assertGreater(white, 8, "the hook card is missing from the cover still")
        beige = sum(1 for red, green, blue in pixels if abs(red - 247) < 8 and abs(green - 243) < 8 and abs(blue - 236) < 8)
        self.assertLess(beige, len(pixels), "the cover is only the empty background")

    def test_icons_are_different_real_objects(self) -> None:
        chat = _icon_frame("chat")
        lock = _icon_frame("lock")
        self.assertGreater(_count_near(chat, (34, 195, 214)), 12, "a chat icon should be a cyan app tile")
        self.assertGreater(_count_near(lock, (43, 43, 43)), 12, "a lock icon should be a dark app tile")
        self.assertNotEqual(list(chat.getdata()), list(lock.getdata()))

    def test_opening_card_looks_like_a_notes_screen_with_icons_behind_it(self) -> None:
        element = {
            "id": "s1-card",
            "type": "card",
            "label": "Your notes hide the gaps",
            "box": {"x": 80, "y": 220, "w": 760, "h": 420},
            "enter_at": 0.6,
            "enter_duration": 0.4,
            "enter_motion": "fade_in",
            "hold_until": 4,
            "exit_motion": "hold",
            "exit_duration": 0,
        }
        frame = opening_still({"width": 1080, "height": 1920, "background": "#F7F3EC"}, [element]).convert("RGB")
        card = frame.crop((80, 220, 840, 640))
        self.assertGreater(_count_near(card, (214, 154, 46)), 40, "the notes tile is missing from the sample screen")
        self.assertGreater(_count_near(card, (255, 255, 255)), 400, "the sample screen lost its page")
        corner = frame.crop((0, 0, 220, 280))
        self.assertGreater(_count_near(corner, (34, 195, 214)), 20, "an app icon should sit behind the host")


def _icon_frame(label: str):
    element = {
        "type": "icon",
        "label": label,
        "box": {"x": 40, "y": 40, "w": 160, "h": 160},
        "enter_at": 0.8,
        "enter_duration": 0.4,
        "enter_motion": "fade_in",
        "hold_until": 3,
        "exit_motion": "hold",
        "exit_duration": 0,
    }
    frame = opening_still({"width": 280, "height": 280, "background": "#F7F3EC"}, [element])
    return frame.crop((40, 40, 200, 200)).convert("RGB")


def _count_near(image, color: tuple, tolerance: int = 18) -> int:
    red, green, blue = color
    return sum(
        1
        for pixel in image.getdata()
        if abs(pixel[0] - red) <= tolerance and abs(pixel[1] - green) <= tolerance and abs(pixel[2] - blue) <= tolerance
    )


if __name__ == "__main__":
    unittest.main()
