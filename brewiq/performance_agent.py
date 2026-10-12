"""BrewIQ Performance Agent: learn from published posts (UC-004, EXP-005).

Takes per-post Instagram metrics (from the Graph API insights endpoint or entered
from the in-app insights screen), compares each post with the account's own
median, says what can and cannot be concluded from the sample, names the three
highest-priority changes, and returns measured learnings that feed hook ranking
(``hook_agent.select_from_pool(technique_bonus=...)``) and format choice.

Nothing here posts or changes a live account. Every post must carry the experiment
it belongs to, so results are recorded against an ``EXP-###`` instead of chat.
"""

from __future__ import annotations

import re
from statistics import mean, median
from typing import Any

RATES = ("hold_3s", "watch_ratio", "save_rate", "send_rate", "comment_rate", "follow_rate", "like_rate")
RATE_LABELS = {
    "hold_3s": "3-second hold",
    "watch_ratio": "average watch / length",
    "save_rate": "saves per reach",
    "send_rate": "sends per reach",
    "comment_rate": "comments per reach",
    "follow_rate": "follows per reach",
    "like_rate": "likes per reach",
}
GROUP_BY = ("format", "style", "hook_technique", "layout")
LAYOUTS = ("rail", "split", "board", "clock", "card")
MIN_REACH = 300  # below this a single post's rates are noise
MIN_POSTS = 3  # fewer posts than this and there is no baseline
MIN_GROUP_POSTS = 2  # a group needs this many posts before it can be compared
STRONG = 1.25  # x the median
WEAK = 0.8
MAX_BONUS = 0.5
_EXPERIMENT = re.compile(r"^EXP-\d{3}$")

# Graph API media insights metric names -> BrewIQ fields.
GRAPH_METRICS = {
    "reach": "reach",
    "views": "views",
    "saved": "saves",
    "shares": "sends",
    "likes": "likes",
    "comments": "comments",
    "follows": "follows",
    "profile_visits": "profile_visits",
}


def from_graph_insights(media: dict[str, Any], insights: dict[str, Any], **labels: Any) -> dict[str, Any]:
    """Build a post record from ``/{media-id}`` fields and ``/{media-id}/insights`` values.

    ``ig_reels_avg_watch_time`` is in milliseconds. The 3-second hold is not in the
    API; pass ``hold_3s`` (0–1) from the in-app insights screen when you have it.
    """
    metrics = {field: insights[name] for name, field in GRAPH_METRICS.items() if name in insights}
    if media.get("like_count") is not None and "likes" not in metrics:
        metrics["likes"] = media["like_count"]
    if "ig_reels_avg_watch_time" in insights:
        metrics["avg_watch_seconds"] = round(float(insights["ig_reels_avg_watch_time"]) / 1000, 2)
    if labels.get("hold_3s") is not None:
        metrics["hold_3s"] = labels.pop("hold_3s")
    media_type = str(media.get("media_product_type") or media.get("media_type") or "").upper()
    default_format = "reel" if media_type in ("REELS", "VIDEO") else "carousel" if "CAROUSEL" in media_type else "post"
    return {
        "post_id": str(media.get("id") or ""),
        "published": str(media.get("timestamp") or "")[:10],
        "format": labels.pop("format", default_format),
        "metrics": metrics,
        **labels,
    }


def post_rates(post: dict[str, Any]) -> dict[str, float | None]:
    m = post.get("metrics") or {}
    reach = float(m.get("reach") or 0)

    def per_reach(key: str) -> float | None:
        return round(float(m[key]) / reach, 4) if reach and m.get(key) is not None else None

    duration = float(post.get("duration_seconds") or m.get("duration_seconds") or 0)
    watch = m.get("avg_watch_seconds")
    return {
        "hold_3s": round(float(m["hold_3s"]), 4) if m.get("hold_3s") is not None else None,
        "watch_ratio": round(float(watch) / duration, 4) if watch is not None and duration else None,
        "save_rate": per_reach("saves"),
        "send_rate": per_reach("sends"),
        "comment_rate": per_reach("comments"),
        "follow_rate": per_reach("follows"),
        "like_rate": per_reach("likes"),
    }


def record_problems(posts: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for index, post in enumerate(posts, start=1):
        tag = post.get("post_id") or f"post {index}"
        if not post.get("post_id"):
            problems.append(f"{tag}: missing post_id.")
        elif post["post_id"] in seen:
            problems.append(f"{tag}: duplicate post_id.")
        seen.add(str(post.get("post_id")))
        if not _EXPERIMENT.match(str(post.get("experiment") or "")):
            problems.append(f"{tag}: needs an experiment ID (EXP-###) so the result is recorded.")
        if not (post.get("metrics") or {}).get("reach"):
            problems.append(f"{tag}: missing reach.")
        for key in ("format", "hook_technique"):
            if not post.get(key):
                problems.append(f"{tag}: missing {key}.")
    return problems


def _baseline(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for rate in RATES:
        values = [r["rates"][rate] for r in rows if r["rates"][rate] is not None]
        out[rate] = round(median(values), 4) if len(values) >= MIN_POSTS else None
    return out


def review_posts(posts: list[dict[str, Any]], *, min_reach: int = MIN_REACH) -> dict[str, Any]:
    """Compare posts with the account median and say what the sample does and doesn't show."""
    problems = record_problems(posts)
    if problems:
        return {"ok": False, "status": "blocked", "problems": problems}

    rows = [
        {
            "post_id": p["post_id"],
            "experiment": p["experiment"],
            "reach": int(p["metrics"]["reach"]),
            "reliable": int(p["metrics"]["reach"]) >= min_reach,
            "labels": {k: p.get(k) for k in GROUP_BY},
            "hook_text": p.get("hook_text", ""),
            "rates": post_rates(p),
        }
        for p in posts
    ]
    reliable = [r for r in rows if r["reliable"]]
    baseline = _baseline(reliable)
    for row in rows:
        row["strengths"], row["weaknesses"] = [], []
        if not row["reliable"]:
            continue
        for rate in RATES:
            value, base = row["rates"][rate], baseline[rate]
            if value is None or not base:
                continue
            if value >= base * STRONG:
                row["strengths"].append(rate)
            elif value <= base * WEAK:
                row["weaknesses"].append(rate)

    # Style and hook technique are only compared within one format ("reel/curiosity_gap"),
    # so a carousel's high send rate can't be credited to the hook technique it used.
    groups: dict[str, dict[str, Any]] = {}
    for dimension in GROUP_BY:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in reliable:
            if row["labels"].get(dimension):
                name = str(row["labels"][dimension])
                key = name if dimension == "format" else f"{row['labels']['format']}/{name}"
                buckets.setdefault(key, []).append(row)
        groups[dimension] = {
            name: {
                "posts": len(items),
                "comparable": len(items) >= MIN_GROUP_POSTS,
                **{
                    rate: round(mean(vals), 4)
                    for rate in RATES
                    if (vals := [i["rates"][rate] for i in items if i["rates"][rate] is not None])
                },
            }
            for name, items in sorted(buckets.items())
        }

    conclusions, unknowns = _conclusions(rows, reliable, baseline, groups)
    review = {
        "ok": True,
        "status": "reviewed",
        "posts": rows,
        "baseline": baseline,
        "groups": groups,
        "conclusions": conclusions,
        "unknowns": unknowns,
    }
    review["priority_changes"] = priority_changes(review)
    review["learnings"] = learnings(review)
    return review


def _conclusions(rows, reliable, baseline, groups) -> tuple[list[str], list[str]]:
    conclusions: list[str] = []
    unknowns: list[str] = []
    thin = [r["post_id"] for r in rows if not r["reliable"]]
    if thin:
        unknowns.append(f"Reach under {MIN_REACH} on {', '.join(thin)}; their rates are not used.")
    if len(reliable) < MIN_POSTS:
        unknowns.append(f"Only {len(reliable)} post(s) with enough reach; need {MIN_POSTS} for a baseline.")
        return conclusions, unknowns
    for rate in RATES:
        if baseline[rate] is None:
            unknowns.append(f"No {RATE_LABELS[rate]} data on enough posts.")
    for dimension, buckets in groups.items():
        for comparable, total in _partitions(buckets):
            if len(comparable) < 2:
                if total > 1:
                    unknowns.append(f"Not enough posts per {dimension} to compare ({MIN_GROUP_POSTS}+ each needed).")
                continue
            conclusions += _compare(dimension, comparable)
    unknowns.append("Why a post did well (topic, timing, audio or the algorithm) can't be separated from these metrics alone.")
    return conclusions, list(dict.fromkeys(unknowns))


def _partitions(buckets: dict[str, Any]) -> list[tuple[dict[str, Any], int]]:
    """Groups that may be compared with each other: all formats, or one format's styles/techniques."""
    parts: dict[str, dict[str, Any]] = {}
    for key, stats in buckets.items():
        parts.setdefault(key.split("/", 1)[0] if "/" in key else "", {})[key] = stats
    return [({k: v for k, v in part.items() if v["comparable"]}, len(part)) for part in parts.values()]


def _compare(dimension: str, comparable: dict[str, Any]) -> list[str]:
    conclusions: list[str] = []
    for rate in ("send_rate", "save_rate", "hold_3s"):
        scored = {k: v[rate] for k, v in comparable.items() if rate in v}
        if len(scored) < 2:
            continue
        best, worst = max(scored, key=scored.get), min(scored, key=scored.get)
        if scored[worst] and scored[best] >= scored[worst] * STRONG:
            conclusions.append(
                f"Directional: {dimension} `{best}` beats `{worst}` on {RATE_LABELS[rate]} "
                f"({scored[best]:.2%} vs {scored[worst]:.2%}, {comparable[best]['posts']} vs "
                f"{comparable[worst]['posts']} posts). Not significant at this sample size."
            )
    return conclusions


def priority_changes(review: dict[str, Any]) -> list[dict[str, str]]:
    """Up to three changes, ordered by where reliable posts most often fall below the median."""
    counts = {rate: 0 for rate in RATES}
    for row in review.get("posts") or []:
        for rate in row.get("weaknesses") or []:
            counts[rate] += 1
    fixes = {
        "hold_3s": ("opening", "Open on action already in motion and a 2–6 word hook; no label, greeting or logo in 0–2s."),
        "watch_ratio": ("pacing", "Cut to 20–25s and add a new visual event every 2–3s; move the reveal earlier."),
        "send_rate": ("share value", "Give one concrete thing worth sending (a prompt, a checklist, a number) and put it in the caption."),
        "save_rate": ("save value", "Add a keepable asset: numbered steps or a copyable prompt the viewer will come back to."),
        "comment_rate": ("conversation", "End on a specific question the viewer can answer in a few words."),
        "follow_rate": ("series", "Make the post part of a named, repeatable series so following has a reason."),
        "like_rate": ("response", "Keep the opening specific enough that a viewer can react to it in the first second."),
    }
    ordered = sorted((rate for rate in RATES if counts[rate]), key=lambda r: (-counts[r], RATES.index(r)))
    changes = [
        {"area": fixes[rate][0], "metric": RATE_LABELS[rate], "change": fixes[rate][1], "evidence": f"Below median on {counts[rate]} post(s)."}
        for rate in ordered[:3]
    ]
    best = _best_group(review, "format", "send_rate")
    if len(changes) < 3 and best:
        changes.append(
            {"area": "format", "metric": RATE_LABELS["send_rate"], "change": f"Post more `{best}`; it leads on sends per reach.", "evidence": "Group comparison (directional)."}
        )
    return changes[:3]


def _best_group(review: dict[str, Any], dimension: str, rate: str) -> str | None:
    """Best name on ``rate`` within the largest comparable partition, or None."""
    buckets = (review.get("groups") or {}).get(dimension, {})
    options = [
        {k: v for k, v in part.items() if rate in v}
        for part, _ in _partitions(buckets)
    ]
    options = [o for o in options if len(o) >= 2]
    if not options:
        return None
    part = max(options, key=lambda o: sum(v["posts"] for v in o.values()))
    return max(part, key=lambda k: part[k][rate]).split("/", 1)[-1]


def learnings(review: dict[str, Any]) -> dict[str, Any]:
    """Measured, bounded adjustments for the next plan. Empty when the sample can't support them.

    Each hook technique is compared with the other techniques in the same format on
    3-second hold (reels) or sends per reach (formats without a hold metric); the
    bonus is the relative difference, doubled and capped at ±0.5.
    """
    per_technique: dict[str, list[float]] = {}
    metrics: set[str] = set()
    for part, _ in _partitions((review.get("groups") or {}).get("hook_technique", {})):
        rate = "hold_3s" if sum("hold_3s" in v for v in part.values()) >= 2 else "send_rate"
        scored = {k: v[rate] for k, v in part.items() if rate in v}
        if len(scored) < 2:
            continue
        base = mean(scored.values())
        if not base:
            continue
        metrics.add(RATE_LABELS[rate])
        for key, value in scored.items():
            per_technique.setdefault(key.split("/", 1)[-1], []).append((value / base - 1) * 2)
    bonus = {k: round(max(-MAX_BONUS, min(MAX_BONUS, mean(v))), 2) for k, v in sorted(per_technique.items())}
    return {
        "technique_bonus": bonus,
        "bonus_metric": ", ".join(sorted(metrics)),
        "preferred_format": _best_group(review, "format", "send_rate"),
        "preferred_style": _best_group(review, "style", "hold_3s") or _best_group(review, "style", "send_rate"),
        "preferred_layout": _preferred_layout(review),
    }


def _preferred_layout(review: dict[str, Any]) -> str | None:
    """The layout people save, unless that layout's 3-second hold is clearly worse."""
    leader = _best_group(review, "layout", "save_rate") or _best_group(review, "layout", "send_rate")
    if leader and _hold_ok(review, leader):
        return leader
    held = _best_group(review, "layout", "hold_3s")
    return held if held in LAYOUTS else None


def _hold_ok(review: dict[str, Any], name: str) -> bool:
    holds = {
        key.split("/", 1)[-1]: stats["hold_3s"]
        for key, stats in ((review.get("groups") or {}).get("layout") or {}).items()
        if stats.get("comparable") and "hold_3s" in stats
    }
    if name not in holds or len(holds) < 2:
        return True
    best = max(holds.values())
    return not best or holds[name] >= best * WEAK


def experiment_record(review: dict[str, Any], experiment: str, *, decision: str = "") -> dict[str, Any]:
    """The outcome block to store in ``research_runs/<date>.performance.json`` and the registry."""
    posts = [p for p in review.get("posts") or [] if p["experiment"] == experiment]
    return {
        "experiment": experiment,
        "posts": [p["post_id"] for p in posts],
        "reliable_posts": sum(1 for p in posts if p["reliable"]),
        "conclusions": review.get("conclusions") or [],
        "unknowns": review.get("unknowns") or [],
        "priority_changes": review.get("priority_changes") or [],
        "learnings": review.get("learnings") or {},
        "decision": decision or "Continue: not enough evidence to accept or reject yet.",
    }
