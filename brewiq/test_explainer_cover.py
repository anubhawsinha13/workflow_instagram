"""The explainer cover still shows the hook, not the empty background."""

from __future__ import annotations

import unittest

from explainer_render import BRAND_COLORS, _sprite, _hook_time, opening_still


class ExplainerCoverTests(unittest.TestCase):
    def test_sample_screen_draws_rows_button_and_summary(self) -> None:
        screen = {
            "app": "chat",
            "title": "#launch-plan · 48 replies",
            "lines": [{"who": "Priya", "text": "Can we move the review?"}, {"who": "Marcus", "text": "Friday works"}],
            "action": "Summarize",
        }
        box = {"x": 0, "y": 0, "w": 866, "h": 754}
        drawn = _sprite({"type": "screen", "box": box, "screen": screen}, dict(BRAND_COLORS), 28, None).convert("RGB")
        self.assertGreater(_count_near(drawn, _hex_rgb(BRAND_COLORS["highlight"])), 500, "the action button should be marked")
        self.assertGreater(_count_near(drawn, _hex_rgb("#2F6BFF")), 200, "the first avatar should be drawn")
        panel = _sprite(
            {"type": "summary", "box": {"x": 0, "y": 0, "w": 786, "h": 360}, "label": "Summary", "items": ["Review moved to Friday"]},
            dict(BRAND_COLORS), 28, None,
        ).convert("RGB")
        self.assertGreater(_count_near(panel, (17, 17, 17), 40), 800, "the summary text and outline should be drawn")

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

    def test_step_rail_marks_one_step_and_split_shows_both_sides(self) -> None:
        rail = _still("rail", "Plan | *Connect | Build | Check", {"x": 40, "y": 40, "w": 640, "h": 140})
        accent = _count_near(rail.crop((200, 20, 420, 120)), _hex_rgb(BRAND_COLORS["accent"]))
        self.assertGreater(accent, 30, "the current step on the rail should be filled")
        split = _still("split", "Checks the date | Ask before you send", {"x": 20, "y": 20, "w": 680, "h": 280})
        self.assertGreater(_count_near(split, (255, 255, 255)), 200, "the result and the prompt each need a card")


def _still(kind: str, label: str, box: dict):
    element = {
        "type": kind,
        "label": label,
        "box": box,
        "enter_at": 0.2,
        "enter_duration": 0.3,
        "enter_motion": "snap",
        "hold_until": 3,
        "exit_motion": "hold",
        "exit_duration": 0,
    }
    return opening_still(
        {"width": box["x"] + box["w"] + 40, "height": box["y"] + box["h"] + 40, "background": "#F7F3EC"},
        [element],
    ).convert("RGB")


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


def _hex_rgb(value: str) -> tuple:
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _count_near(image, color: tuple, tolerance: int = 18) -> int:
    red, green, blue = color
    return sum(
        1
        for pixel in image.getdata()
        if abs(pixel[0] - red) <= tolerance and abs(pixel[1] - green) <= tolerance and abs(pixel[2] - blue) <= tolerance
    )


if __name__ == "__main__":
    unittest.main()
