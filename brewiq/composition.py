"""BrewIQ post-production composition, cover, voice direction and quality gates.

Footage is generated clean (no text). Everything readable — headlines, subtitles,
icons, branding — is laid out here as a separate graphics layer with exact
coordinates, font sizes, timing and z-order, so a programmatic compositor
(Remotion / FFmpeg) can render it and these checks can prove it is legible,
non-overlapping and never behind the presenter.

``composition_problems`` runs before render. ``render_gate`` runs on the
automated post-render report and rejects the render, naming the scenes to
regenerate or fix in post.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

CANVAS = (1080, 1920)
BRAND = {
    "midnight_navy": "#0B1020",
    "electric_cyan": "#13D8E8",
    "vibrant_blue": "#4169FF",
    "warm_amber": "#FFB547",
    "clean_white": "#F6F8FC",
}
BRAND_LOOK = (
    "BRAND LOOK — rich, detailed 3D environment with cinematic lighting: midnight-navy (#0B1020) shadows, "
    "electric-cyan (#13D8E8) and vibrant-blue (#4169FF) rim and practical lights, warm-amber (#FFB547) accents, "
    "clean-white (#F6F8FC) highlights, subtle depth of field. Animated holographic 3D elements may glow and move "
    "but never contain text, letters or symbols. No beige or flat backgrounds, no slides, no floating text cards."
)
_BEIGE = re.compile(r"\b(beige|cream|tan|taupe|off-white)\b", re.IGNORECASE)

# Boxes are (x, y, w, h) on the 1080×1920 canvas.
SAFE_AREA = (60, 250, 900, 1250)  # clear of Instagram's top bar, caption/UI (bottom 420px) and right buttons
PRESENTER_ZONE = (0, 620, 1080, 740)  # reserved for the presenter and key action; no text here
LABEL_BOX = (90, 250, 420, 40)
HEADLINE_BOX = (90, 300, 690, 280)
ICON_BOX = (810, 300, 150, 150)
SUBTITLE_BOX = (90, 1380, 870, 120)
BRAND_BOX = (90, 300, 420, 90)
HEADLINE_SIZES = (84, 76, 68)
SUBTITLE_SIZE = 50
LABEL_SIZE = 28
MIN_TEXT_SIZE = {"headline": 64, "subtitle": 44, "label": 26, "brand": 40}
CHAR_WIDTH = 0.58  # bold sans average advance, as a fraction of font size
LINE_HEIGHT = 1.15
PLATE_PADDING = 24
MAX_HEADLINE_WORDS = 6
MAX_HEADLINE_LINES = 2
MAX_SUBTITLE_WORDS = 6
MAX_SUBTITLE_CPS = 20.0  # characters per second a viewer can read
MIN_CONTRAST = 4.5
VOICE_LUFS = -14.0
MUSIC_LUFS = -26.0
MIN_MUSIC_GAP_DB = 10.0
VOICE_WPM = (145, 160)

VOICE_DIRECTION = {
    "voice": "Warm, engaging, conversational narrator; natural American English.",
    "pace_wpm": list(VOICE_WPM),
    "tone": "Curious on the hook; confident and clear on explanations; expressive but not theatrical.",
    "pauses": "Natural 0.3–0.5s pause before each reveal (the catch and the payoff).",
    "avoid": ["monotone delivery", "synthetic-sounding emphasis", "rushing", "announcer voice"],
    "track": "Record narration as its own audio track; mute all model-generated audio.",
    "loudness": f"Voice integrated {VOICE_LUFS:g} LUFS, true peak below -1 dBTP.",
}

ICON_LIBRARY = {
    "ai_security": {
        "icon": "animated 3D shield and lock",
        "keywords": ("security", "privacy", "hack", "scam", "deepfake", "password", "breach", "police", "fraud"),
    },
    "robotics": {
        "icon": "expressive 3D robotic hand",
        "keywords": ("robot", "humanoid", "robotic", "hardware", "drone"),
    },
    "ai_agents": {
        "icon": "connected glowing workflow nodes",
        "keywords": ("agent", "automat", "workflow", "pipeline", "integrat"),
    },
    "productivity": {
        "icon": "animated 3D calendar with task check-offs",
        "keywords": ("productiv", "calendar", "task", "notes", "study", "email", "notebook", "schedule"),
    },
    "ai_news": {"icon": "glowing 3D digital globe", "keywords": ()},
}

RENDER_CHECKS = {
    "text_overlap": ("fix_in_post", "OCR + layer boxes on sampled frames: no two text/graphic layers intersect."),
    "text_clipped": ("fix_in_post", "OCR text matches the layer text exactly; nothing cut at box or frame edges."),
    "text_hidden": ("fix_in_post", "Person segmentation: no text pixels covered by the presenter."),
    "duplicate_captions": ("fix_in_post", "No subtitle shown twice in a row or duplicating the on-screen headline."),
    "blank_frame": ("regenerate_scene", "No black/empty frames; frame 0 and the cover show the story subject."),
    "icon": ("fix_in_post", "The topic icon is present, matches the topic and animates in."),
    "character_motion": ("regenerate_scene", "Pose tracking: no limb jitter, sliding feet or face/outfit drift."),
    "voice_transition": ("fix_in_post", "Narration: no gaps over 0.6s mid-sentence and no level jumps over 3 dB."),
    "subtitle_sync": ("fix_in_post", "Forced alignment: each subtitle starts within 0.15s of its words."),
    "music_level": ("fix_in_post", f"Music at least {MIN_MUSIC_GAP_DB:g} dB under the voice and ducked under speech."),
    "legibility": ("fix_in_post", "At phone size (390pt wide) every headline and subtitle passes the contrast test."),
    "unsupported_claim": ("block", "Every spoken or shown claim maps to a cited fact; otherwise the reel is blocked."),
}


def icon_for_topic(topic: str, research: dict | None = None) -> tuple[str, str]:
    """(category, icon) chosen from the topic, never a generic decoration."""
    research = research or {}
    text = " ".join(str(v) for v in (topic, research.get("topic"), research.get("category"), research.get("headline")) if v)
    text = text.lower()
    for category, entry in ICON_LIBRARY.items():
        if any(word in text for word in entry["keywords"]):
            return category, entry["icon"]
    return "ai_news", ICON_LIBRARY["ai_news"]["icon"]


def _luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    a, b = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return round((a + 0.05) / (b + 0.05), 2)


def _text_width(text: str, size: int) -> float:
    return len(text) * size * CHAR_WIDTH


def wrap_lines(text: str, size: int, width: int) -> list[str]:
    """Greedy wrap; a separator such as "·" or "—" never starts a line and is dropped at a line end."""
    words: list[str] = []
    for token in str(text).split():
        if words and not any(c.isalnum() for c in token):
            words[-1] = f"{words[-1]} {token}"
        else:
            words.append(token)
    lines: list[str] = []
    for word in words:
        if lines and _text_width(f"{lines[-1]} {word}", size) <= width - 2 * PLATE_PADDING:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    trimmed = []
    for line in lines:
        parts = line.split()
        while len(parts) > 1 and not any(c.isalnum() for c in parts[-1]):
            parts.pop()
        trimmed.append(" ".join(parts))
    return trimmed


def fit_headline(text: str) -> tuple[int, list[str]]:
    """Largest headline size that fits in two lines; returns the smallest size if nothing fits."""
    for size in HEADLINE_SIZES:
        lines = wrap_lines(text, size, HEADLINE_BOX[2])
        if len(lines) <= MAX_HEADLINE_LINES and all(
            _text_width(line, size) <= HEADLINE_BOX[2] - 2 * PLATE_PADDING for line in lines
        ):
            return size, lines
    size = HEADLINE_SIZES[-1]
    return size, wrap_lines(text, size, HEADLINE_BOX[2])


def phrase_subtitles(text: str, start: float, end: float, max_words: int = MAX_SUBTITLE_WORDS) -> list[dict[str, Any]]:
    """Split narration into ≤max_words phrases (breaking at punctuation first), timed by length."""
    words = str(text or "").split()
    if not words:
        return []
    phrases: list[list[str]] = [[]]
    for word in words:
        phrases[-1].append(word)
        if len(phrases[-1]) >= max_words or (word[-1] in ",.?!;:" and len(phrases[-1]) >= 2):
            phrases.append([])
    chunks = [" ".join(p) for p in phrases if p]
    total = sum(len(c) for c in chunks)
    subs, cursor = [], start
    for index, chunk in enumerate(chunks):
        stop = end if index == len(chunks) - 1 else round(cursor + (end - start) * len(chunk) / total, 2)
        subs.append({"start": round(cursor, 2), "end": round(stop, 2), "text": chunk})
        cursor = stop
    return subs


def _layer(kind: str, box: tuple[int, int, int, int], start: float, end: float, z: int, **extra: Any) -> dict[str, Any]:
    return {"type": kind, "box": list(box), "start": round(start, 2), "end": round(end, 2), "z": z, **extra}


def build_composition(
    scenes: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    *,
    icon: tuple[str, str],
    icon_scene: int,
    label: str,
) -> dict[str, Any]:
    """Programmatic composition: clean footage + separate text, icon, brand and audio layers.

    ``scenes`` need start/end and ``on_screen_text`` as a list of {text, start, end}.
    """
    runtime = float(scenes[-1]["end"])
    layers: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes, start=1):
        layers.append(
            _layer("footage", (0, 0, *CANVAS), scene["start"], scene["end"], 0, scene=index, src=f"scene_{index:02d}.mp4")
        )
    layers.append(
        _layer(
            "label", LABEL_BOX, 0.0, runtime, 3, text=label, size=LABEL_SIZE,
            color=BRAND["clean_white"], plate=BRAND["midnight_navy"], plate_opacity=0.7,
        )
    )
    last_headline_end = 0.0
    for scene in scenes:
        for item in scene.get("on_screen_text") or []:
            size, lines = fit_headline(str(item["text"]))
            height = round(len(lines) * size * LINE_HEIGHT + 2 * PLATE_PADDING)
            box = (HEADLINE_BOX[0], HEADLINE_BOX[1], HEADLINE_BOX[2], min(height, HEADLINE_BOX[3]))
            layers.append(
                _layer(
                    "headline", box, float(item["start"]), float(item["end"]), 3,
                    text=str(item["text"]), lines=lines, size=size, weight="800 (bold, rounded sans)",
                    color=BRAND["clean_white"], accent=BRAND["electric_cyan"], plate=BRAND["midnight_navy"],
                    plate_opacity=0.85, entrance="slide up 24px + fade, 0.25s", exit="fade 0.2s",
                )
            )
            last_headline_end = max(last_headline_end, float(item["end"]))
    for sub in subtitles:
        layers.append(
            _layer(
                "subtitle", SUBTITLE_BOX, float(sub["start"]), float(sub["end"]), 4,
                text=str(sub["text"]), size=SUBTITLE_SIZE, color=BRAND["clean_white"],
                plate=BRAND["midnight_navy"], plate_opacity=0.7,
            )
        )
    target = scenes[icon_scene - 1]
    icon_start = float(target["start"]) + 0.3
    layers.append(
        _layer(
            "icon", ICON_BOX, icon_start, min(float(target["end"]), icon_start + 2.4), 2,
            category=icon[0], icon=icon[1], scene=icon_scene,
            entrance="scale 0.8→1.0 with soft cyan glow, 0.3s", glow=BRAND["electric_cyan"],
        )
    )
    brand_start = max(last_headline_end, runtime - 0.8)
    if runtime - brand_start >= 0.5:
        layers.append(
            _layer("brand", BRAND_BOX, brand_start, runtime, 3, text="BrewIQ", size=56,
                   color=BRAND["clean_white"], accent=BRAND["electric_cyan"], plate=BRAND["midnight_navy"])
        )
    return {
        "canvas": list(CANVAS),
        "fps": 30,
        "renderer": "programmatic (Remotion or FFmpeg drawtext/overlay); coordinates in px on 1080×1920",
        "zones": {
            "safe_area": list(SAFE_AREA),
            "presenter": list(PRESENTER_ZONE),
            "headline": list(HEADLINE_BOX),
            "icon": list(ICON_BOX),
            "subtitle": list(SUBTITLE_BOX),
        },
        "layers": layers,
        "audio": [
            {"type": "narration", "src": "narration.wav", "lufs": VOICE_LUFS},
            {"type": "music", "src": "music.wav", "lufs": MUSIC_LUFS, "duck_under_voice_db": 4},
            {"type": "sfx", "src": "sfx/*.wav", "lufs": -20.0},
        ],
    }


def _intersects(a: list[int], b: list[int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _inside(inner: list[int], outer: tuple[int, int, int, int]) -> bool:
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    return x >= ox and y >= oy and x + w <= ox + ow and y + h <= oy + oh


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def composition_problems(composition: dict[str, Any], voiceover: str) -> list[str]:
    """Pre-render quality gates that can be proven from the layout alone."""
    problems: list[str] = []
    layers = composition.get("layers") or []
    footage = sorted((l for l in layers if l["type"] == "footage"), key=lambda l: l["start"])
    graphics = [l for l in layers if l["type"] != "footage"]
    if not footage or footage[0]["start"] > 0.0:
        problems.append("Blank opening: footage must start at 0s.")
    for a, b in pairwise(footage):
        if b["start"] - a["end"] > 0.01:
            problems.append(f"Blank frames between {a['end']}s and {b['start']}s.")

    for layer in graphics:
        name = f"{layer['type']} {layer.get('text') or layer.get('icon')!r}"
        if not _inside(layer["box"], SAFE_AREA):
            problems.append(f"{name} is outside the Instagram-safe area.")
        if _intersects(layer["box"], list(PRESENTER_ZONE)):
            problems.append(f"{name} sits in the presenter area and could be hidden by the character.")
        if layer["z"] <= 0:
            problems.append(f"{name} is not above the footage layer.")
        if "text" not in layer:
            continue
        size = int(layer.get("size") or 0)
        if size < MIN_TEXT_SIZE.get(layer["type"], 0):
            problems.append(f"{name} is {size}px; too small to read on a phone.")
        if layer.get("plate") and contrast_ratio(layer["color"], layer["plate"]) < MIN_CONTRAST:
            problems.append(f"{name} contrast is below {MIN_CONTRAST}:1.")
        if layer["type"] == "headline":
            if len(layer["text"].split()) > MAX_HEADLINE_WORDS:
                problems.append(f"{name} is over {MAX_HEADLINE_WORDS} words.")
            lines = layer.get("lines") or [layer["text"]]
            too_wide = any(_text_width(line, size) > layer["box"][2] - 2 * PLATE_PADDING for line in lines)
            if len(lines) > MAX_HEADLINE_LINES or too_wide:
                problems.append(f"{name} does not fit in {MAX_HEADLINE_LINES} lines; it would be clipped.")
        if layer["type"] == "subtitle":
            if len(layer["text"].split()) > MAX_SUBTITLE_WORDS:
                problems.append(f"{name} is over {MAX_SUBTITLE_WORDS} words.")
            duration = layer["end"] - layer["start"]
            if duration <= 0 or len(layer["text"]) / duration > MAX_SUBTITLE_CPS:
                problems.append(f"{name} is on screen too briefly to read.")

    for a_index, a in enumerate(graphics):
        for b in graphics[a_index + 1 :]:
            if a["start"] < b["end"] - 0.01 and b["start"] < a["end"] - 0.01 and _intersects(a["box"], b["box"]):
                problems.append(f"{a['type']} and {b['type']} overlap at {max(a['start'], b['start']):g}s.")

    subs = sorted((l for l in layers if l["type"] == "subtitle"), key=lambda l: l["start"])
    heads = [l for l in layers if l["type"] == "headline"]
    for a, b in pairwise(subs):
        if _norm(a["text"]).lower() == _norm(b["text"]).lower():
            problems.append(f"Duplicate caption: {a['text']!r}.")
    sentences = [s.strip().lower() for s in re.split(r"(?<=[.?!])\s+", _norm(voiceover)) if len(s.split()) >= 3]
    for sentence in sorted({s for s in sentences if sentences.count(s) > 1}):
        problems.append(f"Narration repeats a line, so its captions repeat: {sentence!r}.")
    for sub in subs:
        for head in heads:
            overlap = sub["start"] < head["end"] and head["start"] < sub["end"]
            if overlap and _norm(sub["text"]).lower().rstrip(".?!") == _norm(head["text"]).lower().rstrip(".?!"):
                problems.append(f"Caption duplicates the headline: {sub['text']!r}.")
    if _norm(" ".join(s["text"] for s in subs)) != _norm(voiceover):
        problems.append("Subtitles are out of sync with the narration (text differs from the voiceover).")

    icons = [l for l in layers if l["type"] == "icon"]
    if not icons:
        problems.append("Missing topic icon.")
    for layer in icons:
        entry = ICON_LIBRARY.get(layer.get("category"))
        if not entry or entry["icon"] != layer.get("icon"):
            problems.append(f"Incorrect icon {layer.get('icon')!r} for category {layer.get('category')!r}.")
    if not any(l["type"] == "brand" for l in layers):
        problems.append("Missing BrewIQ branding.")

    audio = {a["type"]: a for a in composition.get("audio") or []}
    if "narration" not in audio or "music" not in audio:
        problems.append("Narration and music must be separate audio tracks.")
    elif audio["narration"]["lufs"] - audio["music"]["lufs"] < MIN_MUSIC_GAP_DB:
        problems.append(f"Music is less than {MIN_MUSIC_GAP_DB:g} dB under the voice.")
    return problems


def voice_pacing(voiceover: str, subtitles: list[dict[str, Any]]) -> dict[str, Any]:
    """Words per minute over the time narration is on screen."""
    seconds = sum(float(s["end"]) - float(s["start"]) for s in subtitles)
    words = len(str(voiceover or "").split())
    wpm = round(words / seconds * 60, 1) if seconds else 0.0
    low, high = VOICE_WPM
    note = "" if low <= wpm <= high else ("too fast" if wpm > high else "slower than target")
    return {"words": words, "speaking_seconds": round(seconds, 2), "wpm": wpm, "target": list(VOICE_WPM), "note": note}


def build_cover(
    *,
    visual: str,
    headline: str,
    character_lock: str,
    environment_lock: str,
    character_in_cover: bool = True,
) -> dict[str, Any]:
    size, lines = fit_headline(headline)
    subject = character_lock + " " if character_in_cover else ""
    return {
        "size": list(CANVAS),
        "source": "generated",
        "visual": visual,
        "image_prompt": (
            f"{subject}{environment_lock} {BRAND_LOOK} COVER — {visual}. Dramatic, high-contrast key art, the "
            "subject large and sharp in the middle band, clean negative space in the top 30%. Vertical 1080×1920. "
            "No readable text, letters, numbers or logos anywhere."
        ),
        "headline": {
            "text": headline, "lines": lines, "size": size, "box": list(HEADLINE_BOX),
            "color": BRAND["clean_white"], "accent": BRAND["electric_cyan"], "plate": BRAND["midnight_navy"],
        },
        "brand": {"text": "BrewIQ", "box": [90, 1260, 300, 80], "color": BRAND["clean_white"], "accent": BRAND["electric_cyan"]},
        "grid_crop": "Headline and subject stay inside the centre 1080×1440 (3:4) profile-grid crop, y 240–1680.",
    }


def cover_problems(cover: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if cover.get("source") != "generated":
        problems.append("Cover must be a dedicated generated image, never a frame from the reel.")
    if list(cover.get("size") or []) != list(CANVAS):
        problems.append("Cover must be 1080×1920.")
    if not str(cover.get("visual") or "").strip():
        problems.append("Cover has no story visual (empty frame).")
    headline = cover.get("headline") or {}
    text = str(headline.get("text") or "")
    if not text or len(text.split()) > MAX_HEADLINE_WORDS:
        problems.append(f"Cover needs a curiosity headline of 1–{MAX_HEADLINE_WORDS} words.")
    if len(headline.get("lines") or []) > MAX_HEADLINE_LINES:
        problems.append("Cover headline does not fit in two lines.")
    if headline.get("plate") and contrast_ratio(headline["color"], headline["plate"]) < MIN_CONTRAST:
        problems.append("Cover headline contrast is too low.")
    box = headline.get("box") or [0, 0, 0, 0]
    if box[1] < 240 or box[1] + box[3] > 1680:
        problems.append("Cover headline falls outside the profile-grid crop.")
    if text and text.lower() in str(cover.get("image_prompt") or "").lower():
        problems.append("Cover prompt asks the image model to render the headline.")
    if BRAND_LOOK not in str(cover.get("image_prompt") or ""):
        problems.append("Cover prompt is missing the BrewIQ brand look.")
    if not cover.get("brand"):
        problems.append("Cover is missing BrewIQ branding.")
    return problems


def brand_problems(prompts: list[str], environment_lock: str) -> list[str]:
    problems: list[str] = []
    if _BEIGE.search(environment_lock):
        problems.append("Environment uses a generic beige/cream palette; use the BrewIQ brand look.")
    for index, prompt in enumerate(prompts, start=1):
        if BRAND_LOOK not in prompt:
            problems.append(f"Scene {index} prompt is missing the BrewIQ brand look.")
    return problems


def render_gate(report: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide on a finished render from automated check results.

    ``report`` items: {"check": RENDER_CHECKS key, "pass": bool, "scene": int | None, "detail": str}.
    Any failure rejects the render; the result lists scenes to regenerate and fixes for post.
    """
    regenerate: set[int] = set()
    fixes: list[str] = []
    blocked: list[str] = []
    missing = [key for key in RENDER_CHECKS if key not in {r.get("check") for r in report}]
    for item in report:
        if item.get("pass"):
            continue
        action = RENDER_CHECKS.get(item.get("check"), ("block", ""))[0]
        detail = f"{item.get('check')}: {item.get('detail') or 'failed'}"
        if action == "regenerate_scene" and item.get("scene"):
            regenerate.add(int(item["scene"]))
        elif action == "fix_in_post":
            fixes.append(detail + (f" (scene {item['scene']})" if item.get("scene") else ""))
        else:
            blocked.append(detail)
    blocked += [f"{key}: not checked" for key in missing]
    ok = not (regenerate or fixes or blocked)
    return {
        "ok": ok,
        "status": "approved" if ok else "rejected",
        "regenerate_scenes": sorted(regenerate),
        "fix_in_post": fixes,
        "blocked": blocked,
        "nothing_posted": True,
    }
