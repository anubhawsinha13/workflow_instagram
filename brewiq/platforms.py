"""Canvas, safe area, and caption limits for every surface BrewIQ can publish.

One script can become several files. Each file is checked against the surface it
is for. Numbers are the 2026 posting rules gathered on 2026-10-13. Where two
sources disagreed, the stricter limit is the one enforced.

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


# Reel playback covers the top 220px, the bottom 420px, and the right 120px.
# The profile grid keeps the centre 1080×1440, which starts at y 240.
# The box below is the overlap of those two, so a cover still reads on the grid.
INSTAGRAM_REEL = _box(
    "instagram", "reel", "video", 1080, 1920, 64, 250, 120, 420,
    caption_limit=2200, caption_visible=125, max_seconds=90,
    note="9:16. Hook and host inside the centre 3:4. Same master fits a Facebook Reel.",
)
INSTAGRAM_STORY = _box(
    "instagram", "story", "video", 1080, 1920, 64, 250, 64, 250,
    caption_limit=0, caption_visible=0, max_seconds=60,
    note="Same canvas as a Reel. The reply bar covers the bottom 250px.",
)
INSTAGRAM_FEED = _box(
    "instagram", "feed", "image", 1080, 1350, 64, 80, 64, 160,
    caption_limit=2200, caption_visible=125, max_slides=20,
    note="4:5 feed default. Every carousel slide uses this size. Slide 1 carries the hook.",
)
INSTAGRAM_GRID = _box(
    "instagram", "grid", "image", 1080, 1440, 64, 72, 64, 120,
    caption_limit=2200, caption_visible=125, max_slides=20,
    note="3:4. This is the only feed ratio the profile grid shows without a crop.",
)
INSTAGRAM_SQUARE = _box(
    "instagram", "square", "image", 1080, 1080, 64, 64, 64, 64,
    caption_limit=2200, caption_visible=125,
    note="1:1. Use when the same still is also the LinkedIn or Threads image.",
)
INSTAGRAM_LANDSCAPE = _box(
    "instagram", "landscape", "image", 1080, 566, 48, 36, 48, 36,
    caption_limit=2200, caption_visible=125,
    note="1.91:1. Widest feed ratio. A 16:9 frame is cropped if it is posted here.",
)

LINKEDIN_FEED = _box(
    "linkedin", "feed", "image", 1080, 1350, 64, 64, 64, 80,
    caption_limit=3000, caption_visible=210, max_seconds=600,
    note="4:5 is the recommended LinkedIn video ratio, and the feed autoplays muted, so the words are on the image.",
)
LINKEDIN_LINK = _box(
    "linkedin", "link", "image", 1200, 627, 40, 36, 40, 36,
    caption_limit=3000, caption_visible=210,
    note="1.91:1 link preview. Not the explainer still.",
)

X_POST = Surface(
    id="x.post", platform="x", kind="text", width=0, height=0,
    safe_left=0, safe_top=0, safe_right=0, safe_bottom=0,
    caption_limit=280, caption_visible=280,
    note="The whole post is visible. Keep one claim.",
)
X_IMAGE = _box(
    "x", "image", "image", 1080, 1350, 48, 48, 48, 48,
    caption_limit=280, caption_visible=280,
    note="4:5 takes more of the feed than 16:9.",
)
X_VIDEO = _box(
    "x", "video", "video", 1280, 720, 48, 48, 48, 48,
    caption_limit=280, caption_visible=280, max_seconds=140,
    note="1280×720 landscape. Portrait uploads use 720×1280.",
)

THREADS_POST = _box(
    "threads", "post", "image", 1080, 1080, 64, 64, 64, 64,
    caption_limit=500, caption_visible=500,
    note="500 characters, shown in full. Square image.",
)

YOUTUBE_LONG = _box(
    "youtube", "long", "video", 1920, 1080, 64, 64, 64, 64,
    caption_limit=5000, caption_visible=100, max_seconds=0,
    note="16:9. caption_visible is the title limit. The description limit is caption_limit.",
)
YOUTUBE_SHORT = _box(
    "youtube", "short", "video", 1080, 1920, 64, 250, 120, 400,
    caption_limit=100, caption_visible=100, max_seconds=180,
    note="9:16, up to 3 minutes. The title sits over the lower part of the frame.",
)

TIKTOK = _box(
    "tiktok", "video", "video", 1080, 1920, 64, 250, 120, 420,
    caption_limit=2200, caption_visible=80, max_seconds=180,
    note="Same safe box as an Instagram Reel, so one vertical master can be posted to both.",
)
FACEBOOK_REEL = _box(
    "facebook", "reel", "video", 1080, 1920, 64, 250, 120, 420,
    caption_limit=2200, caption_visible=125, max_seconds=90,
    note="Meta's shared 9:16 safe zone. Same box as the Instagram Reel.",
)
FACEBOOK_FEED = _box(
    "facebook", "feed", "image", 1080, 1350, 64, 64, 64, 80,
    caption_limit=63206, caption_visible=477,
    note="4:5 feed image. The preview cuts off near 477 characters.",
)
PINTEREST = _box(
    "pinterest", "pin", "image", 1000, 1500, 40, 48, 40, 80,
    caption_limit=800, caption_visible=100,
    note="2:3 pin. The title has to fit on one line, so caption_visible is that line.",
)

SURFACES = (
    INSTAGRAM_REEL, INSTAGRAM_STORY, INSTAGRAM_FEED, INSTAGRAM_GRID, INSTAGRAM_SQUARE, INSTAGRAM_LANDSCAPE,
    LINKEDIN_FEED, LINKEDIN_LINK, X_POST, X_IMAGE, X_VIDEO, THREADS_POST,
    YOUTUBE_LONG, YOUTUBE_SHORT, TIKTOK, FACEBOOK_REEL, FACEBOOK_FEED, PINTEREST,
)

# What one approved explainer produces first. Later surfaces stay in SURFACES
# so a new file is checked before anyone posts it.
PACK = (INSTAGRAM_REEL, INSTAGRAM_FEED, INSTAGRAM_SQUARE, INSTAGRAM_LANDSCAPE)

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
