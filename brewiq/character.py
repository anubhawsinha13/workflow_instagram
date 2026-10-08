"""The owner's character reference for animated reels."""

from __future__ import annotations

from pathlib import Path

REFERENCE = Path(__file__).resolve().parent / "brand" / "character-reference.png"

CLAUSE = (
    "Use the same face as the reference image. Keep the short dark hair and light stubble. "
    "Clothing is a plain black quilted jacket with no logo and no brand mark. "
    "Invent a new background. "
)


def character_reference() -> Path | None:
    return REFERENCE if REFERENCE.is_file() else None


def with_character(prompts: list[str]) -> list[str]:
    return [f"{CLAUSE}{prompt}" for prompt in prompts]


SCENE_CLAUSE = (
    "Use the attached reference image as the visual starting point. "
    "Keep its subject and lighting, and show the next moment of the same idea. "
    "No logos and no brand marks. "
)


def with_scene(prompts: list[str]) -> list[str]:
    return [f"{SCENE_CLAUSE}{prompt}" for prompt in prompts]
