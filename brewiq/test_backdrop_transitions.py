"""Checks for the transitions between stills. No ffmpeg: only the picture maths."""

from __future__ import annotations

import unittest

from PIL import Image

import explainer_render

W, H = 120, 200


def backdrop(styles: list) -> "explainer_render._Backdrop":
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    shots = []
    for index, (color, style) in enumerate(zip(((255, 0, 0), (0, 0, 255)), styles)):
        path = folder / f"{index}.png"
        Image.new("RGB", (W, H), color).save(path)
        shots.append({"start": index * 3.0, "duration": 3.0, "path": str(path), **style})
    return explainer_render._Backdrop({"shots": shots, "fade": 1.0}, W, H, 10, "ffmpeg")


class TransitionTests(unittest.TestCase):
    def pixel(self, style: str, t: float, at=(10, 100)):
        shot = backdrop([{}, {"transition": style}])
        return shot.frame(t).getpixel(at)[:3]

    def test_every_style_starts_on_the_old_shot_and_ends_on_the_new_one(self) -> None:
        for style in ("dissolve", "push", "zoom", "dip"):
            first = self.pixel(style, 3.0)
            last = self.pixel(style, 3.999)
            self.assertGreater(first[0], 200, f"{style} starts red")
            self.assertGreater(last[2], 200, f"{style} ends blue")
            self.assertGreater(self.pixel(style, 4.5)[2], 250, f"{style} is finished after the fade")

    def test_a_cut_is_instant_and_a_dip_passes_through_warm_light(self) -> None:
        self.assertGreater(self.pixel("cut", 3.0)[2], 250)
        middle = self.pixel("dip", 3.5)
        self.assertGreater(min(middle), 200, "halfway through a dip the picture is warm light")
        self.assertEqual(self.pixel("dissolve", 3.5)[1], 0)

    def test_push_slides_the_new_shot_in_from_the_right(self) -> None:
        early_left = self.pixel("push", 3.5, (5, 100))
        early_right = self.pixel("push", 3.5, (W - 5, 100))
        self.assertGreater(early_left[0], 200, "the old shot is still on the left half way through")
        self.assertGreater(early_right[2], 200, "the new shot has entered from the right")

    def test_bad_names_fall_back_and_every_move_makes_a_full_frame(self) -> None:
        shot = backdrop([{"move": "sideways"}, {"transition": "spin"}])
        self.assertEqual(shot.styles[0], {"transition": "dissolve", "move": "in"})
        self.assertEqual(shot.styles[1]["transition"], "dissolve")
        for move in explainer_render._Backdrop.MOVES:
            moved = backdrop([{"move": move}, {}])
            for t in (0.0, 1.5, 2.9):
                self.assertEqual(moved.frame(t).size, (W, H))


if __name__ == "__main__":
    unittest.main()
