"""BrewIQ weekly test planner: plan the week's posts as experiments (UC-008, EXP-006).

Each post gets an ``EXP-###``, the hypothesis it tests, one primary metric and the
labels the performance review groups by (format, style, hook technique). Half the
week uses what the last review learned ("exploit"); the rest deliberately tries
something else ("explore"), so the agent keeps learning instead of repeating
itself. After publishing, ``post_labels(slot)`` goes into
``performance_agent.from_graph_insights`` so results land on the right experiment.

Planning a slot does not skip any step: each reel still goes through research,
the hook choice, the script and the director gates, and nothing is posted without
``post it``.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from hook_agent import POOL_TECHNIQUES
from learning_loop import has_learnings, hook_bonus, preferred_style
from performance_agent import RATE_LABELS, RATES

MIN_POSTS, MAX_POSTS = 5, 7
FORMATS = ("reel", "utility_carousel")
REEL_STYLES = ("cinematic_3d", "interactive_explainer", "tech_storytelling", "motion_graphics")
MIN_FORMATS = 2
MIN_TECHNIQUES = 3
MIN_EXPLORE = 2

# experiment -> (hypothesis, primary metric)
EXPERIMENTS = {
    "EXP-003": ("PH-001", "send_rate"),
    "EXP-004": ("PH-002", "hold_3s"),
    "EXP-006": ("PH-004", "send_rate"),
}


def _techniques(learnings: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """(techniques that measured above average, best first; techniques to try: untested, then weaker)."""
    bonus = hook_bonus(learnings)
    better = sorted((t for t in bonus if t in POOL_TECHNIQUES and bonus[t] > 0), key=lambda t: -bonus[t])
    untested = [t for t in POOL_TECHNIQUES if t not in bonus]
    weaker = sorted((t for t in bonus if t in POOL_TECHNIQUES and bonus[t] <= 0), key=lambda t: -bonus[t])
    return better, untested + weaker


def _topic(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return {"topic": str(candidate.get("topic") or "").strip(), "formats": tuple(candidate.get("formats") or FORMATS)}
    return {"topic": str(candidate or "").strip(), "formats": FORMATS}


def _carousel_days(posts: int, count: int) -> set[int]:
    return {round((k + 1) * posts / (count + 1)) - 1 for k in range(count)}


def plan_week(
    candidates: list[Any],
    *,
    week_of: date,
    learnings: dict[str, Any] | None = None,
    posts: int = MIN_POSTS,
) -> dict[str, Any]:
    """Plan ``posts`` slots from candidate topics (strings or {topic, formats}).

    Two utility carousels a week (three when the last review found they lead on
    sends); the rest are reels. With learnings, reels alternate between applying
    them (EXP-006) and trying an untested or weaker hook technique in another style
    (EXP-004). Without learnings, every slot is a baseline that rotates technique
    and style.
    """
    posts = max(MIN_POSTS, min(MAX_POSTS, int(posts)))
    learned = has_learnings(learnings)
    style_first = preferred_style(learnings)
    styles = [style_first, *[s for s in REEL_STYLES if s != style_first]] if style_first in REEL_STYLES else list(REEL_STYLES)
    better, to_try = _techniques(learnings)
    carousel_leads = learned and (learnings or {}).get("preferred_format") == "utility_carousel"
    carousels = _carousel_days(posts, min(posts // 2, 3 if carousel_leads else 2))

    topics = [t for t in (_topic(c) for c in candidates) if t["topic"]]
    slots: list[dict[str, Any]] = []
    reel_k = carousel_k = 0
    for index in range(posts):
        topic = topics[index] if index < len(topics) else {"topic": "", "formats": FORMATS}
        wants_carousel = index in carousels
        fmt = "utility_carousel" if wants_carousel and "utility_carousel" in topic["formats"] else "reel"
        if fmt == "reel" and "reel" not in topic["formats"]:
            fmt = topic["formats"][0]
        if fmt == "utility_carousel":
            role = "baseline" if not learned else ("exploit" if carousel_leads else "explore")
            technique = POOL_TECHNIQUES[(carousel_k * 3 + 8) % len(POOL_TECHNIQUES)]
            style, experiment = None, "EXP-003"
            carousel_k += 1
        elif not learned:
            role, experiment = "baseline", "EXP-004"
            technique = POOL_TECHNIQUES[reel_k % len(POOL_TECHNIQUES)]
            style = styles[reel_k % len(styles)]
            reel_k += 1
        elif reel_k % 2 == 0 and better:
            role, experiment = "exploit", "EXP-006"
            technique = better[(reel_k // 2) % len(better)]
            style = styles[0]
            reel_k += 1
        else:
            role, experiment = "explore", "EXP-004"
            technique = to_try[(reel_k // 2) % len(to_try)]
            style = styles[1 + (reel_k // 2) % (len(styles) - 1)]
            reel_k += 1
        hypothesis, metric = EXPERIMENTS[experiment]
        slots.append(
            {
                "day": (week_of + timedelta(days=index)).isoformat(),
                "topic": topic["topic"],
                "format": fmt,
                "style": style,
                "hook_technique": technique,
                "experiment": experiment,
                "hypothesis": hypothesis,
                "primary_metric": metric,
                "role": role,
                "test": _test_line(fmt, style, technique, metric, role),
            }
        )
    if learned:
        exploit_reels = [s for s in slots if s["role"] == "exploit" and s["format"] == "reel"]
        while sum(s["role"] == "explore" for s in slots) < MIN_EXPLORE and len(exploit_reels) > 1:
            slot = exploit_reels.pop()
            used_techniques = {s["hook_technique"] for s in slots}
            used_styles = {s["style"] for s in slots if s["role"] == "explore"}
            technique = next((t for t in to_try if t not in used_techniques), to_try[0])
            style = next((s for s in styles[1:] if s not in used_styles), styles[1])
            hypothesis, metric = EXPERIMENTS["EXP-004"]
            slot.update(
                role="explore", experiment="EXP-004", hypothesis=hypothesis, primary_metric=metric,
                hook_technique=technique, style=style, test=_test_line("reel", style, technique, metric, "explore"),
            )
    plan = {
        "ok": True,
        "week_of": week_of.isoformat(),
        "uses_learnings": learned,
        "learned_from": (learnings or {}).get("reviewed_on") if learned else None,
        "slots": slots,
        "steps": (
            "Each slot still runs research, the hook choice, the script and every director gate; "
            "nothing is posted without `post it`."
        ),
    }
    plan["problems"] = week_problems(plan)
    plan["ok"] = not plan["problems"]
    return plan


def _test_line(fmt: str, style: str | None, technique: str, metric: str, role: str) -> str:
    what = f"a `{technique}` hook on a {fmt}" + (f" in `{style}`" if style else "")
    why = {
        "exploit": "applies what the last review measured",
        "explore": "tries something the review hasn't measured or ranked lower",
        "baseline": "sets the baseline before any learnings exist",
    }[role]
    if fmt == "utility_carousel" and role == "exploit":
        why = "repeats the format the last review found leads on sends"
    return f"Does {what} beat the account median on {RATE_LABELS[metric]}? ({why})"


def week_problems(plan: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    slots = plan.get("slots") or []
    if not MIN_POSTS <= len(slots) <= MAX_POSTS:
        problems.append(f"Plan {MIN_POSTS}–{MAX_POSTS} posts, got {len(slots)}.")
    for slot in slots:
        tag = f"{slot.get('day')}"
        if not slot.get("topic"):
            problems.append(f"{tag}: needs a topic (add more candidates).")
        if slot.get("experiment") not in EXPERIMENTS:
            problems.append(f"{tag}: needs a known experiment ID.")
        elif slot.get("hypothesis") != EXPERIMENTS[slot["experiment"]][0]:
            problems.append(f"{tag}: hypothesis does not match {slot['experiment']}.")
        if slot.get("primary_metric") not in RATES:
            problems.append(f"{tag}: primary metric must be one of {', '.join(RATES)}.")
        if slot.get("format") == "reel" and slot.get("style") not in REEL_STYLES:
            problems.append(f"{tag}: a reel needs a style.")
        if slot.get("hook_technique") not in POOL_TECHNIQUES:
            problems.append(f"{tag}: unknown hook technique.")
    topics = [s.get("topic") for s in slots if s.get("topic")]
    if len(set(topics)) != len(topics):
        problems.append("The same topic appears twice in one week.")
    if len({s.get("format") for s in slots}) < MIN_FORMATS:
        problems.append(f"Vary the format: use at least {MIN_FORMATS}.")
    if len({s.get("hook_technique") for s in slots}) < MIN_TECHNIQUES:
        problems.append(f"Vary the hook technique: use at least {MIN_TECHNIQUES}.")
    if plan.get("uses_learnings") and sum(s.get("role") == "explore" for s in slots) < MIN_EXPLORE:
        problems.append(f"Keep at least {MIN_EXPLORE} explore slots so the agent keeps learning.")
    for a, b in pairwise(slots):
        if (a.get("format"), a.get("style"), a.get("hook_technique")) == (b.get("format"), b.get("style"), b.get("hook_technique")):
            problems.append(f"{a.get('day')} and {b.get('day')} test the same thing twice in a row.")
    return problems


def post_labels(slot: dict[str, Any]) -> dict[str, Any]:
    """Labels for ``performance_agent.from_graph_insights`` once the slot is published."""
    labels = {"experiment": slot["experiment"], "format": slot["format"], "hook_technique": slot["hook_technique"]}
    if slot.get("style"):
        labels["style"] = slot["style"]
    return labels


def format_week_for_slack(plan: dict[str, Any]) -> str:
    source = f"learnings from {plan['learned_from']}" if plan.get("uses_learnings") else "no learnings yet (baseline week)"
    lines = [f"*BrewIQ test plan, week of {plan['week_of']}* ({source})", ""]
    for slot in plan.get("slots") or []:
        style = f" · `{slot['style']}`" if slot.get("style") else ""
        lines.append(
            f"• {slot['day']} — {slot['topic'] or '(needs a topic)'}: {slot['format']}{style} · `{slot['hook_technique']}` hook "
            f"· {slot['experiment']}/{slot['hypothesis']} · metric: {RATE_LABELS[slot['primary_metric']]} · {slot['role']}"
        )
    if plan.get("problems"):
        lines += ["", "*Fix before starting:*", *(f"• {p}" for p in plan["problems"])]
    lines += ["", plan.get("steps") or "", "*Nothing has been posted.*"]
    return "\n".join(lines)
