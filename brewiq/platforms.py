"""Canvas, safe area, and caption limits for every surface BrewIQ can publish.

One script becomes five files. Thirteen platforms share those files. The ratios
are the one-post diagram: 4:5, 16:9, 1:1, 9:16, and 2:3. Caption limits are the
2026 posting rules gathered on 2026-10-13. Where two sources disagreed, the
stricter limit is the one enforced.

Instagram feed and grid: https://posteverywhere.ai/blog/instagram-aspect-ratios
Instagram carousel: https://carouselpost.io/guides/instagram-carousel-size
LinkedIn video: https://www.linkedin.com/help/linkedin/answer/a424737
Character limits: https://publedia.com/blog/social-media-character-limits
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Surface:
    id: str
    platform: str
    kind: str
    width: int
    height: int
    safe_left: int
    safe_top: int
    safe_right: int
    safe_bottom: int
    caption_limit: int
    caption_visible: int
    max_seconds: int = 0
    max_slides: int = 1
    note: str = ""

    def critical(self) -> tuple[int, int, int, int]:
        """Left, top, right, bottom. Critical type and the host stay inside this."""
        return (self.safe_left, self.safe_top, self.safe_right, self.safe_bottom)


def _box(platform: str, name: str, kind: str, width: int, height: int,
         left: int, top: int, right_inset: int, bottom_inset: int, **rest) -> Surface:
    return Surface(
        id=f"{platform}.{name}",
        platform=platform,
        kind=kind,
        width=width,
        height=height,
        safe_left=left,
        safe_top=top,
        safe_right=width - right_inset,
        safe_bottom=height - bottom_inset,
        **rest,
    )


def _assign(shape: Surface, platform: str, name: str, **changes) -> Surface:
    """Same pixels and safe box as the shape. Caption limits belong to the platform."""
    values = {
        "id": f"{platform}.{name}",
        "platform": platform,
        "kind": shape.kind,
        "width": shape.width,
        "height": shape.height,
        "safe_left": shape.safe_left,
        "safe_top": shape.safe_top,
        "safe_right": shape.safe_right,
        "safe_bottom": shape.safe_bottom,
        "caption_limit": shape.caption_limit,
        "caption_visible": shape.caption_visible,
        "max_seconds": shape.max_seconds,
        "max_slides": shape.max_slides,
        "note": shape.note,
    }
    values.update(changes)
    return Surface(**values)


# Five frames. Thirteen platforms share them. Ratios match the one-post diagram:
# 4:5 Instagram, Facebook, Reddit. 16:9 YouTube, Google Business.
# 1:1 LinkedIn, X, Telegram. 9:16 TikTok, Threads, Discord. 2:3 Pinterest, WhatsApp.
SHAPE_4_5 = _box(
    "shape", "4x5", "image", 1080, 1350, 64, 80, 64, 160,
    caption_limit=2200, caption_visible=125, max_slides=20,
    note="4:5. Instagram, Facebook, and Reddit.",
)
SHAPE_16_9 = _box(
    "shape", "16x9", "image", 1920, 1080, 64, 64, 64, 64,
    caption_limit=5000, caption_visible=100,
    note="16:9. YouTube and Google Business.",
)
SHAPE_1_1 = _box(
    "shape", "1x1", "image", 1080, 1080, 64, 64, 64, 64,
    caption_limit=3000, caption_visible=210,
    note="1:1. LinkedIn, X, and Telegram.",
)
# Buttons cover the top, the right edge, and the bottom of a vertical video.
SHAPE_9_16 = _box(
    "shape", "9x16", "video", 1080, 1920, 64, 250, 120, 420,
    caption_limit=2200, caption_visible=125, max_seconds=180,
    note="9:16. TikTok, Threads, and Discord.",
)
SHAPE_2_3 = _box(
    "shape", "2x3", "image", 1080, 1620, 48, 64, 48, 120,
    caption_limit=800, caption_visible=100,
    note="2:3. Pinterest and WhatsApp.",
)
VERTICAL = SHAPE_9_16

INSTAGRAM_FEED = _assign(SHAPE_4_5, "instagram", "post", max_slides=20, caption_limit=2200, caption_visible=125,
                         note="4:5. The Instagram file.")
FACEBOOK = _assign(SHAPE_4_5, "facebook", "post", caption_limit=63206, caption_visible=477,
                   note="4:5. Same picture as Instagram.")
REDDIT = _assign(SHAPE_4_5, "reddit", "post", caption_limit=40000, caption_visible=300,
                 note="4:5. Same picture as Instagram.")
YOUTUBE = _assign(SHAPE_16_9, "youtube", "video", caption_limit=5000, caption_visible=100,
                  note="16:9. caption_visible is the title.")
GOOGLE_BUSINESS = _assign(SHAPE_16_9, "google_business", "post", caption_limit=1500, caption_visible=150,
                          note="16:9. Same picture as YouTube.")
LINKEDIN = _assign(SHAPE_1_1, "linkedin", "post", caption_limit=3000, caption_visible=210,
                   note="1:1. The feed shows about 210 characters.")
X_POST = _assign(SHAPE_1_1, "x", "post", caption_limit=280, caption_visible=280,
                 note="1:1. The whole post is visible.")
TELEGRAM = _assign(SHAPE_1_1, "telegram", "post", caption_limit=1024, caption_visible=200,
                   note="1:1. Same picture as LinkedIn and X.")
TIKTOK = _assign(SHAPE_9_16, "tiktok", "video", caption_limit=2200, caption_visible=80,
                 note="9:16.")
THREADS = _assign(SHAPE_9_16, "threads", "post", caption_limit=500, caption_visible=500,
                  note="9:16. 500 characters, shown in full.")
DISCORD = _assign(SHAPE_9_16, "discord", "post", caption_limit=2000, caption_visible=200,
                  note="9:16.")
PINTEREST = _assign(SHAPE_2_3, "pinterest", "pin", caption_limit=800, caption_visible=100,
                    note="2:3. The title fits on one line.")
WHATSAPP = _assign(SHAPE_2_3, "whatsapp", "status", caption_limit=700, caption_visible=140,
                   note="2:3. Same picture as Pinterest.")

SHAPES = (SHAPE_4_5, SHAPE_16_9, SHAPE_1_1, SHAPE_9_16, SHAPE_2_3)
PLATFORMS = (
    INSTAGRAM_FEED, FACEBOOK, REDDIT,
    YOUTUBE, GOOGLE_BUSINESS,
    LINKEDIN, X_POST, TELEGRAM,
    TIKTOK, THREADS, DISCORD,
    PINTEREST, WHATSAPP,
)
SURFACES = SHAPES + PLATFORMS
PACK = SHAPES

BY_ID = {surface.id: surface for surface in SURFACES}


def fit_host(bounds: list[tuple[float, float]], safe_left: int, column_x: int,
             figure: int, max_host_w: int) -> tuple[int, float]:
    """Scale and place the pose canvas so every opaque pixel stays in [safe_left, column_x].

    bounds are (source_left, source_right) pairs from the pose files. Returns
    (host width, image origin). The origin may be negative when a pose has
    empty canvas to the left of the figure; the opaque pixels still start at
    safe_left or to its right.
    """
    if not bounds or figure <= 0 or column_x <= safe_left:
        return max_host_w, float(safe_left)
    floor = max(1, int(figure * 0.3))
    for host_w in range(int(max_host_w), floor - 1, -1):
        scale = host_w / figure
        lower = max(safe_left - left * scale for left, _right in bounds)
        upper = min(column_x - right * scale for _left, right in bounds)
        if lower <= upper:
            return host_w, lower
    raise ValueError("The pose library does not fit between the safe edge and the text column.")


def box_problems(surface: Surface, box: dict, label: str = "box") -> list[str]:
    if surface.kind == "text":
        return []
    left, top, right, bottom = surface.critical()
    x, y = float(box.get("x") or 0), float(box.get("y") or 0)
    w, h = float(box.get("w") or 0), float(box.get("h") or 0)
    problems = []
    if x < left or y < top or x + w > right or y + h > bottom:
        problems.append(
            f"{label} is outside the {surface.id} safe area "
            f"({left},{top})–({right},{bottom})."
        )
    return problems


def size_problems(surface: Surface, width: int, height: int) -> list[str]:
    if surface.kind == "text":
        return []
    if width != surface.width or height != surface.height:
        return [f"{surface.id} is {surface.width}×{surface.height}, not {width}×{height}."]
    return []


def text_problems(surface: Surface, text: str) -> list[str]:
    body = text or ""
    problems = []
    if surface.caption_limit and len(body) > surface.caption_limit:
        problems.append(
            f"{surface.id} allows {surface.caption_limit} characters. This has {len(body)}."
        )
    visible = surface.caption_visible
    if visible and len(body) > visible and not any(mark in body[:visible] for mark in ".?!"):
        problems.append(
            f"The first {visible} characters of a {surface.id} post do not finish a sentence."
        )
    return problems


def carousel_problems(surface: Surface, sizes: list[tuple[int, int]]) -> list[str]:
    problems = []
    if surface.max_slides and len(sizes) > surface.max_slides:
        problems.append(f"{surface.id} allows {surface.max_slides} slides. This has {len(sizes)}.")
    for index, (width, height) in enumerate(sizes, start=1):
        for problem in size_problems(surface, width, height):
            problems.append(f"Slide {index}: {problem}")
    return problems
