"""BrewIQ Reel Script Agent: validate a 20–30s script against the research brief.

The script itself is written by the model (or an editor) using SCRIPT_AGENT.md.
This module enforces the structure and factual rules before the script reaches
the Visual Director Prompt Agent.
"""

from __future__ import annotations

import re
from typing import Any

from cinematic_director import is_weak_opener

MIN_WORDS, MAX_WORDS = 45, 65
MIN_SECONDS, MAX_SECONDS = 20.0, 30.0
MAX_SHOT_SECONDS = 4.0
SHOT_KINDS = ("illustration", "real_footage")
QUALIFICATION_PLACES = ("voiceover", "on_screen", "caption")

# (beat, latest allowed start, latest allowed end); ending must close the reel.
BEAT_WINDOWS = (
    ("hook", 0.0, 2.5),
    ("setup", 3.0, 7.5),
    ("reveal", 8.0, 18.5),
    ("payoff", 18.5, 25.5),
    ("ending", 26.0, MAX_SECONDS),
)
_BAIT = re.compile(
    r"\b(follow (us|for more)|like and subscribe|smash (that|the) like|comment below|link in bio|share this with)\b",
    re.IGNORECASE,
)
_HYPE = re.compile(r"\b(revolutionar\w*|game[- ]?chang\w*|mind[- ]?blowing|will change everything)\b", re.IGNORECASE)


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", str(text or "")))


def validate_script(script: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Return problems; an empty list means the script can go to the Visual Director."""
    problems: list[str] = []
    voiceover = str(script.get("voiceover") or "")
    words = word_count(voiceover)
    if not MIN_WORDS <= words <= MAX_WORDS:
        problems.append(f"Voiceover is {words} words; target {MIN_WORDS}–{MAX_WORDS}.")
    if _BAIT.search(voiceover):
        problems.append("Voiceover contains engagement bait.")
    if _HYPE.search(voiceover):
        problems.append("Voiceover contains exaggerated hype.")

    beats = script.get("beats") or []
    names = [b.get("beat") for b in beats]
    if names != [name for name, _, _ in BEAT_WINDOWS]:
        problems.append("Beats must be hook, setup, reveal, payoff, ending in order.")
    else:
        prev_end = 0.0
        for beat, (name, latest_start, latest_end) in zip(beats, BEAT_WINDOWS, strict=True):
            start, end = float(beat["start"]), float(beat["end"])
            if start < prev_end - 0.01 or end <= start:
                problems.append(f"Beat `{name}` timing overlaps or is empty.")
            if start > latest_start or end > latest_end:
                problems.append(f"Beat `{name}` ({start}–{end}s) is outside its window.")
            prev_end = end
        joined = " ".join(str(b.get("narration") or "") for b in beats)
        if " ".join(joined.split()) != " ".join(voiceover.split()):
            problems.append("Beat narration does not add up to the voiceover.")
        hook_line = str(beats[0].get("narration") or "")
        if is_weak_opener(hook_line):
            problems.append("Hook narration is a weak opener.")

    shots = script.get("shots") or []
    if not shots:
        problems.append("No shots.")
    else:
        if float(shots[0]["start"]) != 0.0:
            problems.append("First shot must start at 0s.")
        if is_weak_opener(shots[0].get("on_screen_text", "")):
            problems.append("First on-screen text is a weak opener.")
        prev_end = 0.0
        for shot in shots:
            start, end = float(shot["start"]), float(shot["end"])
            if abs(start - prev_end) > 0.01:
                problems.append(f"Gap or overlap between shots at {prev_end}s.")
            if end - start > MAX_SHOT_SECONDS:
                problems.append(f"Shot {start}–{end}s holds longer than {MAX_SHOT_SECONDS}s without a visual change.")
            if shot.get("kind") not in SHOT_KINDS:
                problems.append(f"Shot {start}–{end}s must be marked illustration or real_footage.")
            prev_end = end
        if not MIN_SECONDS <= prev_end <= MAX_SECONDS:
            problems.append(f"Reel runs {prev_end}s; target {MIN_SECONDS:.0f}–{MAX_SECONDS:.0f}s.")
        if beats and abs(prev_end - float(beats[-1]["end"])) > 0.01:
            problems.append("Shots and narration end at different times.")

    if str(brief.get("winning_hook", {}).get("text") or "") != str(script.get("winning_hook") or ""):
        problems.append("Script must use the brief's winning hook.")

    covered = {q.get("limitation") for q in script.get("qualifications") or [] if q.get("where") in QUALIFICATION_PLACES}
    for limitation in brief.get("limitations") or []:
        if limitation not in covered:
            problems.append(f"Qualification not preserved: {limitation}")

    allowed = {brief.get("source", {}).get("primary_source_url")} | set(brief.get("secondary_sources") or [])
    for url in script.get("sources") or []:
        if url not in allowed:
            problems.append(f"Source not in the research brief: {url}")
    if brief.get("source", {}).get("primary_source_url") not in (script.get("sources") or []):
        problems.append("Primary source must be cited.")

    for key in ("title", "emotional_tone", "final_takeaway", "visual_concept", "caption"):
        if not str(script.get(key) or "").strip():
            problems.append(f"Missing {key}.")
    if not script.get("facts_used"):
        problems.append("No verified facts listed.")
    return problems


def to_visual_director(script: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    """Handoff package for the Visual Director Prompt Agent."""
    return {
        "topic": brief["selected_topic"],
        "style": brief.get("suggested_style", ""),
        "hook": script["winning_hook"],
        "voiceover": script["voiceover"],
        "beats": script["beats"],
        "shots": script["shots"],
        "key_visual_moment": brief.get("key_visual_moment", ""),
        "do_not_depict": script.get("do_not_depict", []),
        "sources": script["sources"],
    }
