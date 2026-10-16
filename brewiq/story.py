"""The animated story behind the 8-second Reel: one original 3D character living the moment and doing the fix.

The image model draws three film stills of the same character: the moment (hook), doing the fix, and a look
to camera (call to action). Veo animates the first still into one continuous clip when it can. When it can't,
the stills play with slow camera moves. Phone and laptop screens are never readable in the picture; the reel
lays the real sample screen over it. Nothing is published here.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

from PIL import Image

ROLES = ("hook", "fix", "cta")
SIZE = (1080, 1920)

LOOK = (
    "Feature-film quality stylized 3D animation, Pixar-inspired, premium cinematic look, warm practical light, "
    "soft bokeh, shallow depth of field, expressive face, real materials and textures. "
)
FRAMING = (
    " Vertical 9:16 medium-wide shot. The character's head sits in the middle of the frame with open wall or "
    "ceiling above it, and the hands are in the lower half."
)
CLEAN = (
    " The phone or laptop screen faces away from the camera or is too soft to read. "
    "No text, no captions, no logos, no brand names, no watermark."
)
SAME = (
    "Keep the exact same character, face, hair, clothes, place, lighting, and 3D animated style as this image. "
    "Only the moment changes: "
)


def problems(story) -> list:
    """What is missing from a story. An empty list means it can be drawn."""
    if not isinstance(story, dict):
        return ["The story must be an object."]
    found = []
    for field in ("character", "setting"):
        if not str(story.get(field) or "").strip():
            found.append(f"The story needs a {field}.")
    moments = story.get("moments") if isinstance(story.get("moments"), dict) else {}
    for role in ROLES:
        if not str(moments.get(role) or "").strip():
            found.append(f"The story needs a {role} moment.")
    return found


def frame_prompt(story: dict, role: str) -> str:
    moment = str(story["moments"][role]).strip()
    if role == "hook":
        return f"{LOOK}An original adult character: {story['character']}. Place: {story['setting']}. {moment}{FRAMING}{CLEAN}"
    return f"{SAME}{moment}{FRAMING}{CLEAN}"


def motion_prompt(story: dict) -> str:
    """One continuous shot that walks through the three moments, for Veo."""
    moments = story["moments"]
    return (
        f"{LOOK}The original adult character in the image: {story['character']}. Place: {story['setting']}. "
        "One continuous vertical shot with a gentle handheld push-in. No dialogue, no speech, no text, no subtitles. "
        f"First: {moments['hook']} Then: {moments['fix']} Finally: {moments['cta']}{CLEAN}"
    )


def _vertical(image: Image.Image) -> Image.Image:
    width, height = image.size
    target = round(height * 9 / 16)
    if target <= width:
        left = (width - target) // 2
        image = image.crop((left, 0, left + target, height))
    else:
        tall = round(width * 16 / 9)
        top = (height - tall) // 2
        image = image.crop((0, top, width, top + tall))
    return image.convert("RGB").resize(SIZE, Image.LANCZOS)


def make_frames(story: dict, folder: Path, *, generate=None, edit=None) -> dict:
    """Draw the three stills. The fix and call-to-action stills are edits of the first, so the character matches."""
    if generate is None or edit is None:
        from art import openai_edit_image, openai_image  # noqa: PLC0415 - loads the image client only when needed.

        generate = generate or openai_image
        edit = edit or openai_edit_image
    folder.mkdir(parents=True, exist_ok=True)
    paths = {role: folder / f"story-{role}.png" for role in ROLES}
    if not paths["hook"].is_file():
        made = generate(frame_prompt(story, "hook"))
        if not made.get("ok") or made.get("image") is None:
            return {"ok": False, "error": made.get("error") or "The opening story frame could not be drawn."}
        _vertical(made["image"]).save(paths["hook"])

    def draw(role: str) -> str:
        if paths[role].is_file():
            return ""
        made = edit(paths["hook"], frame_prompt(story, role), require_reference=True)
        if not made.get("ok") or made.get("image") is None:
            return made.get("error") or f"The {role} story frame could not be drawn."
        _vertical(made["image"]).save(paths[role])
        return ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        errors = [error for error in pool.map(draw, ROLES[1:]) if error]
    if errors:
        return {"ok": False, "error": errors[0]}
    return {"ok": True, "frames": {role: str(path) for role, path in paths.items()}, "error": ""}


def make_backdrop(story: dict, folder: Path, *, generate=None, edit=None, animate=None) -> dict:
    """The picture behind the reel: a Veo clip when it can be made, otherwise the three stills."""
    missing = problems(story)
    if missing:
        return {"ok": False, "error": " ".join(missing)}
    folder = Path(folder)
    drawn = make_frames(story, folder, generate=generate, edit=edit)
    if not drawn.get("ok"):
        return drawn
    frames = drawn["frames"]
    clip = folder / "story.mp4"
    if clip.is_file() and clip.stat().st_size > 0:
        return {"ok": True, "kind": "video", "video": str(clip), "frames": frames, "notes": []}
    if animate is None:
        import director_reel  # noqa: PLC0415

        animate = director_reel._generate_veo_clip
    made = animate(Path(frames["hook"]), motion_prompt(story), clip)
    if made.get("ok") and clip.is_file():
        return {"ok": True, "kind": "video", "video": str(clip), "frames": frames, "notes": []}
    reason = made.get("error") or "Veo did not return a clip."
    return {"ok": True, "kind": "stills", "frames": frames,
            "notes": [f"{reason} The story plays as moving stills instead."]}
