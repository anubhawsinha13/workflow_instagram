"""Turn verified research into six short slides."""

from __future__ import annotations

from brand import SLIDE_COUNT, category_style

NEXT = {
    "cover": "Next: why it matters",
    "why": "Next: the point",
    "point": "Next: try it",
    "try": "Next: the limit",
    "limit": "Next: the close",
    "close": None,
}


def _words(text: str) -> list[str]:
    return [word for word in (text or "").split() if word]


def split_lines(text: str, max_lines: int = 3, max_chars: int = 46) -> list[str]:
    words = _words(text)
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if len(trial) <= max_chars:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            current = ""
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    lines = [line for line in lines if line][:max_lines]
    kept = " ".join(lines)
    if len(kept.split()) < len(words) and kept and not kept.endswith((".", "!", "?")):
        end = max(kept.rfind("."), kept.rfind("!"), kept.rfind("?"))
        if end >= 20:
            return split_lines(kept[: end + 1], max_lines, max_chars)
    return lines


def _date_line(research: dict) -> str:
    if research.get("timeliness") == "timely":
        event = research.get("event_date") or "not stated"
        published = research.get("publication_date") or "not stated"
        return f"Event date: {event}. Source published: {published}."
    return "Evergreen note, not a breaking story."


def build_slides(research: dict) -> list[dict]:
    label = category_style(research["category"])["label"]
    product = research.get("product") or "the product you use"
    try_lines = split_lines(research.get("try_it") or "", max_lines=2, max_chars=42)
    if research["category"] == "try_this":
        try_lines = (try_lines + ["", ""])[:2]
        try_lines.append(f"Not tested in {product}."[:46])
    point_lines = split_lines(research.get("point") or "", max_lines=2, max_chars=46)
    point_lines.append(split_lines(_date_line(research), max_lines=1, max_chars=52)[0] if _date_line(research) else "")
    point_lines = [line for line in point_lines if line][:3]

    slides = [
        {
            "number": 1,
            "role": "cover",
            "headline": research.get("headline") or research.get("topic") or label,
            "body": [],
            "next_cue": NEXT["cover"],
        },
        {
            "number": 2,
            "role": "why",
            "headline": "Why it matters",
            "body": split_lines(research.get("why_it_matters") or research.get("hook") or ""),
            "next_cue": NEXT["why"],
        },
        {
            "number": 3,
            "role": "point",
            "headline": "The point",
            "body": point_lines,
            "next_cue": NEXT["point"],
        },
        {
            "number": 4,
            "role": "try",
            "headline": "Try this" if research["category"] == "try_this" else "Use it",
            "body": try_lines if research["category"] == "try_this" else split_lines(research.get("try_it") or ""),
            "next_cue": NEXT["try"],
        },
        {
            "number": 5,
            "role": "limit",
            "headline": "The limit",
            "body": split_lines(research.get("limitations") or "Details can change. Check the source."),
            "next_cue": NEXT["limit"],
        },
        {
            "number": 6,
            "role": "close",
            "headline": research.get("takeaway") or "Keep the source nearby",
            "body": ["Follow @_brewiq", "One idea worth saving."],
            "next_cue": NEXT["close"],
        },
    ]
    if len(slides) != SLIDE_COUNT:
        raise RuntimeError("Carousel must contain six slides.")
    for slide in slides:
        slide["body"] = [line for line in slide["body"] if line][:3]
    return slides
