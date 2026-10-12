"""BrewIQ learning loop: remember what the weekly review measured and apply it (UC-007, EXP-006).

``performance_agent.review_posts`` measures; this module makes the agent use it:

1. **Memory.** ``weekly_review`` stores the review's learnings in
   ``research_runs/learnings.json`` (committed, so every change is auditable) and the
   outcome per experiment in ``research_runs/<date>.performance.json``.
2. **Apply.** Every plan loads the file. ``instructions_block`` goes into the
   research prompt, ``hook_bonus`` into ``hook_agent.select_from_pool``, the learned
   style into ``cinematic_director.recommend_style``, and ``applied_summary`` into
   the Slack message, so the operator sees what was applied.
3. **Rules.** A signal seen in ``PROMOTE_AFTER`` reviews in a row becomes a rule
   proposal. It changes nothing by itself: a person approves it in Slack, then it
   ships as a PR with a ``DEC-###`` record.

Learnings only adjust scores and recommendations. They never override the accuracy,
clickbait, brand or posting gates, and the operator still picks style and hook.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from performance_agent import LAYOUTS, experiment_record, review_posts

RUNS = Path(__file__).with_name("research_runs")
LEARNINGS_FILE = RUNS / "learnings.json"
PROMOTE_AFTER = 3  # consecutive reviews showing the same signal
STRONG_TECHNIQUE = 0.2  # bonus at or above this counts as a "works" signal
MAX_HISTORY = 26  # about six months of weekly reviews
RULE_STATUSES = ("proposed", "approved", "rejected")

_RULE_CHANGES = {
    "priority": "Make the `{value}` fix a standing rule (DIRECTOR.md and the matching gate), not a weekly reminder.",
    "technique": "Rank `{value}` hooks first by default in HOOK_AGENT.md, instead of relying on the weekly bonus.",
    "format": "Shift the default weekly mix in `weekly_planner` toward `{value}`.",
    "style": "Make `{value}` the default recommended style in `recommend_style` for matching topics.",
    "layout": "Make `{value}` the default explainer opening in the motion-graphics renderer.",
}


def empty_learnings() -> dict[str, Any]:
    return {
        "version": 1,
        "reviewed_on": None,
        "experiments": [],
        "technique_bonus": {},
        "bonus_metric": "",
        "preferred_format": None,
        "preferred_style": None,
        "preferred_layout": None,
        "layout_counts": {},
        "priority_changes": [],
        "history": [],
        "rule_proposals": [],
    }


def load_learnings(path: Path | str | None = None) -> dict[str, Any]:
    """The stored learnings, or empty learnings when nothing has been reviewed yet."""
    file = Path(path or LEARNINGS_FILE)
    if not file.is_file():
        return empty_learnings()
    data = json.loads(file.read_text(encoding="utf-8"))
    return {**empty_learnings(), **data}


def save_learnings(learnings: dict[str, Any], path: Path | str | None = None) -> Path:
    file = Path(path or LEARNINGS_FILE)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(learnings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return file


def _signals(entry: dict[str, Any]) -> set[tuple[str, str]]:
    found = {("priority", area) for area in entry.get("priority_areas") or []}
    found |= {("technique", t) for t in entry.get("strong_techniques") or []}
    if entry.get("preferred_format"):
        found.add(("format", entry["preferred_format"]))
    if entry.get("preferred_style"):
        found.add(("style", entry["preferred_style"]))
    if entry.get("preferred_layout"):
        found.add(("layout", entry["preferred_layout"]))
    return found


def rule_proposals(history: list[dict[str, Any]], previous: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Signals present in each of the last ``PROMOTE_AFTER`` reviews. Keeps a person's approve/reject decision."""
    decided = {p["id"]: p for p in previous or [] if p.get("status") in ("approved", "rejected")}
    recent = history[-PROMOTE_AFTER:]
    proposals = list(decided.values())
    if len(recent) < PROMOTE_AFTER:
        return proposals
    common = set.intersection(*(_signals(e) for e in recent))
    for kind, value in sorted(common):
        rule_id = f"{kind}:{value}"
        if rule_id in decided:
            continue
        proposals.append(
            {
                "id": rule_id,
                "kind": kind,
                "value": value,
                "seen_in": [e["reviewed_on"] for e in recent],
                "status": "proposed",
                "change": _RULE_CHANGES[kind].format(value=value),
                "how": "Approve in Slack with `approve rule <id>`, then ship it as a PR with a DEC-### record.",
            }
        )
    return proposals


def update_learnings(
    previous: dict[str, Any] | None,
    review: dict[str, Any],
    *,
    reviewed_on: str,
    experiments: list[str],
) -> dict[str, Any]:
    """Fold one review into the stored learnings. A review that measured nothing keeps the old values."""
    learned = copy.deepcopy(previous) if previous else empty_learnings()
    measured = review.get("learnings") or {}
    reliable = sum(1 for p in review.get("posts") or [] if p.get("reliable"))
    if measured.get("technique_bonus"):
        learned["technique_bonus"] = dict(measured["technique_bonus"])
        learned["bonus_metric"] = measured.get("bonus_metric", "")
    for key in ("preferred_format", "preferred_style", "preferred_layout"):
        if measured.get(key):
            learned[key] = measured[key]
    counts: dict[str, int] = {}
    for row in review.get("posts") or []:
        layout = str((row.get("labels") or {}).get("layout") or "")
        if layout in LAYOUTS:
            counts[layout] = counts.get(layout, 0) + 1
    if counts:
        learned["layout_counts"] = counts
    learned["priority_changes"] = list(review.get("priority_changes") or [])
    learned["reviewed_on"] = reviewed_on
    learned["experiments"] = sorted(set(experiments))
    learned["history"] = [
        *learned.get("history", []),
        {
            "reviewed_on": reviewed_on,
            "experiments": sorted(set(experiments)),
            "reliable_posts": reliable,
            "priority_areas": [c["area"] for c in review.get("priority_changes") or []],
            "strong_techniques": sorted(k for k, v in (measured.get("technique_bonus") or {}).items() if v >= STRONG_TECHNIQUE),
            "preferred_format": measured.get("preferred_format"),
            "preferred_style": measured.get("preferred_style"),
            "preferred_layout": measured.get("preferred_layout"),
        },
    ][-MAX_HISTORY:]
    learned["rule_proposals"] = rule_proposals(learned["history"], learned.get("rule_proposals"))
    return learned


def set_rule_status(learnings: dict[str, Any], rule_id: str, status: str) -> dict[str, Any]:
    """Record a person's decision on a rule proposal. Approval does not edit any rule by itself."""
    if status not in RULE_STATUSES:
        raise ValueError(f"status must be one of {RULE_STATUSES}")
    updated = copy.deepcopy(learnings)
    for proposal in updated.get("rule_proposals") or []:
        if proposal["id"] == rule_id:
            proposal["status"] = status
            return updated
    raise KeyError(f"No rule proposal {rule_id!r}")


def has_learnings(learnings: dict[str, Any] | None) -> bool:
    learned = learnings or {}
    return bool(learned.get("reviewed_on")) and bool(
        learned.get("technique_bonus")
        or learned.get("priority_changes")
        or learned.get("preferred_style")
        or learned.get("preferred_format")
        or learned.get("preferred_layout")
    )


def hook_bonus(learnings: dict[str, Any] | None) -> dict[str, float]:
    return dict((learnings or {}).get("technique_bonus") or {}) if has_learnings(learnings) else {}


def preferred_style(learnings: dict[str, Any] | None) -> str | None:
    return (learnings or {}).get("preferred_style") if has_learnings(learnings) else None


def next_layout(learnings: dict[str, Any] | None) -> str:
    """The explainer opening to use next.

    A measured winner is reused until it is two posts ahead of the least-used layout,
    then the least-used layout is tried so the next review can compare them.
    With no measurement yet, the opening is a step rail.
    """
    learned = learnings or {}
    counts = {name: int((learned.get("layout_counts") or {}).get(name) or 0) for name in LAYOUTS}
    preferred = learned.get("preferred_layout") if has_learnings(learned) and learned.get("preferred_layout") in LAYOUTS else None
    if any(counts.values()):
        least = min(LAYOUTS, key=lambda name: (counts[name], name))
        leader = preferred or max(LAYOUTS, key=lambda name: (counts[name], name))
        if counts[leader] >= counts[least] + 2:
            return least
        if preferred:
            return preferred
    return preferred or "rail"


def _source(learnings: dict[str, Any]) -> str:
    experiments = ", ".join(learnings.get("experiments") or []) or "no experiment"
    return f"review {learnings.get('reviewed_on')}, {experiments}"


def applied_summary(learnings: dict[str, Any] | None) -> list[str]:
    """One line per learning the next plan uses, for Slack and the plan record."""
    if not has_learnings(learnings):
        return []
    learned = learnings or {}
    lines = [f"Fix {c['area']}: {c['change']}" for c in learned.get("priority_changes") or []]
    bonus = learned.get("technique_bonus") or {}
    better = [f"{k} ({v:+.2f})" for k, v in sorted(bonus.items(), key=lambda kv: -kv[1]) if v > 0]
    worse = [f"{k} ({v:+.2f})" for k, v in sorted(bonus.items(), key=lambda kv: kv[1]) if v < 0]
    if better or worse:
        lines.append(
            "Hook ranking bonus"
            + (f" on {learned['bonus_metric']}" if learned.get("bonus_metric") else "")
            + ": "
            + "; ".join(part for part in (", ".join(better), ", ".join(worse)) if part)
        )
    if learned.get("preferred_style"):
        lines.append(f"Recommended style: `{learned['preferred_style']}` (you still pick).")
    if learned.get("preferred_format"):
        lines.append(f"Format leading on sends: `{learned['preferred_format']}`.")
    if learned.get("preferred_layout"):
        lines.append(f"Explainer opening layout: `{learned['preferred_layout']}` (next plan uses `{next_layout(learned)}`).")
    return [f"{line} [{_source(learned)}; directional]" for line in lines]


def instructions_block(learnings: dict[str, Any] | None) -> str:
    """Text added to the research and planning prompts. Empty when there is nothing measured."""
    lines = applied_summary(learnings)
    if not lines:
        return ""
    return "\n".join(
        [
            "LEARNINGS FROM THE LAST PERFORMANCE REVIEW (directional; never override accuracy, clickbait or brand rules):",
            *(f"- {line}" for line in lines),
        ]
    )


def weekly_review(
    posts: list[dict[str, Any]],
    *,
    reviewed_on: str,
    learnings_path: Path | str | None = None,
    runs_dir: Path | str | None = None,
    previous: dict[str, Any] | None = None,
    decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The weekly job: review, update learnings, record each experiment, and write files when paths are given."""
    review = review_posts(posts)
    if not review.get("ok"):
        return {**review, "slack": format_weekly_review({"ok": False, **review})}
    experiments = sorted({str(p["experiment"]) for p in posts})
    base = previous if previous is not None else load_learnings(learnings_path)
    learned = update_learnings(base, review, reviewed_on=reviewed_on, experiments=experiments)
    records = {exp: experiment_record(review, exp, decision=(decisions or {}).get(exp, "")) for exp in experiments}
    written: list[str] = []
    if learnings_path is not None:
        written.append(str(save_learnings(learned, learnings_path)))
    if runs_dir is not None:
        out = Path(runs_dir) / f"{reviewed_on}.performance.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"review": review, "records": records}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(str(out))
    result = {"ok": True, "status": "reviewed", "review": review, "learnings": learned, "records": records, "written": written}
    result["slack"] = format_weekly_review(result)
    return result


def format_weekly_review(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return "\n".join(
            ["BrewIQ weekly review blocked.", *(f"• {p}" for p in result.get("problems") or []), "*Nothing has been changed.*"]
        )
    review, learned = result["review"], result["learnings"]
    lines = [f"*BrewIQ weekly review* ({learned['reviewed_on']}; {', '.join(learned['experiments'])})", "", "*What we can conclude:*"]
    lines += [f"• {c}" for c in review.get("conclusions") or []] or ["• Nothing yet."]
    lines += ["", "*What we can't know yet:*", *(f"• {u}" for u in review.get("unknowns") or [])]
    lines += ["", "*Three changes for next week:*"]
    lines += [f"{i}. {c['area']}: {c['change']} ({c['evidence']})" for i, c in enumerate(review.get("priority_changes") or [], start=1)] or ["• None."]
    applied = applied_summary(learned)
    lines += ["", "*Applied automatically to the next plans:*", *(f"• {a}" for a in applied)] if applied else []
    proposals = [p for p in learned.get("rule_proposals") or [] if p["status"] == "proposed"]
    if proposals:
        lines += ["", f"*Rule proposals (same result {PROMOTE_AFTER} reviews in a row; need your approval):*"]
        lines += [f"• `{p['id']}`: {p['change']} Reply `approve rule {p['id']}` or `reject rule {p['id']}`." for p in proposals]
    lines.append("*Nothing has been posted.*")
    return "\n".join(lines)
