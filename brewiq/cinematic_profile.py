"""BrewIQ cinematic profile: shared "miniature movie" rules for reels and carousels.

Used by ``visual_director`` (hand-built scene packages), ``cinematic_director``
(Slack-planned reels for the character styles) and ``slides_director`` (six-slide
carousel fallback), so every format follows the same opening, story, camera,
typography and accuracy rules.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

HOST_LOCK = (
    "CHARACTER LOCK — the BrewIQ host: the man in the reference image, about 30, warm light-brown South Asian skin, "
    "short dark wavy hair, dark brown eyes, strong dark eyebrows, light stubble, friendly confident half-smile; plain "
    "black quilted jacket with no logo or brand mark; no glasses. Identical face, hair, outfit and proportions to the "
    "reference image; never change clothing or colors; natural weight and follow-through in every movement."
)
HOST_REFERENCES = ("brand/character-reference.png",)
FRAME_RULE = (
    "FRAME RULE — compose with clean, uncluttered negative space in the top 30% of the frame and keep every head and "
    "face below it; keep the bottom 28% (subtitle band) free of faces and key action."
)
NO_TEXT_RULE = "No readable text, letters, numbers or logos anywhere."
LABEL = "Illustrative animation"

CINEMATIC_RUNTIME = (20.0, 30.0)
CINEMATIC_SCENE_SECONDS = (3.0, 5.0)
FIRST_MOTION_BY = 0.5
MAX_EVENT_GAP = 4.0
TEXT_PLACEMENTS = ("top_safe", "center_safe")
REQUIRED_CAMERA_MOVES = {
    "tracking": re.compile(r"\btrack(s|ing)?\b", re.IGNORECASE),
    "over-the-shoulder": re.compile(r"over[- ]the[- ]shoulder", re.IGNORECASE),
    "close-up": re.compile(r"close[- ]up", re.IGNORECASE),
    "push-in": re.compile(r"push[- ]in", re.IGNORECASE),
}
_ZOOM = re.compile(r"\bzoom", re.IGNORECASE)
TITLE_SLIDE = re.compile(r"\b(title (card|slide)|intro card|logo (sting|reveal|card))\b", re.IGNORECASE)
POINTING = re.compile(r"(?<!no )(?<!never )\bpoint(s|ing|ed)?\b(?! of view)", re.IGNORECASE)
BANNED_GESTURE = re.compile(
    r"(?<!no )(?<!never )\b(thumbs?[- ]up|wav(e|es|ing) (at|to|hello|goodbye)|waves? hello)\b", re.IGNORECASE
)
STATIONARY = re.compile(r"\b(stands? still|stationary|static presenter|talking head|holds? (a|the) pose)\b", re.IGNORECASE)
TO_CAMERA = re.compile(r"\bto (the )?(camera|lens|audience)\b", re.IGNORECASE)


def fact_basis_problem(basis: Any, fact_count: int) -> str | None:
    """``basis`` must be verified_facts indices or a string starting 'illustrative:'."""
    if isinstance(basis, list) and basis:
        if any(not isinstance(i, int) or not 0 <= i < fact_count for i in basis):
            return "fact_basis cites an unknown verified fact."
        return None
    if isinstance(basis, str) and basis.lower().startswith("illustrative:"):
        return None
    return "needs fact_basis: verified_facts indices or 'illustrative: <why>'."


def cinematic_problems(package: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Stricter "miniature movie" profile, run in addition to ``validate_package``.

    Requires visible motion by 0.5s, a new story event at least every 4s, real camera
    moves (no zooms), no thumbs-up, waves or stationary presenter shots, one on-screen line at a time in a safe zone above the character
    layer, and every scene tied to a verified fact or labelled illustrative.
    """
    problems: list[str] = []
    scenes = package.get("scenes") or []
    if not scenes:
        return ["No scenes."]
    runtime = float(scenes[-1].get("end", 0))
    if not CINEMATIC_RUNTIME[0] <= runtime <= CINEMATIC_RUNTIME[1]:
        problems.append(f"Runtime {runtime}s is outside {CINEMATIC_RUNTIME[0]:g}–{CINEMATIC_RUNTIME[1]:g}s.")

    env_lock = str(package.get("environment", {}).get("lock_prompt") or "").strip()
    frame_rule = str(package.get("typography", {}).get("frame_rule") or "").strip()
    if not env_lock:
        problems.append("Missing environment lock prompt.")
    if not frame_rule:
        problems.append("Missing typography frame rule (keeps the text zone clear of the characters).")
    if package.get("typography", {}).get("subtitle_zone") != "lower_safe":
        problems.append("Subtitles must sit in the lower safe zone.")

    facts = brief.get("verified_facts") or []
    events: list[float] = []
    texts: list[tuple[float, float, str]] = []
    pointing_scenes = 0
    speaks_to_camera = False
    for index, scene in enumerate(scenes, start=1):
        tag = f"Scene {index}"
        start, end = float(scene.get("start", 0)), float(scene.get("end", 0))
        length = round(end - start, 2)
        if not CINEMATIC_SCENE_SECONDS[0] <= length <= CINEMATIC_SCENE_SECONDS[1]:
            problems.append(f"{tag} runs {length:g}s; clips must be 3–5s.")
        prompt = str(scene.get("prompt") or "")
        if env_lock and env_lock not in prompt:
            problems.append(f"{tag} prompt does not include the environment lock.")
        if frame_rule and frame_rule not in prompt:
            problems.append(f"{tag} prompt does not include the typography frame rule.")
        if _ZOOM.search(str(scene.get("camera") or "")):
            problems.append(f"{tag} uses a zoom; use a physical camera move instead.")
        actions = str(scene.get("character_actions") or "")
        if POINTING.search(actions):
            pointing_scenes += 1
        if BANNED_GESTURE.search(actions):
            problems.append(f"{tag} uses a thumbs-up or wave; use a restrained, natural gesture.")
        if STATIONARY.search(actions):
            problems.append(f"{tag} has a stationary presenter; the host must move or demonstrate.")
        if TO_CAMERA.search(actions):
            speaks_to_camera = True

        scene_events = sorted(float(e.get("t", -1)) for e in scene.get("events") or [] if e.get("event"))
        if not scene_events:
            problems.append(f"{tag} lists no story events.")
        elif scene_events[0] < start - 0.01 or scene_events[-1] > end + 0.01:
            problems.append(f"{tag} has story events outside the scene.")
        events += scene_events

        for item in scene.get("on_screen_text") or []:
            label = repr(item.get("text"))
            if item.get("placement") not in TEXT_PLACEMENTS:
                problems.append(f"{tag} text {label} must be placed in {TEXT_PLACEMENTS}.")
            if item.get("layer") != "above_all":
                problems.append(f"{tag} text {label} must sit above the character layer.")
            texts.append((float(item["start"]), float(item["end"]), str(item.get("text"))))

        basis_problem = fact_basis_problem(scene.get("fact_basis"), len(facts))
        if basis_problem:
            problems.append(f"{tag} {basis_problem}")

    first = scenes[0]
    if not events or events[0] > FIRST_MOTION_BY:
        problems.append(f"Scene 1 must show visible motion by {FIRST_MOTION_BY}s.")
    if TITLE_SLIDE.search(" ".join(str(first.get(k) or "") for k in ("prompt", "character_actions", "camera"))):
        problems.append("Scene 1 opens on a title slide or logo.")
    for prev, nxt in zip([0.0, *events], [*events, runtime], strict=True):
        if nxt - prev > MAX_EVENT_GAP + 0.01:
            problems.append(f"No new story event between {prev:g}s and {nxt:g}s.")

    for move, pattern in REQUIRED_CAMERA_MOVES.items():
        if not any(pattern.search(str(s.get("camera") or "")) for s in scenes):
            problems.append(f"No {move} shot in the reel.")
    if pointing_scenes > 1:
        problems.append(f"Host points in {pointing_scenes} scenes; avoid repeated pointing.")
    if not speaks_to_camera:
        problems.append("Host never speaks to camera.")

    texts.sort()
    for (_, a_end, a_text), (b_start, _, b_text) in pairwise(texts):
        if b_start < a_end - 0.01:
            problems.append(f"On-screen text overlaps: {a_text!r} and {b_text!r}. Show one line at a time.")
    if not any(isinstance(s.get("fact_basis"), list) for s in scenes):
        problems.append("No scene is grounded in a verified fact.")
    return problems
