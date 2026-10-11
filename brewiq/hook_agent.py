"""BrewIQ Hook Selection Agent: score five hooks, gate on accuracy, pick an action-first opening.

Runs between research (``research_agent``) and script (``script_agent``). The
model scores each hook and cites which verified facts support it; this module
enforces the rules, ranks the hooks, and validates the opening visual.
"""

from __future__ import annotations

import re
from typing import Any

from cinematic_director import is_weak_opener, opening_frame_problems
from research_agent import HOOK_APPROACHES, hook_problems

# Equal weights are BrewIQ's starting assumption, not a measured result (EXP-002).
CRITERIA = ("curiosity", "clarity", "relatability", "visual_potential")
ACCURACY_LEVELS = ("supported", "partial", "unsupported")
MAX_OPENING_TEXT_WORDS = 8
_STATIC_OPENING = re.compile(
    r"\b(title (card|slide)|logo (sting|reveal|card)|text on (a )?(black|plain)|static|still frame|"
    r"talking head|smiling at (the )?camera|greeting|intro card)\b",
    re.IGNORECASE,
)


def score_hook(evaluation: dict[str, Any]) -> float:
    scores = evaluation.get("scores") or {}
    values = []
    for key in CRITERIA:
        value = float(scores.get(key, 0))
        if not 1 <= value <= 10:
            raise ValueError(f"Hook score `{key}` must be 1–10, got {value}.")
        values.append(value)
    return round(sum(values) / len(values), 2)


def hook_eligibility(evaluation: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Reasons a hook cannot win. Accuracy is a gate, not a weighted score."""
    reasons = list(hook_problems(evaluation.get("text", "")))
    accuracy = evaluation.get("accuracy")
    if accuracy not in ACCURACY_LEVELS:
        reasons.append(f"accuracy must be one of {ACCURACY_LEVELS}.")
    elif accuracy != "supported":
        reasons.append(f"Accuracy is {accuracy}: {evaluation.get('accuracy_note', 'not fully supported')}")
    facts = brief.get("verified_facts") or []
    support = evaluation.get("supported_by") or []
    if not support or any(not isinstance(i, int) or not 0 <= i < len(facts) for i in support):
        reasons.append("supported_by must cite verified_facts indices from the brief.")
    return reasons


def opening_visual_problems(opening: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key in ("first_frame", "action", "camera", "on_screen_text"):
        if not str(opening.get(key) or "").strip():
            problems.append(f"Opening visual missing {key}.")
    blob = " ".join(str(opening.get(k) or "") for k in ("first_frame", "action", "camera"))
    if _STATIC_OPENING.search(blob):
        problems.append("Opening visual is a title slide, logo, greeting, or static frame. Start on action.")
    text = str(opening.get("on_screen_text") or "")
    if len(text.split()) > MAX_OPENING_TEXT_WORDS:
        problems.append(f"Opening on-screen text is over {MAX_OPENING_TEXT_WORDS} words.")
    if is_weak_opener(text):
        problems.append("Opening on-screen text is a weak opener.")
    problems += opening_frame_problems(text, {"prompt": blob, "narration": opening.get("narration", "")})
    if "character_in_first_frame" not in opening:
        problems.append("State whether the BrewIQ host is in the first frame (optional, not required).")
    return problems


def select_hook(evaluations: list[dict[str, Any]], brief: dict[str, Any]) -> dict[str, Any]:
    approaches = sorted(str(e.get("approach")) for e in evaluations)
    if approaches != sorted(HOOK_APPROACHES):
        return {"ok": False, "error": f"Need one evaluation per approach: {', '.join(HOOK_APPROACHES)}."}

    ranked = []
    for evaluation in evaluations:
        try:
            score = score_hook(evaluation)
        except ValueError as exc:
            score, reasons = 0.0, [str(exc)]
        else:
            reasons = hook_eligibility(evaluation, brief)
        ranked.append(
            {
                "approach": evaluation["approach"],
                "text": evaluation["text"],
                "score": score,
                "accuracy": evaluation.get("accuracy"),
                "eligible": not reasons,
                "rejected": reasons,
                "why": evaluation.get("why", ""),
            }
        )
    ranked.sort(key=lambda r: (r["eligible"], r["score"]), reverse=True)
    winner = ranked[0] if ranked[0]["eligible"] else None
    if winner is None:
        return {"ok": False, "ranked": ranked, "error": "No hook is both fully supported and clear."}
    return {"ok": True, "winner": winner, "ranked": ranked, "error": ""}


POOL_TECHNIQUES = (
    "curiosity_gap",
    "surprising_fact",
    "surprising_contrast",
    "everyday_problem",
    "specific_mistake",
    "transformation",
    "bold_opinion",
    "narrative_tension",
    "useful_promise",
    "future_implication",
    "contrarian",
)
POOL_CRITERIA = ("clarity", "curiosity", "relevance", "keeps_right_viewer")
POOL_SIZE = 20
MIN_POOL_TECHNIQUES = 8
TOP_HOOKS = 5
MAX_TECHNIQUE_BONUS = 0.5
_CLICKBAIT = re.compile(
    r"\b(shocking|insane|secret|hack(s)? (that|they)|this changes everything|you need to see|guaranteed|"
    r"100%|everyone is wrong|they don'?t want you to know|before it'?s deleted)\b",
    re.IGNORECASE,
)


def _key(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split())


def select_from_pool(
    evaluations: list[dict[str, Any]],
    brief: dict[str, Any],
    *,
    technique_bonus: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Rank a pool of ~20 hooks across techniques and return the top five eligible ones.

    Each evaluation has ``technique``, ``text``, ``scores`` (1–10 on ``POOL_CRITERIA``),
    ``accuracy`` and ``supported_by``. Accuracy and clickbait are gates; the score is the
    mean of the criteria plus an optional ``technique_bonus`` measured by
    ``performance_agent.learnings`` (capped at ±0.5, so it can break ties but not
    lift a weak hook over a strong one).
    """
    problems: list[str] = []
    if len(evaluations) < POOL_SIZE:
        problems.append(f"Generate at least {POOL_SIZE} hooks (got {len(evaluations)}).")
    techniques = {str(e.get("technique")) for e in evaluations}
    unknown = sorted(techniques - set(POOL_TECHNIQUES))
    if unknown:
        problems.append(f"Unknown techniques: {', '.join(unknown)}.")
    if len(techniques & set(POOL_TECHNIQUES)) < MIN_POOL_TECHNIQUES:
        problems.append(f"Use at least {MIN_POOL_TECHNIQUES} different techniques.")
    if problems:
        return {"ok": False, "error": " ".join(problems), "ranked": [], "top": []}

    bonus = {k: max(-MAX_TECHNIQUE_BONUS, min(MAX_TECHNIQUE_BONUS, float(v))) for k, v in (technique_bonus or {}).items()}
    seen: set[str] = set()
    ranked = []
    for evaluation in evaluations:
        scores = evaluation.get("scores") or {}
        reasons: list[str] = []
        try:
            values = [float(scores[k]) for k in POOL_CRITERIA]
            if any(not 1 <= v <= 10 for v in values):
                raise ValueError
            base = round(sum(values) / len(values), 2)
        except (KeyError, TypeError, ValueError):
            base, reasons = 0.0, [f"scores must give 1–10 for {', '.join(POOL_CRITERIA)}."]
        text = str(evaluation.get("text") or "")
        reasons += hook_eligibility(evaluation, brief)
        if _CLICKBAIT.search(text):
            reasons.append("Clickbait or empty-promise wording.")
        key = _key(text)
        if key in seen:
            reasons.append("Duplicate of another hook.")
        seen.add(key)
        technique = str(evaluation.get("technique"))
        ranked.append(
            {
                "technique": technique,
                "text": text,
                "base_score": base,
                "technique_bonus": bonus.get(technique, 0.0),
                "score": round(base + bonus.get(technique, 0.0), 2),
                "accuracy": evaluation.get("accuracy"),
                "eligible": not reasons,
                "rejected": reasons,
                "why": evaluation.get("why", ""),
            }
        )
    ranked.sort(key=lambda r: (r["eligible"], r["score"]), reverse=True)
    top = [r for r in ranked if r["eligible"]][:TOP_HOOKS]
    if not top:
        return {"ok": False, "ranked": ranked, "top": [], "error": "No hook is both fully supported and clear."}
    return {
        "ok": True,
        "winner": top[0],
        "top": top,
        "ranked": ranked,
        "techniques_in_top": sorted({r["technique"] for r in top}),
        "error": "",
    }


def pool_to_brief_hooks(selection: dict[str, Any]) -> list[dict[str, str]]:
    """The top five as ``research["brief_hooks"]``, which ``plan_reel`` offers in Slack."""
    return [
        {"approach": r["technique"], "text": r["text"], "why": r["why"] or f"Score {r['score']} ({r['technique']})."}
        for r in selection.get("top") or []
    ]


def apply_to_brief(brief: dict[str, Any], selection: dict[str, Any], opening: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the brief with the selected hook and opening visual for the Script Agent."""
    winner = selection["winner"]
    updated = dict(brief)
    updated["winning_hook"] = {"approach": winner["approach"], "text": winner["text"], "why": winner["why"]}
    updated["opening_visual"] = dict(opening)
    updated["hook_ranking"] = [
        {"approach": r["approach"], "text": r["text"], "score": r["score"], "eligible": r["eligible"]}
        for r in selection["ranked"]
    ]
    return updated
