"""A picture editor for mood Reels: looks at the drawn stills as a viewer would and says which ones to redraw.

A vision model sees every still next to the shot it was meant to show and the opening scene, and answers for each: does it
tell its part of the story, are the characters the same people, is anything broken (hands, faces, stray text, panels or
seams, a crowded lower third)? A shot that fails gets one fix instruction, and the Reel redraws it once.
"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

MODEL = (os.getenv("BREWIQ_VISION_MODEL") or "gpt-4o").strip()
MAX_SIDE = 1024

RUBRIC = """You are the picture editor of a small studio that makes silent, painterly-anime Reels that tell one tiny story
in a few stills. You are shown the stills in order, each with the shot it was meant to show. Be a strict viewer.

Judge each still on:
1. STORY: does it show its part of the beat as written, and does the order read as a story (setting, a closer moment,
   a small detail, a turn or payoff) with something that changes from still to still?
2. CONTINUITY: the same two people (or one), the same hair, clothes, place, time of day and light as the opening still.
3. CRAFT: no extra or missing fingers, warped hands or faces, melted objects, extra people, text, letters, logos or
   watermarks, no panels, strips, borders or collage, no hard seam across the picture.
4. COMPOSITION: faces and hands in the upper two thirds; the lower third calm, empty and uncluttered.
5. DETAIL shots show hands and objects only, with no faces.

Return only JSON:
{"story": "one sentence on whether the sequence reads as a story and what is weak", "score": 1-10,
 "shots": [{"id": "wide", "pass": true, "issue": "", "fix": ""}, ...]}
- One entry per still, using the ids you are given. pass is false only for a real problem a viewer would notice.
- fix is one concrete instruction for redrawing that still, such as "show only her left hand holding the cup, five
  fingers, and keep the lower third empty". Empty when it passes."""


def _jpeg(path: str | Path) -> str:
    from PIL import Image  # noqa: PLC0415

    image = Image.open(path).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _vision(system: str, text: str, frames: list) -> str:
    from openai import OpenAI  # noqa: PLC0415

    content: list = [{"type": "text", "text": text}]
    for shot_id, path in frames:
        content.append({"type": "text", "text": f"Still: {shot_id}"})
        content.append({"type": "image_url", "image_url": {"url": _jpeg(path), "detail": "high"}})
    response = OpenAI(timeout=180).chat.completions.create(
        model=MODEL, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
    )
    return response.choices[0].message.content or ""


def parse_review(raw: str, shot_ids: list) -> dict:
    """The verdicts, with a shot the editor did not mention counted as passing. Raises on unreadable JSON."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("The picture review was not an object.")
    verdicts = {}
    for item in data.get("shots") or []:
        if isinstance(item, dict) and str(item.get("id")) in shot_ids:
            failed = item.get("pass") is False
            fix = " ".join(str(item.get("fix") or "").split())[:400]
            verdicts[str(item["id"])] = {
                "pass": not failed or not fix,  # A failure with no fix to apply cannot be acted on.
                "issue": " ".join(str(item.get("issue") or "").split())[:300],
                "fix": fix,
            }
    try:
        score = max(1, min(10, int(data.get("score"))))
    except (TypeError, ValueError):
        score = 0
    return {"story": " ".join(str(data.get("story") or "").split())[:300], "score": score,
            "shots": {shot_id: verdicts.get(shot_id, {"pass": True, "issue": "", "fix": ""}) for shot_id in shot_ids}}


def review_frames(spec: dict, frames: dict, complete=None) -> dict:
    """Ask the picture editor about every still. `complete(system, text, [(id, path)])` can be replaced in tests."""
    order = [shot_id for shot_id in frames]
    beats = {str(s.get("id")): str(s.get("prompt") or "") for s in spec.get("shots") or []}
    text = "\n".join([
        f"Mood: {spec.get('mood')}. Setting: {spec.get('setting')}. Characters: {spec.get('characters')}.",
        f"On-screen line (added later, not part of the pictures): {spec.get('text') or 'none'}.",
        "Shots in order:", *[f"- {shot_id}: {beats.get(shot_id, '')}" for shot_id in order],
    ])
    raw = (complete or _vision)(RUBRIC, text, [(shot_id, frames[shot_id]) for shot_id in order])
    return parse_review(raw, order)
