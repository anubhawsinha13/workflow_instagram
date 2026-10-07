"""Read and update the local topic history."""

from __future__ import annotations

import json
import re
from pathlib import Path

from brand import normalize_category

ORDER = ["ai_news", "try_this", "ai_research"]


def history_path(root: Path) -> Path:
    return root / "history" / "index.jsonl"


def load_history(root: Path) -> tuple[list[dict], bool]:
    """Return records and whether a history file was available."""
    path = history_path(root)
    if not path.exists():
        return [], False
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records, True


def next_category(records: list[dict], available: bool) -> str:
    if not available or not records:
        return "ai_news"
    last_seen = {}
    last = None
    for index, record in enumerate(records):
        category = normalize_category(record.get("category"))
        if category in ORDER:
            last_seen[category] = index
            last = category
    ranked = sorted(ORDER, key=lambda category: last_seen.get(category, -1))
    for category in ranked:
        if category != last:
            return category
    return ranked[0]


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))


def is_repeat(title: str, keywords: list[str], records: list[dict]) -> bool:
    title_tokens = _tokens(title)
    keyword_tokens = set()
    for word in keywords:
        keyword_tokens |= _tokens(word)
    probe = title_tokens or keyword_tokens
    if not probe:
        return False
    for record in records:
        previous = _tokens(record.get("title") or "")
        for word in record.get("keywords") or []:
            previous |= _tokens(str(word))
        if not previous:
            continue
        if title_tokens and title_tokens == _tokens(record.get("title") or ""):
            return True
        overlap = probe & previous
        union = probe | previous
        if union and len(overlap) / len(union) >= 0.6:
            return True
    return False


def append_history(root: Path, record: dict) -> None:
    path = history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def history_note(available: bool) -> str:
    if not available:
        return "Project history was not available. This run did not check earlier topics."
    return "Earlier topics in history/index.jsonl were checked so this run could avoid a repeat."
