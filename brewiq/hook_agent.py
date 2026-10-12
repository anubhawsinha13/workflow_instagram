"""BrewIQ Hook Selection Agent: score five hooks, gate on accuracy, pick an action-first opening.

Runs between research (``research_agent``) and script (``script_agent``). The
model scores each hook and cites which verified facts support it; this module
enforces the rules, ranks the hooks, and validates the opening visual.
"""

from __future__ import annotations

import re
from typing import Any

from cinematic_director import is_weak_opener, opening_frame_problems
from learning_loop import hook_bonus
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
    reasons += opening_line_problems(str(evaluation.get("text") or ""))
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
# Lines that talk about the reel instead of the idea. They do not stop a scroll.
_TEMPLATE_HOOK = re.compile(
    r"\b(stop scrolling|watch this|watch closely|most people miss|most people get this wrong|"
    r"you'?re doing .+ backwards|one mistake ruins|here'?s why|let me explain|in this video)\b",
    re.IGNORECASE,
)
# Two or more of these in the opening means a nontechnical viewer cannot read it in one second.
_JARGON = re.compile(
    r"\b(api|idempoten\w*|llm|transformer|inference|latency|pipeline|architecture|"
    r"embedding|fine-?tun\w*|neural net\w*|algorithm|tokeniz\w*|throughput|"
    r"webhook|kubernetes|microservice)\b",
    re.IGNORECASE,
)
_VERB = re.compile(
    r"\b(is|are|was|were|be|been|do|does|did|don'?t|doesn'?t|didn'?t|has|have|had|"
    r"can|can'?t|cannot|will|won'?t|sent|send|hide|hides|hid|hiding|miss|missed|"
    r"save|saved|ruin|ruins|fold|folds|folded|stall|stalls|stalled|beat|beats|"
    r"leave|leaves|left|shrink|shrinks|trust|try|tries|invented|caught|catch|"
    r"fail|fails|failed|work|works|stop|stops|show|shows|need|needs|get|gets|got|"
    r"make|makes|made|take|takes|took|know|knows|want|wants|see|sees|saw|"
    r"click|clicks|clicked|check|checks|act|acts|hack|happen|happens|touch|touches|"
    r"[a-z]{4,}ed|[a-z]{5,}ing)\b",
    re.IGNORECASE,
)
_CLARITY_FLOOR = 7


def opening_line_problems(text: str, *, clarity: float | None = None) -> list[str]:
    """Why this line will not hold a viewer through the first second.

    Catchy means it makes a concrete claim. Intuitive means a nontechnical adult
    can understand it without rereading. A low clarity score is the same gate
    when the model supplied one.
    """
    value = " ".join(str(text or "").split())
    problems: list[str] = []
    if _TEMPLATE_HOOK.search(value):
        problems.append("Hook talks about scrolling instead of the idea.")
    if len(_JARGON.findall(value)) >= 2:
        problems.append("Hook uses technical words a viewer cannot read in the first second.")
    if "?" not in value and not _VERB.search(value):
        problems.append("Hook is a label, not a line someone can grasp immediately.")
    if clarity is not None and clarity < _CLARITY_FLOOR:
        problems.append(f"Clarity {clarity} is below {_CLARITY_FLOOR}; the line is not intuitive.")
    return problems


def _key(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split())


def select_from_pool(
    evaluations: list[dict[str, Any]],
    brief: dict[str, Any],
    *,
    technique_bonus: dict[str, float] | None = None,
    learnings: dict[str, Any] | None = None,
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

    if technique_bonus is None:
        technique_bonus = hook_bonus(learnings)
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
    """The top five as ``research["brief_hooks"]``. ``plan_reel`` then picks one per post type."""
    return [
        {"approach": r["technique"], "text": r["text"], "why": r["why"] or f"Score {r['score']} ({r['technique']})."}
        for r in selection.get("top") or []
    ]


# Which research hook fits each post. Earlier techniques are a better fit.
# The agent only chooses among hooks research already wrote.
POST_TECHNIQUE_RANK: dict[str, tuple[str, ...]] = {
    "cinematic_3d": (
        "surprising_contrast", "narrative_tension", "curiosity_gap", "bold_opinion",
        "surprising_fact", "future_implication", "contrarian", "transformation",
        "everyday_problem", "specific_mistake", "useful_promise",
    ),
    "interactive_explainer": (
        "curiosity_gap", "surprising_fact", "specific_mistake", "everyday_problem",
        "useful_promise", "transformation", "surprising_contrast", "narrative_tension",
        "bold_opinion", "future_implication", "contrarian",
    ),
    "tech_storytelling": (
        "narrative_tension", "transformation", "curiosity_gap", "surprising_contrast",
        "bold_opinion", "everyday_problem", "surprising_fact", "future_implication",
        "contrarian", "specific_mistake", "useful_promise",
    ),
    "motion_graphics": (
        "useful_promise", "specific_mistake", "surprising_fact", "everyday_problem",
        "future_implication", "curiosity_gap", "transformation", "surprising_contrast",
        "narrative_tension", "bold_opinion", "contrarian",
    ),
    "utility_carousel": (
        "useful_promise", "specific_mistake", "everyday_problem", "transformation",
        "surprising_fact", "curiosity_gap", "future_implication", "contrarian",
        "bold_opinion", "narrative_tension", "surprising_contrast",
    ),
    "slides": (
        "curiosity_gap", "useful_promise", "surprising_fact", "everyday_problem",
        "contrarian", "future_implication", "specific_mistake", "transformation",
        "narrative_tension", "surprising_contrast", "bold_opinion",
    ),
}
POST_TYPE_LABELS = {
    "cinematic_3d": "Cinematic 3D",
    "interactive_explainer": "Interactive Explainer",
    "tech_storytelling": "Tech Storytelling",
    "motion_graphics": "Motion Graphics",
    "utility_carousel": "Prompt pack",
    "slides": "Slides",
}


def _mean_score(scores: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    try:
        values = [float(scores[key]) for key in keys]
    except (KeyError, TypeError, ValueError):
        return None
    if any(not 1 <= value <= 10 for value in values):
        return None
    return round(sum(values) / len(values), 2)


def research_hook_candidates(research: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Hooks research actually wrote. Empty when the brief has no hook to choose."""
    research = research or {}
    facts = research.get("verified_facts") or []
    brief = {"verified_facts": facts}
    found: list[dict[str, Any]] = []
    evaluations = list(research.get("hook_evaluations") or [])
    for index, evaluation in enumerate(evaluations):
        text = str(evaluation.get("text") or "").strip()
        if not text or is_weak_opener(text):
            continue
        if facts and hook_eligibility(evaluation, brief):
            continue
        scores = evaluation.get("scores") or {}
        score = _mean_score(scores, POOL_CRITERIA)
        if score is None:
            score = _mean_score(scores, CRITERIA)
        if score is None:
            score = float(len(evaluations) - index)
        clarity = _mean_score({"clarity": (evaluation.get("scores") or {}).get("clarity")}, ("clarity",))
        found.append(
            {
                "approach": str(evaluation.get("technique") or evaluation.get("approach") or ""),
                "text": text,
                "why": str(evaluation.get("why") or ""),
                "score": score,
                "clarity": clarity,
                "research_rank": index,
            }
        )
    if found:
        return found

    brief_hooks = [h for h in research.get("brief_hooks") or [] if isinstance(h, dict)]
    for index, hook in enumerate(brief_hooks):
        text = str(hook.get("text") or "").strip()
        if not text or is_weak_opener(text):
            continue
        try:
            score = float(hook["score"]) if hook.get("score") is not None else float(len(brief_hooks) - index)
        except (TypeError, ValueError):
            score = float(len(brief_hooks) - index)
        found.append(
            {
                "approach": str(hook.get("approach") or hook.get("technique") or ""),
                "text": text,
                "why": str(hook.get("why") or ""),
                "score": score,
                "research_rank": index,
            }
        )
    if found:
        return found

    text = str(research.get("hook") or "").strip()
    if text and not is_weak_opener(text):
        return [
            {
                "approach": str(research.get("hook_approach") or ""),
                "text": text,
                "why": "Research hook.",
                "score": 1.0,
                "research_rank": 0,
            }
        ]
    return []


def best_hook_for_post(
    research: dict[str, Any] | None,
    post_type: str,
    learnings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Best research-backed hook for this post type.

    A line that is not catchy and intuitive cannot beat one that is, even when
    its technique fits the format better. Among clear lines, technique fit comes
    next, then the research score, then a capped learning bonus. Hooks that
    research did not write are never invented here.
    """
    candidates = research_hook_candidates(research)
    if not candidates:
        return None
    order = POST_TECHNIQUE_RANK.get(post_type, ())
    fit = {name: index for index, name in enumerate(order)}
    bonus = {k: max(-MAX_TECHNIQUE_BONUS, min(MAX_TECHNIQUE_BONUS, float(v))) for k, v in hook_bonus(learnings).items()}
    unknown = len(fit)

    def sort_key(candidate: dict[str, Any]) -> tuple:
        technique = candidate["approach"]
        unclear = 1 if opening_line_problems(candidate["text"], clarity=candidate.get("clarity")) else 0
        return (
            unclear,
            fit.get(technique, unknown),
            -float(candidate["score"]),
            -bonus.get(technique, 0.0),
            candidate["research_rank"],
        )

    ranked = sorted(candidates, key=sort_key)
    winner = ranked[0]
    why = winner["why"] or f"Best research {winner['approach'] or 'hook'} for {POST_TYPE_LABELS.get(post_type, post_type)}."
    return {
        "text": winner["text"],
        "approach": winner["approach"],
        "why": why,
        "score": winner["score"],
        "post_type": post_type,
        "source": "research",
        "ranked": ranked,
    }


def hooks_for_post_types(
    research: dict[str, Any] | None,
    learnings: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """The research hook each post type would use."""
    if not research_hook_candidates(research):
        return []
    chosen = []
    for post_type, label in POST_TYPE_LABELS.items():
        hook = best_hook_for_post(research, post_type, learnings)
        if hook is None:
            continue
        chosen.append(
            {
                "id": post_type,
                "label": label,
                "text": hook["text"],
                "approach": hook["approach"],
                "why": hook["why"],
            }
        )
    return chosen


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
