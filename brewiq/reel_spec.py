"""ReelSpec: one plan for every BrewIQ reel and explainer. It is checked, laid out, built, and rendered here.

The video director writes a ReelSpec. It names a format and a list of beats; it never gives pixel positions.
The layout below owns every position, so text stays inside the Instagram safe zones by construction.
Nothing here publishes, and no generated video is used: motion comes from the compositor, stills come from
gpt-image, narration comes from voice.py, and the host is always the pose library, so the character never changes.

Run: python reel_spec.py spec.json out_folder [--preview]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voice as voice_module  # noqa: E402
from explainer_render import (  # noqa: E402
    BRAND_COLORS, FIGURE_WIDTH, MIN_SWATCH_CONTRAST, POSE_FILES, POSE_HEAD, TILE_GLYPHS, contrast_ratio, load_pose_library,
    render_explainer,
)  # noqa: E402

FORMATS = ("beat_explainer", "chapter_build", "workflow_reel", "product_shot")
SHOT_MODES = ("graphics", "pose", "still")
ALLOWED_MODES = {
    "chapter_build": ("graphics", "pose", "still"),
    "beat_explainer": ("graphics", "still"),
    "workflow_reel": ("graphics", "still"),
    "product_shot": ("still",),
}
POSES = tuple(name for name in POSE_FILES if not name.startswith("walk"))
CAMERAS = ("steady", "push_in", "pull_out")
SUBJECTS = ("character", "product", "scene")
ROLE_LABELS = {
    "intro": "Intro",
    "problem": "Problem",
    "solution": "Solution",
    "use_case": "Use case",
    "proof": "Proof",
    "recap": "Recap",
    "cta": "Call to action",
}

W, H, FPS = 1080, 1920, 30
# Content stays inside these lines. The right edge clears the Reels buttons, and the bottom clears the caption.
SAFE = {"left": 64, "right": 930, "top": 190, "bottom": 1500}
LOWER_THIRD_LEFT = 40
BEAT_PAD = 0.35
MIN_BEAT = 2.4
MAX_TOTAL = 75.0

COLORS = dict(BRAND_COLORS)

# Layout regions. The host stands on the left with the cut-off edge hidden behind the lower third.
LOWER = {"x": LOWER_THIRD_LEFT, "y": 1330, "w": 890, "h": 170}
HOST_SCALE = 0.48  # About 30% of the frame, so the words lead.
HOST_FOOT = 1460
HOST_LEFT = 36
MAX_HOST_SHIFT = 150
HOST = {"x": HOST_LEFT, "y": 0, "w": round(620 * HOST_SCALE), "h": 900}
HOST_ZONE_Y = (540, 1330)
COLUMN = {"x": 440, "y": 470, "w": 490, "h": 780}
RAIL_ROW = {"x": 64, "y": 190, "w": 640, "h": 100}  # The wordmark takes the top-right corner.
HERO = {"x": 64, "y": 256, "w": 866, "h": 754}  # Starts below the wordmark.
CHIPS_ROW = {"x": 64, "y": 1030, "w": 866, "h": 74}
HEADLINE_ROW = {"x": 64, "y": 1130, "w": 866, "h": 180}
WORKFLOW_IMAGE = {"x": 64, "y": 250, "w": 866, "h": 680}
WORKFLOW_PROMPT = {"x": 64, "y": 960, "w": 866, "h": 340}
PRODUCT_HERO = {"x": 64, "y": 220, "w": 866, "h": 840}
PRODUCT_THUMB = {"x": 64, "y": 1090, "w": 300, "h": 210}
PRODUCT_PROMPT = {"x": 390, "y": 1090, "w": 540, "h": 210}


def _words(text) -> int:
    return len(str(text or "").split())


def _text(value) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def validate_spec(spec) -> list:
    """Return every problem found. An empty list means the spec can be built."""
    if not isinstance(spec, dict):
        return ["The reel spec must be a JSON object."]
    problems: list = []
    fmt = spec.get("format")
    if fmt not in FORMATS:
        problems.append(f"format must be one of {', '.join(FORMATS)}.")
    canvas = spec.get("canvas")
    if isinstance(canvas, dict):
        if canvas.get("width") not in (None, W) or canvas.get("height") not in (None, H):
            problems.append(f"The canvas must be {W} by {H}.")
    if spec.get("hook") is not None and _words(spec.get("hook")) > 8:
        problems.append("The hook is longer than 8 words.")
    beats = spec.get("beats")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 10:
        problems.append("A reel needs 3 to 10 beats.")
        return problems

    seen: set = set()
    has_still = False
    for index, beat in enumerate(beats, start=1):
        if not isinstance(beat, dict):
            problems.append(f"Beat {index} must be an object.")
            continue
        label = f"Beat {_text(beat.get('id')) or index}"
        beat_id = _text(beat.get("id"))
        if not beat_id or not beat_id.replace("_", "").replace("-", "").isalnum():
            problems.append(f"Beat {index} needs a short id with letters, numbers, - or _.")
        elif beat_id in seen:
            problems.append(f"{label}: the id is used twice.")
        seen.add(beat_id)

        voice_words = _words(beat.get("voice"))
        if not 3 <= voice_words <= 45:
            problems.append(f"{label}: the voice line must be 3 to 45 words.")
        lower = _text(beat.get("lower_third"))
        if not lower or len(lower) > 90:
            problems.append(f"{label}: lower_third is required and must be 90 characters or fewer.")

        shot = beat.get("shot") if isinstance(beat.get("shot"), dict) else {}
        mode = shot.get("mode")
        if mode not in SHOT_MODES:
            problems.append(
                f"{label}: shot mode must be graphics, pose, or still. Generated video clips are not available."
            )
            continue
        if fmt in ALLOWED_MODES and mode not in ALLOWED_MODES[fmt]:
            problems.append(f"{label}: {fmt} does not allow the {mode} shot mode.")
        if shot.get("camera") is not None and shot.get("camera") not in CAMERAS:
            problems.append(f"{label}: camera must be steady, push_in, or pull_out.")
        if shot.get("continuous"):
            problems.append(f"{label}: a continuous shot cannot be made without video generation. Use a still.")
        if beat.get("pose") is not None and beat.get("pose") not in POSES:
            problems.append(f"{label}: pose must be one of {', '.join(POSES)}.")
        if mode == "still":
            has_still = True
            if _words(shot.get("prompt")) < 8:
                problems.append(f"{label}: a still needs a prompt of at least 8 words.")
            if shot.get("subject") is not None and shot.get("subject") not in SUBJECTS:
                problems.append(f"{label}: subject must be character, product, or scene.")
            if fmt == "product_shot" and shot.get("subject") != "product":
                problems.append(f"{label}: every product_shot still must use the product subject.")

        on_screen = beat.get("on_screen") if isinstance(beat.get("on_screen"), dict) else {}
        if len(_text(on_screen.get("headline"))) > 60:
            problems.append(f"{label}: headline must be 60 characters or fewer.")
        if len(_text(on_screen.get("card"))) > 70:
            problems.append(f"{label}: card must be 70 characters or fewer.")
        if len(_text(on_screen.get("prompt_text"))) > 220:
            problems.append(f"{label}: prompt_text must be 220 characters or fewer.")
        stat = on_screen.get("stat")
        if stat is not None and (not isinstance(stat, dict) or len(_text(stat.get("value"))) > 4
                                 or len(_text(stat.get("unit"))) > 12):
            problems.append(f"{label}: stat needs a value of 4 characters or fewer and a short unit.")
        tiles = on_screen.get("tiles")
        if tiles is not None:
            problems.extend(_tile_problems(label, fmt, mode, tiles, on_screen.get("tile_focus")))
        elif on_screen.get("tile_focus") is not None:
            problems.append(f"{label}: tile_focus needs tiles.")
        if on_screen.get("swatch") is not None:
            problems.extend(_swatch_problems(label, fmt, mode, on_screen))
        if on_screen.get("poses") is not None:
            names = on_screen.get("poses")
            if not isinstance(names, list) or not names or any(name not in POSES for name in names):
                problems.append(f"{label}: poses must list names from the pose library.")

        if fmt == "chapter_build":
            chapter = _text(beat.get("chapter"))
            if not chapter or len(chapter) > 10:
                problems.append(f"{label}: chapter is required and must be 10 characters or fewer.")
        if fmt == "beat_explainer" and beat.get("role") not in ROLE_LABELS:
            problems.append(f"{label}: role must be one of {', '.join(ROLE_LABELS)}.")
        if fmt == "workflow_reel" and not _text(on_screen.get("prompt_text")):
            problems.append(f"{label}: workflow_reel beats need prompt_text for the on-screen prompt card.")

    if fmt == "chapter_build":
        chapters = _chapters(beats)
        if len(chapters) > 8:
            problems.append("chapter_build supports at most 8 chapters.")
        first = (beats[0].get("on_screen") or {}) if isinstance(beats[0], dict) else {}
        if not (_text(spec.get("title")) or _text(first.get("headline"))):
            problems.append("chapter_build needs a title for the opening beat.")
    if fmt == "beat_explainer":
        if len(_chips(beats)) > 6:
            problems.append("beat_explainer supports at most 6 labelled beats.")
    if fmt == "product_shot" and not _text(spec.get("product_reference")):
        problems.append("product_shot needs product_reference, the image that fixes what the product looks like.")
    if has_still and not _text(spec.get("disclosure")):
        problems.append("A reel that uses generated stills needs a disclosure line for the caption.")
    if fmt == "product_shot" and "animated still" not in _text(spec.get("disclosure")).lower():
        problems.append('A product_shot disclosure must say "animated still" so it is not mistaken for filmed footage.')
    return problems


TILE_FORMATS = ("beat_explainer", "workflow_reel")


def _tile_problems(label: str, fmt, mode, tiles, focus) -> list:
    problems: list = []
    if fmt not in TILE_FORMATS:
        problems.append(f"{label}: tiles can only be used in {' or '.join(TILE_FORMATS)}.")
    if mode == "still":
        problems.append(f"{label}: a beat shows either a still or a tile grid, not both.")
    if not isinstance(tiles, list) or not 4 <= len(tiles) <= 16:
        return problems + [f"{label}: tiles needs 4 to 16 entries."]
    for number, tile in enumerate(tiles, start=1):
        if not isinstance(tile, dict):
            problems.append(f"{label}: tile {number} must be an object.")
            continue
        name = _text(tile.get("label"))
        if not name or len(name) > 24:
            problems.append(f"{label}: tile {number} needs a label of 24 characters or fewer.")
        if len(_text(tile.get("value"))) > 8:
            problems.append(f"{label}: tile {number} value must be 8 characters or fewer.")
        if tile.get("glyph") is not None and tile.get("glyph") not in TILE_GLYPHS:
            problems.append(f"{label}: tile {number} glyph must be one of {', '.join(TILE_GLYPHS)}.")
    if focus is not None and (isinstance(focus, bool) or not isinstance(focus, int) or not 1 <= focus <= len(tiles)):
        problems.append(f"{label}: tile_focus must be a tile number from 1 to {len(tiles)}.")
    return problems


HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _swatch_problems(label: str, fmt, mode, on_screen: dict) -> list:
    """A color pair: two named hex colors that can be read against each other."""
    problems: list = []
    swatch = on_screen.get("swatch")
    if fmt not in TILE_FORMATS:
        problems.append(f"{label}: a color pair can only be used in {' or '.join(TILE_FORMATS)}.")
    if mode == "still" or on_screen.get("tiles"):
        problems.append(f"{label}: a beat shows one of a still, a tile grid, or a color pair.")
    if not isinstance(swatch, dict) or not all(isinstance(swatch.get(side), dict) for side in ("top", "bottom")):
        return problems + [f"{label}: swatch needs a top and a bottom color, each with a name and a hex."]
    colors: list = []
    for side in ("top", "bottom"):
        item = swatch[side]
        name = _text(item.get("name"))
        code = _text(item.get("hex"))
        if not name or len(name) > 20:
            problems.append(f"{label}: the {side} color needs a name of 20 characters or fewer.")
        if not HEX_COLOR.match(code):
            problems.append(f"{label}: the {side} hex must look like #014BAA.")
        else:
            colors.append((name, tuple(int(code[i:i + 2], 16) for i in (1, 3, 5))))
    if len(colors) == 2:
        ratio = contrast_ratio(colors[0][1], colors[1][1])
        if ratio < MIN_SWATCH_CONTRAST:
            problems.append(
                f"{label}: {colors[0][0]} and {colors[1][0]} have a contrast of {ratio:.1f} to 1. "
                f"A pair needs at least {MIN_SWATCH_CONTRAST:g} to 1 so the name can be read."
            )
    return problems


def _chapters(beats: list) -> list:
    chapters: list = []
    for beat in beats:
        chapter = _text(beat.get("chapter")).upper() if isinstance(beat, dict) else ""
        if chapter and chapter not in chapters:
            chapters.append(chapter)
    return chapters


def _chips(beats: list) -> list:
    chips: list = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        label = _text(beat.get("chapter")) or ROLE_LABELS.get(beat.get("role"), "")
        label = label.upper()
        if label and label not in chips:
            chips.append(label)
    return chips


def beat_timing(beats: list, voice_seconds: list) -> list:
    """Start and length for each beat. A beat lasts as long as its narration plus a short pad."""
    timing = []
    cursor = 0.0
    for beat, spoken in zip(beats, voice_seconds):
        length = round(max(float(spoken) + BEAT_PAD, MIN_BEAT), 3)
        timing.append({"id": beat["id"], "start": round(cursor, 3), "duration": length, "voice_seconds": round(float(spoken), 3)})
        cursor += length
    return timing


def _box(region: dict, **changes) -> dict:
    box = dict(region)
    box.update(changes)
    return box


def _element(element_id: str, kind: str, box: dict, *, motion: str = "slide_up", at: float = 0.1, length: float = 0.45,
             persist: bool = False, **extra) -> dict:
    element = {
        "id": element_id, "type": kind, "box": box,
        "enter_at": 0.0 if persist else at, "enter_duration": length,
        "enter_motion": "none" if persist else motion, "exit_motion": "hold",
    }
    element.update(extra)
    return element


def _mmss(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def layout(spec: dict, timing: list, plates: dict) -> dict:
    """Turn a checked spec into the renderer's scenes. Positions come from the regions above."""
    fmt = spec["format"]
    beats = spec["beats"]
    scenes = []
    previous_pose = None
    previous_tiles = None
    left = host_left(beats) if fmt == "chapter_build" else HOST_LEFT
    for index, (beat, slot) in enumerate(zip(beats, timing)):
        shot = beat.get("shot") or {}
        on_screen = dict(beat.get("on_screen") or {})
        if fmt == "chapter_build" and index == 0:
            if _text(spec.get("title")) and not on_screen.get("headline"):
                on_screen["headline"] = _text(spec.get("title"))
            if spec.get("stat") and not on_screen.get("stat"):
                on_screen["stat"] = spec.get("stat")
        key = f"b{index + 1}"
        plate = (plates.get(beat["id"]) or {}).get("path")
        elements: list = []
        if fmt == "chapter_build":
            elements = _chapter_scene(spec, beat, on_screen, key, index, plate, shot, previous_pose, left)
            previous_pose = beat.get("pose") or "neutral"
        elif fmt == "beat_explainer":
            elements = _explainer_scene(spec, beat, on_screen, key, index, plate, shot, previous_tiles)
        elif fmt == "workflow_reel":
            elements = _workflow_scene(spec, beat, on_screen, key, index, plate, shot, slot, previous_tiles)
        elif fmt == "product_shot":
            elements = _product_scene(spec, beat, on_screen, key, plate, shot)
        previous_tiles = on_screen.get("tiles") or None
        caption = _text(beat.get("lower_third"))
        headline = next((_text(e.get("label")) for e in elements if e.get("type") == "title"), "")
        if caption == headline and 0 < len(_text(beat.get("voice"))) <= 90:
            # The headline already shows these words, so the caption carries the full spoken sentence.
            caption = _text(beat.get("voice"))
        elements.append(_element(f"{key}-lower", "lower_third", dict(LOWER), label=caption,
                                 motion="slide_up", at=0.15, length=0.4))
        scenes.append({
            "start_seconds": slot["start"], "duration_seconds": slot["duration"],
            "camera": shot.get("camera") or "steady", "elements": elements,
        })
    return {"canvas": {"width": W, "height": H, "fps": FPS, **COLORS}, "scenes": scenes}


def _rail(spec: dict, beats: list, key: str, active: int, region: dict, *, chips: list, label: str, timeline: bool) -> dict:
    timer = None  # The wordmark sits where the countdown was.
    box = dict(region)
    box["h"] = (50 if label or timer else 0) + (46 if chips else 0) + (24 if timeline and chips else 0) + 4
    return _element(f"{key}-rail", "rail", box, persist=True, label=label, chips=chips, active=active,
                    timer=timer, timeline=timeline)


def _pose_right(name: str, left: float) -> float:
    """Right edge, in canvas pixels, of a pose when the host's left anchor is at `left`."""
    library = load_pose_library()
    entry = library.get(name) or library.get("neutral")
    if not entry:
        return left + 500
    scale = HOST["w"] / FIGURE_WIDTH
    bounds = entry[0].getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    origin = left - (POSE_HEAD[0] - FIGURE_WIDTH / 2) * scale
    return origin + (bounds[2] if bounds else entry[0].width) * scale


def host_left(beats: list) -> int:
    """One left position for the whole reel, far enough left that his widest pose clears the text column."""
    used = {(beat.get("pose") or "neutral") for beat in beats if isinstance(beat, dict)}
    widest = max(_pose_right(name, HOST_LEFT) for name in used)
    shift = min(MAX_HOST_SHIFT, max(0, widest - (COLUMN["x"] - 20)))
    return round(HOST_LEFT - shift)


def _host(key: str, beat: dict, previous_pose, left: int) -> dict:
    pose = beat.get("pose") or "neutral"
    box = dict(HOST, x=left)
    zone = {"x": min(left, 0), "y": HOST_ZONE_Y[0], "w": COLUMN["x"] - 20 - min(left, 0), "h": HOST_ZONE_Y[1] - HOST_ZONE_Y[0]}
    return _element(f"{key}-host", "character", box, persist=True, pose=pose, foot_y=HOST_FOOT,
                    settle=pose != previous_pose, zone=zone)


def _chapter_scene(spec, beat, on_screen, key, index, plate, shot, previous_pose, left) -> list:
    chips = _chapters(spec["beats"])
    active = chips.index(_text(beat.get("chapter")).upper()) if _text(beat.get("chapter")).upper() in chips else 0
    label = _text(spec.get("rail_label"))
    elements = [_rail(spec, spec["beats"], key, active, RAIL_ROW, chips=chips, label=label, timeline=False)]
    if shot.get("mode") == "still" and plate:
        elements.append(_element(f"{key}-image", "image", _box(COLUMN, y=520, h=560), path=plate, zoom=0.08,
                                 sweep=True, tag="Illustration", motion="scale_in"))
    elif on_screen.get("headline"):
        elements.append(_element(f"{key}-title", "title", _box(COLUMN, h=600), label=_text(on_screen.get("headline")),
                                 stat=on_screen.get("stat"), motion="slide_up", at=0.1, length=0.55))
    elif on_screen.get("prompt_text"):
        elements.append(_element(f"{key}-prompt", "prompt_card", _box(COLUMN, y=520, h=520),
                                 label=_text(on_screen.get("card")) or "PROMPT", text=_text(on_screen.get("prompt_text")),
                                 motion="slide_up"))
    elif on_screen.get("card"):
        elements.append(_element(f"{key}-card", "card", _box(COLUMN, y=560, h=340), label=_text(on_screen.get("card")),
                                 motion="snap", at=0.2, length=0.4))
    elif _text(beat.get("lower_third")):
        # A beat with nothing on screen left half the frame empty. Show its words as the headline.
        elements.append(_element(f"{key}-title", "title", _box(COLUMN, h=600), label=_text(beat.get("lower_third")),
                                 motion="slide_up", at=0.1, length=0.55))
    elements.append(_host(key, beat, previous_pose, left))
    return elements


def _screen_elements(key: str, region: dict, screen: dict) -> list:
    """A sample app screen, and its summary panel when the beat shows the after state."""
    elements = [_element(f"{key}-screen", "screen", dict(region), motion="scale_in", at=0.0, length=0.45, screen=screen)]
    result = [_text(item) for item in (screen.get("result") or []) if _text(item)][:3]
    if result:
        # The panel covers the lower rows and the action button, like a summary sheet sliding up.
        panel = {"x": region["x"] + 28, "y": region["y"] + region["h"] - 392, "w": region["w"] - 56, "h": 372}
        elements.append(_element(f"{key}-summary", "summary", panel, motion="snap", at=1.1, length=0.35,
                                 label=_text(screen.get("result_label")) or "Summary", items=result))
    return elements


def _swatch_element(key: str, region: dict, on_screen: dict) -> dict:
    swatch = on_screen["swatch"]
    pair = [{"name": _text(swatch[side].get("name")), "hex": _text(swatch[side].get("hex")).upper()}
            for side in ("top", "bottom")]
    return _element(f"{key}-swatch", "swatch", dict(region), motion="scale_in", at=0.0, length=0.5, swatch=pair)


def _tiles_element(key: str, region: dict, on_screen: dict, previous) -> dict:
    """The tile grid. The first beat that shows a grid reveals it tile by tile; later beats with the same grid
    keep it on screen and only move the focus, so the viewer sees one grid and not a restart."""
    tiles = [dict(tile) for tile in on_screen["tiles"]]
    same = previous is not None and [t.get("label") for t in previous] == [t.get("label") for t in tiles]
    stagger = 0 if same else round(min(0.1, 1.1 / len(tiles)), 3)
    revealed = 0.0 if same else (len(tiles) - 1) * stagger + 0.32
    focus = on_screen.get("tile_focus")
    return _element(f"{key}-tiles", "tiles", dict(region), motion="none", at=0.0, length=0.01, tiles=tiles,
                    stagger=stagger, focus=focus, focus_at=round(revealed + (0.5 if not same else 0.25), 3))


def _explainer_scene(spec, beat, on_screen, key, index, plate, shot, previous_tiles=None) -> list:
    chips = _chips(spec["beats"])
    label = (_text(beat.get("chapter")) or ROLE_LABELS.get(beat.get("role"), "")).upper()
    active = chips.index(label) if label in chips else 0
    elements: list = []
    if on_screen.get("swatch"):
        elements.append(_swatch_element(key, HERO, on_screen))
    elif on_screen.get("tiles"):
        elements.append(_tiles_element(key, HERO, on_screen, previous_tiles))
    elif shot.get("mode") == "still" and plate:
        elements.append(_element(f"{key}-hero", "image", dict(HERO), path=plate, zoom=0.1, sweep=True,
                                 tag="Illustration", motion="scale_in", at=0.0, length=0.5))
    elif isinstance(on_screen.get("screen"), dict):
        elements.extend(_screen_elements(key, HERO, on_screen["screen"]))
    elif _text(on_screen.get("card")):
        # Only a card with its own words. Repeating the headline here showed it twice.
        elements.append(_element(f"{key}-hero", "card", dict(HERO), label=_text(on_screen.get("card")),
                                 motion="scale_in", at=0.0, length=0.5))
    elements.append(_rail(spec, spec["beats"], key, active, CHIPS_ROW, chips=chips, label="", timeline=True))
    headline = _text(on_screen.get("headline")) or _text(spec.get("title")) if index == 0 else _text(on_screen.get("headline"))
    if headline:
        elements.append(_element(f"{key}-title", "title", dict(HEADLINE_ROW), label=headline, stat=None,
                                 motion="slide_up", at=0.15))
    return elements


def _workflow_scene(spec, beat, on_screen, key, index, plate, shot, slot, previous_tiles=None) -> list:
    elements: list = []
    if on_screen.get("swatch"):
        elements.append(_swatch_element(key, WORKFLOW_IMAGE, on_screen))
    elif on_screen.get("tiles"):
        elements.append(_tiles_element(key, WORKFLOW_IMAGE, on_screen, previous_tiles))
    elif shot.get("mode") == "still" and plate:
        elements.append(_element(f"{key}-image", "image", dict(WORKFLOW_IMAGE), path=plate, zoom=0.08, sweep=True,
                                 motion="scale_in", at=0.0, length=0.5))
    elif on_screen.get("poses"):
        elements.append(_element(f"{key}-sheet", "sheet", dict(WORKFLOW_IMAGE),
                                 label=_text(on_screen.get("card")) or "Character", poses=on_screen.get("poses"),
                                 captions=on_screen.get("captions") or [], motion="scale_in", at=0.0, length=0.5))
    else:
        elements.append(_element(f"{key}-card", "card", dict(WORKFLOW_IMAGE), label=_text(on_screen.get("card")),
                                 motion="scale_in", at=0.0, length=0.5))
    scene_number = sum(1 for earlier in spec["beats"][: index + 1] if (earlier.get("shot") or {}).get("mode") == "still")
    when = f"{_mmss(slot['start'])}–{_mmss(slot['start'] + slot['duration'])}"
    meta = f"Scene {scene_number} · {when}" if shot.get("mode") == "still" else f"Setup · {when}"
    elements.append(_element(f"{key}-prompt", "prompt_card", dict(WORKFLOW_PROMPT), label="PROMPT", meta=meta,
                             text=_text(on_screen.get("prompt_text")), motion="slide_up", at=0.2))
    elements.insert(0, _element(f"{key}-rail", "rail", _box(RAIL_ROW, y=190, h=48), persist=True,
                                label=_text(spec.get("rail_label")) or "Workflow",
                                timer=None, chips=[], active=0,
                                timeline=False))
    return elements


def _product_scene(spec, beat, on_screen, key, plate, shot) -> list:
    elements = [
        _element(f"{key}-hero", "image", dict(PRODUCT_HERO), path=plate, zoom=0.1, sweep=True, tag="Animated still",
                 motion="scale_in", at=0.0, length=0.5),
        _element(f"{key}-product", "image", dict(PRODUCT_THUMB), path=_text(spec.get("product_reference")),
                 tag="Product", motion="slide_up", at=0.2),
        _element(f"{key}-prompt", "prompt_card", dict(PRODUCT_PROMPT), label="PROMPT",
                 text=_text(on_screen.get("prompt_text")), motion="slide_up", at=0.3),
    ]
    return elements


def _intersects(a: dict, b: dict) -> bool:
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def layout_problems(renderer: dict) -> list:
    """Check every scene: content inside the safe zones, and no two blocks on top of each other."""
    problems = []
    for number, scene in enumerate(renderer.get("scenes") or [], start=1):
        boxes = []
        for element in scene.get("elements") or []:
            box = element.get("box") or {}
            kind = element.get("type")
            if kind == "character":
                box = element.get("zone") or {"x": 0, "y": HOST_ZONE_Y[0], "w": 520, "h": HOST_ZONE_Y[1] - HOST_ZONE_Y[0]}
            left = LOWER_THIRD_LEFT if kind == "lower_third" else SAFE["left"]
            if kind != "character" and (
                box["x"] < left or box["x"] + box["w"] > SAFE["right"] or box["y"] < SAFE["top"]
                or box["y"] + box["h"] > SAFE["bottom"]
            ):
                problems.append(f"Scene {number}: {element.get('id')} is outside the safe zone.")
            boxes.append((element.get("id"), kind, box))
        for i, (id_a, kind_a, box_a) in enumerate(boxes):
            for id_b, kind_b, box_b in boxes[i + 1:]:
                if "character" in (kind_a, kind_b) and "lower_third" in (kind_a, kind_b):
                    continue
                if {kind_a, kind_b} == {"screen", "summary"}:
                    continue  # The summary panel sits on its screen on purpose: it is the after state.
                if _intersects(box_a, box_b):
                    problems.append(f"Scene {number}: {id_a} overlaps {id_b}.")
    return problems


def build_reel(spec: dict, folder: Path, *, speak=None, plates: dict | None = None, make_plates=None,
               preview: bool = False, require_voice: bool = True, render=None) -> dict:
    """Validate, narrate, make stills, lay out, and render one reel into folder. Never publishes."""
    problems = validate_spec(spec)
    if problems:
        return {"ok": False, "error": "The reel spec is not valid: " + " ".join(problems), "problems": problems}
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    beats = spec["beats"]
    notes: list = []

    voice_files: list = []
    seconds: list = []
    narrated = True
    for beat in beats:
        spoken = None
        if not preview:
            made = (speak or voice_module.speak)(_text(beat["voice"]), folder / f"voice-{beat['id']}.wav")
            if made.get("ok"):
                spoken = made
            else:
                narrated = False
                notes.append(f"Beat {beat['id']}: {made.get('error') or 'narration failed'}")
        if spoken is None:
            narrated = False
            seconds.append(voice_module.estimate_seconds(_text(beat["voice"])))
            voice_files.append(None)
        else:
            seconds.append(float(spoken.get("seconds") or voice_module.estimate_seconds(_text(beat["voice"]))))
            voice_files.append(spoken["path"])
    if not preview and not narrated and require_voice:
        return {"ok": False, "error": "Narration was not created, so the reel was not rendered. " + " ".join(notes),
                "notes": notes}

    timing = beat_timing(beats, seconds)
    total = sum(item["duration"] for item in timing)
    if total > MAX_TOTAL:
        return {"ok": False, "error": f"The reel runs {total:.0f} seconds. The limit is {MAX_TOTAL:.0f}."}

    if plates is None:
        if make_plates is None:
            import plates as plates_module

            make_plates = plates_module.make_plates
        made_plates = make_plates(
            beats, folder, product_reference=_text(spec.get("product_reference")) or None, offline=preview
        )
        if not made_plates.get("ok"):
            return {"ok": False, "error": made_plates.get("error") or "The stills could not be made.", "notes": notes}
        plates = made_plates["plates"]
        notes.extend(made_plates.get("notes") or [])

    renderer = layout(spec, timing, plates)
    issues = layout_problems(renderer)
    if issues:
        return {"ok": False, "error": "The layout broke a safe-zone rule: " + " ".join(issues), "problems": issues}
    (folder / "renderer.json").write_text(json.dumps(renderer, indent=2, default=str), encoding="utf-8")
    (folder / "reel-spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")

    payload = {"renderer": renderer, "output": str(folder / "reel.mp4")}
    if preview:
        starts = [item["start"] + item["duration"] * 0.7 for item in timing]
        payload["preview"] = {"folder": str(folder), "times": starts}
    elif narrated:
        track = voice_module.build_track([(path, item["duration"]) for path, item in zip(voice_files, timing)],
                                         folder / "narration.wav")
        if not track.get("ok"):
            return {"ok": False, "error": track.get("error") or "The narration track could not be built.", "notes": notes}
        payload["voiceover"] = str(track["path"])
    result = (render or render_explainer)(payload)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "The reel could not be rendered.", "notes": notes}
    return {
        "ok": True,
        "path": result.get("path") or "",
        "previews": result.get("previews") or [],
        "seconds": result.get("seconds"),
        "has_audio": bool(result.get("has_audio")),
        "narrated": narrated,
        "disclosure": _text(spec.get("disclosure")),
        "caption": _text(spec.get("caption")),
        "notes": notes,
        "error": "",
    }


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if len(args) < 2:
        print(json.dumps({"ok": False, "error": "Usage: reel_spec.py spec.json out_folder [--preview]"}))
        return 1
    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    print(json.dumps(build_reel(spec, Path(args[1]), preview="--preview" in sys.argv), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
