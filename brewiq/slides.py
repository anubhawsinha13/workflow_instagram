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


def poster_phrase(text: str, fallback: str = "Keep the source nearby") -> tuple[str, str]:
    """Keep the close card to a short poster line. The remainder stays with the slide."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return fallback, ""
    clause, separator, rest = cleaned.partition(";")
    clause = clause.strip()
    rest = rest.strip()
    if separator and 1 < len(clause.split()) <= 7:
        return clause, rest
    words = cleaned.split()
    if len(words) <= 6:
        return cleaned, ""
    return " ".join(words[:5]), " ".join(words[5:])


def _title(value: str, fallback: str, max_words: int = 5) -> str:
    words = _words(value)
    if not words:
        return fallback
    return " ".join(words[:max_words])


def build_slides(research: dict) -> list[dict]:
    label = category_style(research["category"])["label"]
    try_lines = split_lines(research.get("try_it") or "", max_lines=3, max_chars=46)
    point_lines = split_lines(research.get("point") or "", max_lines=3, max_chars=46)

    takeaway = " ".join((research.get("takeaway") or "").split())
    if takeaway and len(takeaway.split()) <= 8:
        close, close_rest = takeaway.rstrip("."), ""
    else:
        close, close_rest = poster_phrase(takeaway)
    close_body = split_lines(close_rest, max_lines=2, max_chars=46) if close_rest else []
    stat = " ".join(_words(research.get("stat") or "")[:6])

    slides = [
        {
            "number": 1,
            "role": "cover",
            "headline": research.get("headline") or research.get("topic") or label,
            "accent_line": stat,
            "body": [],
            "next_cue": NEXT["cover"],
        },
        {
            "number": 2,
            "role": "why",
            "headline": _title(research.get("why_title") or "", "Why it lands"),
            "accent_line": "",
            "body": split_lines(research.get("why_it_matters") or research.get("hook") or ""),
            "next_cue": NEXT["why"],
        },
        {
            "number": 3,
            "role": "point",
            "headline": _title(research.get("point_title") or "", "The real shift"),
            "accent_line": "",
            "body": point_lines,
            "next_cue": NEXT["point"],
        },
        {
            "number": 4,
            "role": "try",
            "headline": _title(
                research.get("try_title") or "",
                "Try this tonight" if research["category"] == "try_this" else "Put it to work",
            ),
            "accent_line": "",
            "body": try_lines,
            "next_cue": NEXT["try"],
        },
        {
            "number": 5,
            "role": "limit",
            "headline": _title(research.get("limit_title") or "", "Where it breaks"),
            "accent_line": "",
            "body": split_lines(research.get("limitations") or "Details can change. Check the source."),
            "next_cue": NEXT["limit"],
        },
        {
            "number": 6,
            "role": "close",
            "headline": close,
            "accent_line": "",
            "body": close_body,
            "next_cue": NEXT["close"],
        },
    ]
    if len(slides) != SLIDE_COUNT:
        raise RuntimeError("Carousel must contain six slides.")
    for slide in slides:
        slide["body"] = [line for line in slide["body"] if line][:3]
    return slides
