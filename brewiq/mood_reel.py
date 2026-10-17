"""The Animated Music Reel: a soft, cinematic animated moment, silent, to be paired with a song in Instagram.

One scene, drawn as painterly anime stills, plays for about ten seconds with slow camera drifts and dissolves, or as
one animated clip when the video model has credits. A single line of text sits in the safe zone and the account's mark in
the corner. There is no narration: the song is picked by a person inside Instagram, because the popular tracks are
not in the API's catalog. Two original characters recur from episode to episode and are drawn from a saved
reference sheet so they look the same each time. Nothing is published here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import story as story_module  # noqa: E402
from explainer_render import render_explainer  # noqa: E402
from reel_spec import COLORS, FPS, H, SAFE, W, _element  # noqa: E402

STYLE = "anime_painterly"
ACCOUNT_MARK = "logo:a48"
ACCOUNT_NAME = "A48 STUDIO"
# The golden-hour tone from the brand palette. The highlighted word is always this color, so every Reel reads as A48.
BRAND_ACCENT = "#F7B95B"
CAST_DIR = ROOT / "cast"

PILLARS = {
    "soft_romance": "First love, unspoken feelings, balcony glances, golden-hour walks",
    "rain_nostalgia": "Rainy windows, old memories, quiet city streets, reflective moods",
    "everyday_love": "Small gestures, coffee-shop moments, reconnecting, companionship",
    "dreamy_escapes": "Train windows, sunset journeys, solitude, peaceful exploration",
}
CHARACTERS = ("couple", "meera", "aarav", "none")
CAST = {
    "meera": "Meera, an original young Indian woman in her early twenties, long dark wavy hair, expressive brown eyes, "
             "a deep red knit cardigan over a cream top",
    "aarav": "Aarav, an original young Indian man in his mid twenties, short tousled black hair, a plaid flannel shirt "
             "over a white tee, dark trousers, a canvas backpack",
}
SHOT_IDS = ("wide", "medium", "detail")
# Seconds on screen: the wide opening, the closer moment, the small detail, then back to the opening so it loops.
# The whole Reel is 10 seconds or less, so a trending song's 7 to 10 second hook fits it.
TIMELINE = (("wide", 3.2), ("medium", 3.0), ("detail", 2.2), ("wide", 1.6))
# An optional longer cut (spec "seconds" above 12): two more shots, "close" and "glance", for about 20 seconds. The default
# stays 10 seconds; a longer Reel is a choice for one episode.
LONG_SHOT_IDS = ("close", "glance")
LONG_TIMELINE = (("wide", 4.0), ("medium", 3.4), ("close", 3.4), ("detail", 3.0), ("glance", 3.4), ("wide", 2.8))
LONG_THRESHOLD = 12.0
# The Reel lasts as long as its song, within these limits.
MIN_SECONDS = 7.0
MAX_SECONDS = 30.0
FADE = 0.55
PUSH = 0.06
MAX_TEXT_WORDS = 9
# A poem Reel shows an original poem a stanza at a time over the scenes, instead of one line.
POEM_STANZAS = (2, 6)
POEM_STANZA_WORDS = 16
POEM_LEAD_IN = 0.8
POEM_TAIL = 0.6
TEXT_BOX = {"x": 64, "y": 1190, "w": 866, "h": 250}
TEXT_AT = 0.9
TEXT_SIZE = 84
NO_TEXT = " No text, no captions, no lettering, no logos, no watermark, no user interface."
SAFE_SPACE = (
    " Compose the characters and the main action in the upper two thirds of the frame, framed from the waist up. "
    "Let the lower third of the scene itself be calm and open (a table, a path, ground, water or sky) with no faces or "
    "hands, for one short line of text. It is one continuous picture: no panels, strips, borders or collage."
)
SAME = (
    "Keep the exact same characters, faces, hair, clothes, place, lighting and painterly anime style as this image. "
    "This shot: "
)


def problems(spec) -> list:
    """What is missing or wrong. An empty list means the Reel can be made."""
    if not isinstance(spec, dict):
        return ["The mood spec must be an object."]
    found = []
    if spec.get("pillar") not in PILLARS:
        found.append(f"pillar must be one of {', '.join(PILLARS)}.")
    if spec.get("characters") not in CHARACTERS:
        found.append(f"characters must be one of {', '.join(CHARACTERS)}.")
    for field in ("setting", "mood", "caption"):
        if not str(spec.get(field) or "").strip():
            found.append(f"The mood spec needs a {field}.")
    poem = spec.get("poem")
    if poem is not None:
        stanzas = [str(item).strip() for item in poem] if isinstance(poem, list) else []
        if not POEM_STANZAS[0] <= len(stanzas) <= POEM_STANZAS[1] or not all(stanzas):
            found.append(f"The poem needs {POEM_STANZAS[0]} to {POEM_STANZAS[1]} non-empty stanzas.")
        elif any(len(item.split()) > POEM_STANZA_WORDS for item in stanzas):
            found.append(f"A stanza is longer than {POEM_STANZA_WORDS} words.")
    text = str(spec.get("text") or "").strip()
    if not text and not spec.get("lyrics") and poem is None:
        found.append("The mood spec needs one line of text.")
    elif len(text.split()) > MAX_TEXT_WORDS:
        found.append(f"The text line is longer than {MAX_TEXT_WORDS} words.")
    shots = {str(shot.get("id")): shot for shot in spec.get("shots") or [] if isinstance(shot, dict)}
    for shot_id in SHOT_IDS + (LONG_SHOT_IDS if is_long(spec) else ()):
        if not str((shots.get(shot_id) or {}).get("prompt") or "").strip():
            found.append(f"The mood spec needs a {shot_id} shot.")
    return found


def is_long(spec: dict) -> bool:
    """True for the optional 20-second cut, which needs the two extra shots."""
    try:
        return float(spec.get("seconds") or 0) > LONG_THRESHOLD
    except (TypeError, ValueError):
        return False


def _people(spec: dict) -> str:
    who = spec.get("characters")
    if who == "couple":
        return f"{CAST['meera']}; and {CAST['aarav']}"
    return CAST.get(str(who), "")


def shot_prompt(spec: dict, shot_id: str) -> str:
    """The image prompt for one shot, in the channel's painterly anime look."""
    look = story_module.STYLES[STYLE]["look"]
    avoid = story_module.STYLES[STYLE]["avoid"]
    prompt = str({str(s.get("id")): s for s in spec["shots"]}[shot_id].get("prompt")).strip()
    if shot_id == "wide":
        people = _people(spec)
        cast = (f" Original characters: {people}. Draw them exactly as they look in the reference image."
                if people else " No people in this scene.")
        return (f"Create an ORIGINAL vertical 9:16 cinematic illustrated scene for an Instagram Reel. {look}{avoid} "
                f"Mood: {spec['mood']}. Setting: {spec['setting']}.{cast} {prompt}{SAFE_SPACE}{NO_TEXT} Art style: "
                f"{story_module.STYLES[STYLE]['label']}.")
    if shot_id == "detail":
        # The third beat is a different, intimate picture: hands and objects, never faces.
        prompt += " Extreme close-up of hands and objects only, with no faces visible."
    return f"{SAME}{prompt} Show only the characters named in this shot; no one else appears.{SAFE_SPACE}{NO_TEXT} Art style: {story_module.STYLES[STYLE]['label']}. {avoid}"


def motion_prompt(spec: dict) -> str:
    """One seamless shot for the video model: subtle, natural, ending where it began so it can loop."""
    return (
        "Animate the supplied illustration into a seamless vertical cinematic shot. Preserve the original characters, "
        "outfit, faces and environment. Motion is subtle and natural: a light breeze moves hair and foliage; gentle "
        "breathing, blinking and small gestures; a slow, restrained camera push. Keep perspective and anatomy "
        f"stable. {str(spec.get('motion') or '').strip()} No abrupt cuts, distortions, flicker, unwanted objects or "
        "added text. End in a composition that can loop smoothly."
    ).strip()


def cast_sheet(spec: dict, generate=None) -> Path | None:
    """The saved reference sheet that keeps the recurring characters looking the same. Drawn once, then reused."""
    if spec.get("characters") == "none":
        return None
    # One sheet for the whole cast, so a solo scene still draws the same faces as the couple scenes.
    people = f"{CAST['meera']}; and {CAST['aarav']}"
    sheet = CAST_DIR / "a48" / "couple.png"
    if sheet.is_file():
        return sheet
    if generate is None:
        from art import openai_image  # noqa: PLC0415

        generate = openai_image
    made = generate(
        "Character reference sheet for a recurring animated series. " + story_module.STYLES[STYLE]["look"]
        + f"Original characters, full body, standing side by side, calm neutral expressions, plain soft warm background: "
        f"{people}. Clear faces and outfits so they can be redrawn identically." + NO_TEXT
    )
    if not made.get("ok") or made.get("image") is None:
        return None
    sheet.parent.mkdir(parents=True, exist_ok=True)
    story_module._vertical(made["image"]).save(sheet)
    return sheet


def make_frames(spec: dict, folder: Path, *, generate=None, edit=None, sheet=None) -> dict:
    """Draw the wide, medium and detail stills. The wide shot comes from the cast sheet, the others are edits of it."""
    if generate is None or edit is None:
        from art import openai_edit_image, openai_image  # noqa: PLC0415

        generate = generate or openai_image
        edit = edit or openai_edit_image
    folder.mkdir(parents=True, exist_ok=True)
    ids = SHOT_IDS + (LONG_SHOT_IDS if is_long(spec) else ())
    paths = {shot_id: folder / f"mood-{shot_id}.png" for shot_id in ids}
    if not paths["wide"].is_file():
        reference = sheet if sheet is not None else cast_sheet(spec, generate)
        prompt = shot_prompt(spec, "wide")
        made = edit(reference, prompt, require_reference=True) if reference else generate(prompt)
        if not made.get("ok") or made.get("image") is None:
            return {"ok": False, "error": made.get("error") or "The opening scene could not be drawn."}
        story_module._vertical(made["image"]).save(paths["wide"])
    for shot_id in ids[1:]:
        if paths[shot_id].is_file():
            continue
        made = edit(paths["wide"], shot_prompt(spec, shot_id), require_reference=True)
        if not made.get("ok") or made.get("image") is None:
            return {"ok": False, "error": made.get("error") or f"The {shot_id} shot could not be drawn."}
        story_module._vertical(made["image"]).save(paths[shot_id])
    return {"ok": True, "frames": {key: str(path) for key, path in paths.items()}, "error": ""}


def target_seconds(spec: dict):
    """The Reel length the spec asks for, kept between MIN_SECONDS and MAX_SECONDS, or None to use the default cut."""
    try:
        wanted = float(spec.get("seconds") or 0)
    except (TypeError, ValueError):
        return None
    return round(min(max(wanted, MIN_SECONDS), MAX_SECONDS), 3) if wanted > 0 else None


def _default(name: str):
    from art import openai_edit_image, openai_image  # noqa: PLC0415

    return {"openai_image": openai_image, "openai_edit_image": openai_edit_image}[name]


def redraw(spec: dict, folder: Path, frames: dict, shot_id: str, fix: str, *, generate, edit, sheet) -> bool:
    """Draw one still again with the picture editor's fix added to its prompt. The old file is replaced only on success."""
    wide = Path(frames["wide"])
    note = f" Fix: {fix}" if fix else ""
    if shot_id == "wide":
        reference = sheet if sheet is not None else cast_sheet(spec, generate)
        prompt = shot_prompt(spec, "wide") + note
        made = edit(reference, prompt, require_reference=True) if reference else generate(prompt)
    else:
        made = edit(wide, shot_prompt(spec, shot_id) + note, require_reference=True)
    if not made.get("ok") or made.get("image") is None:
        return False
    story_module._vertical(made["image"]).save(frames[shot_id])
    return True


def edit_pictures(spec: dict, folder: Path, frames: dict, *, generate, edit, sheet, review=None) -> dict:
    """Self-critique: the picture editor reviews the stills and any that fail are redrawn once. Never blocks the Reel.

    If the opening scene is redrawn, the shots that were edited from it are redrawn too so they still match it.
    """
    report = {"score": 0, "story": "", "fixed": [], "left": [], "error": ""}
    try:
        if review is None:
            import mood_critic  # noqa: PLC0415

            review = mood_critic.review_frames
        first = review(spec, frames)
    except Exception as exc:  # The reel is still made when the editor is unavailable.
        report["error"] = " ".join(str(exc).split())[:200]
        return report
    report["score"], report["story"] = first["score"], first["story"]
    failed = {shot_id: v for shot_id, v in first["shots"].items() if not v["pass"]}
    if "wide" in failed:
        # Others are edits of the opening scene: redraw them against the new one, keeping any fix they already have.
        for shot_id in frames:
            failed.setdefault(shot_id, {"issue": "Redrawn to match the new opening scene.", "fix": ""})
    for shot_id in [key for key in frames if key in failed]:
        verdict = failed[shot_id]
        if redraw(spec, folder, frames, shot_id, verdict["fix"], generate=generate, edit=edit, sheet=sheet):
            report["fixed"].append({"shot": shot_id, "issue": verdict["issue"], "fix": verdict["fix"]})
        else:
            report["left"].append({"shot": shot_id, "issue": verdict["issue"]})
    return report


def timeline(frames: dict, long: bool = False, seconds=None) -> tuple:
    """The shots with their start times, and the total length.

    With `seconds`, every shot is scaled so the Reel lasts exactly that long (the song's length): the same shots and order,
    held longer or shorter. The last shot takes the rounding so the total is exact.
    """
    base = LONG_TIMELINE if long else TIMELINE
    scale = seconds / sum(duration for _, duration in base) if seconds else 1.0
    shots, cursor = [], 0.0
    for index, (shot_id, duration) in enumerate(base):
        length = round(duration * scale, 3)
        if index == len(base) - 1 and seconds:
            length = round(seconds - cursor, 3)
        shots.append({"start": round(cursor, 3), "duration": length, "role": shot_id, "path": frames[shot_id]})
        cursor += length
    return shots, round(cursor, 3)


def layout(spec: dict, total: float, accents: list) -> dict:
    """One scene for the whole Reel: a single line of text in the safe zone, fading in under the opening.

    In lyrics mode there is no text: the lower third stays clear for Instagram's Lyrics sticker.
    """
    canvas = {"width": W, "height": H, "fps": FPS, **COLORS}
    if isinstance(spec.get("poem"), list) and spec["poem"]:
        stanzas = [str(item).strip() for item in spec["poem"]]
        span = round((total - POEM_LEAD_IN - POEM_TAIL) / len(stanzas), 3)
        # The renderer sets the video's length from the scenes, so they must cover it end to end with no gaps:
        # an empty lead-in, one scene per stanza (each fades as the next pops in), and an empty tail.
        scenes = [{"start_seconds": 0, "duration_seconds": POEM_LEAD_IN, "camera": "steady", "elements": []}]
        for index, stanza in enumerate(stanzas):
            element = _element(f"poem-{index + 1}", "kinetic", dict(TEXT_BOX), label=stanza, center=True, size=76,
                               min_size=44, at=0.0, accents=accents, keywords=[])
            scenes.append({"start_seconds": round(POEM_LEAD_IN + index * span, 3), "duration_seconds": span,
                           "camera": "steady", "elements": [element]})
        end = round(POEM_LEAD_IN + len(stanzas) * span, 3)
        scenes.append({"start_seconds": end, "duration_seconds": round(total - end, 3), "camera": "steady", "elements": []})
        return {"canvas": canvas, "scenes": scenes}
    if spec.get("lyrics"):
        return {"canvas": canvas, "scenes": [{"start_seconds": 0, "duration_seconds": total, "camera": "steady", "elements": []}]}
    words = str(spec.get("text") or "").split()
    stress = str(spec.get("stress") or "").strip().lower()
    element = _element("mood-text", "kinetic", dict(TEXT_BOX), label=" ".join(words), center=True, size=TEXT_SIZE,
                       min_size=48, at=TEXT_AT, accents=accents, keywords=[stress] if stress else [])
    return {"canvas": canvas,
            "scenes": [{"start_seconds": 0, "duration_seconds": total, "camera": "steady", "elements": [element]}]}


def layout_problems(renderer: dict) -> list:
    found = []
    for scene in renderer.get("scenes") or []:
        for element in scene.get("elements") or []:
            box = element["box"]
            if box["x"] < SAFE["left"] or box["x"] + box["w"] > SAFE["right"] or box["y"] + box["h"] > SAFE["bottom"]:
                found.append(f"{element.get('id')} is outside the safe zone.")
    return found


def build_mood_reel(spec: dict, folder: Path, *, generate=None, edit=None, animate=None, render=None, sheet=None,
                    critic=None) -> dict:
    """Make the silent Reel, ready to be paired with a song in Instagram. Never publishes."""
    missing = problems(spec)
    if missing:
        return {"ok": False, "error": "The mood spec is not valid: " + " ".join(missing), "problems": missing}
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    drawn = make_frames(spec, folder, generate=generate, edit=edit, sheet=sheet)
    if not drawn.get("ok"):
        return {"ok": False, "error": drawn["error"]}
    frames = drawn["frames"]
    # The picture editor looks at the stills before the Reel is made. It is skipped when the drawing functions are injected
    # (tests) unless a critic is given too, and `critic=False` turns it off.
    skip = critic is False or (critic is None and (generate is not None or edit is not None))
    edited = {} if skip else edit_pictures(spec, folder, frames, generate=generate or _default("openai_image"),
                                           edit=edit or _default("openai_edit_image"), sheet=sheet, review=critic)
    shots, total = timeline(frames, is_long(spec), target_seconds(spec))
    accents = [{"start": 0.0, "color": BRAND_ACCENT}]
    notes = []
    backdrop = {"shots": shots, "accents": accents, "fade": FADE, "push": PUSH, "mark": ACCOUNT_MARK,
                "mark_fallback": ACCOUNT_NAME}
    clip = folder / "mood.mp4"
    if animate is not None or not clip.is_file():
        if animate is None:
            import director_reel  # noqa: PLC0415

            animate = director_reel._generate_veo_clip
        if not (clip.is_file() and clip.stat().st_size > 0):
            made = animate(Path(frames["wide"]), motion_prompt(spec), clip)
            if not (made.get("ok") and clip.is_file()):
                notes.append(f"{made.get('error') or 'The video model did not return a clip.'} "
                             "The scene plays as moving stills instead.")
    if clip.is_file() and clip.stat().st_size > 0:
        backdrop = {"video": str(clip), "accents": accents, "mark": ACCOUNT_MARK, "mark_fallback": ACCOUNT_NAME}
    renderer = layout(spec, total, accents)
    issues = layout_problems(renderer)
    if issues:
        return {"ok": False, "error": "The layout broke a safe-zone rule: " + " ".join(issues), "problems": issues}
    (folder / "mood-spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    payload = {"renderer": renderer, "output": str(folder / "reel.mp4"), "backdrop": backdrop}  # No voiceover: silent.
    result = (render or render_explainer)(payload)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "The Reel could not be rendered.", "notes": notes}
    return {
        "ok": True, "path": result.get("path") or "", "cover": result.get("cover") or "", "seconds": result.get("seconds"),
        "motion": "video" if "video" in backdrop else "stills", "lyrics": bool(spec.get("lyrics")),
        "poem": [str(item) for item in spec.get("poem") or []],
        "pictures": edited, "caption": str(spec.get("caption") or "").strip(),
        "songs": [str(song) for song in spec.get("songs") or []], "notes": notes, "error": "",
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "Usage: mood_reel.py spec.json out_folder"}))
        return 1
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(build_mood_reel(spec, Path(sys.argv[2])), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
