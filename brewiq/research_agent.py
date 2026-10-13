"""BrewIQ Reel-First Research Agent: validate, score, and select a research brief.

The live search (Perplexity / OpenAI web search) returns JSON in the shape
documented in RESEARCH_AGENT.md. This module enforces the editorial rules on
that JSON and produces the brief handed to the Script Agent
(``cinematic_director.plan_reel``). It never fabricates sources or facts.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cinematic_director import STYLES, is_weak_opener
from learning_loop import instructions_block

# BrewIQ's initial editorial experiment, not Instagram algorithm weights.
WEIGHTS: dict[str, float] = {
    "curiosity": 0.25,
    "relatability": 0.20,
    "visual_potential": 0.20,
    "surprise": 0.15,
    "shareability": 0.15,
    "timeliness": 0.05,
}
MIN_SCORE = 7.5
HOOK_APPROACHES = (
    "curiosity_gap",
    "surprising_fact",
    "everyday_problem",
    "future_implication",
    "contrarian",
)
CATEGORIES = ("everyday_life", "robots", "jobs", "scams_privacy", "applied_ai", "breakthrough")
HUMAN_STORY_FIELDS = (
    "surprise",
    "who_is_affected",
    "why_care",
    "everyday_situation",
    "most_compelling_fact",
    "viewer_question",
    "scroll_stop_visual",
)

# Aggregators and social posts are leads, not primary sources.
_SECONDARY_HOSTS = (
    "news.google.",
    "twitter.com",
    "x.com",
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "medium.com",
)
_GENERIC_HOOK = re.compile(
    r"\b(ai is changing (the|our) world|the future is here|game[- ]?changer|"
    r"you won'?t believe|nobody is talking about|mind[- ]?blowing|"
    r"(announces|launches|unveils|introduces) (a |its )?new)\b",
    re.IGNORECASE,
)
_BREAKING = re.compile(r"\b(breaking|just announced|just now)\b", re.IGNORECASE)


def weighted_score(scores: dict[str, Any]) -> float:
    total = 0.0
    for key, weight in WEIGHTS.items():
        value = float(scores.get(key, 0))
        if not 1 <= value <= 10:
            raise ValueError(f"Score `{key}` must be 1–10, got {value}.")
        total += value * weight
    return round(total, 2)


def build_research_prompt(
    today: date,
    recent: list[dict[str, Any]] | None = None,
    learnings: dict[str, Any] | None = None,
) -> str:
    """Prompt for the live-search model. Includes recent reels so it avoids repeats, and the stored learnings."""
    body = (Path(__file__).with_name("RESEARCH_AGENT.md")).read_text(encoding="utf-8")
    lines = [
        body,
        "",
        (
            f"Today is {today.isoformat()}. Last 72 hours = since {(today - timedelta(days=3)).isoformat()}; "
            f"7 days = since {(today - timedelta(days=7)).isoformat()}."
        ),
    ]
    if recent:
        lines.append("Recently published BrewIQ reels — do not repeat these topics, visuals, or hook structures:")
        for item in recent:
            lines.append(
                f"- topic: {item.get('topic', '')} | visual: {item.get('key_visual_moment', '')} "
                f"| hook approach: {item.get('hook_approach', '')}"
            )
    block = instructions_block(learnings)
    if block:
        lines.append(block)
    lines.append("Return only the JSON object.")
    return "\n".join(lines)


def parse_research_response(text: str) -> dict[str, Any]:
    """Extract the JSON object from a model response (tolerates ```json fences)."""
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Research response contained no JSON object.")
    return json.loads(raw[start : end + 1])


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _is_primary_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    return not any(host == bad.rstrip(".") or host.startswith(bad) or host.endswith("." + bad) for bad in _SECONDARY_HOSTS)


def hook_problems(text: str) -> list[str]:
    value = " ".join(str(text or "").split())
    problems: list[str] = []
    words = len(value.split())
    if not value:
        return ["Hook is empty."]
    if words < 4 or words > 15:
        problems.append(f"Hook should be ~6–12 words (got {words}).")
    if is_weak_opener(value):
        problems.append("Hook is a section label or soft intro.")
    if _GENERIC_HOOK.search(value):
        problems.append("Hook is generic, clickbait, or a product-announcement opener.")
    return problems


def validate_candidate(
    candidate: dict[str, Any],
    today: date,
    *,
    source_reachable: Any = None,
) -> list[str]:
    """Return reasons to reject a candidate. Empty list means it passes the gates.

    ``source_reachable`` is an optional ``callable(url) -> bool``; when given,
    an unreachable primary source rejects the story.
    """
    reasons: list[str] = []
    topic = str(candidate.get("topic") or "").strip()
    if not topic:
        reasons.append("Missing topic.")

    url = str(candidate.get("primary_source_url") or "")
    if not _is_primary_url(url):
        reasons.append("No primary-source URL (aggregators and social posts do not count).")
    elif source_reachable is not None and not source_reachable(url):
        reasons.append(f"Primary source not accessible: {url}")

    event = _parse_date(candidate.get("event_date"))
    published = _parse_date(candidate.get("publication_date"))
    if event is None or published is None:
        reasons.append("Event date and publication date must both be recorded (YYYY-MM-DD).")
    else:
        if published > today or event > today:
            reasons.append("Dates are in the future.")
        age = (today - published).days
        freshness = candidate.get("freshness")
        if age > 7 and freshness != "evergreen_new_development":
            reasons.append(f"Published {age} days ago without a new development.")
        if freshness == "last_72h" and age > 3:
            reasons.append(f"Labelled last_72h but published {age} days ago.")
        if age > 3 and _BREAKING.search(" ".join(str(h.get("text", "")) for h in candidate.get("hooks") or [])):
            reasons.append("Older story framed as breaking news.")

    if not candidate.get("verified_facts"):
        reasons.append("No verified facts recorded.")
    if not str(candidate.get("can_do_today") or "").strip():
        reasons.append("Missing what the technology can do today.")
    if not candidate.get("limitations"):
        reasons.append("Limitations not recorded.")
    if "speculative" not in candidate:
        reasons.append("Speculative claims not separated (use [] if none).")

    try:
        score = weighted_score(candidate.get("scores") or {})
    except (TypeError, ValueError) as exc:
        reasons.append(str(exc))
    else:
        if score < MIN_SCORE:
            reasons.append(f"Reel potential {score} is below {MIN_SCORE}.")
    return reasons


def validate_brief_fields(candidate: dict[str, Any]) -> list[str]:
    """Human-story, hook, and handoff fields required for a shortlisted winner."""
    reasons: list[str] = []
    human = candidate.get("human_story") or {}
    missing = [key for key in HUMAN_STORY_FIELDS if not str(human.get(key) or "").strip()]
    if missing:
        reasons.append(f"Human story missing: {', '.join(missing)}.")

    hooks = candidate.get("hooks") or []
    approaches = [str(item.get("approach") or "") for item in hooks]
    if sorted(approaches) != sorted(HOOK_APPROACHES):
        reasons.append(f"Need exactly one hook per approach: {', '.join(HOOK_APPROACHES)}.")
    for item in hooks:
        for problem in hook_problems(item.get("text", "")):
            reasons.append(f"{item.get('approach')}: {problem}")

    index = candidate.get("winning_hook_index")
    if not isinstance(index, int) or not 0 <= index < len(hooks):
        reasons.append("winning_hook_index must point at one of the five hooks.")
    if not str(candidate.get("winning_hook_reason") or "").strip():
        reasons.append("Explain why the winning hook is strongest.")
    for key in ("everyday_angle", "key_visual_moment", "share_reason"):
        if not str(candidate.get(key) or "").strip():
            reasons.append(f"Missing {key}.")
    if candidate.get("suggested_style") not in STYLES:
        reasons.append(f"suggested_style must be one of: {', '.join(STYLES)}.")
    return reasons


def _norm(text: Any) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) > 3}


def repeats_recent(candidate: dict[str, Any], recent: list[dict[str, Any]] | None) -> str:
    """Reason string when the topic or visual overlaps a recent reel, else ''."""
    for item in recent or []:
        for field in ("topic", "key_visual_moment"):
            mine, theirs = _norm(candidate.get(field)), _norm(item.get(field))
            if mine and theirs and len(mine & theirs) / max(1, min(len(mine), len(theirs))) >= 0.6:
                return f"Repeats recent reel {field}: {item.get(field)}"
    return ""


def select_winner(
    research: dict[str, Any],
    today: date,
    *,
    recent: list[dict[str, Any]] | None = None,
    source_reachable: Any = None,
) -> dict[str, Any]:
    """Gate, score, rank top three, and return the winning research brief."""
    candidates = research.get("candidates") or []
    evaluated: list[dict[str, Any]] = []
    for candidate in candidates:
        reasons = validate_candidate(candidate, today, source_reachable=source_reachable)
        repeat = repeats_recent(candidate, recent)
        if repeat:
            reasons.append(repeat)
        try:
            score = weighted_score(candidate.get("scores") or {})
        except (TypeError, ValueError):
            score = 0.0
        evaluated.append({"topic": candidate.get("topic", ""), "score": score, "rejected": reasons, "_c": candidate})

    passing = sorted((e for e in evaluated if not e["rejected"]), key=lambda e: e["score"], reverse=True)
    # A shortlisted story without a complete human story / hooks cannot win.
    shortlisted: list[dict[str, Any]] = []
    for entry in passing:
        problems = validate_brief_fields(entry["_c"])
        if problems:
            entry["rejected"] = problems
        else:
            shortlisted.append(entry)

    summary = [
        {"topic": e["topic"], "score": e["score"], "rejected": e["rejected"]}
        for e in sorted(evaluated, key=lambda e: e["score"], reverse=True)
    ]
    top_three = [{"rank": i + 1, "topic": e["topic"], "score": e["score"]} for i, e in enumerate(shortlisted[:3])]

    if len(candidates) < 10:
        warning = f"Only {len(candidates)} candidates researched; the brief asks for 10."
    else:
        warning = ""

    if not shortlisted:
        return {
            "ok": False,
            "status": "blocked",
            "nothing_posted": True,
            "waiting_on": ["No candidate passed verification and the 7.5 reel-potential bar."],
            "candidates": summary,
            "top_three": [],
            "warning": warning,
            "error": "No publishable research brief.",
        }

    winner = shortlisted[0]
    return {
        "ok": True,
        "status": "brief_ready",
        "nothing_posted": True,
        "brief": build_brief(winner["_c"]),
        "top_three": top_three,
        "candidates": summary,
        "warning": warning,
        "error": "",
    }


def build_brief(candidate: dict[str, Any]) -> dict[str, Any]:
    """The ten-field brief for the Script Agent. No script is written here."""
    hooks = candidate["hooks"]
    winning = hooks[candidate["winning_hook_index"]]
    return {
        "selected_topic": candidate["topic"],
        "source": {
            "primary_source_url": candidate["primary_source_url"],
            "event_date": candidate["event_date"],
            "publication_date": candidate["publication_date"],
            "freshness": candidate.get("freshness", ""),
        },
        "secondary_sources": list(candidate.get("secondary_sources") or []),
        "verified_facts": list(candidate["verified_facts"]),
        "can_do_today": candidate["can_do_today"],
        "limitations": list(candidate["limitations"]),
        "speculative": list(candidate.get("speculative") or []),
        "reel_potential": {
            "scores": dict(candidate["scores"]),
            "weighted": weighted_score(candidate["scores"]),
        },
        "hooks": [{"approach": h["approach"], "text": h["text"]} for h in hooks],
        "winning_hook": {
            "approach": winning["approach"],
            "text": winning["text"],
            "why": candidate["winning_hook_reason"],
        },
        "human_story": dict(candidate["human_story"]),
        "everyday_angle": candidate["everyday_angle"],
        "key_visual_moment": candidate["key_visual_moment"],
        "suggested_style": candidate["suggested_style"],
        "share_reason": candidate["share_reason"],
    }


def brief_to_script_research(brief: dict[str, Any]) -> dict[str, Any]:
    """Map a research brief onto the ``research`` dict ``plan_reel`` consumes."""
    winning = brief["winning_hook"]
    ordered = [winning] + [h for h in brief["hooks"] if h["text"] != winning["text"]]
    facts = brief.get("verified_facts") or []
    return {
        "topic": brief["selected_topic"],
        "headline": brief["human_story"].get("most_compelling_fact", ""),
        "hook": winning["text"],
        "brief_hooks": ordered,
        "point": brief.get("everyday_angle", ""),
        "bullets": facts[:3],
        "verified_facts": facts,
        "viewer_question": brief["human_story"].get("viewer_question", ""),
        "limitations": brief.get("limitations", []),
        "source_url": brief["source"]["primary_source_url"],
        "key_visual_moment": brief.get("key_visual_moment", ""),
        "suggested_style": brief.get("suggested_style", ""),
    }


def format_brief_for_slack(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        lines = ["BrewIQ research blocked — no story passed the gates.", ""]
        for item in result.get("candidates") or []:
            lines.append(f"• {item['topic']} ({item['score']}): {'; '.join(item['rejected'])}")
        lines.append("")
        lines.append("Reply `research again` to widen to 7 days. *Nothing has been posted.*")
        return "\n".join(lines)

    brief = result["brief"]
    lines = ["BrewIQ research brief ready (script not written yet).", ""]
    lines.append("*Top three:*")
    for item in result["top_three"]:
        lines.append(f"{item['rank']}. {item['topic']} — {item['score']}/10")
    lines += [
        "",
        f"*Winner:* {brief['selected_topic']}",
        (
            f"*Source:* {brief['source']['primary_source_url']} "
            f"(event {brief['source']['event_date']}, published {brief['source']['publication_date']})"
        ),
        f"*Reel potential:* {brief['reel_potential']['weighted']}/10",
        f"*Winning hook:* {brief['winning_hook']['text']} — _{brief['winning_hook']['why']}_",
        f"*Everyday angle:* {brief['everyday_angle']}",
        f"*Key visual:* {brief['key_visual_moment']}",
        f"*Suggested style:* `{brief['suggested_style']}`",
        f"*Limitations:* {'; '.join(item.rstrip('.') for item in brief['limitations'])}",
    ]
    if result.get("warning"):
        lines += ["", f"_{result['warning']}_"]
    lines += ["", "Reply `approve brief` to hand off to the Script Agent. *Nothing has been posted.*"]
    return "\n".join(lines)
