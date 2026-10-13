"""BrewIQ utility carousel: a branded prompt pack built to be saved and sent (UC-005, EXP-003).

Unlike the cinematic reel, the text *is* the content here: each slide is a numbered
step, a one-line benefit and a copyable prompt in a chat-style card. It needs no
Veo, so it is cheap to post often. The rules differ from the reel's on purpose
(long body text is allowed), but every slide is still laid out on a separate text
layer and checked for legibility, fit, contrast, share value, honest calls to
action and originality.
"""

from __future__ import annotations

import re
from typing import Any

from cinematic_profile import HOST_LOCK, HOST_REFERENCES, NO_TEXT_RULE
from composition import (
    BRAND,
    BRAND_LOOK,
    CHAR_WIDTH,
    PLATE_PADDING,
    contrast_ratio,
    fit_headline,
    wrap_lines,
)

CANVAS = (1080, 1350)
MIN_ITEMS, MAX_ITEMS = 5, 8
MAX_TITLE_WORDS = 6
MAX_BENEFIT_WORDS = 12
MAX_PROMPT_WORDS = 70
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 5
TITLE_BOX = (90, 140, 900, 150)
BENEFIT_BOX = (90, 300, 900, 100)
CARD_BOX = (90, 430, 900, 760)
CARD_PADDING = 48
CARD_TEXT_WIDTH = CARD_BOX[2] - 2 * CARD_PADDING
CARD_TEXT_HEIGHT = CARD_BOX[3] - 2 * CARD_PADDING - 80  # 80px reserved for the chat-input icons
TITLE_SIZE, BENEFIT_SIZE, PROMPT_SIZE = 56, 36, 34
MIN_PROMPT_SIZE = 30
LINE_HEIGHT = 1.35
COLORS = {
    "background": BRAND["midnight_navy"],
    "card": "#151C33",
    "card_border": BRAND["electric_cyan"],
    "title": BRAND["clean_white"],
    "benefit": "#AEB8CF",
    "prompt": BRAND["clean_white"],
    "placeholder": BRAND["warm_amber"],
    "number": BRAND["electric_cyan"],
}
PLACEHOLDER = re.compile(r"\[[A-Z0-9][A-Z0-9 /_+&-]*\]")
_BEGGING = re.compile(
    r"\b(share this (with|to)|tag (a|your) friends?|like and (follow|share)|smash (that|the)|"
    r"comment below if|follow for more|don'?t forget to (like|share|follow))\b",
    re.IGNORECASE,
)
_OVERCLAIM = re.compile(r"\b(guaranteed|100%|secret|go viral|instantly rich|never fails)\b", re.IGNORECASE)
_GENERIC_REASON = re.compile(r"^\s*(it'?s useful|people like it|good content|engagement)\.?\s*$", re.IGNORECASE)
SIMILARITY_LIMIT = 0.6


def _words(text: str) -> list[str]:
    return str(text or "").split()


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def similarity(a: str, b: str) -> float:
    """Word-set overlap (Jaccard). 0.6+ means the prompt is a near-copy, not an adaptation."""
    x, y = _tokens(a), _tokens(b)
    return round(len(x & y) / len(x | y), 2) if x and y else 0.0


def _card_lines(prompt: str, size: int) -> list[str]:
    return wrap_lines(prompt, size, CARD_TEXT_WIDTH + 2 * PLATE_PADDING)


def _card_capacity(size: int) -> int:
    return int(CARD_TEXT_HEIGHT // (size * LINE_HEIGHT))


def _fit_prompt(prompt: str) -> tuple[int, list[str]]:
    """Largest prompt size whose lines fit the card; the smallest size if none does (the gate then fails)."""
    for size in (PROMPT_SIZE, 32, MIN_PROMPT_SIZE):
        lines = _card_lines(prompt, size)
        if len(lines) <= _card_capacity(size):
            return size, lines
    return MIN_PROMPT_SIZE, _card_lines(prompt, MIN_PROMPT_SIZE)


def plan_utility_carousel(
    topic: str,
    items: list[dict[str, str]],
    *,
    cover_headline: str,
    cover_visual: str,
    save_reason: str,
    share_reason: str,
    closing_line: str,
    search_keywords: list[str] | None = None,
    hashtags: list[str] | None = None,
    reference_prompts: list[str] | None = None,
    series: str = "",
) -> dict[str, Any]:
    """Lay out a cover, one slide per prompt item and a closing slide, then run the gates.

    ``items``: 5–8 of {title (≤6 words), benefit (≤12 words), prompt (≤70 words, at
    least one [PLACEHOLDER])}. ``reference_prompts`` are prompts that inspired the pack
    (for example another creator's); a near-copy of any of them is rejected.
    """
    slides: list[dict[str, Any]] = []
    cover_size, cover_lines = fit_headline(cover_headline)
    slides.append(
        {
            "index": 1,
            "role": "cover",
            "image_prompt": " ".join(
                [
                    HOST_LOCK,
                    BRAND_LOOK,
                    (
                        f"COVER — {cover_visual}. 4:5 vertical still, the host in the lower half, clean negative "
                        "space in the top 35% for the headline."
                    ),
                    NO_TEXT_RULE,
                ]
            ),
            "reference_assets": list(HOST_REFERENCES),
            "layers": [
                {"type": "headline", "text": cover_headline, "lines": cover_lines, "size": cover_size,
                 "box": [90, 120, 900, 300], "color": COLORS["title"], "plate": COLORS["background"]},
                {"type": "swipe_cue", "text": f"{len(items)} prompts →", "size": 34, "box": [90, 1210, 400, 60],
                 "color": BRAND["electric_cyan"], "plate": COLORS["background"]},
                {"type": "brand", "text": "BrewIQ", "size": 40, "box": [780, 1210, 210, 60],
                 "color": COLORS["title"], "plate": COLORS["background"]},
            ],
        }
    )
    for number, item in enumerate(items, start=1):
        prompt = " ".join(_words(item.get("prompt")))
        size, lines = _fit_prompt(prompt)
        slides.append(
            {
                "index": number + 1,
                "role": "prompt",
                "number": number,
                "title": f"{number}. {item.get('title', '').strip()}",
                "benefit": " ".join(_words(item.get("benefit"))),
                "prompt": prompt,
                "placeholders": PLACEHOLDER.findall(prompt),
                "layers": [
                    {"type": "background", "color": COLORS["background"], "box": [0, 0, *CANVAS]},
                    {"type": "title", "text": f"{number}. {item.get('title', '').strip()}", "size": TITLE_SIZE,
                     "box": list(TITLE_BOX), "color": COLORS["title"], "plate": COLORS["background"],
                     "lines": wrap_lines(f"{number}. {item.get('title', '')}", TITLE_SIZE, TITLE_BOX[2])},
                    {"type": "benefit", "text": item.get("benefit", ""), "size": BENEFIT_SIZE, "box": list(BENEFIT_BOX),
                     "color": COLORS["benefit"], "plate": COLORS["background"],
                     "lines": wrap_lines(item.get("benefit", ""), BENEFIT_SIZE, BENEFIT_BOX[2])},
                    {"type": "card", "box": list(CARD_BOX), "fill": COLORS["card"], "border": COLORS["card_border"],
                     "radius": 36, "ui": "chat input: '+' bottom-left, mic and send arrow bottom-right"},
                    {"type": "prompt", "text": prompt, "lines": lines, "size": size, "box": list(CARD_BOX),
                     "color": COLORS["prompt"], "plate": COLORS["card"], "placeholder_color": COLORS["placeholder"],
                     "placeholder_weight": "bold"},
                    {"type": "page", "text": f"{number + 1}/{len(items) + 2}", "size": 28, "box": [900, 60, 90, 50],
                     "color": COLORS["benefit"], "plate": COLORS["background"]},
                ],
            }
        )
    slides.append(
        {
            "index": len(items) + 2,
            "role": "closing",
            "layers": [
                {"type": "closing", "text": closing_line, "size": TITLE_SIZE, "box": [90, 420, 900, 300],
                 "color": COLORS["title"], "plate": COLORS["background"],
                 "lines": wrap_lines(closing_line, TITLE_SIZE, 900)},
                {"type": "brand", "text": "BrewIQ", "size": 48, "box": [90, 1180, 300, 80],
                 "color": COLORS["title"], "plate": COLORS["background"]},
            ],
        }
    )
    tags = [t if t.startswith("#") else f"#{t}" for t in (hashtags or [])]
    caption = "\n\n".join(
        part
        for part in (
            cover_headline,
            f"{len(items)} copy-and-paste prompts: {topic}. Swap the [BRACKETS] for your details.",
            "\n".join(f"{s['number']}. {s['title'][len(str(s['number'])) + 2:]}" for s in slides if s["role"] == "prompt"),
            closing_line,
            " · ".join(search_keywords or []),
            " ".join(tags),
        )
        if part
    )
    plan = {
        "ok": True,
        "format": "utility_carousel",
        "topic": topic,
        "series": series,
        "size": list(CANVAS),
        "aspect_ratio": "4:5",
        "colors": dict(COLORS),
        "slides": slides,
        "caption": caption,
        "hashtags": tags,
        "search_keywords": list(search_keywords or []),
        "save_reason": save_reason,
        "share_reason": share_reason,
        "audio": "Optional: add a track from Instagram's licensed library in the app; never a ripped file.",
        "nothing_posted": True,
    }
    plan["problems"] = carousel_problems(plan, reference_prompts or [])
    plan["ok"] = not plan["problems"]
    plan["status"] = "planned" if plan["ok"] else "blocked"
    return plan


def carousel_problems(plan: dict[str, Any], reference_prompts: list[str] | None = None) -> list[str]:
    problems: list[str] = []
    slides = plan.get("slides") or []
    prompts = [s for s in slides if s.get("role") == "prompt"]
    if not MIN_ITEMS <= len(prompts) <= MAX_ITEMS:
        problems.append(f"Need {MIN_ITEMS}–{MAX_ITEMS} prompt slides, got {len(prompts)}.")
    if not slides or slides[0].get("role") != "cover":
        problems.append("Slide 1 must be the cover.")
    else:
        cover = slides[0]
        headline = next((l for l in cover["layers"] if l["type"] == "headline"), {})
        if not 2 <= len(_words(headline.get("text"))) <= 6:
            problems.append("Cover headline must be 2–6 words.")
        if len(headline.get("lines") or []) > 2:
            problems.append("Cover headline does not fit in 2 lines.")
        if BRAND_LOOK not in str(cover.get("image_prompt") or "") or NO_TEXT_RULE not in str(cover.get("image_prompt") or ""):
            problems.append("Cover image prompt needs the brand look and the no-text rule.")
    if not slides or slides[-1].get("role") != "closing":
        problems.append("Last slide must be the closing slide.")
    else:
        closing = str(slides[-1]["layers"][0].get("text") or "")
        if not closing.strip():
            problems.append("Closing slide needs a line.")
        if _BEGGING.search(closing):
            problems.append("Closing line begs for engagement; give a reason to save or send instead.")

    seen: list[str] = []
    for slide in prompts:
        tag = f"Slide {slide['index']}"
        title = slide["title"].split(". ", 1)[-1]
        if not title or len(_words(title)) > MAX_TITLE_WORDS:
            problems.append(f"{tag} title must be 1–{MAX_TITLE_WORDS} words.")
        if not slide["benefit"] or len(_words(slide["benefit"])) > MAX_BENEFIT_WORDS:
            problems.append(f"{tag} benefit must say what you get in 1–{MAX_BENEFIT_WORDS} words.")
        prompt = slide["prompt"]
        if len(_words(prompt)) > MAX_PROMPT_WORDS:
            problems.append(f"{tag} prompt is over {MAX_PROMPT_WORDS} words; split it or cut it.")
        if not slide["placeholders"]:
            problems.append(f"{tag} prompt needs at least one [PLACEHOLDER] the reader fills in.")
        if _OVERCLAIM.search(" ".join((title, slide["benefit"], prompt))):
            problems.append(f"{tag} overclaims (guaranteed, secret, go viral…).")
        for other in seen:
            if similarity(prompt, other) >= SIMILARITY_LIMIT:
                problems.append(f"{tag} repeats an earlier prompt.")
                break
        seen.append(prompt)
        for ref in reference_prompts or []:
            if similarity(prompt, ref) >= SIMILARITY_LIMIT:
                problems.append(f"{tag} is a near-copy of a reference prompt; adapt the mechanism, don't copy it.")
                break
        for layer in slide["layers"]:
            if "text" not in layer:
                continue
            if layer.get("plate") and contrast_ratio(layer["color"], layer["plate"]) < 4.5:
                problems.append(f"{tag} {layer['type']} contrast is below 4.5:1.")
            if layer["type"] == "prompt":
                if layer["size"] < MIN_PROMPT_SIZE:
                    problems.append(f"{tag} prompt text is under {MIN_PROMPT_SIZE}px.")
                if len(layer["lines"]) > _card_capacity(layer["size"]):
                    problems.append(f"{tag} prompt does not fit in the card; it would be clipped.")
                if any(len(line) * layer["size"] * CHAR_WIDTH > CARD_TEXT_WIDTH for line in layer["lines"]):
                    problems.append(f"{tag} prompt has a line wider than the card.")
            if layer["type"] in ("title", "benefit") and len(layer.get("lines") or []) > 2:
                problems.append(f"{tag} {layer['type']} does not fit in 2 lines.")
        if contrast_ratio(COLORS["placeholder"], COLORS["card"]) < 4.5:
            problems.append(f"{tag} placeholder colour contrast is below 4.5:1.")

    for key in ("save_reason", "share_reason"):
        value = str(plan.get(key) or "")
        if len(_words(value)) < 5 or _GENERIC_REASON.match(value):
            problems.append(f"Say concretely why someone would {key.split('_')[0]} this ({key}).")
    caption = str(plan.get("caption") or "")
    if len(caption) > MAX_CAPTION_CHARS:
        problems.append(f"Caption is over {MAX_CAPTION_CHARS} characters.")
    if _BEGGING.search(caption):
        problems.append("Caption begs for engagement.")
    if len(plan.get("hashtags") or []) > MAX_HASHTAGS:
        problems.append(f"Use at most {MAX_HASHTAGS} hashtags.")
    if not plan.get("search_keywords"):
        problems.append("Add 2–4 search keywords so the post can be found in Instagram search.")
    return problems
