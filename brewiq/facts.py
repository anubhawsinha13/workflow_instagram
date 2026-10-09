#!/usr/bin/env python3
"""Return verified facts for a reel. This does not generate images or publish."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["BREWIQ_NONINTERACTIVE"] = "1"

from history import load_history, next_category  # noqa: E402
from research_md import primary_urls  # noqa: E402
from rights import copyright_problems, prepare_post_copy  # noqa: E402
from run import resolve_research  # noqa: E402


def verified_facts(topic: str) -> dict:
    records, history_available = load_history(ROOT)
    category = next_category(records, history_available)
    resolved = resolve_research(topic, None, category, records)
    if not resolved.get("ok") or not resolved.get("research"):
        return {"ok": False, "error": _public(resolved.get("error") or "Research did not return verified facts.")}
    research = prepare_post_copy(resolved["research"])
    sources = primary_urls(research)
    if not sources:
        return {"ok": False, "error": "No primary source URL was available, so the reel was not created."}
    blocked = copyright_problems(research)
    if blocked:
        return {"ok": False, "error": " ".join(blocked)}
    lines = [
        str(research.get("headline") or "").strip(),
        str(research.get("why_it_matters") or "").strip(),
        str(research.get("point") or "").strip(),
        str(research.get("limitations") or "").strip(),
        str(research.get("availability") or "").strip(),
    ]
    for claim in research.get("claims") or []:
        text = str(claim.get("text") or "").strip()
        url = str(claim.get("source_url") or "").strip()
        if text and url:
            lines.append(f"{text} Source: {url}")
    facts = "\n".join(line for line in lines if line)
    if not facts:
        return {"ok": False, "error": "Research did not return verified facts."}
    return {"ok": True, "facts": facts, "sources": sources}


def _public(detail: str) -> str:
    text = " ".join(str(detail).split())
    if not text or len(text) > 240 or any(word in text.lower() for word in ("api_key", "token", "sk-", "secret")):
        return "Research could not verify this topic, so the reel was not created."
    return text


def main() -> int:
    topic = " ".join(sys.argv[1:]).strip()
    if not topic:
        print(json.dumps({"ok": False, "error": "A topic is required."}))
        return 1
    print(json.dumps(verified_facts(topic)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
