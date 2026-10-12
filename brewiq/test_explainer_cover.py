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


if __name__ == "__main__":
    unittest.main()
