"""Each surface has one canvas and one safe area. Layouts that leave that area fail."""

from __future__ import annotations

import unittest

import platforms
import reel_spec
from brand import HEIGHT, MARGIN_X, MARGIN_Y, WIDTH
from explainer_render import FIGURE_WIDTH, POSE_HEAD, TEXT_COLUMN, _fitted_host, _stage_explainer
from platforms import (
    INSTAGRAM_FEED, INSTAGRAM_LANDSCAPE, INSTAGRAM_REEL, INSTAGRAM_SQUARE, PACK, SURFACES, fit_host,
    text_problems,
)


class PlatformSpecTests(unittest.TestCase):
    def test_every_surface_keeps_its_safe_area_inside_the_canvas(self) -> None:
        ids = set()
        for surface in SURFACES:
            self.assertNotIn(surface.id, ids)
            ids.add(surface.id)
            if surface.kind == "text":
                self.assertGreater(surface.caption_limit, 0)
                continue
            self.assertLess(surface.safe_left, surface.safe_right)
            self.assertLess(surface.safe_top, surface.safe_bottom)
            self.assertGreaterEqual(surface.safe_left, 0)
            self.assertGreaterEqual(surface.safe_top, 0)
            self.assertLessEqual(surface.safe_right, surface.width)
            self.assertLessEqual(surface.safe_bottom, surface.height)

    def test_the_instagram_pack_uses_the_sizes_instagram_will_not_crop(self) -> None:
        self.assertEqual((INSTAGRAM_REEL.width, INSTAGRAM_REEL.height), (1080, 1920))
        self.assertEqual((INSTAGRAM_FEED.width, INSTAGRAM_FEED.height), (1080, 1350))
        self.assertEqual((INSTAGRAM_SQUARE.width, INSTAGRAM_SQUARE.height), (1080, 1080))
        self.assertEqual((INSTAGRAM_LANDSCAPE.width, INSTAGRAM_LANDSCAPE.height), (1080, 566))
        self.assertEqual(INSTAGRAM_REEL.safe_top, 250)
        self.assertEqual(INSTAGRAM_REEL.safe_bottom, 1500)
        self.assertEqual(INSTAGRAM_REEL.safe_right, 960)
        self.assertIn(INSTAGRAM_REEL, PACK)
        self.assertIn(INSTAGRAM_FEED, PACK)

    def test_feed_slides_already_match_the_feed_surface(self) -> None:
        self.assertEqual((WIDTH, HEIGHT), (INSTAGRAM_FEED.width, INSTAGRAM_FEED.height))
        self.assertGreaterEqual(MARGIN_X, INSTAGRAM_FEED.safe_left)
        self.assertGreaterEqual(MARGIN_Y, INSTAGRAM_FEED.safe_top)
        self.assertLessEqual(HEIGHT - MARGIN_Y, INSTAGRAM_FEED.safe_bottom)

    def test_a_caption_that_hides_the_point_is_rejected(self) -> None:
        buried = "word " * 40 + "The date was wrong."
        self.assertTrue(text_problems(INSTAGRAM_FEED, buried))
        clear = "The date was wrong. Ask where it came from."
        self.assertEqual(text_problems(INSTAGRAM_FEED, clear), [])
        self.assertTrue(text_problems(platforms.X_POST, "word " * 80))

    def test_carousel_slides_must_share_the_feed_size(self) -> None:
        self.assertEqual(platforms.carousel_problems(INSTAGRAM_FEED, [(1080, 1350), (1080, 1350)]), [])
        problems = platforms.carousel_problems(INSTAGRAM_FEED, [(1080, 1350), (1080, 1080)])
        self.assertTrue(problems)

    def test_the_reel_host_stays_inside_the_safe_area_for_every_pose(self) -> None:
        for pose in reel_spec.POSES:
            left = reel_spec.host_left([{"pose": pose}])
            edge_left, edge_right = reel_spec._pose_edges(pose, left)
            self.assertGreaterEqual(edge_left, INSTAGRAM_REEL.safe_left - 1, pose)
            self.assertLessEqual(edge_right, INSTAGRAM_REEL.safe_right, pose)

    def test_a_staged_explainer_does_not_paint_the_host_off_the_left_edge(self) -> None:
        anchor, width = _fitted_host()
        scale = width / FIGURE_WIDTH
        origin = anchor - (POSE_HEAD[0] - FIGURE_WIDTH / 2) * scale
        staged = _stage_explainer([{
            "purpose": "Hook",
            "elements": [{"type": "character", "pose": "magnify", "label": ""}],
        }])
        host = next(element for element in staged[0]["elements"] if element["type"] == "character")
        self.assertEqual(host["box"]["x"], anchor)
        self.assertGreaterEqual(origin, INSTAGRAM_REEL.safe_left - 1)
        rail = next(element for element in staged[0]["elements"] if element["type"] == "rail")
        self.assertGreaterEqual(rail["box"]["y"], INSTAGRAM_REEL.safe_top)
        self.assertLessEqual(rail["box"]["x"] + rail["box"]["w"], INSTAGRAM_REEL.safe_right)
        words = {"x": TEXT_COLUMN["x"], "y": TEXT_COLUMN["y"], "w": TEXT_COLUMN["w"], "h": TEXT_COLUMN["h"]}
        self.assertEqual(platforms.box_problems(INSTAGRAM_REEL, words, "type"), [])

    def test_fit_host_shrinks_a_pose_that_would_cross_the_column(self) -> None:
        host_w, origin = fit_host([(0, 1000)], 64, 560, 620, 434)
        scale = host_w / 620
        self.assertLessEqual(origin + 1000 * scale, 560)
        self.assertGreaterEqual(origin, 64)


if __name__ == "__main__":
    unittest.main()
