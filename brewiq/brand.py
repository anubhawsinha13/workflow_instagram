"""BrewIQ visual identity."""

from __future__ import annotations

BRAND = "BrewIQ"
HANDLE = "@_brewiq"

BG = "#10141C"
WHITE = "#FFFFFF"
CYAN = "#35D5F4"
GOLD = "#FFC76A"
MUTED = "#C5CDD6"

WIDTH = 1080
HEIGHT = 1350
MARGIN_X = 86  # about 8% of 1080
MARGIN_Y = 108  # about 8% of 1350
SLIDE_COUNT = 6

CATEGORIES = {
    "ai_news": {"label": "AI NEWS", "accent": CYAN},
    "ai_research": {"label": "AI RESEARCH", "accent": CYAN},
    "try_this": {"label": "TRY THIS", "accent": GOLD},
}

_ALIASES = {
    "ai news": "ai_news",
    "news": "ai_news",
    "ai_news": "ai_news",
    "ai research": "ai_research",
    "research": "ai_research",
    "ai_research": "ai_research",
    "try this": "try_this",
    "try_this": "try_this",
    "practical": "try_this",
    "comparison": "try_this",
    "prompt": "try_this",
    "prompts": "try_this",
}


def normalize_category(value: str | None) -> str:
    key = (value or "").strip().lower().replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    if key in _ALIASES:
        return _ALIASES[key]
    compact = key.replace(" ", "_")
    if compact in CATEGORIES:
        return compact
    return "ai_news"


def category_style(category: str) -> dict:
    return CATEGORIES[normalize_category(category)]


def hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
