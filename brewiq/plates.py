"""Stills for reels, made with OpenAI gpt-image and kept on disk so a rerun does not pay twice.

The host is never redrawn from a description. A still that shows him is an edit of his own pose image, and a
vision check compares the result with that image. If the check fails or cannot run, the still is replaced by his
approved pose on the brand background, so a different man never reaches a reel.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT.parent / ".env")

STYLE = (
    "Premium stylized 3D animated film still, vertical composition, warm natural light, shallow depth of field, "
    "rich detail and real materials. No text, no letters, no numbers, no logos, no watermarks, no collage, no split screen."
)
CHARACTER_CLAUSE = (
    "The man is the same person as in the reference image: the same face, short dark hair, light stubble, "
    "medium-brown complexion, black zip hoodie over a charcoal t-shirt, and the same stylized rendering. "
    "Do not change his face or outfit. "
)
PRODUCT_CLAUSE = (
    "The product in the reference image is the only visual truth. Keep its exact shape, proportions, colors, "
    "materials, and badges. Do not add, remove, or restyle any part of it. "
)
BACKGROUND = (246, 240, 230)
VISION_MODEL = (os.getenv("BREWIQ_VISION_MODEL") or "gpt-4o").strip()
MIN_CONFIDENCE = 0.7
PLATE_SIZE = (1080, 1350)


def _secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or "your_" in value or value.endswith("_here"):
        return ""
    return value


def prompt_for(shot: dict) -> str:
    subject = shot.get("subject") or "scene"
    clause = CHARACTER_CLAUSE if subject == "character" else PRODUCT_CLAUSE if subject == "product" else ""
    return f"{clause}{STYLE} Scene: {str(shot.get('prompt') or '').strip()}"


def character_reference(folder: Path) -> Path | None:
    """The approved host, standing on the brand background. This is what every character still is edited from."""
    from explainer_render import load_pose_library

    library = load_pose_library()
    if "neutral" not in library:
        return None
    dest = folder / "character-reference.png"
    if not dest.is_file():
        figure = library["neutral"][0]
        bounds = figure.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
        if bounds:
            figure = figure.crop(bounds)
        canvas = Image.new("RGB", (1024, 1280), BACKGROUND)
        scale = min(900 / figure.height, 900 / figure.width)
        figure = figure.resize((round(figure.width * scale), round(figure.height * scale)), Image.LANCZOS)
        canvas.paste(figure, ((1024 - figure.width) // 2, 1280 - figure.height - 40), figure)
        canvas.save(dest)
    return dest


def pose_plate(pose: str, dest: Path) -> Path:
    """The approved pose on the brand background. It is always the same man."""
    from explainer_render import load_pose_library

    canvas = Image.new("RGBA", PLATE_SIZE, BACKGROUND + (255,))
    glow = Image.new("RGBA", PLATE_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((120, 160, 960, 1000), fill=(34, 195, 214, 40))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(110)))
    library = load_pose_library()
    figure = (library.get(pose) or library.get("neutral") or (None,))[0]
    if figure is not None:
        bounds = figure.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
        if bounds:
            figure = figure.crop(bounds)
        scale = min(1180 / figure.height, 960 / figure.width)
        figure = figure.resize((round(figure.width * scale), round(figure.height * scale)), Image.LANCZOS)
        canvas.alpha_composite(figure, ((PLATE_SIZE[0] - figure.width) // 2, PLATE_SIZE[1] - figure.height))
    canvas.convert("RGB").save(dest)
    return dest


def _data_url(image: Image.Image) -> str:
    copy = image.convert("RGB")
    copy.thumbnail((768, 768))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def vision_check(reference: Path, image: Image.Image, client=None) -> dict:
    """Ask a vision model whether the man in a new still is the approved character."""
    if client is None:
        key = _secret("OPENAI_API_KEY")
        if not key:
            return {"ok": False, "reason": "OPENAI_API_KEY is not set, so the character was not verified."}
        from openai import OpenAI

        client = OpenAI(api_key=key, timeout=90)
    try:
        with Image.open(reference) as source:
            approved = source.convert("RGB")
        response = client.chat.completions.create(
            model=VISION_MODEL,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "Image 1 is the approved animated character. Image 2 is a new scene. Is the main man in image 2 "
                        "the same character as image 1: face shape, hair, stubble, complexion, outfit, and rendering "
                        'style? Reply with JSON only: {"same_character": boolean, "confidence": number from 0 to 1, '
                        '"reason": short string}.'
                    )},
                    {"type": "image_url", "image_url": {"url": _data_url(approved)}},
                    {"type": "image_url", "image_url": {"url": _data_url(image)}},
                ],
            }],
        )
        verdict = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:
        return {"ok": False, "reason": f"The character check could not run: {str(exc)[:160]}"}
    confident = float(verdict.get("confidence") or 0) >= MIN_CONFIDENCE
    return {
        "ok": bool(verdict.get("same_character")) and confident,
        "reason": str(verdict.get("reason") or "")[:200],
    }


def _generate(reference: Path | None, prompt: str) -> dict:
    from art import openai_edit_image, openai_image

    if reference is not None:
        return openai_edit_image(reference, prompt, require_reference=True)
    return openai_image(prompt)


def make_plates(beats: list, folder: Path, *, product_reference: str | None = None, generate=None, check=None,
                offline: bool = False) -> dict:
    """One still per beat whose shot is a still. Returns {"ok", "plates": {beat_id: {path, source}}, "notes"}."""
    folder = Path(folder)
    generate = generate or _generate
    check = check or vision_check
    plates: dict = {}
    notes: list = []
    host_reference = None
    for beat in beats:
        shot = beat.get("shot") or {}
        if shot.get("mode") != "still":
            continue
        beat_id = beat["id"]
        subject = shot.get("subject") or "scene"
        dest = folder / f"plate-{beat_id}.png"
        sidecar = folder / f"plate-{beat_id}.json"
        if dest.is_file() and sidecar.is_file():
            plates[beat_id] = {"path": str(dest), **json.loads(sidecar.read_text(encoding="utf-8"))}
            continue
        pose = beat.get("pose") or "neutral"

        if subject == "product":
            reference = Path(str(product_reference or "")).expanduser()
            if not reference.is_file():
                return {"ok": False, "error": "The product reference image is missing, so the product still was not made.",
                        "plates": plates, "notes": notes}
            outcome = {"ok": False, "error": "offline"} if offline else generate(reference, prompt_for(shot))
            if outcome.get("ok") and outcome.get("image") is not None:
                outcome["image"].save(dest)
                record = {"source": "generated"}
            else:
                # The reference photo is the product, so it can stand in without showing anything untrue.
                with Image.open(reference) as source:
                    source.convert("RGB").save(dest)
                record = {"source": "reference_photo"}
                if not offline:
                    notes.append(f"Beat {beat_id}: {outcome.get('error') or 'the still was not generated'}. The product photo was used.")
        elif subject == "character":
            if host_reference is None:
                host_reference = character_reference(folder)
            outcome = {"ok": False, "error": "offline"} if offline or host_reference is None else generate(host_reference, prompt_for(shot))
            verdict = {"ok": False, "reason": outcome.get("error") or "no image"}
            if outcome.get("ok") and outcome.get("image") is not None:
                verdict = check(host_reference, outcome["image"])
            if outcome.get("ok") and verdict.get("ok"):
                outcome["image"].save(dest)
                record = {"source": "generated"}
            else:
                pose_plate(pose, dest)
                record = {"source": "pose_fallback"}
                if not offline:
                    notes.append(f"Beat {beat_id}: the approved {pose} pose was used. {verdict.get('reason') or ''}".strip())
        else:
            outcome = {"ok": False, "error": "offline"} if offline else generate(None, prompt_for(shot))
            if outcome.get("ok") and outcome.get("image") is not None:
                outcome["image"].save(dest)
                record = {"source": "generated"}
            else:
                pose_plate(pose, dest)
                record = {"source": "pose_fallback"}
                if not offline:
                    notes.append(f"Beat {beat_id}: {outcome.get('error') or 'the still was not generated'}. The approved {pose} pose was used.")
        if record["source"] == "generated":
            # Only a real generation is cached. A fallback is retried on the next run.
            sidecar.write_text(json.dumps(record), encoding="utf-8")
        plates[beat_id] = {"path": str(dest), **record}
    return {"ok": True, "plates": plates, "notes": notes, "error": ""}
