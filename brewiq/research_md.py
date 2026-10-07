"""Read a research markdown file into the shared research shape."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from brand import normalize_category

SOCIAL_HOSTS = {
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "facebook.com",
    "threads.net",
    "reddit.com",
    "example.com",
}

_URL = re.compile(r"https?://[^\s|>)]+")


def _host(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def is_primary_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False
    host = _host(url)
    if not host or "." not in host:
        return False
    if host in SOCIAL_HOSTS or host.endswith(".example") or host.endswith(".example.com"):
        return False
    return True


def primary_urls(research: dict) -> list[str]:
    found = []
    for claim in research.get("claims") or []:
        url = (claim.get("source_url") or "").strip().rstrip(".,)")
        if is_primary_url(url) and url not in found:
            found.append(url)
    return found


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip()


def _section_map(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _claims(block: str) -> list[dict]:
    claims = []
    for raw_line in block.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        url = ""
        for part in parts:
            match = _URL.search(part)
            if match:
                url = match.group(0).rstrip(".,)")
                break
        claims.append(
            {
                "text": parts[0] if parts else line,
                "source_url": url,
                "source_title": parts[2] if len(parts) > 2 else "",
                "published": parts[3] if len(parts) > 3 else "",
                "event_date": parts[4] if len(parts) > 4 else "",
            }
        )
    return claims


def _keywords(block: str) -> list[str]:
    pieces = re.split(r"[\n,]", block)
    return [piece.strip() for piece in pieces if piece.strip()]


def research_from_fields(raw: dict, source: str, live_verified: bool, origin_path: str = "") -> dict:
    claims = raw.get("claims") or []
    if isinstance(claims, str):
        claims = _claims(claims)
    cleaned_claims = []
    for claim in claims:
        if isinstance(claim, str):
            cleaned_claims.extend(_claims(claim))
            continue
        cleaned_claims.append(
            {
                "text": _clean(str(claim.get("text") or "")),
                "source_url": _clean(str(claim.get("source_url") or "")).rstrip(".,)"),
                "source_title": _clean(str(claim.get("source_title") or "")),
                "published": _clean(str(claim.get("published") or "")),
                "event_date": _clean(str(claim.get("event_date") or "")),
            }
        )
    keywords = raw.get("keywords") or []
    if isinstance(keywords, str):
        keywords = _keywords(keywords)
    timeliness = _clean(str(raw.get("timeliness") or "evergreen")).lower()
    if timeliness not in ("timely", "evergreen"):
        timeliness = "evergreen"
    return {
        "topic": _clean(str(raw.get("topic") or "")),
        "category": normalize_category(str(raw.get("category") or "")),
        "timeliness": timeliness,
        "headline": _clean(str(raw.get("headline") or "")),
        "hook": _clean(str(raw.get("hook") or "")),
        "why_it_matters": _clean(str(raw.get("why_it_matters") or "")),
        "point": _clean(str(raw.get("point") or "")),
        "event_date": _clean(str(raw.get("event_date") or "")),
        "publication_date": _clean(str(raw.get("publication_date") or "")),
        "claims": cleaned_claims,
        "availability": _clean(str(raw.get("availability") or "")),
        "limitations": _clean(str(raw.get("limitations") or "")),
        "try_it": _clean(str(raw.get("try_it") or "")),
        "product": _clean(str(raw.get("product") or "")) or "the product you use",
        "takeaway": _clean(str(raw.get("takeaway") or "")),
        "visual_idea": _clean(str(raw.get("visual_idea") or "")),
        "keywords": [_clean(str(word)) for word in keywords if _clean(str(word))],
        "source": source,
        "live_verified": live_verified,
        "origin_path": origin_path,
    }


def parse_markdown(text: str, origin_path: str = "") -> dict:
    sections = _section_map(text)
    raw = {
        "topic": sections.get("topic", ""),
        "category": sections.get("category", ""),
        "timeliness": sections.get("timeliness", ""),
        "headline": sections.get("headline", ""),
        "hook": sections.get("hook", ""),
        "why_it_matters": sections.get("why it matters", ""),
        "point": sections.get("the point", ""),
        "event_date": sections.get("event date", ""),
        "publication_date": sections.get("publication date", ""),
        "claims": _claims(sections.get("claims", "")),
        "availability": sections.get("availability", ""),
        "limitations": sections.get("limitations", ""),
        "try_it": sections.get("try it", ""),
        "product": sections.get("product", ""),
        "takeaway": sections.get("takeaway", ""),
        "visual_idea": sections.get("visual idea", ""),
        "keywords": _keywords(sections.get("keywords", "")),
    }
    return research_from_fields(raw, source="markdown", live_verified=False, origin_path=origin_path)


def load_research_file(path: Path) -> dict:
    if not path.exists():
        return {"ok": False, "error": f"Research file not found: {path}", "research": None}
    text = path.read_text(encoding="utf-8")
    research = parse_markdown(text, origin_path=str(path))
    if not research["topic"] and not research["headline"]:
        return {
            "ok": False,
            "error": "The markdown file needs a ## Topic or ## Headline section.",
            "research": research,
            "text": text,
        }
    if not primary_urls(research):
        return {
            "ok": False,
            "error": "The markdown file has no primary source URL. Social posts and example.com links do not count.",
            "research": research,
            "text": text,
        }
    return {"ok": True, "error": "", "research": research, "text": text}


def render_research_markdown(research: dict) -> str:
    claim_lines = []
    for claim in research.get("claims") or []:
        claim_lines.append(
            "- {text} | {url} | {title} | {published} | {event}".format(
                text=claim.get("text") or "",
                url=claim.get("source_url") or "",
                title=claim.get("source_title") or "",
                published=claim.get("published") or "",
                event=claim.get("event_date") or "",
            )
        )
    keywords = ", ".join(research.get("keywords") or [])
    return "\n".join(
        [
            "# Research",
            "",
            "## Topic",
            research.get("topic") or "",
            "",
            "## Category",
            research.get("category") or "",
            "",
            "## Timeliness",
            research.get("timeliness") or "",
            "",
            "## Headline",
            research.get("headline") or "",
            "",
            "## Hook",
            research.get("hook") or "",
            "",
            "## Why it matters",
            research.get("why_it_matters") or "",
            "",
            "## The point",
            research.get("point") or "",
            "",
            "## Event date",
            research.get("event_date") or "",
            "",
            "## Publication date",
            research.get("publication_date") or "",
            "",
            "## Claims",
            "\n".join(claim_lines),
            "",
            "## Availability",
            research.get("availability") or "",
            "",
            "## Limitations",
            research.get("limitations") or "",
            "",
            "## Try it",
            research.get("try_it") or "",
            "",
            "## Product",
            research.get("product") or "",
            "",
            "## Takeaway",
            research.get("takeaway") or "",
            "",
            "## Visual idea",
            research.get("visual_idea") or "",
            "",
            "## Keywords",
            keywords,
            "",
        ]
    )
