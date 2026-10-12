"""Slack-facing helpers for the BrewIQ cinematic director.

The aegis-agent-platform Slack host should call these instead of jumping
straight into Veo and posting a dead-end Waiting-on list.
"""

from __future__ import annotations

import re
from typing import Any

from cinematic_director import STYLES, apply_recovery, plan_reel, recovery_options
from utility_carousel import MAX_ITEMS, MIN_ITEMS, plan_utility_carousel

_STYLE = re.compile(r"\bstyle\s*=\s*([a-z0-9_]+)", re.IGNORECASE)
_STYLE_NUMBER = re.compile(r"\b(?:style|option)\s*[=#:]?\s*([1-4])\b", re.IGNORECASE)
_HOOK = re.compile(r"\bhook\s*[=#:_ ]?\s*(?:hook_)?([1-5])\b", re.IGNORECASE)
_RECOVERY = re.compile(r"\brecovery\s*=\s*([a-z0-9_]+)", re.IGNORECASE)

# Keywords only choose the style. The hook choice and every later gate still run.
STYLE_KEYWORDS: dict[str, re.Pattern[str]] = {
    "cinematic_3d": re.compile(r"(#cinematic\b|\bcinematic(?:[ _-]?3d)?\b|\b3d reel\b)", re.IGNORECASE),
    "interactive_explainer": re.compile(r"(#explainer\b|\bexplainer\b)", re.IGNORECASE),
    "tech_storytelling": re.compile(r"(#story(?:telling)?\b|\btech[ _-]?story(?:telling)?\b|\bstorytelling\b)", re.IGNORECASE),
    "motion_graphics": re.compile(r"(#motion\b|\bmotion[ _-]?graphics\b)", re.IGNORECASE),
}
UTILITY_KEYWORDS = re.compile(r"(#prompts\b|\bprompt[ _-]?pack\b|\butility[ _-]?carousel\b)", re.IGNORECASE)
_FILLER = re.compile(r"^\W*(?:(?:make|create|do|start|build|a|an|the|brewiq|reel|video|please)\b\W*)*(?:about|on|for)?\W*", re.IGNORECASE)


def keyword_style(text: str) -> str | None:
    """The style named by the earliest keyword in ``text`` (e.g. "explainer"), or None."""
    hits = [(m.start(), style) for style, pattern in STYLE_KEYWORDS.items() if (m := pattern.search(text or ""))]
    return min(hits)[1] if hits else None


def topic_from_request(text: str) -> str:
    """The topic left after removing style keywords and picks: "explainer: NotebookLM quizzes" -> "NotebookLM quizzes"."""
    value = str(text or "")
    for pattern in (*STYLE_KEYWORDS.values(), UTILITY_KEYWORDS, _STYLE, _STYLE_NUMBER, _HOOK, _RECOVERY):
        value = pattern.sub(" ", value)
    value = _FILLER.sub("", " ".join(value.split()))
    return value.strip(" :-—,.")


def parse_operator_reply(text: str) -> dict[str, str]:
    message = text or ""
    found: dict[str, str] = {}
    style = _STYLE.search(message)
    number = _STYLE_NUMBER.search(message)
    hook = _HOOK.search(message)
    recovery = _RECOVERY.search(message)
    if style and not style.group(1).isdigit():
        found["style"] = style.group(1).lower()
    elif number:
        found["style"] = list(STYLES)[int(number.group(1)) - 1]
    elif keyword := keyword_style(message):
        found["style"] = keyword
    if hook:
        found["hook_id"] = f"hook_{hook.group(1)}"
    if recovery:
        found["recovery"] = recovery.group(1).lower()
    return found


def thread_picks(messages: list[str]) -> dict[str, str]:
    """Merge picks across a Slack thread, oldest first; a later message overrides an earlier one."""
    picks: dict[str, str] = {}
    for message in messages:
        picks.update(parse_operator_reply(message))
    return picks


def start_or_continue(
    topic: str,
    *,
    research: dict | None = None,
    operator_reply: str = "",
    prior_errors: list[str] | None = None,
    thread: list[str] | None = None,
    learnings: dict | None = None,
) -> dict[str, Any]:
    """One entry point for Slack: plan, continue after a pick, or offer recovery.

    ``thread`` is the earlier messages in the Slack thread (oldest first), so a style
    chosen by keyword in the first message is kept while the operator picks the hook.
    ``learnings`` is ``learning_loop.load_learnings()``; the host loads it on every request.
    """
    messages = [*(thread or []), operator_reply]
    if any(UTILITY_KEYWORDS.search(m or "") for m in messages):
        return _utility_request(topic or topic_from_request(messages[0]), research, learnings)
    picks = thread_picks(messages)
    current = parse_operator_reply(operator_reply)
    if current.get("recovery"):
        return apply_recovery(current["recovery"], topic, research)
    picks.pop("recovery", None)
    if prior_errors and not (picks.get("style") and picks.get("hook_id")):
        # Still blocked from a prior render attempt — ask recovery unless they also sent style+hook.
        if not current:
            return recovery_options(*prior_errors)
    topic = topic or topic_from_request((thread or [operator_reply])[0])
    return plan_reel(
        topic,
        research=research,
        style=picks.get("style"),
        hook_id=picks.get("hook_id"),
        learnings=learnings,
    )


_RULE_REPLY = re.compile(r"\b(approve|reject)\s+rule\s+([a-z_]+:[a-z0-9_]+)\b", re.IGNORECASE)


def parse_rule_reply(text: str) -> tuple[str, str] | None:
    """``approve rule technique:curiosity_gap`` -> ("approved", "technique:curiosity_gap")."""
    match = _RULE_REPLY.search(text or "")
    if not match:
        return None
    return ("approved" if match.group(1).lower() == "approve" else "rejected"), match.group(2).lower()


def _learned_lines(payload: dict[str, Any]) -> list[str]:
    applied = payload.get("learnings_applied") or []
    return ["", "*Applied from the last review:*", *(f"• {line}" for line in applied)] if applied else []


def _cover_from_hook(text: str) -> str:
    words = re.sub(r"[?!.]", "", str(text or "")).split()
    if 2 <= len(words) <= 6:
        return " ".join(words)
    return ""


def _utility_request(topic: str, research: dict | None, learnings: dict | None = None) -> dict[str, Any]:
    """Prompt-pack carousel. The cover hook comes from research; the operator still writes the prompts."""
    from hook_agent import best_hook_for_post

    spec = dict((research or {}).get("utility_carousel") or {})
    picked = best_hook_for_post(research, "utility_carousel", learnings)
    hook_line = ""
    if picked:
        cover = _cover_from_hook(picked["text"])
        if cover and not spec.get("cover_headline"):
            spec["cover_headline"] = cover
        hook_line = (
            f" Research hook for this prompt pack: \"{picked['text']}\""
            + (f" ({picked['approach']})." if picked.get("approach") else ".")
            + (" That line is the cover." if cover else " Write a 2–6 word cover_headline that keeps this idea.")
        )
    if not spec.get("items"):
        return {
            "ok": False,
            "status": "awaiting_content",
            "format": "utility_carousel",
            "topic": topic,
            "nothing_posted": True,
            "hook": picked,
            "prompt": (
                f"Prompt pack for: {topic}.{hook_line} Send {MIN_ITEMS}–{MAX_ITEMS} items as research.utility_carousel.items "
                "[{title ≤6 words, benefit ≤12 words, prompt ≤70 words with [PLACEHOLDERS]}], plus cover_headline "
                "(2–6 words), cover_visual, save_reason, share_reason, closing_line and search_keywords. "
                "Adapt other creators' formats; don't copy their prompts."
            ),
        }
    plan = plan_utility_carousel(topic, spec.pop("items"), **spec)
    if picked:
        plan["hook"] = {
            "text": picked["text"],
            "approach": picked["approach"],
            "why": picked["why"],
            "source": "research",
            "post_type": "utility_carousel",
        }
    return plan


def format_slack_message(payload: dict[str, Any]) -> str:
    """Plain-text Slack body (Block Kit can wrap the same options later)."""
    status = payload.get("status")
    lines: list[str] = []
    if status == "awaiting_choice":
        lines.append("Starting a BrewIQ reel — pick options before generation.")
        lines.append(f"*Topic:* {payload.get('topic') or ''}")
        lines.append("")
        chosen = payload.get("chosen_style")
        if chosen:
            lines.append(f"*Style:* {STYLES[chosen]['label']} (`{chosen}`), from your message.")
        else:
            lines.append("*Styles:*")
            for number, style in enumerate(payload.get("options", {}).get("styles") or [], start=1):
                mark = " (recommended)" if style["id"] == payload["options"].get("recommended_style") else ""
                lines.append(f"{number}. `{style['id']}` — {style['label']}{mark}: {style['description']}")
        lines.append("")
        by_type = (payload.get("options") or {}).get("hooks_for_style") or []
        if by_type:
            lines.append("*Research hook for each post type:*")
            for item in by_type:
                approach = f" ({item['approach']})" if item.get("approach") else ""
                lines.append(f"• {item['label']}: {item['text']}{approach}")
            lines.append("Pick a style. That post type's research hook is used. Reply `hook 2` only to override it.")
        else:
            lines.append("*Hooks:*")
            for hook in payload.get("options", {}).get("hooks") or []:
                lines.append(f"• `{hook['id']}` (rank {hook['rank']}): {hook['text']}")
                lines.append(f"  _{hook['why']}_")
        lines += _learned_lines(payload)
        lines.append("")
        lines.append(payload.get("prompt") or "")
        lines.append("*Nothing has been posted.*")
        return "\n".join(lines)

    if status == "blocked":
        lines.append("BrewIQ reel blocked.")
        lines.append("")
        lines.append("*Waiting on:*")
        for item in payload.get("waiting_on") or []:
            lines.append(f"• {item}")
        lines.append("")
        lines.append("*Options:*")
        for item in payload.get("options", {}).get("recovery") or []:
            lines.append(f"• `{item['id']}` — {item['label']}")
        lines.append("")
        lines.append(payload.get("prompt") or "")
        lines.append("*Nothing has been posted.*")
        return "\n".join(lines)

    if payload.get("format") == "utility_carousel":
        if status == "awaiting_content":
            return f"{payload['prompt']}\n*Nothing has been posted.*"
        lines.append(f"BrewIQ prompt pack {'ready' if payload.get('ok') else 'blocked'} (not posted): {payload.get('topic')}")
        for slide in payload.get("slides") or []:
            if slide["role"] == "prompt":
                lines.append(f"{slide['index']}. *{slide['title']}* — {slide['benefit']}")
        for item in payload.get("problems") or []:
            lines.append(f"• Needs fix: {item}")
        hook = payload.get("hook") or {}
        if hook.get("text"):
            lines.append(f"*Hook:* {hook['text']} — chosen from research for this prompt pack.")
        if payload.get("ok"):
            lines.append("Reply `post it` only after the rendered slides are approved.")
        lines.append("*Nothing has been posted.*")
        return "\n".join(lines)

    if status == "planned":
        style = payload.get("style") or {}
        hook = payload.get("hook") or {}
        lines.append("BrewIQ reel plan ready (not posted).")
        lines.append(f"*Style:* {style.get('label')} (`{style.get('id')}`)")
        hook_line = f"*Hook:* {hook.get('text')}"
        if hook.get("source") == "research":
            hook_line += " — chosen from research for this style."
        lines.append(hook_line)
        lines.append(f"*Scenes:* {len(payload.get('scenes') or [])}")
        lines.append(f"*Pipeline:* {style.get('pipeline')}")
        lines += _learned_lines(payload)
        lines.append("")
        lines.append("Reply `post it` only after the rendered draft is approved.")
        lines.append("*Nothing has been posted.*")
        return "\n".join(lines)

    if status == "redirect":
        lines.append(f"Redirecting to `{payload.get('format')}` for topic: {payload.get('topic')}.")
        for slide in (payload.get("slides") or {}).get("slides") or []:
            lines.append(f"{slide['index']}. *{slide['role']}* ({slide['frame']}): {slide['headline']['text']}")
        for item in payload.get("waiting_on") or []:
            lines.append(f"• Needs fix: {item}")
        lines.append("*Nothing has been posted.*")
        return "\n".join(lines)

    return payload.get("prompt") or payload.get("error") or "Nothing has been posted."
