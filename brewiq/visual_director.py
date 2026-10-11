"""BrewIQ Cinematic Video Director Prompt Agent: validate a scene package and export Veo jobs.

Input is the approved script (``script_agent``) plus the research brief. The
package is written by the model/editor using VISUAL_DIRECTOR.md; this module
checks it before any paid video generation and converts it to the
``director_reel`` JSON used by workflow_instagram.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cinematic_director import is_weak_opener
from cinematic_profile import cinematic_problems

__all__ = ["asset_path", "cinematic_problems", "to_director_reel", "validate_package"]

MIN_SCENES, MAX_SCENES = 5, 7
CLIP_SECONDS = (4, 6, 8)  # Veo 3.x clip lengths
MAX_SUBTITLE_WORDS = 6
LABEL = "Illustrative animation"
SCENE_FIELDS = (
    "start",
    "end",
    "voiceover",
    "location",
    "character_actions",
    "moving_objects",
    "camera",
    "lighting",
    "on_screen_text",
    "transition",
    "prompt",
    "generation",
)
_STATIC_CAMERA = re.compile(r"\b(static|locked[- ]off|still image|ken burns|zoom only|slideshow)\b", re.IGNORECASE)
_NO_TEXT_RULE = re.compile(r"no (readable )?text", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return str(text or "").split()


def asset_path(ref: str) -> str:
    """Strip trailing notes like ' (pose reference only)' from a reference entry."""
    return str(ref).split(" (", 1)[0].strip()


def validate_package(package: dict[str, Any], script: dict[str, Any], base_dir: Path | None = None) -> list[str]:
    """``base_dir``, when given, is where character reference images must exist."""
    problems: list[str] = []
    if base_dir is not None:
        for ref in package.get("character", {}).get("reference_assets") or []:
            if not (base_dir / asset_path(ref)).is_file():
                problems.append(f"Character reference not found: {asset_path(ref)}")
    scenes = package.get("scenes") or []
    if not MIN_SCENES <= len(scenes) <= MAX_SCENES:
        problems.append(f"Need {MIN_SCENES}–{MAX_SCENES} scenes, got {len(scenes)}.")

    lock = str(package.get("character", {}).get("lock_prompt") or "").strip()
    if not lock:
        problems.append("Missing character lock prompt.")
    if not package.get("character", {}).get("reference_assets"):
        problems.append("Missing character reference assets.")
    if package.get("label") != LABEL:
        problems.append(f"Package must carry the '{LABEL}' label.")

    prev_end = 0.0
    for index, scene in enumerate(scenes, start=1):
        tag = f"Scene {index}"
        missing = [
            key
            for key in SCENE_FIELDS
            if key not in scene or (scene[key] in ("", [], None) and not (key == "on_screen_text" and scene[key] == []))
        ]
        if missing:
            problems.append(f"{tag} missing: {', '.join(missing)}.")
            continue
        start, end = float(scene["start"]), float(scene["end"])
        if abs(start - prev_end) > 0.01 or end <= start:
            problems.append(f"{tag} timing is not contiguous ({start}–{end}s).")
        prev_end = end

        if _STATIC_CAMERA.search(scene["camera"]):
            problems.append(f"{tag} camera is static or a fake zoom.")
        prompt = str(scene["prompt"])
        if lock and lock not in prompt:
            problems.append(f"{tag} prompt does not include the character lock.")
        if not _NO_TEXT_RULE.search(prompt):
            problems.append(f"{tag} prompt must tell the model not to render text.")
        for item in scene["on_screen_text"]:
            text = str(item.get("text") or "")
            if len(_words(text)) >= 3 and text.lower() in prompt.lower():
                problems.append(f"{tag} prompt asks the model to render on-screen text: {text!r}")
            if not float(item["start"]) >= start - 0.01 or not float(item["end"]) <= end + 0.01:
                problems.append(f"{tag} on-screen text {text!r} falls outside the scene.")

        gen = scene["generation"]
        clip = gen.get("clip_seconds")
        if clip not in CLIP_SECONDS:
            problems.append(f"{tag} clip_seconds must be one of {CLIP_SECONDS}.")
        elif clip < end - start:
            problems.append(f"{tag} clip ({clip}s) is shorter than the scene ({end - start}s).")
        if gen.get("aspect_ratio") != "9:16":
            problems.append(f"{tag} must generate at 9:16.")
        if not gen.get("reference_assets"):
            problems.append(f"{tag} has no reference assets.")

    if scenes:
        first_text = (scenes[0].get("on_screen_text") or [{}])[0].get("text", "")
        if is_weak_opener(first_text):
            problems.append("Scene 1 opens on a weak on-screen line.")

    beats_end = float((script.get("beats") or [{}])[-1].get("end", 0))
    if scenes and abs(prev_end - beats_end) > 0.01:
        problems.append(f"Scenes end at {prev_end}s but the script ends at {beats_end}s.")
    joined = " ".join(str(s.get("voiceover") or "") for s in scenes)
    if " ".join(joined.split()) != " ".join(str(script.get("voiceover") or "").split()):
        problems.append("Scene voiceover segments do not add up to the approved script.")

    subtitles = package.get("subtitles") or []
    sub_text = " ".join(str(s.get("text") or "") for s in subtitles)
    if " ".join(sub_text.split()) != " ".join(str(script.get("voiceover") or "").split()):
        problems.append("Subtitles do not match the approved voiceover word for word.")
    last = 0.0
    for sub in subtitles:
        if len(_words(sub.get("text"))) > MAX_SUBTITLE_WORDS:
            problems.append(f"Subtitle too long: {sub.get('text')!r}")
        if float(sub["start"]) < last - 0.01 or float(sub["end"]) <= float(sub["start"]):
            problems.append(f"Subtitle timing overlaps at {sub['start']}s.")
        last = float(sub["end"])

    for key in ("master_direction", "sound", "assembly", "qc_checklist"):
        if not package.get(key):
            problems.append(f"Missing {key}.")
    return problems


def to_director_reel(package: dict[str, Any]) -> dict[str, Any]:
    """``director_reel`` JSON for workflow_instagram (one Veo job per scene)."""
    return {
        "aspect_ratio": "9:16",
        "scenes": [
            {
                "prompt": scene["prompt"],
                "use_character": True,
                "timing": f"{scene['start']:g}–{scene['end']:g}s",
                "role": scene.get("role", f"Scene {index}"),
                "duration_seconds": scene["generation"]["clip_seconds"],
                "trim_to_seconds": round(scene["end"] - scene["start"], 2),
                "reference_assets": scene["generation"]["reference_assets"],
            }
            for index, scene in enumerate(package["scenes"], start=1)
        ],
    }
