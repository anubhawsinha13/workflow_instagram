"""Each surface has one canvas and one safe area. Layouts that leave that area fail."""

from __future__ import annotations

import unittest

import platforms
import reel_spec
from brand import HEIGHT, MARGIN_X, MARGIN_Y, WIDTH
from explainer_render import FIGURE_WIDTH, POSE_HEAD, TEXT_COLUMN, _fitted_host, _stage_explainer
from platforms import (
    DISCORD, FACEBOOK, GOOGLE_BUSINESS, INSTAGRAM_FEED, LINKEDIN, PACK, PINTEREST, PLATFORMS, REDDIT,
    SHAPE_1_1, SHAPE_16_9, SHAPE_2_3, SHAPE_4_5, SHAPE_9_16, SURFACES, TELEGRAM, THREADS, TIKTOK,
    VERTICAL, WHATSAPP, X_POST, YOUTUBE, fit_host, text_problems,
)
from shape_pack import SAMPLE, caption_problems, edge_problems, render_shapes


EXPECTED = {
    SHAPE_4_5: (1080, 1350),
    SHAPE_16_9: (1920, 1080),
    SHAPE_1_1: (1080, 1080),
    SHAPE_9_16: (1080, 1920),
    SHAPE_2_3: (1080, 1620),
}


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

    def test_five_shapes_match_the_diagram_and_platforms_share_them(self) -> None:
        self.assertEqual(PACK, (SHAPE_4_5, SHAPE_16_9, SHAPE_1_1, SHAPE_9_16, SHAPE_2_3))
        for shape, size in EXPECTED.items():
            self.assertEqual((shape.width, shape.height), size)
        assignments = {
            INSTAGRAM_FEED: SHAPE_4_5, FACEBOOK: SHAPE_4_5, REDDIT: SHAPE_4_5,
            YOUTUBE: SHAPE_16_9, GOOGLE_BUSINESS: SHAPE_16_9,
            LINKEDIN: SHAPE_1_1, X_POST: SHAPE_1_1, TELEGRAM: SHAPE_1_1,
            TIKTOK: SHAPE_9_16, THREADS: SHAPE_9_16, DISCORD: SHAPE_9_16,
            PINTEREST: SHAPE_2_3, WHATSAPP: SHAPE_2_3,
        }
        self.assertEqual(set(assignments), set(PLATFORMS))
        for platform, shape in assignments.items():
            self.assertEqual((platform.width, platform.height), (shape.width, shape.height))
            self.assertEqual(platform.critical(), shape.critical())
        self.assertIs(VERTICAL, SHAPE_9_16)
        self.assertEqual(VERTICAL.safe_top, 250)
        self.assertEqual(VERTICAL.safe_bottom, 1500)
        self.assertEqual(VERTICAL.safe_right, 960)
        self.assertEqual(X_POST.caption_limit, 280)

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

    def test_the_vertical_host_stays_inside_the_safe_area_for_every_pose(self) -> None:
        for pose in reel_spec.POSES:
            left = reel_spec.host_left([{"pose": pose}])
            edge_left, edge_right = reel_spec._pose_edges(pose, left)
            self.assertGreaterEqual(edge_left, VERTICAL.safe_left - 1, pose)
            self.assertLessEqual(edge_right, VERTICAL.safe_right, pose)

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
        self.assertGreaterEqual(origin, VERTICAL.safe_left - 1)
        rail = next(element for element in staged[0]["elements"] if element["type"] == "rail")
        self.assertGreaterEqual(rail["box"]["y"], VERTICAL.safe_top)
        self.assertLessEqual(rail["box"]["x"] + rail["box"]["w"], VERTICAL.safe_right)
        words = {"x": TEXT_COLUMN["x"], "y": TEXT_COLUMN["y"], "w": TEXT_COLUMN["w"], "h": TEXT_COLUMN["h"]}
        self.assertEqual(platforms.box_problems(VERTICAL, words, "type"), [])

    def test_fit_host_shrinks_a_pose_that_would_cross_the_column(self) -> None:
        host_w, origin = fit_host([(0, 1000)], 64, 560, 620, 434)
        scale = host_w / 620
        self.assertLessEqual(origin + 1000 * scale, 560)
        self.assertGreaterEqual(origin, 64)

    def test_the_sample_pack_draws_five_frames_inside_their_safe_areas(self) -> None:
        frames = render_shapes(SAMPLE)
        self.assertEqual(set(frames), {shape.id for shape in PACK})
        for shape in PACK:
            image = frames[shape.id]
            self.assertEqual(image.size, (shape.width, shape.height))
            self.assertEqual(edge_problems(shape, image), [])
        self.assertEqual(caption_problems(SAMPLE), [])


if __name__ == "__main__":
    unittest.main()
