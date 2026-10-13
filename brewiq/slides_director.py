"""BrewIQ Slides Director: six-slide carousel plan that follows the cinematic profile.

The ``switch_slides`` recovery used to stop at a redirect. This module plans the
carousel as six story frames (not title cards): the first slide is a mid-action
moment, every slide is a new story beat with a different camera framing, one
headline sits in the top safe zone above the character layer, and every slide is
tied to a research fact or labelled illustrative. No image model renders text.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from cinematic_director import (
    CHARACTER_ENVIRONMENTS,
    is_weak_opener,
    rank_hooks,
    research_facts,
    research_limitations,
    short_line,
)
from cinematic_profile import (
    BANNED_GESTURE,
    HOST_LOCK,
    HOST_REFERENCES,
    LABEL,
    NO_TEXT_RULE,
    POINTING,
    STATIONARY,
    TEXT_PLACEMENTS,
    TITLE_SLIDE,
    TO_CAMERA,
    fact_basis_problem,
)
from composition import BRAND_LOOK, MAX_HEADLINE_LINES, MAX_HEADLINE_WORDS, wrap_lines

SLIDE_COUNT = 6
SLIDE_ASPECT = "4:5"
SLIDE_SIZE = "1080×1350"
SLIDE_HEADLINE_SIZE = 84
SLIDE_HEADLINE_WIDTH = 900
MIN_DISTINCT_FRAMES = 4
SLIDE_FRAME_RULE = (
    "FRAME RULE — 4:5 carousel still: keep clean negative space in the top 25% with every head and face below it; "
    "keep the bottom 15% free of key detail."
)
_STILL_RULE = (
    "Cinematic film still captured mid-motion: natural motion blur on moving parts, shallow depth of field, "
    "motivated light. No pointing, thumbs-up or waving."
)
_REQUIRED_FRAMES = {
    "close-up": re.compile(r"close[- ]up", re.IGNORECASE),
    "over-the-shoulder": re.compile(r"over[- ]the[- ]shoulder", re.IGNORECASE),
}
# (role, framing, host action, headline key)
_SLIDE_BEATS = (
    ("Hook", "Low-angle action close-up", "The host is at the edge of frame, mid-stride, just arriving.", "hook"),
    ("Setup", "Over-the-shoulder from behind the host", "The host watches, one hand still on the door frame.", "point"),
    ("How it works", "Close-up on hands and the device or object", "The host tries it himself, leaning in.", "try_it"),
    ("The catch", "Side-angle medium wide", "The host winces and half-steps forward.", "limitation"),
    ("Payoff", "Low-angle medium shot", "The host holds up the result, quietly impressed.", "takeaway"),
    ("Question", "Medium close-up, host facing the reader", "The host turns to camera with a raised eyebrow.", "question"),
)


def plan_slides(
    topic: str,
    research: dict | None = None,
    *,
    hook_text: str = "",
    style: str = "cinematic_3d",
    headlines: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a six-slide carousel plan plus ``slide_problems`` (empty means ready to render).

    ``headlines`` (or ``research["slide_headlines"]``) maps hook/point/try_it/limitation/
    takeaway/question to a written headline of at most 6 words. Without one, a research
    line is used only if it already fits; it is never cut off.
    """
    research = dict(research or {})
    env = CHARACTER_ENVIRONMENTS.get(style, CHARACTER_ENVIRONMENTS["cinematic_3d"])
    hook = rank_hooks(topic, research)[0]
    headline_hook = hook_text or hook["on_screen_text"]
    facts = research_facts(research)
    limitations = research_limitations(research)
    limit_index = len(facts) - len(limitations)
    grounded = list(range(limit_index)) or None
    moment = str(research.get("key_visual_moment") or research.get("headline") or topic).strip().rstrip(".")
    lines = {
        "hook": headline_hook,
        "point": str(research.get("point") or "").strip(),
        "try_it": str(research.get("try_it") or "").strip(),
        "limitation": limitations[0] if limitations else str(research.get("headline") or "").strip(),
        "takeaway": str(research.get("takeaway") or "").strip(),
        "question": str(research.get("viewer_question") or "Would you try it?").strip(),
    }
    moments = (
        f"{moment}, caught mid-action",
        "The subject keeps working while the host takes it in",
        "The method working up close, step by step",
        "The limit, shown honestly: one step visibly fails" if lines["limitation"] else "A tricky detail, up close",
        "The result, finished and clear",
        "The host asks the reader, the subject finishing behind him",
    )

    written = {str(k): str(v) for k, v in (headlines or research.get("slide_headlines") or {}).items()}
    slides = []
    for index, (role, frame, action, key) in enumerate(_SLIDE_BEATS, start=1):
        text = written.get(key) or short_line(lines[key], MAX_HEADLINE_WORDS)
        if key == "limitation" and lines["limitation"]:
            basis: Any = [limit_index]
        elif key in ("hook", "point", "try_it", "takeaway") and grounded:
            basis = grounded
        else:
            basis = f"illustrative: {role.lower()} staging; no new claim"
        slides.append(
            {
                "index": index,
                "role": role,
                "frame": frame,
                "moment": moments[index - 1],
                "character_action": action,
                "headline": {
                    "text": text,
                    "lines": wrap_lines(text, SLIDE_HEADLINE_SIZE, SLIDE_HEADLINE_WIDTH),
                    "size": SLIDE_HEADLINE_SIZE,
                    "placement": "top_safe",
                    "layer": "above_all",
                },
                "fact_basis": basis,
                "image_prompt": " ".join(
                    [
                        HOST_LOCK,
                        env,
                        BRAND_LOOK,
                        f"SHOT — {frame}. {moments[index - 1]}. {action}",
                        SLIDE_FRAME_RULE,
                        _STILL_RULE,
                        NO_TEXT_RULE,
                    ]
                ),
                "alt_text": f"{role}: {moments[index - 1]}. {action}",
                "reference_assets": list(HOST_REFERENCES),
            }
        )

    plan = {
        "ok": True,
        "format": "slides",
        "topic": topic,
        "aspect_ratio": SLIDE_ASPECT,
        "size": SLIDE_SIZE,
        "label": LABEL,
        "hook": headline_hook,
        "environment_lock": env,
        "typography": {
            "frame_rule": SLIDE_FRAME_RULE,
            "rules": [
                (
                    f"One bold headline per slide (max {MAX_HEADLINE_WORDS} words, {MAX_HEADLINE_LINES} lines at "
                    f"{SLIDE_HEADLINE_SIZE}px), top safe band (y 110–420px), white on a midnight-navy plate, "
                    "composited as the top layer."
                ),
                "Never place text over a face or head; the frame rule keeps the top band clear.",
                f"Small '{LABEL}' tag bottom-left on every slide.",
            ],
        },
        "slides": slides,
        "caption": " ".join(
            part
            for part in (
                headline_hook,
                lines["takeaway"],
                *limitations,
                f"Source: {research['source_url']}." if research.get("source_url") else "",
                f"{LABEL}.",
            )
            if part
        ),
    }
    problems = slides_problems(plan, facts)
    plan["slide_problems"] = problems
    plan["ok"] = not problems
    return plan


def slides_problems(plan: dict[str, Any], facts: list[str]) -> list[str]:
    problems: list[str] = []
    slides = plan.get("slides") or []
    if len(slides) != SLIDE_COUNT:
        problems.append(f"Need {SLIDE_COUNT} slides, got {len(slides)}.")
    if plan.get("aspect_ratio") != SLIDE_ASPECT:
        problems.append(f"Slides must be {SLIDE_ASPECT}.")
    if plan.get("label") != LABEL:
        problems.append(f"Carousel must carry the '{LABEL}' label.")
    env = str(plan.get("environment_lock") or "")
    frame_rule = str(plan.get("typography", {}).get("frame_rule") or "")

    pointing = 0
    for slide in slides:
        tag = f"Slide {slide.get('index')}"
        prompt = str(slide.get("image_prompt") or "")
        for name, lock in (("character lock", HOST_LOCK), ("environment lock", env), ("frame rule", frame_rule)):
            if not lock or lock not in prompt:
                problems.append(f"{tag} prompt is missing the {name}.")
        if BRAND_LOOK not in prompt:
            problems.append(f"{tag} prompt is missing the BrewIQ brand look.")
        if NO_TEXT_RULE not in prompt:
            problems.append(f"{tag} prompt must tell the model not to render text.")
        headline = slide.get("headline") or {}
        text = str(headline.get("text") or "")
        if not text:
            problems.append(f"{tag} needs a written headline of at most {MAX_HEADLINE_WORDS} words (slide_headlines).")
        elif len(text.split()) > MAX_HEADLINE_WORDS:
            problems.append(f"{tag} headline is over {MAX_HEADLINE_WORDS} words.")
        if len(headline.get("lines") or wrap_lines(text, SLIDE_HEADLINE_SIZE, SLIDE_HEADLINE_WIDTH)) > MAX_HEADLINE_LINES:
            problems.append(f"{tag} headline does not fit in {MAX_HEADLINE_LINES} lines.")
        if len(text.split()) >= 3 and text.lower() in prompt.lower():
            problems.append(f"{tag} prompt asks the model to render the headline.")
        if headline.get("placement") not in TEXT_PLACEMENTS:
            problems.append(f"{tag} headline must be placed in {TEXT_PLACEMENTS}.")
        if headline.get("layer") != "above_all":
            problems.append(f"{tag} headline must sit above the character layer.")
        action = str(slide.get("character_action") or "")
        if POINTING.search(action):
            pointing += 1
        if BANNED_GESTURE.search(action) or STATIONARY.search(action):
            problems.append(f"{tag} uses a thumbs-up, wave or stationary pose; show a natural, restrained action.")
        basis_problem = fact_basis_problem(slide.get("fact_basis"), len(facts))
        if basis_problem:
            problems.append(f"{tag} {basis_problem}")

    if slides:
        first = slides[0]
        if is_weak_opener(str((first.get("headline") or {}).get("text") or "")):
            problems.append("Slide 1 headline is a weak opener.")
        if TITLE_SLIDE.search(" ".join(str(first.get(k) or "") for k in ("frame", "moment", "image_prompt"))):
            problems.append("Slide 1 is a title card; open on a mid-action story moment.")
        if not TO_CAMERA.search(str(slides[-1].get("character_action") or "")):
            problems.append("The last slide should have the host address the reader (turn to camera).")
    frames = [str(s.get("frame") or "") for s in slides]
    if any(a == b for a, b in pairwise(frames)):
        problems.append("Two slides in a row use the same framing.")
    if len(set(frames)) < MIN_DISTINCT_FRAMES:
        problems.append(f"Use at least {MIN_DISTINCT_FRAMES} different framings.")
    for name, pattern in _REQUIRED_FRAMES.items():
        if not any(pattern.search(f) for f in frames):
            problems.append(f"No {name} slide.")
    moments = [str(s.get("moment") or "") for s in slides]
    if len(set(moments)) != len(moments):
        problems.append("Every slide must show a new story moment.")
    if pointing > 1:
        problems.append(f"Host points in {pointing} slides; avoid repeated pointing.")
    if not any(isinstance(s.get("fact_basis"), list) for s in slides):
        problems.append("No slide is grounded in a research fact.")
    return problems
