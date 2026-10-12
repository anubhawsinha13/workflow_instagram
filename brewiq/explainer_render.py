"""Render a BrewIQ motion-graphics explainer plan into a vertical mp4. This does not publish."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reel import ffmpeg_bin  # noqa: E402

FONT_FILE = "/System/Library/Fonts/Avenir Next.ttc"
SLIDE = 70
SPIN_SECONDS = 1.4
POSE_DIR = ROOT / "brand" / "poses"
POSE_CANVAS = (1120, 1280)
POSE_HEAD = (440, 60)
FIGURE_WIDTH = 620
POSE_FILES = {
    "neutral": "host-green",
    "present": "present",
    "think": "eyebrow",
    "reach": "reach",
    "hold": "hold",
    "point": "lean_point",
    "shrug": "shrug",
    "push": "push",
    "thumbs_up": "relief",
    "point_viewer": "point_camera",
    "magnify": "magnify",
    "magnify_doubt": "magnify_doubt",
    "pinch": "pinch",
    "toss": "toss",
    "walk_a": "walk_a",
    "walk_b": "walk_b",
}
HOST_PROMPT = (
    "Turn this photo into a premium stylized 3D animated portrait of the same man, from the chest up, "
    "friendly expression, looking at the viewer. Keep his face, short dark hair, light stubble, and "
    "medium-brown complexion recognizable. Plain black jacket with no logo. "
    "Plain warm off-white studio background, soft light. No text, no logos."
)


def render_explainer(payload: dict, make_host=None) -> dict:
    data = payload.get("renderer") if isinstance(payload.get("renderer"), dict) else {}
    canvas = data.get("canvas") if isinstance(data.get("canvas"), dict) else {}
    scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
    if not scenes:
        return {"ok": False, "error": "The explainer plan has no scenes to render."}
    out = Path(str(payload.get("output") or "")).expanduser()
    if not out.parent.is_dir():
        return {"ok": False, "error": "The explainer output folder is not available."}
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg is not installed, so the explainer could not be rendered."}

    width = int(canvas.get("width") or 1080)
    height = int(canvas.get("height") or 1920)
    fps = int(canvas.get("fps") or 30)
    colors = {
        "background": canvas.get("background") or "#F7F3EC",
        "text": canvas.get("text") or "#2B2B2B",
        "accent": canvas.get("accent") or "#22C3D6",
        "warning": canvas.get("warning") or "#D6623E",
        "card": canvas.get("card") or "#FFFFFF",
    }
    radius = int(canvas.get("corner_radius") or 32)

    host = None
    library = load_pose_library()
    if not library and any(element.get("type") == "character" for scene in scenes for element in scene.get("elements") or []):
        host = _host_image(payload, out.parent, make_host)

    background = _background(width, height, colors)
    prepared = []
    for scene in scenes:
        sprites = []
        for element in scene.get("elements") or []:
            if element.get("type") == "character" and library:
                sprites.append((element, None))
                continue
            sprite = _sprite(element, colors, radius, host)
            if sprite is not None:
                sprites.append((element, sprite))
        prepared.append((
            float(scene.get("start_seconds") or 0),
            float(scene.get("duration_seconds") or 0),
            sprites,
            str(scene.get("camera") or "steady"),
            _focus(scene.get("elements") or [], width, height),
            _backdrop(width, height, colors, radius, scene.get("elements") or []),
        ))
    total = sum(item[1] for item in prepared)
    frames = max(1, round(total * fps))
    hook_element = _first_hook(prepared[0][2] if prepared else [])

    audio = Path(str(payload.get("voiceover") or ""))
    command = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
    ]
    if audio.is_file():
        command += ["-i", str(audio), "-af", "apad", "-c:a", "aac", "-b:a", "160k"]
    command += [
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for index in range(frames):
            t = index / fps
            frame = background.copy()
            for start, duration, sprites, camera, focus, backdrop in prepared:
                if start <= t < start + duration or (index == frames - 1 and start <= t):
                    local = t - start
                    frame.alpha_composite(backdrop)
                    for element, sprite in sprites:
                        early = element is hook_element or element.get("type") in _EARLY_TYPES
                        draw_at = _hook_time(element, local) if early else local
                        if sprite is None:
                            _draw_character(frame, element, library, draw_at, duration, colors)
                        else:
                            _place(frame, element, sprite, draw_at, duration, colors)
                    frame = _camera(frame, camera, focus, local / max(0.01, duration))
            process.stdin.write(frame.convert("RGB").tobytes())
        process.stdin.close()
    except BrokenPipeError:
        pass
    stderr = process.stderr.read().decode("utf-8", "ignore") if process.stderr else ""
    process.wait()
    if process.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        detail = stderr.strip().splitlines()
        return {"ok": False, "error": (detail[-1] if detail else "ffmpeg could not render the explainer.")[:240]}
    cover = out.with_name("cover.jpg")
    try:
        cover_frame = _opening_still(
            width, height, colors, radius,
            prepared[0][2] if prepared else [],
            prepared[0][5] if prepared else None,
            hook_element,
        )
        cover_frame.convert("RGB").save(cover, quality=90)
    except OSError:
        cover = None
    return {
        "ok": True,
        "path": str(out),
        "cover": str(cover) if cover and cover.is_file() else "",
        "seconds": round(total, 2),
        "has_audio": audio.is_file(),
        "error": "",
    }


_HOOK_TYPES = {"card", "text", "bubble", "token"}
_EARLY_TYPES = {"icon", "rail", "clock", "split", "board"}


def _first_hook(sprites: list) -> dict | None:
    for element, sprite in sprites:
        if sprite is not None and element.get("type") in _HOOK_TYPES and str(element.get("label") or "").strip():
            return element
    return None


def _hook_time(element: dict, local: float) -> float:
    """The opening label is fully drawn from the first frame.

    Instagram uses that frame as the reel cover. Waiting for enter_at leaves a blank beige still.
    """
    enter = float(element.get("enter_at") or 0)
    enter_for = max(0.01, float(element.get("enter_duration") or 0.4))
    ready = enter + enter_for
    return ready if local < ready else local


def _opening_still(width: int, height: int, colors: dict, radius: int, sprites: list, backdrop: Image.Image | None,
                   hook: dict | None) -> Image.Image:
    frame = _background(width, height, colors)
    if backdrop is not None:
        frame.alpha_composite(backdrop)
    for element, sprite in sprites:
        early = element is hook or element.get("type") in _EARLY_TYPES
        draw_at = _hook_time(element, 0.0) if early else 0.0
        duration = float(element.get("hold_until") or 2) + 1
        if sprite is None:
            continue
        _place(frame, element, sprite, draw_at, duration, colors)
    return frame


def opening_still(canvas: dict, elements: list) -> Image.Image:
    """The cover frame: the hook label is visible even when its entrance is later than 0."""
    width = int(canvas.get("width") or 1080)
    height = int(canvas.get("height") or 1920)
    colors = {
        "background": canvas.get("background") or "#F7F3EC",
        "text": canvas.get("text") or "#2B2B2B",
        "accent": canvas.get("accent") or "#22C3D6",
        "warning": canvas.get("warning") or "#D6623E",
        "card": canvas.get("card") or "#FFFFFF",
    }
    radius = int(canvas.get("corner_radius") or 32)
    sprites = []
    for element in elements:
        sprite = _sprite(element, colors, radius, None)
        if sprite is not None:
            sprites.append((element, sprite))
    return _opening_still(
        width, height, colors, radius, sprites,
        _backdrop(width, height, colors, radius, elements),
        _first_hook(sprites),
    )


def build_pose_library(source: Path, dest: Path = POSE_DIR) -> dict:
    """Key green-screen pose stills made from the brand character into aligned cutouts with prop anchors."""
    dest.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, stem in POSE_FILES.items():
        path = source / f"{stem}.png"
        if not path.is_file():
            path = source.parent / f"{stem}.png"
        if not path.is_file():
            continue
        cutout = _align(_key_green(Image.open(path)))
        cutout.save(dest / f"{name}.png")
        meta[name] = _anchors(cutout, lens=name.startswith("magnify"))
    (dest / "poses.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


_LIBRARY: dict = {}


def load_pose_library(folder: Path = POSE_DIR) -> dict:
    key = str(folder)
    if key in _LIBRARY:
        return _LIBRARY[key]
    library = {}
    meta_file = folder / "poses.json"
    if meta_file.is_file():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        for name, anchors in meta.items():
            path = folder / f"{name}.png"
            if path.is_file():
                library[name] = (Image.open(path).convert("RGBA"), anchors)
    if "neutral" not in library:
        library = {}
    _LIBRARY[key] = library
    return library


def _key_green(image: Image.Image) -> Image.Image:
    r, g, b = image.convert("RGB").split()
    other = ImageChops.lighter(r, b)
    spill = ImageChops.subtract(g, other)
    alpha = spill.point(lambda v: 255 if v < 28 else max(0, 255 - (v - 28) * 7))
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    g = ImageChops.darker(g, other.point(lambda v: min(255, v + 12)))
    return Image.merge("RGBA", (r, g, b, alpha))


def _align(image: Image.Image) -> Image.Image:
    if image.height != POSE_CANVAS[1]:
        image = image.resize((round(image.width * POSE_CANVAS[1] / image.height), POSE_CANVAS[1]), Image.LANCZOS)
    alpha = image.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    head = alpha.crop((0, 0, alpha.width, min(alpha.height, 420))).getbbox()
    canvas = Image.new("RGBA", POSE_CANVAS, (0, 0, 0, 0))
    if not head:
        canvas.paste(image, (0, 0), image)
        return canvas
    row = alpha.crop((0, head[1] + 90, alpha.width, head[1] + 130)).getbbox()
    center = (row[0] + row[2]) / 2 if row else alpha.width / 2
    canvas.paste(image, (round(POSE_HEAD[0] - center), round(POSE_HEAD[1] - head[1])), image)
    return canvas


def _anchors(cutout: Image.Image, lens: bool = False) -> dict:
    solid = cutout.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    anchors: dict = {}
    if lens:
        outside = solid.copy()
        ImageDraw.floodfill(outside, (0, 0), 128)
        region = (POSE_HEAD[0] + 60, 0, POSE_CANVAS[0], 620)
        holes = outside.point(lambda v: 255 if v == 0 else 0).crop(region).getbbox()
        if holes and holes[2] - holes[0] > 90 and holes[3] - holes[1] > 90:
            anchors["lens"] = [holes[0] + region[0], holes[1] + region[1], holes[2] + region[0], holes[3] + region[1]]
    hand_area = solid.crop((POSE_HEAD[0] + 190, 0, POSE_CANVAS[0], 900))
    box = hand_area.getbbox()
    if box:
        top = box[1]
        line = hand_area.crop((0, top, hand_area.width, top + 12)).getbbox()
        x = (line[0] + line[2]) / 2 if line else (box[0] + box[2]) / 2
        anchors["hand"] = [round(x + POSE_HEAD[0] + 190), top]
    return anchors


def _host_image(payload: dict, folder: Path, make_host) -> Image.Image | None:
    reference = Path(str(payload.get("reference") or ""))
    dest = folder / "host.png"
    if dest.is_file():
        return Image.open(dest).convert("RGB")
    if not reference.is_file():
        return None
    if make_host is None:
        from art import openai_edit_image

        def make_host(path: Path) -> dict:
            return openai_edit_image(path, HOST_PROMPT, require_reference=True)

    result = make_host(reference)
    image = result.get("image") if result.get("ok") else None
    if image is None:
        return None
    image = image.convert("RGB")
    image.save(dest)
    return image


def _background(width: int, height: int, colors: dict) -> Image.Image:
    image = Image.new("RGBA", (width, height), colors["background"])
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    accent = _rgb(colors["accent"])
    draw.ellipse((-260, -200, 520, 560), fill=accent + (34,))
    draw.ellipse((width - 420, height - 760, width + 260, height - 80), fill=accent + (26,))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    grain = Image.effect_noise((width, height), 22).convert("RGB")
    textured = Image.blend(image.convert("RGB"), grain, 0.035)
    return textured.convert("RGBA")


def _focus(elements: list, width: int, height: int) -> tuple:
    boxes = [element.get("box") or {} for element in elements if element.get("type") != "character"]
    boxes = [box for box in boxes if all(isinstance(box.get(key), (int, float)) for key in ("x", "y", "w", "h"))]
    if not boxes:
        return (width / 2, height / 2)
    left = min(box["x"] for box in boxes)
    top = min(box["y"] for box in boxes)
    right = max(box["x"] + box["w"] for box in boxes)
    bottom = max(box["y"] + box["h"] for box in boxes)
    return ((left + right) / 2, (top + bottom) / 2)


def _camera(frame: Image.Image, camera: str, focus: tuple, progress: float) -> Image.Image:
    eased = _ease_io(progress)
    if camera == "push_in":
        zoom = 1 + 0.06 * eased
    elif camera == "pull_out":
        zoom = 1.06 - 0.06 * eased
    else:
        return frame
    if zoom <= 1.001:
        return frame
    width, height = frame.size
    left = focus[0] - focus[0] / zoom
    top = focus[1] - focus[1] / zoom
    box = (round(left), round(top), round(left + width / zoom), round(top + height / zoom))
    return frame.crop(box).resize((width, height), Image.BILINEAR)


def _tone(element: dict, colors: dict) -> tuple:
    return _rgb(colors["warning"] if element.get("tone") == "warning" else colors["accent"])


# Original drawings of everyday objects. These are not company logos or product screenshots.
_ICON_KEYS = (
    ("chat", ("chat", "message", "reply", "comment")),
    ("gear", ("setting", "gear", "toggle", "preference")),
    ("lock", ("lock", "password", "privacy", "secure")),
    ("mail", ("mail", "email", "inbox")),
    ("phone", ("phone", "call", "mobile")),
    ("calendar", ("calendar", "schedule")),
    ("search", ("search", "find", "lookup")),
    ("person", ("profile", "account", "person")),
    ("alert", ("alert", "risk", "wrong")),
    ("check", ("done", "approve", "correct")),
    ("photo", ("photo", "image", "picture")),
    ("link", ("link", "url")),
    ("note", ("note", "doc", "file", "page", "paper")),
)
_TILE_COLOR = {
    "chat": (34, 195, 214),
    "mail": (61, 107, 140),
    "note": (214, 154, 46),
    "calendar": (214, 98, 62),
    "lock": (43, 43, 43),
    "search": (46, 138, 122),
    "gear": (92, 107, 115),
    "phone": (47, 111, 143),
    "person": (107, 91, 149),
    "alert": (214, 98, 62),
    "check": (46, 138, 122),
    "photo": (184, 112, 78),
    "link": (61, 107, 140),
}
_BACKDROP_SLOTS = ((0.76, 0.07), (0.06, 0.09), (0.76, 0.50), (0.56, 0.68))
_FILLER_ICONS = ("chat", "mail", "calendar", "lock", "search", "note")


def _has_word(key: str, text: str) -> bool:
    return any(word.startswith(key) for word in text.split())


def _icon_kind(label: str) -> str:
    text = label.lower()
    for kind, keys in _ICON_KEYS:
        if any(_has_word(key, text) for key in keys):
            return kind
    return "note"


def _kinds_for(labels: list[str]) -> list[str]:
    found: list[str] = []
    for label in labels:
        if not str(label).strip():
            continue
        kind = _icon_kind(label)
        if kind not in found:
            found.append(kind)
    for kind in _FILLER_ICONS:
        if len(found) >= 4:
            break
        if kind not in found:
            found.append(kind)
    return found[:4]


def _draw_glyph(draw: ImageDraw.ImageDraw, kind: str, box: tuple, fill: tuple) -> None:
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    stroke = max(3, round(min(width, height) / 7))

    def line(points: list) -> None:
        draw.line(points, fill=fill, width=stroke, joint="curve")

    if kind == "chat":
        body_bottom = top + height * 0.78
        draw.rounded_rectangle((left, top, right, body_bottom), stroke * 1.3, fill=fill)
        draw.polygon(
            [(left + width * 0.18, body_bottom - 1), (left + width * 0.46, body_bottom - 1), (left + width * 0.16, bottom)],
            fill=fill,
        )
    elif kind == "mail":
        draw.rounded_rectangle((left, top + height * 0.16, right, bottom), max(6, stroke), outline=fill, width=stroke)
        line([(left + stroke, top + height * 0.28), (left + width / 2, top + height * 0.66), (right - stroke, top + height * 0.28)])
    elif kind == "calendar":
        draw.rounded_rectangle((left, top + height * 0.18, right, bottom), max(6, stroke), outline=fill, width=stroke)
        line([(left + width * 0.28, top), (left + width * 0.28, top + height * 0.32)])
        line([(left + width * 0.72, top), (left + width * 0.72, top + height * 0.32)])
        line([(left + width * 0.2, top + height * 0.55), (right - width * 0.2, top + height * 0.55)])
    elif kind == "lock":
        draw.arc((left + width * 0.22, top, right - width * 0.22, top + height * 0.7), 200, 340, fill=fill, width=stroke)
        draw.rounded_rectangle((left + width * 0.12, top + height * 0.4, right - width * 0.12, bottom), max(4, stroke), fill=fill)
    elif kind == "search":
        draw.ellipse((left, top, left + width * 0.68, top + height * 0.68), outline=fill, width=stroke)
        line([(left + width * 0.58, top + height * 0.58), (right, bottom)])
    elif kind == "gear":
        draw.ellipse((left + width * 0.22, top + height * 0.22, right - width * 0.22, bottom - height * 0.22), outline=fill, width=stroke)
        draw.ellipse((left + width * 0.4, top + height * 0.4, right - width * 0.4, bottom - height * 0.4), outline=fill, width=stroke)
        mid_x, mid_y = left + width / 2, top + height / 2
        for dx, dy in ((0, -0.46), (0, 0.46), (-0.46, 0), (0.46, 0)):
            line([(mid_x + dx * width * 0.55, mid_y + dy * height * 0.55), (mid_x + dx * width * 0.95, mid_y + dy * height * 0.95)])
    elif kind == "phone":
        draw.rounded_rectangle((left + width * 0.22, top, right - width * 0.22, bottom), max(8, stroke), outline=fill, width=stroke)
        draw.ellipse((left + width * 0.42, bottom - height * 0.2, left + width * 0.58, bottom - height * 0.06), outline=fill, width=max(2, stroke - 1))
    elif kind == "person":
        draw.ellipse((left + width * 0.28, top, right - width * 0.28, top + height * 0.4), outline=fill, width=stroke)
        draw.arc((left, top + height * 0.46, right, bottom + height * 0.15), 200, 340, fill=fill, width=stroke)
    elif kind == "alert":
        draw.polygon([(left + width / 2, top + 2), (right - 2, bottom), (left + 2, bottom)], fill=fill)
    elif kind == "check":
        line([(left + width * 0.08, top + height * 0.52), (left + width * 0.38, bottom - height * 0.08), (right - width * 0.06, top + height * 0.16)])
    elif kind == "photo":
        draw.rounded_rectangle((left, top + height * 0.12, right, bottom), max(6, stroke), outline=fill, width=stroke)
        draw.ellipse((left + width * 0.16, top + height * 0.28, left + width * 0.4, top + height * 0.52), outline=fill, width=max(2, stroke - 1))
        line([
            (left + width * 0.14, bottom - height * 0.22),
            (left + width * 0.4, top + height * 0.5),
            (left + width * 0.62, bottom - height * 0.28),
            (right - width * 0.12, top + height * 0.46),
        ])
    elif kind == "link":
        draw.rounded_rectangle((left, top + height * 0.28, left + width * 0.62, bottom - height * 0.1), max(6, stroke), outline=fill, width=stroke)
        draw.rounded_rectangle((right - width * 0.62, top + height * 0.1, right, bottom - height * 0.28), max(6, stroke), outline=fill, width=stroke)
    else:
        draw.rounded_rectangle((left + width * 0.08, top, right, bottom), max(6, stroke), outline=fill, width=stroke)
        dog = width * 0.28
        draw.polygon([(right - dog, top), (right, top + dog), (right - dog, top + dog)], fill=fill)
        for index in range(3):
            y = top + height * (0.32 + index * 0.18)
            line([(left + width * 0.22, y), (right - width * 0.18, y)])


def _paint_tile(image: Image.Image, box: tuple, kind: str) -> None:
    left, top, right, bottom = (round(value) for value in box)
    size = min(right - left, bottom - top)
    if size < 12:
        return
    color = _TILE_COLOR.get(kind, _TILE_COLOR["note"])
    ImageDraw.Draw(image).rounded_rectangle((left, top, left + size, top + size), max(8, size // 4), fill=color + (255,))
    inset = size * 0.24
    _draw_glyph(
        ImageDraw.Draw(image),
        kind,
        (left + inset, top + inset, left + size - inset, top + size - inset),
        (255, 255, 255, 255),
    )


def _sample_rows(sprite: Image.Image, kind: str, area: tuple, text: tuple, accent: tuple) -> None:
    left, top, right, bottom = area
    width, height = right - left, bottom - top
    if width < 48 or height < 36:
        return
    draw = ImageDraw.Draw(sprite)
    ink = text + (36,)
    soft = accent + (80,)
    if kind == "chat":
        draw.rounded_rectangle((left, top, left + width * 0.62, top + height * 0.4), 18, fill=ink)
        draw.rounded_rectangle((left + width * 0.3, top + height * 0.52, right, min(bottom, top + height * 0.96)), 18, fill=soft)
    elif kind in ("gear", "lock"):
        for index in range(3):
            y = top + index * (height / 3)
            draw.rounded_rectangle((left, y + 4, left + width * 0.52, y + height / 3 - 8), 8, fill=ink)
            draw.rounded_rectangle((right - 64, y + 2, right, y + height / 3 - 10), 16, fill=soft)
    elif kind == "calendar":
        gap = 8
        cell_w = (width - gap * 3) / 4
        cell_h = (height - gap) / 2
        for row in range(2):
            for col in range(4):
                x = left + col * (cell_w + gap)
                y = top + row * (cell_h + gap)
                fill = soft if (row, col) == (0, 1) else ink
                draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), 8, fill=fill)
    elif kind == "mail":
        for index, frac in enumerate((0.86, 0.64, 0.48)):
            y = top + index * (height / 3)
            draw.ellipse((left, y + 2, left + 22, y + 24), fill=ink)
            draw.rounded_rectangle((left + 34, y + 6, left + 34 + (width - 34) * frac, y + 20), 6, fill=ink)
    else:
        for index, frac in enumerate((1.0, 0.92, 0.74, 0.56)):
            y = top + index * (height / 4)
            draw.rounded_rectangle((left, y, left + width * frac, y + max(5, height * 0.1)), 4, fill=ink)


def _dress_card(sprite: Image.Image, inner: tuple, label: str, text: tuple, accent: tuple) -> None:
    """A card reads as a sample screen: an app tile, the hook, then rows like a real app."""
    left, top, right, bottom = inner
    width, height = right - left, bottom - top
    margin = max(20, round(min(width, height) * 0.08))
    if width < 180 or height < 150:
        _write(sprite, label, (left + margin, top + margin, right - margin, bottom - margin), text, weight="Demi Bold", max_size=104)
        return
    kind = _icon_kind(label)
    tile = min(88, max(44, round(min(width, height) * 0.2)))
    _paint_tile(sprite, (left + margin, top + margin, left + margin + tile, top + margin + tile), kind)
    label_room = height - margin * 2 - tile - 12
    rows = min(label_room * 0.42, 140) if label_room >= 170 else 0
    _write(
        sprite,
        label,
        (left + margin, top + margin + tile + 12, right - margin, bottom - margin - rows),
        text,
        weight="Demi Bold",
        max_size=104,
    )
    if rows:
        _sample_rows(sprite, kind, (left + margin, bottom - margin - rows + 8, right - margin, bottom - margin), text, accent)


def _backdrop(width: int, height: int, colors: dict, radius: int, elements: list) -> Image.Image:
    """App tiles behind the host when the plan did not already place icons."""
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if any(element.get("type") == "icon" for element in elements):
        return layer
    size = max(64, round(width * 0.15))
    labels = [str(element.get("label") or "") for element in elements]
    for (fx, fy), kind in zip(_BACKDROP_SLOTS, _kinds_for(labels)):
        sprite = _sprite(
            {"type": "icon", "label": kind, "box": {"x": 0, "y": 0, "w": size, "h": size}},
            colors,
            radius,
            None,
        )
        if sprite is None:
            continue
        _composite(layer, sprite, round(width * fx) - 40, round(height * fy) - 40)
    return layer


def _composite(base: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
    if x >= base.width or y >= base.height or x + sprite.width <= 0 or y + sprite.height <= 0:
        return
    src_left, src_top = max(0, -x), max(0, -y)
    dest_x, dest_y = max(0, x), max(0, y)
    src_right = min(sprite.width, base.width - dest_x + src_left)
    src_bottom = min(sprite.height, base.height - dest_y + src_top)
    if src_right <= src_left or src_bottom <= src_top:
        return
    base.alpha_composite(sprite.crop((src_left, src_top, src_right, src_bottom)), (dest_x, dest_y))


def _marked_steps(label: str) -> list[tuple[str, bool]]:
    parts = [part.strip() for part in label.split("|") if part.strip()]
    steps = [(part.lstrip("*").strip(), part.startswith("*")) for part in parts]
    if steps and not any(active for _, active in steps):
        steps[0] = (steps[0][0], True)
    return steps or [("Plan", True), ("Build", False), ("Check", False)]


def _draw_rail(sprite: Image.Image, inner: tuple, label: str, text: tuple, accent: tuple) -> None:
    left, top, right, bottom = inner
    steps = _marked_steps(label)
    gap = 12
    width = right - left - 36
    height = bottom - top - 36
    pill_w = max(40, (width - gap * (len(steps) - 1)) / len(steps))
    pill_h = min(height, 72)
    y = top + (bottom - top - pill_h) / 2
    draw = ImageDraw.Draw(sprite)
    for index, (name, active) in enumerate(steps):
        x = left + 18 + index * (pill_w + gap)
        box = (x, y, x + pill_w, y + pill_h)
        if active:
            draw.rounded_rectangle(box, pill_h / 2, fill=accent + (255,))
            _write(sprite, name, (x + 8, y + 6, x + pill_w - 8, y + pill_h - 6), (255, 255, 255), weight="Bold", max_size=36, center=True)
        else:
            draw.rounded_rectangle(box, pill_h / 2, outline=text + (180,), width=3)
            _write(sprite, name, (x + 8, y + 6, x + pill_w - 8, y + pill_h - 6), text, weight="Demi Bold", max_size=32, center=True)


def _draw_split(sprite: Image.Image, inner: tuple, label: str, text: tuple, accent: tuple, card: tuple, radius: int) -> None:
    left, right_text = (label.split("|", 1) + [""])[:2]
    x0, y0, x1, y1 = inner
    gap = 16
    mid = (x0 + x1) / 2
    panels = ((x0, y0, mid - gap / 2, y1, "Result", left.strip()), (mid + gap / 2, y0, x1, y1, "Prompt", right_text.strip()))
    for px0, py0, px1, py1, title, body in panels:
        _shadow(sprite, (px0, py0, px1, py1), radius)
        ImageDraw.Draw(sprite).rounded_rectangle((px0, py0, px1, py1), radius, fill=card + (255,))
        _write(sprite, title, (px0 + 20, py0 + 16, px1 - 20, py0 + 64), accent, weight="Bold", max_size=32)
        _write(sprite, body, (px0 + 20, py0 + 72, px1 - 20, py1 - 20), text, weight="Demi Bold", max_size=64)


def _draw_board(sprite: Image.Image, inner: tuple, label: str, text: tuple, accent: tuple) -> None:
    title, line = (label.split("|", 1) + [""])[:2]
    left, top, right, bottom = inner
    _write(sprite, "Scene", (left + 28, top + 20, right - 28, top + 64), accent, weight="Bold", max_size=28)
    _write(sprite, title.strip(), (left + 28, top + 68, right - 28, top + (bottom - top) * 0.48), text, weight="Bold", max_size=72)
    _write(sprite, line.strip(), (left + 28, top + (bottom - top) * 0.52, right - 28, bottom - 24), text, weight="Demi Bold", max_size=48)


def _sprite(element: dict, colors: dict, radius: int, host: Image.Image | None) -> Image.Image | None:
    box = element.get("box") or {}
    w, h = max(8, int(box.get("w") or 0)), max(8, int(box.get("h") or 0))
    kind = element.get("type")
    label = str(element.get("label") or "").strip()
    pad = 40
    sprite = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    inner = (pad, pad, pad + w, pad + h)
    text = _rgb(colors["text"])
    accent = _tone(element, colors)
    card = _rgb(colors["card"])

    if kind == "card":
        _shadow(sprite, inner, radius)
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius, fill=card + (255,))
        _dress_card(sprite, inner, label, text, accent)
    elif kind == "text":
        color = accent if element.get("tone") == "warning" else text
        _write(sprite, label, inner, color, weight="Bold", max_size=120)
    elif kind == "icon":
        size = min(w, h)
        left, top = pad + (w - size) // 2, pad + (h - size) // 2
        _shadow(sprite, (left, top, left + size, top + size), size // 5)
        _paint_tile(sprite, (left, top, left + size, top + size), _icon_kind(label))
    elif kind == "rail":
        _shadow(sprite, inner, radius)
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius, fill=card + (255,))
        _draw_rail(sprite, inner, label, text, accent)
    elif kind == "clock":
        _shadow(sprite, inner, radius)
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius, fill=card + (255,))
        _write(sprite, label or "0:00", (pad + 24, pad + 16, pad + w - 24, pad + h - 16), accent, weight="Bold", max_size=120, center=True)
    elif kind == "split":
        _draw_split(sprite, inner, label, text, accent, card, radius)
    elif kind == "board":
        _shadow(sprite, inner, radius)
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius, fill=card + (255,))
        _draw_board(sprite, inner, label, text, accent)
    elif kind == "line":
        y = pad + h // 2
        ImageDraw.Draw(sprite).rounded_rectangle((pad, y - 5, pad + w, y + 5), 5, fill=accent + (255,))
    elif kind == "progress":
        draw = ImageDraw.Draw(sprite)
        bar = min(h, 36)
        top = pad + (h - bar) // 2
        draw.rounded_rectangle((pad, top, pad + w, top + bar), bar // 2, fill=text + (36,))
        draw.rounded_rectangle((pad, top, pad + w, top + bar), bar // 2, fill=accent + (255,))
        element["_track"] = (pad, top, pad + w, top + bar)
    elif kind == "highlight":
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius // 2, fill=accent + (70,))
        if label:
            _write(sprite, label, (pad + 24, pad + 12, pad + w - 24, pad + h - 12), text, weight="Demi Bold", max_size=72)
    elif kind == "bubble":
        tail = min(70, h // 4)
        body = (pad, pad, pad + w, pad + h - tail)
        _shadow(sprite, body, radius)
        draw = ImageDraw.Draw(sprite)
        draw.rounded_rectangle(body, radius, fill=card + (255,))
        draw.polygon([(pad + 70, body[3] - 2), (pad + 150, body[3] - 2), (pad + 60, pad + h)], fill=card + (255,))
        tile = min(72, max(40, (body[3] - body[1]) // 5))
        _paint_tile(sprite, (pad + 28, pad + 28, pad + 28 + tile, pad + 28 + tile), _icon_kind(label or "chat"))
        _write(sprite, label, (pad + 40 + tile, pad + 28, pad + w - 36, body[3] - 28), text, weight="Demi Bold", max_size=96)
    elif kind == "slots":
        _shadow(sprite, inner, radius)
        draw = ImageDraw.Draw(sprite)
        draw.rounded_rectangle(inner, radius, fill=card + (255,))
        window = (pad + 36, pad + 36, pad + w - 36, pad + h - 36)
        draw.rounded_rectangle(window, radius // 2, fill=text + (14,), outline=accent + (255,), width=4)
        element["_window"] = window
        element["_strip"] = _slot_strip(label, window, text, accent)
    elif kind == "token":
        _shadow(sprite, inner, h // 2)
        draw = ImageDraw.Draw(sprite)
        draw.rounded_rectangle(inner, h // 2, fill=card + (255,), outline=accent + (255,), width=4)
        _write(sprite, label, (pad + h // 3, pad + 8, pad + w - h // 3, pad + h - 8), accent, weight="Bold", max_size=96, center=True)
    elif kind == "lens":
        size = min(w, h)
        ring = max(10, size // 16)
        lens = (pad, pad, pad + size, pad + size)
        draw = ImageDraw.Draw(sprite)
        handle_start = (pad + size * 0.85, pad + size * 0.85)
        draw.line((handle_start, (pad + w, pad + h)), fill=text + (255,), width=ring * 2)
        _shadow(sprite, lens, size // 2)
        draw.ellipse(lens, fill=card + (245,), outline=text + (255,), width=ring)
        draw.ellipse((lens[0] + ring, lens[1] + ring, lens[2] - ring, lens[3] - ring), outline=accent + (120,), width=4)
        inset = size * 0.18
        _write(sprite, label, (lens[0] + inset, lens[1] + inset, lens[2] - inset, lens[3] - inset), text, weight="Bold",
               max_size=140, center=True)
    elif kind == "character":
        if host is None:
            return None
        portrait = _cover(host, w, h)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius, fill=255)
        _shadow(sprite, inner, radius)
        sprite.paste(portrait, (pad, pad), mask)
    else:
        return None
    return sprite


def _slot_strip(label: str, window: tuple, text: tuple, accent: tuple) -> Image.Image:
    options = [part.strip() for part in label.split("|") if part.strip()] or [label or " "]
    reel = options * 3 + options
    row_w, row_h = window[2] - window[0], window[3] - window[1]
    strip = Image.new("RGBA", (row_w, row_h * len(reel)), (0, 0, 0, 0))
    for index, option in enumerate(reel):
        color = accent if index == len(reel) - 1 else text
        tile = Image.new("RGBA", (row_w, row_h), (0, 0, 0, 0))
        _write(tile, option, (24, 8, row_w - 24, row_h - 8), color, weight="Bold", max_size=96, center=True)
        strip.alpha_composite(tile, (0, index * row_h))
    return strip


def _motion(element: dict, t: float, duration: float) -> dict | None:
    enter_at = float(element.get("enter_at") or 0)
    enter_for = max(0.01, float(element.get("enter_duration") or 0.4))
    hold_until = float(element.get("hold_until") or duration)
    exit_for = max(0.01, float(element.get("exit_duration") or 0.4))
    enter_motion = element.get("enter_motion") or "fade_in"
    exit_motion = element.get("exit_motion") or "fade_out"
    if t < enter_at:
        return None
    raw = min(1.0, (t - enter_at) / enter_for)
    p = _ease(raw)
    q = 0.0
    if exit_motion != "hold" and t > hold_until:
        q = _ease(min(1.0, (t - hold_until) / exit_for))
        if q >= 1:
            return None

    state = {"alpha": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "reveal": 1.0, "angle": 0.0, "crack": 0.0,
             "walking": False}
    if enter_motion in ("fade_in", "count_up"):
        state["alpha"] = p
    elif enter_motion in ("slide_up", "stagger"):
        state["alpha"], state["dy"] = p, (1 - p) * SLIDE
    elif enter_motion == "slide_left":
        state["alpha"], state["dx"] = p, (1 - p) * SLIDE
    elif enter_motion == "scale_in":
        state["alpha"], state["scale"] = p, 0.92 + 0.08 * p
    elif enter_motion == "snap":
        state["alpha"], state["scale"] = min(1.0, raw * 3), _back(raw) * 0.4 + 0.6
    elif enter_motion == "walk_in":
        state["dx"], state["walking"] = -(1 - _ease_io(raw)) * 760, raw < 1
    elif enter_motion in ("draw", "fill"):
        state["reveal"] = p
        state["alpha"] = min(1.0, p * 3)
    if element.get("type") == "progress" and enter_motion in ("count_up", "fill"):
        state["reveal"], state["alpha"] = p, 1.0

    if exit_motion == "fade_out":
        state["alpha"] *= 1 - q
    elif exit_motion == "slide_up":
        state["alpha"], state["dy"] = state["alpha"] * (1 - q), state["dy"] - q * SLIDE
    elif exit_motion == "slide_left":
        state["alpha"], state["dx"] = state["alpha"] * (1 - q), state["dx"] - q * SLIDE
    elif exit_motion == "collapse":
        state["alpha"], state["scale"] = state["alpha"] * (1 - q), state["scale"] * (1 - 0.12 * q)
    elif exit_motion == "toss":
        state["dx"], state["dy"], state["angle"] = state["dx"] + q * 620, state["dy"] - q * 820, -q * 300
        state["alpha"] *= 1 - max(0.0, q - 0.7) / 0.3
    elif exit_motion == "crack":
        state["crack"] = q
    return state if state["alpha"] > 0.01 else None


def _place(frame: Image.Image, element: dict, sprite: Image.Image, t: float, duration: float, colors: dict) -> None:
    state = _motion(element, t, duration)
    if state is None:
        return
    image = sprite
    if element.get("type") == "progress":
        image = _progress(sprite, element, state["reveal"])
    elif element.get("type") == "slots":
        image = _spin(sprite, element, t)
    elif state["reveal"] < 1:
        cut = max(1, round(sprite.width * state["reveal"]))
        image = sprite.copy()
        ImageDraw.Draw(image).rectangle((cut, 0, sprite.width, sprite.height), fill=(0, 0, 0, 0))
    box = element.get("box") or {}
    x = int(box.get("x") or 0) - 40 + state["dx"]
    y = int(box.get("y") or 0) - 40 + state["dy"]
    if state["crack"] > 0:
        _crack(frame, image, x, y, state["crack"], _rgb(colors["warning"]), state["alpha"])
        return
    _paste(frame, image, x, y, state["scale"], state["alpha"], state["angle"])


def _paste(frame: Image.Image, image: Image.Image, x: float, y: float, scale: float = 1.0, alpha: float = 1.0,
           angle: float = 0.0) -> None:
    if scale != 1:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        x, y = x + (image.width - size[0]) / 2, y + (image.height - size[1]) / 2
        image = image.resize(size, Image.BILINEAR)
    if angle:
        rotated = image.rotate(angle, resample=Image.BICUBIC, expand=True)
        x, y = x - (rotated.width - image.width) / 2, y - (rotated.height - image.height) / 2
        image = rotated
    if alpha < 1:
        image = image.copy()
        image.putalpha(image.getchannel("A").point(lambda value: round(value * alpha)))
    x, y = round(x), round(y)
    if x >= frame.width or y >= frame.height or x + image.width <= 0 or y + image.height <= 0:
        return
    frame.alpha_composite(image, (max(0, x), max(0, y)), (max(0, -x), max(0, -y)))


def _spin(sprite: Image.Image, element: dict, t: float) -> Image.Image:
    strip, window = element.get("_strip"), element.get("_window")
    if strip is None or window is None:
        return sprite
    row_h = window[3] - window[1]
    spin = 1 - (1 - min(1.0, max(0.0, (t - float(element.get("enter_at") or 0)) / SPIN_SECONDS))) ** 3
    offset = round(spin * (strip.height - row_h))
    image = sprite.copy()
    view = strip.crop((0, offset, strip.width, offset + row_h))
    if spin < 1:
        view = view.filter(ImageFilter.GaussianBlur(4 * (1 - spin)))
    image.alpha_composite(view, (window[0], window[1]))
    return image


def _crack(frame: Image.Image, image: Image.Image, x: float, y: float, q: float, color: tuple, alpha: float) -> None:
    lines = min(1.0, q * 2)
    cracked = image.copy()
    draw = ImageDraw.Draw(cracked)
    mid = cracked.width / 2
    path = [(mid + offset, cracked.height * index / 6) for index, offset in enumerate((0, -26, 18, -14, 22, -10, 6))]
    shown = path[: max(2, round(len(path) * lines))]
    draw.line(shown, fill=color + (255,), width=7, joint="curve")
    if q < 0.5:
        _paste(frame, cracked, x, y, 1.0, alpha)
        return
    split = (q - 0.5) / 0.5
    left = cracked.crop((0, 0, round(mid), cracked.height))
    right = cracked.crop((round(mid), 0, cracked.width, cracked.height))
    fade = alpha * (1 - split)
    _paste(frame, left, x - split * 70, y + split * split * 260, 1.0, fade, split * 8)
    _paste(frame, right, x + mid + split * 70, y + split * split * 300, 1.0, fade, -split * 10)


def _beat(element: dict, t: float) -> tuple:
    pose = str(element.get("pose") or "neutral")
    prop = str(element.get("prop_label") or "")
    since = t - float(element.get("enter_at") or 0)
    for beat in sorted(element.get("beats") or [], key=lambda item: float(item.get("at") or 0)):
        at = float(beat.get("at") or 0)
        if t >= at:
            pose = str(beat.get("pose") or pose)
            prop = str(beat.get("prop_label") if beat.get("prop_label") is not None else prop)
            since = t - at
    return pose, prop, since


_SIZED: dict = {}


def _draw_character(frame: Image.Image, element: dict, library: dict, t: float, duration: float, colors: dict) -> None:
    state = _motion(element, t, duration)
    if state is None:
        return
    pose, prop, since = _beat(element, t)
    if state["walking"]:
        pose = "walk_a" if int(t / 0.22) % 2 == 0 else "walk_b"
        since = 1.0
    image, anchors = library.get(pose) or library["neutral"]
    box = element.get("box") or {}
    s = max(0.2, float(box.get("w") or FIGURE_WIDTH) / FIGURE_WIDTH)
    key = (pose, round(s, 3))
    if key not in _SIZED:
        _SIZED[key] = image.resize((round(image.width * s), round(image.height * s)), Image.LANCZOS)
    sized = _SIZED[key]
    settle = (1 - _ease(since / 0.35)) * 14 * s
    breathe = math.sin(t * 2 * math.pi / 3.4) * 4 * s
    if state["walking"]:
        settle = -abs(math.sin(t * math.pi / 0.22)) * 10 * s
    x = float(box.get("x") or 0) - (POSE_HEAD[0] - FIGURE_WIDTH / 2) * s + state["dx"]
    y = max(float(box.get("y") or 0), frame.height + 40 - sized.height) + state["dy"] + settle + breathe
    lens = anchors.get("lens")
    if lens and prop:
        _lens_view(frame, prop, [x + value * s if index % 2 == 0 else y + value * s for index, value in enumerate(lens)],
                   colors, state["alpha"])
    _paste(frame, sized, x, y, 1.0, state["alpha"])
    hand = anchors.get("hand")
    if hand and prop and pose in ("pinch", "toss"):
        chip = _chip(prop, round(64 * s / 0.75), colors, element.get("tone") == "warning")
        hx, hy = x + hand[0] * s - chip.width / 2, y + hand[1] * s - chip.height + 18 * s
        if pose == "pinch":
            _paste(frame, chip, hx, hy, 1.0, state["alpha"])
        elif since < 0.9:
            fly = _ease(since / 0.9)
            _paste(frame, chip, hx + fly * 520, hy - fly * 760 + fly * fly * 200, 1.0, state["alpha"] * (1 - fly * 0.6), -fly * 320)


def _lens_view(frame: Image.Image, label: str, box: list, colors: dict, alpha: float) -> None:
    left, top, right, bottom = box
    w, h = max(8, round(right - left)), max(8, round(bottom - top))
    view = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(view)
    draw.ellipse((0, 0, w + 7, h + 7), fill=_rgb(colors["card"]) + (240,), outline=_rgb(colors["accent"]) + (160,), width=6)
    inset = min(w, h) * 0.16
    _write(view, label, (inset, inset, w + 8 - inset, h + 8 - inset), _rgb(colors["text"]), weight="Bold",
           max_size=120, center=True)
    _paste(frame, view, left - 4, top - 4, 1.0, alpha)


def _chip(label: str, height: int, colors: dict, warning: bool) -> Image.Image:
    font = _font(round(height * 0.62), "Bold")
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    width = round(measure.textlength(label, font=font) + height)
    pad = 24
    chip = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    inner = (pad, pad, pad + width, pad + height)
    _shadow(chip, inner, height // 2)
    color = _rgb(colors["warning"] if warning else colors["accent"])
    draw = ImageDraw.Draw(chip)
    draw.rounded_rectangle(inner, height // 2, fill=_rgb(colors["card"]) + (255,), outline=color + (255,), width=4)
    box = draw.textbbox((0, 0), label, font=font)
    draw.text((pad + (width - (box[2] - box[0])) / 2 - box[0], pad + (height - (box[3] - box[1])) / 2 - box[1]), label,
              font=font, fill=color + (255,))
    return chip


def _progress(sprite: Image.Image, element: dict, fraction: float) -> Image.Image:
    left, top, right, bottom = element.get("_track") or (0, 0, sprite.width, sprite.height)
    image = sprite.copy()
    draw = ImageDraw.Draw(image)
    cut = left + max(0, round((right - left) * fraction))
    track = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    ImageDraw.Draw(track).rounded_rectangle((0, 0, right - left, bottom - top), (bottom - top) // 2, fill=(43, 43, 43, 36))
    draw.rectangle((cut, top, right, bottom), fill=(0, 0, 0, 0))
    image.alpha_composite(track.crop((cut - left, 0, right - left, bottom - top)), (cut, top))
    return image


def _write(sprite: Image.Image, label: str, area: tuple, color: tuple, *, weight: str, max_size: int,
           center: bool = False) -> None:
    if not label:
        return
    left, top, right, bottom = area
    width, height = right - left, bottom - top
    draw = ImageDraw.Draw(sprite)
    for size in range(max_size, 27, -4):
        font = _font(size, weight)
        chars = max(6, int(width / (size * 0.52)))
        lines = textwrap.wrap(label, chars, break_long_words=False, break_on_hyphens=False) or [label]
        line_height = round(size * 1.18)
        widest = max(draw.textlength(line, font=font) for line in lines)
        if widest <= width and line_height * len(lines) <= height:
            y = top + (height - line_height * len(lines)) // 2
            for line in lines:
                x = left + (width - draw.textlength(line, font=font)) / 2 if center else left
                draw.text((x, y), line, font=font, fill=color + (255,))
                y += line_height
            return
    font = _font(28, weight)
    draw.text((left, top), textwrap.shorten(label, 60), font=font, fill=color + (255,))


_FONTS: dict = {}


def _font(size: int, weight: str) -> ImageFont.FreeTypeFont:
    key = (size, weight)
    if key in _FONTS:
        return _FONTS[key]
    chosen = None
    try:
        for index in range(16):
            candidate = ImageFont.truetype(FONT_FILE, size, index=index)
            if candidate.getname()[1] == weight:
                chosen = candidate
                break
            if chosen is None and candidate.getname()[1] in ("Bold", "Demi Bold"):
                chosen = candidate
    except OSError:
        pass
    _FONTS[key] = chosen or ImageFont.load_default(size)
    return _FONTS[key]


def _shadow(sprite: Image.Image, box: tuple, radius: int) -> None:
    layer = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
    left, top, right, bottom = box
    ImageDraw.Draw(layer).rounded_rectangle((left, top + 12, right, bottom + 12), radius, fill=(43, 43, 43, 40))
    sprite.alpha_composite(layer.filter(ImageFilter.GaussianBlur(16)))


def _cover(image: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / image.width, h / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left = (resized.width - w) // 2
    top = max(0, (resized.height - h) // 4)
    return resized.crop((left, top, left + w, top + h))


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3


def _ease_io(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def _back(value: float) -> float:
    value = max(0.0, min(1.0, value))
    c = 1.70158
    return 1 + (c + 1) * (value - 1) ** 3 + c * (value - 1) ** 2


def _rgb(value: str) -> tuple:
    value = str(value).lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--build-poses":
        print(json.dumps(build_pose_library(Path(sys.argv[2]))))
        return 0
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "An explainer render file is required."}))
        return 1
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(render_explainer(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
