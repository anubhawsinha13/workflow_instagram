"""Assemble one copyable caption from verified fields."""

from __future__ import annotations

import re

from research_md import primary_urls

CAPTION_LIMIT = 2200
HASHTAG_LIMIT = 5


def _hashtag(keyword: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "", keyword or "")
    if len(token) < 2 or token.isdigit():
        return ""
    return f"#{token}"


def hashtags_for(keywords: list[str]) -> list[str]:
    tags = []
    for keyword in keywords:
        tag = _hashtag(keyword)
        if tag and tag.lower() not in {item.lower() for item in tags}:
            tags.append(tag)
        if len(tags) == HASHTAG_LIMIT:
            break
    return tags


def _date_sentence(research: dict) -> str:
    if research.get("timeliness") == "timely":
        event = research.get("event_date") or "not stated in the source notes"
        published = research.get("publication_date") or "not stated in the source notes"
        return f"The event date is {event}. The source publication date is {published}."
    return "This is an evergreen practical note, not a breaking story."


def _source_line(research: dict) -> str:
    parts = []
    seen = set()
    for claim in research.get("claims") or []:
        url = (claim.get("source_url") or "").strip()
        if url not in primary_urls(research) or url in seen:
            continue
        seen.add(url)
        title = claim.get("source_title") or claim.get("text") or "Source"
        parts.append(f"{title}: {url}")
    if not parts:
        return "Source: none verified."
    return "Source: " + " ".join(parts)


def build_caption(research: dict, image_note: str) -> str:
    product = research.get("product") or "the product you use"
    try_it = research.get("try_it") or ""
    blocks = [
        research.get("hook") or research.get("headline") or research.get("topic") or "",
        research.get("why_it_matters") or "",
        research.get("point") or "",
        _date_sentence(research),
    ]
    if research.get("availability"):
        blocks.append(research["availability"])
    if try_it:
        if research.get("category") == "try_this":
            blocks.append(try_it)
            blocks.append(f"Original suggested prompt; not tested in {product}.")
        else:
            blocks.append(try_it)
    if research.get("limitations"):
        blocks.append(research["limitations"])
    takeaway = (research.get("takeaway") or "").strip()
    if takeaway and takeaway not in blocks:
        blocks.append(takeaway)
    blocks.append("Save this for the next time you want to check an answer before you trust it.")
    blocks.append("Follow @_brewiq.")
    blocks.append(_source_line(research))
    blocks.append(image_note)
    tags = hashtags_for(research.get("keywords") or [])
    text = "\n\n".join(block.strip() for block in blocks if block and block.strip())
    if tags:
        text = text + "\n\n" + " ".join(tags)
    if len(text) > CAPTION_LIMIT:
        text = text[: CAPTION_LIMIT - 1].rsplit(" ", 1)[0].rstrip()
    return text


def caption_problems(caption: str) -> list[str]:
    problems = []
    if len(caption) > CAPTION_LIMIT:
        problems.append(f"Caption is {len(caption)} characters.")
    tags = re.findall(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]*)", caption)
    if len(tags) > HASHTAG_LIMIT:
        problems.append(f"Caption has {len(tags)} hashtags.")
    return problems
