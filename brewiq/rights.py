"""Stop a post that asks for a copied image or a long quotation.

These checks do not clear copyright. A draft that fails is not hosted or posted.
"""

from __future__ import annotations

import re

SPAN = 10

_RISKY_VISUAL = re.compile(
    r"\b("
    r"logos?|trademarks?|watermarks?|screenshots?|likeness|celebrity|celebrities|"
    r"movie still|album cover|book cover|copyrighted|fan art|"
    r"in the style of|reproduce|copy of"
    r")\b",
    re.IGNORECASE,
)
_LONG_QUOTE = re.compile(r"[\"“]([^\"”]{40,})[\"”]")
_WORDS = re.compile(r"[a-z0-9']+")


def original_scene_clause() -> str:
    return (
        "Invent an original scene. Do not depict a copyrighted character, celebrity, "
        "logo, trademarked product, existing photograph, movie still, album cover, "
        "book cover, or known artwork. No text, no letters, no numbers, no logos, "
        "no watermarks, no interface, and no screenshots."
    )


def visual_problems(visual_idea: str) -> list[str]:
    described = _EXCLUSION.sub("", visual_idea or "")
    if _RISKY_VISUAL.search(described):
        return [
            "The image idea asks for a logo, screenshot, or copy of an existing work. "
            "The post was not created."
        ]
    return []


_EXCLUSION = re.compile(
    r"\b(?:no|without|avoid|excluding|do not|don't|never)\b[^.;]*",
    re.IGNORECASE,
)


_PROSE_FIELDS = (
    "headline",
    "hook",
    "why_it_matters",
    "point",
    "try_it",
    "limitations",
    "takeaway",
    "availability",
)


def prepare_post_copy(research: dict) -> dict:
    """Remove long quotations and shorten source passages so the reel can continue."""
    return paraphrase_repeated_notes(omit_long_quotations(research))


def paraphrase_repeated_notes(research: dict) -> dict:
    """Drop any 10-word stretch that copies a source note. The source URL stays attached."""
    cleaned = dict(research)
    claims = [claim for claim in (cleaned.get("claims") or []) if isinstance(claim, dict)]
    for field in _PROSE_FIELDS:
        value = cleaned.get(field)
        if isinstance(value, str) and value.strip():
            cleaned[field] = _drop_overlapping_spans(value, claims)
    return cleaned


def omit_long_quotations(research: dict) -> dict:
    """Drop quoted passages of 12 or more words so a source sentence is not posted."""
    cleaned = dict(research)
    for field in _PROSE_FIELDS:
        value = cleaned.get(field)
        if isinstance(value, str):
            cleaned[field] = _LONG_QUOTE.sub(_drop_long_quote, value).strip()
    return cleaned


def copyright_problems(research: dict, extra_texts: list[str] | None = None) -> list[str]:
    """Return reasons to refuse hosting. An empty list means the automated checks passed."""
    problems = visual_problems(str(research.get("visual_idea") or ""))
    prose = [
        research.get("headline"),
        research.get("hook"),
        research.get("why_it_matters"),
        research.get("point"),
        research.get("try_it"),
        research.get("limitations"),
        research.get("takeaway"),
        research.get("availability"),
        *(extra_texts or []),
    ]
    text = "\n".join(str(item) for item in prose if item)
    if _long_quotation(text):
        problems.append("The post includes a long quotation. Remove it before posting.")
    if _repeats_source_note(text, research.get("claims") or []):
        problems.append(
            "The post repeats a long passage from the source notes. "
            "It needs a shorter paraphrase before it can be posted."
        )
    return problems


def _long_quotation(text: str) -> bool:
    for match in _LONG_QUOTE.finditer(text):
        if len(_words(match.group(1))) >= 12:
            return True
    return False


def _drop_long_quote(match: re.Match) -> str:
    if len(_words(match.group(1))) >= 12:
        return ""
    return match.group(0)


def _drop_overlapping_spans(text: str, claims: list[dict]) -> str:
    spans = []
    for claim in claims:
        words = _words(str(claim.get("text") or ""))
        if len(words) < SPAN:
            continue
        for index in range(len(words) - SPAN + 1):
            spans.append(words[index : index + SPAN])
    current = text
    for _ in range(12):
        tokens = list(_WORDS.finditer(current))
        lowered = [token.group(0).lower() for token in tokens]
        start = _matching_window(lowered, spans)
        if start is None:
            break
        cut_from = tokens[start].start()
        cut_to = tokens[start + SPAN - 1].end()
        current = f"{current[:cut_from]} {current[cut_to:]}".strip()
        current = re.sub(r"\s{2,}", " ", current)
    if len(_words(current)) < 4:
        return "The source notes support this in shorter form."
    return current


def _matching_window(words: list[str], spans: list[list[str]]) -> int | None:
    if len(words) < SPAN:
        return None
    for span in spans:
        for index in range(len(words) - SPAN + 1):
            if words[index : index + SPAN] == span:
                return index
    return None


def _repeats_source_note(text: str, claims: list[dict]) -> bool:
    haystack = _words(_without_source_block(text))
    if not haystack:
        return False
    joined = " ".join(haystack)
    for claim in claims:
        claim_words = _words(str(claim.get("text") or ""))
        if len(claim_words) < SPAN:
            continue
        for index in range(len(claim_words) - SPAN + 1):
            if " ".join(claim_words[index : index + SPAN]) in joined:
                return True
    return False


def _without_source_block(text: str) -> str:
    blocks = []
    for block in text.split("\n\n"):
        if block.strip().lower().startswith("source:"):
            continue
        blocks.append(block)
    return "\n".join(blocks)


def _words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())
