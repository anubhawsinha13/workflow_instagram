"""Turn a video-director storyboard into one vertical reel with Veo. This does not publish."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reel import ffmpeg_bin, motion_changes  # noqa: E402

VEO_MODEL = (os.getenv("VEO_MODEL") or "veo-3.1-lite-generate-preview").strip()
MOTION_FLOOR = 1.5
FRAME_SIZE = (720, 1280)

START_FRAME = (
    "Turn this photo into one premium stylized 3D animated film still of the same man, vertical 9:16. "
    "Keep his face, short dark hair, light stubble, and medium-brown complexion recognizable. "
    "He wears a plain black jacket with no logo. "
    "Place him in a richly detailed room with warm practical light, soft bokeh, real materials, "
    "and a color that contrasts with his black jacket. Shallow depth of field. "
    "No text, no logos, no collage. The opening moment of this scene: "
)

CHARACTER = (
    "The host is the stylized 3D animated man in the supplied character image. "
    "Keep his face, short dark hair, light stubble, medium-brown complexion, and premium 3D style. "
    "He wears a plain black jacket with no logo. "
    "One continuous vertical shot. The character and the objects move. No text and no collage. "
    "The room behind him is richly detailed, with warm practical light, soft bokeh, real materials, and a color that contrasts with his black jacket. "
    "Shallow depth of field keeps him sharp and the background colorful. "
)


def render_director_reel(payload: dict, generate_clip=None, make_start_frame=None, model: str | None = None) -> dict:
    model = model or VEO_MODEL
    scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    if len(scenes) < 2:
        return {"ok": False, "error": "A reel needs at least two scenes."}
    folder = Path(str(payload.get("folder") or "")).expanduser()
    if not folder.is_dir():
        return {"ok": False, "error": "The reel folder is not available."}
    reference = Path(str(payload.get("reference") or "")).expanduser()
    if not reference.is_file():
        return {
            "ok": False,
            "error": "The approved BrewIQ character reference is missing, so this reel was not created.",
        }
    prompts = []
    for scene in scenes:
        if not isinstance(scene, dict) or not str(scene.get("prompt") or "").strip():
            return {"ok": False, "error": "A scene is missing its prompt."}
        if not scene.get("use_character"):
            return {
                "ok": False,
                "error": "Every scene needs the approved BrewIQ character. A different person was not generated.",
            }
        prompts.append(f"{CHARACTER}{str(scene.get('prompt') or '').strip()}")
    if generate_clip is None and not _gemini_key():
        return {"ok": False, "error": "GEMINI_API_KEY is not set, so this reel was not created."}
    create = generate_clip or (lambda start, prompt, dest: _generate_veo_clip(start, prompt, dest, model))
    chained = not accepts_reference_images(model)
    start = reference
    if chained:
        start = folder / "start-frame.png"
        made = (make_start_frame or _start_frame)(reference, str(scenes[0].get("prompt") or ""), start)
        if not made.get("ok") or not start.is_file():
            return {"ok": False, "error": made.get("error") or "The opening character frame could not be created."}
    clips = []
    provider = model
    for index, prompt in enumerate(prompts, start=1):
        dest = folder / f"clip-{index:02d}.mp4"
        created = create(start, prompt, dest)
        if not created.get("ok") or not dest.is_file():
            return {"ok": False, "error": _public(created.get("error") or "Veo did not create the clip.")}
        provider = str(created.get("provider") or provider)
        if motion_changes(dest) < MOTION_FLOOR:
            return {
                "ok": False,
                "error": "The clip did not show continuous motion, so this reel was not created.",
            }
        clips.append(dest)
        if chained:
            start = _last_frame(dest, folder / f"clip-{index:02d}-last.png") or start
    joined = folder / "joined.mp4"
    assembled = _join(clips, joined)
    if not assembled.get("ok"):
        return {"ok": False, "error": assembled.get("error") or "The reel could not be assembled."}
    return {"ok": True, "path": str(joined), "provider": provider, "error": ""}


def accepts_reference_images(model: str) -> bool:
    return "lite" not in model.lower()


def _start_frame(reference: Path, scene_prompt: str, dest: Path) -> dict:
    from art import openai_edit_image

    result = openai_edit_image(reference, f"{START_FRAME}{scene_prompt.strip()}", require_reference=True)
    image = result.get("image")
    if not result.get("ok") or image is None:
        return {"ok": False, "error": result.get("error") or "The opening character frame could not be created."}
    width, height = image.size
    target = round(height * 9 / 16)
    if target <= width:
        left = (width - target) // 2
        image = image.crop((left, 0, left + target, height))
    else:
        tall = round(width * 16 / 9)
        top = (height - tall) // 2
        image = image.crop((0, top, width, top + tall))
    image.resize(FRAME_SIZE).save(dest)
    return {"ok": True, "error": ""}


def _last_frame(clip: Path, dest: Path) -> Path | None:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return None
    completed = subprocess.run(
        [ffmpeg, "-y", "-sseof", "-0.1", "-i", str(clip), "-frames:v", "1", "-update", "1", str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        return None
    return dest


def _generate_veo_clip(start: Path, prompt: str, dest: Path, model: str = VEO_MODEL) -> dict:
    key = _gemini_key()
    if not key:
        return {"ok": False, "error": "GEMINI_API_KEY is not set, so this reel was not created."}
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"ok": False, "error": "The Gemini video package is not installed, so this reel was not created."}
    client = genai.Client(api_key=key)
    mime = "image/jpeg" if start.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    image = types.Image(image_bytes=start.read_bytes(), mime_type=mime)
    frame_config = types.GenerateVideosConfig(aspect_ratio="9:16", duration_seconds=8)
    try:
        if accepts_reference_images(model):
            reference_config = types.GenerateVideosConfig(
                aspect_ratio="9:16",
                duration_seconds=8,
                reference_images=[types.VideoGenerationReferenceImage(image=image, reference_type="asset")],
            )
            try:
                operation = client.models.generate_videos(model=model, prompt=prompt[:4000], config=reference_config)
            except Exception as exc:
                if not _reference_rejected(exc):
                    raise
                operation = client.models.generate_videos(
                    model=model, prompt=prompt[:4000], image=image, config=frame_config
                )
        else:
            operation = client.models.generate_videos(model=model, prompt=prompt[:4000], image=image, config=frame_config)
    except Exception as exc:
        return {"ok": False, "error": _public(exc)}
    deadline = time.monotonic() + 8 * 60
    while not operation.done:
        if time.monotonic() > deadline:
            return {"ok": False, "error": "Veo did not finish the clip in time, so this reel was not created."}
        time.sleep(10)
        operation = client.operations.get(operation)
    failure = getattr(operation, "error", None)
    if failure:
        return {"ok": False, "error": _public(failure)}
    response = getattr(operation, "response", None)
    videos = getattr(response, "generated_videos", None) if response else None
    if not videos:
        return {"ok": False, "error": "Veo did not return a video, so this reel was not created."}
    client.files.download(file=videos[0].video, destination=str(dest))
    if not dest.is_file() or dest.stat().st_size == 0:
        return {"ok": False, "error": "Veo did not save the clip, so this reel was not created."}
    return {"ok": True, "provider": model, "error": ""}


def _join(clips: list, dest: Path) -> dict:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg is not installed, so the reel could not be assembled."}
    listing = dest.parent / "veo-clips.txt"
    listing.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not dest.is_file():
        silent = [arg for arg in command if arg not in ("-c:a", "aac")]
        audio_at = silent.index("-movflags")
        completed = subprocess.run(silent[:audio_at] + silent[audio_at:], capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        detail = (completed.stderr or "").strip().splitlines()
        return {"ok": False, "error": (detail[-1] if detail else "ffmpeg could not join the clips.")[:240]}
    return {"ok": True, "error": ""}


def _gemini_key() -> str:
    value = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not value or "your_" in value or value.endswith("_here"):
        return ""
    return value


def _reference_rejected(exc: Exception) -> bool:
    text = str(exc).lower()
    return "reference" in text or "aspect" in text or "not supported" in text


def _public(detail: object) -> str:
    text = " ".join(str(detail).split())
    lowered = text.lower()
    if any(word in lowered for word in ("quota", "resource_exhausted", "billing")):
        return "Google Veo rejected the clip because the Gemini quota or billing limit is exhausted."
    if not text or len(text) > 240 or any(word in lowered for word in ("api_key", "aiza", "secret", "bearer")):
        return "Veo could not create the moving clip, so this reel was not created."
    return text


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "A storyboard file is required."}))
        return 1
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(render_director_reel(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
