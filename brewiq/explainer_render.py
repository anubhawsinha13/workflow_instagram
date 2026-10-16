"""Render a BrewIQ motion-graphics explainer plan into a vertical mp4. This does not publish."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reel import ffmpeg_bin  # noqa: E402

FONT_DIR = ROOT / "brand" / "fonts"
FONT_FILE = str(FONT_DIR / "Archivo-Variable.ttf")
DISPLAY_FONT = str(FONT_DIR / "ArchivoBlack-Regular.ttf")
FALLBACK_FONT_FILE = "/System/Library/Fonts/Avenir Next.ttc"
FONT_WEIGHTS = {"Regular": 400, "Medium": 500, "Demi Bold": 600, "Bold": 700, "Heavy": 800}

# The Highlighter look: white page, near-black heavy type, a yellow marker behind key words.
BRAND_COLORS = {
    "background": "#FFFFFF",
    "text": "#111111",
    "accent": "#2F6BFF",
    "accent_dark": "#1B3FB8",
    "warning": "#E5484D",
    "card": "#FFFFFF",
    "highlight": "#FFE14D",
    "grid": "#E6E6E1",
}
WORDMARK = "BrewIQ"
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

# Standing composition, matching the reference reel: host on the left, type on the right.
HOST_LEFT = 8
HOST_FOOT = 1460
HOST_WIDTH = 280  # About 30% of the frame, so the words lead.
TEXT_COLUMN = {"x": 440, "y": 470, "w": 490, "h": 780}
WIDE_POSES = {"present", "reach", "point", "point_viewer", "push", "pinch", "toss"}
RAIL_BOX = {"x": 64, "y": 190, "w": 640, "h": 100}  # The wordmark takes the top-right corner.
LOWER_BOX = {"x": 40, "y": 1330, "w": 890, "h": 170}
STAGE_TYPES = ("card", "text", "bubble", "slots", "token", "lens", "title", "prompt_card")
HOOK_TYPES = ("card", "text", "bubble", "title")
# Between the chapter rail and the top of the host's head.
HOOK_BAND = {"x": 64, "y": 310, "w": 866, "h": 330}


def _overlaps(box: dict, other: dict) -> bool:
    x, y, w, h = (float(box.get(key) or 0) for key in ("x", "y", "w", "h"))
    return x < other["x"] + other["w"] and other["x"] < x + w and y < other["y"] + other["h"] and other["y"] < y + h


def _stage_explainer(scenes: list) -> list:
    """Put the host on the left and every word on the right, and keep the opening frame filled.

    Slack explainers used to let the model pick coordinates, so cards sat on the host's head
    and scene 1 walked him in from off-screen, which left the first still blank.
    """
    chips = []
    for scene in scenes:
        label = str(scene.get("purpose") or "").replace("_", " ").strip()
        if label and label.upper() not in chips:
            chips.append(label.upper())
    staged = []
    for index, scene in enumerate(scenes):
        elements = [dict(element) for element in (scene.get("elements") or [])]
        host = next((element for element in elements if element.get("type") == "character"), None)
        words = [element for element in elements if element.get("type") in STAGE_TYPES]
        extras = [element for element in elements
                  if element.get("type") not in ("character", "rail", "lower_third") and element not in words]
        if host:
            host = dict(host)
            left = HOST_LEFT - (60 if (host.get("pose") or "neutral") in WIDE_POSES else 0)
            host["box"] = {"x": left, "y": 0, "w": HOST_WIDTH, "h": 900}
            host["foot_y"] = HOST_FOOT
            host["enter_at"] = 0.0
            host["enter_duration"] = 0.01
            host["enter_motion"] = "none"
            host["exit_motion"] = "hold"
            host["settle"] = index > 0
        gap = 24
        placed = []
        # Scene 1 sets the hook large across the top, above the host, so it reads in the first second.
        hook = words[0] if index == 0 and host and words and words[0].get("type") in HOOK_TYPES else None
        column = TEXT_COLUMN
        if hook:
            item = dict(hook)
            item["box"] = dict(HOOK_BAND)
            item["type"] = "title"
            item["enter_at"] = 0.0
            item["enter_duration"] = 0.01
            item["enter_motion"] = "none"
            placed.append(item)
            words = words[1:]
            top = HOOK_BAND["y"] + HOOK_BAND["h"] + gap
            column = {**TEXT_COLUMN, "y": top, "h": TEXT_COLUMN["y"] + TEXT_COLUMN["h"] - top}
            for extra in extras:
                if _overlaps(extra.get("box") or {}, HOOK_BAND):
                    extra["box"] = {**(extra.get("box") or {}), "x": column["x"], "y": top}
                    column = {**column, "y": top + 64 + gap, "h": column["h"] - 64 - gap}
        count = max(1, len(words))
        cell_h = (column["h"] - gap * (count - 1)) // count
        for order, element in enumerate(words):
            item = dict(element)
            item["box"] = {
                "x": column["x"],
                "y": column["y"] + order * (cell_h + gap),
                "w": column["w"],
                "h": cell_h,
            }
            if count == 1 and not hook and item.get("type") == "card" and len(str(item.get("label") or "").split()) <= 10:
                item["type"] = "title"
            # Only the first words on screen are pinned to frame 0 so the stage is never empty.
            # Later words keep the planner's entrance, so the snaps that carry the story still move.
            if order == 0 and not hook:
                item["enter_at"] = 0.0
                item["enter_duration"] = 0.01
                item["enter_motion"] = "none"
            placed.append(item)
        rail = {
            "id": f"rail-{index + 1}", "type": "rail", "box": dict(RAIL_BOX),
            "enter_at": 0.0, "enter_duration": 0.01, "enter_motion": "none", "exit_motion": "hold",
            "label": str(scene.get("rail_label") or ""),
            "chips": chips, "active": min(index, max(0, len(chips) - 1)),
            "timer": None, "timeline": False, "chrome": True,
        }
        lower = {
            "id": f"lower-{index + 1}", "type": "lower_third", "box": dict(LOWER_BOX),
            "enter_at": 0.0, "enter_duration": 0.01, "enter_motion": "none", "exit_motion": "hold",
            "label": str(scene.get("caption") or scene.get("narration") or "").strip(), "chrome": True,
        }
        next_elements = [rail, *placed, *extras]
        if host:
            next_elements.append(host)
        if lower["label"]:
            next_elements.append(lower)
        staged.append({**scene, "elements": next_elements})
    return staged


LIVE_TYPES = ("kinetic", "alert")
WHITE = (255, 255, 255)
ALERT_RED = (255, 59, 48)


def _mix(a: tuple, b: tuple, amount: float) -> tuple:
    amount = max(0.0, min(1.0, amount))
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def _accent_at(accents: list, t: float) -> tuple:
    """The scene color at time t. Each change blends over 0.4 seconds instead of jumping."""
    if not accents:
        return _rgb(BRAND_COLORS["highlight"])
    color = _rgb(accents[0]["color"])
    for item in accents[1:]:
        start = float(item["start"])
        if t >= start - 0.2:
            color = _mix(color, _rgb(item["color"]), (t - start + 0.2) / 0.4)
    return color


def _glow_text(frame: Image.Image, xy: tuple, text: str, font, fill: tuple, alpha: float = 1.0, scale: float = 1.0) -> None:
    """Type that reads on any picture: a soft dark shadow under it, the way phone captions do it."""
    box = font.getbbox(text)
    width, height = box[2] + 24, box[3] + 24
    layer = Image.new("RGBA", (width + 24, height + 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((12, 14), text, font=font, fill=(0, 0, 0, 200), stroke_width=4, stroke_fill=(0, 0, 0, 200))
    layer = layer.filter(ImageFilter.GaussianBlur(8))
    # A dark outline keeps the scene-colored words readable even when the picture around them is the same color.
    ImageDraw.Draw(layer).text((12, 8), text, font=font, fill=fill + (255,), stroke_width=4, stroke_fill=(20, 14, 10, 235))
    if scale != 1:
        size = (max(1, round(layer.width * scale)), max(1, round(layer.height * scale)))
        offset = ((layer.width - size[0]) / 2, (layer.height - size[1]) / 2)
        layer = layer.resize(size, Image.BILINEAR)
    else:
        offset = (0, 0)
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda value: round(value * alpha)))
    frame.alpha_composite(layer, (max(0, round(xy[0] - 12 + offset[0])), max(0, round(xy[1] - 12 + offset[1]))))


def _kinetic_lines(text: str, width: int, height: int, top: int, low: int) -> tuple:
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    for size in range(top, low - 1, -4):
        font = _serif(size, True)
        lines, line = [], []
        for word in text.split():
            trial = " ".join(line + [word])
            if line and probe.textlength(trial, font=font) > width:
                lines.append(line)
                line = [word]
            else:
                line.append(word)
        if line:
            lines.append(line)
        if len(lines) * size * 1.12 <= height and len(lines) <= 3:
            return font, lines, round(size * 1.12)
    font = _serif(low, True)
    return font, [text.split()], round(low * 1.12)


def _draw_live(frame: Image.Image, element: dict, t: float, duration: float, last: bool = False) -> None:
    """Text drawn fresh each frame: words that pop in like iOS text effects, and an alert that shakes."""
    box = element.get("box") or {}
    x, y, w, h = (int(box.get(key) or 0) for key in ("x", "y", "w", "h"))
    at = float(element.get("enter_at") or 0)
    local = t - at
    if local < 0:
        return
    # Fade out in the last moments of the beat so the next words take over smoothly.
    fade = 1.0 if last else max(0.0, min(1.0, (duration - t) / 0.14))
    if element.get("type") == "alert":
        label = str(element.get("label") or "").strip().upper()
        font = _serif(78, True)
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        text_w = probe.textlength(label, font=font)
        pill_w, pill_h = text_w + 170, 128
        sprite = Image.new("RGBA", (round(pill_w) + 40, pill_h + 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sprite)
        draw.rounded_rectangle((26, 30, 26 + pill_w, 30 + pill_h), 64, fill=(0, 0, 0, 90))
        sprite = sprite.filter(ImageFilter.GaussianBlur(8))
        draw = ImageDraw.Draw(sprite)
        draw.rounded_rectangle((20, 20, 20 + pill_w, 20 + pill_h), 64, fill=ALERT_RED + (255,))
        # A warning triangle with an exclamation mark.
        tx, ty = 60, 20 + pill_h / 2
        draw.polygon(((tx, ty + 30), (tx + 34, ty - 32), (tx + 68, ty + 30)), fill=(255, 255, 255, 255))
        draw.rectangle((tx + 31, ty - 10, tx + 37, ty + 12), fill=ALERT_RED + (255,))
        draw.rectangle((tx + 31, ty + 17, tx + 37, ty + 23), fill=ALERT_RED + (255,))
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text((146, 20 + pill_h / 2 - (bbox[1] + bbox[3]) / 2), label, font=font, fill=(255, 255, 255, 255))
        slam = 1 + 0.6 * (1 - _ease(local / 0.18))
        # Jitter, like the iOS effect: fast at first, then a small tremble that stays.
        shake = (14 * max(0.0, 1 - local / 0.5) + 3) * math.sin(local * 70)
        tilt = (4 * max(0.0, 1 - local / 0.5) + 0.8) * math.sin(local * 55 + 1)
        left = x + (w - sprite.width) / 2 + shake
        _paste(frame, sprite, left, y + (h - sprite.height) / 2, slam, min(1.0, local / 0.08) * fade, tilt)
        return
    text = str(element.get("label") or "").strip()
    if not text:
        return
    font, lines, line_h = _kinetic_lines(text, w, h, int(element.get("size") or 108), int(element.get("min_size") or 56))
    accent = _accent_at(element.get("accents") or [], float(element.get("_scene_start") or 0) + t)
    keys = {word.lower().strip(".,!?") for word in element.get("keywords") or []}
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    space = probe.textlength(" ", font=font)
    total_h = line_h * len(lines)
    cursor_y = y + (h - total_h) * float(element.get("valign", 0.0))
    index = 0
    for line in lines:
        line_w = probe.textlength(" ".join(line), font=font)
        cursor_x = x + (w - line_w) / 2 if element.get("center") else x
        for word in line:
            start = index * 0.07
            grow = _ease((local - start) / 0.22)
            if grow > 0:
                is_key = word.lower().strip(".,!?") in keys
                # "Big": each word lands slightly oversized, then settles.
                scale = 1 + 0.16 * (1 - _back((local - start) / 0.24)) if grow < 1 else 1.0
                _glow_text(frame, (cursor_x, cursor_y), word, font, accent if is_key else WHITE, min(1.0, grow * 1.4) * fade,
                           max(0.6, scale))
            cursor_x += probe.textlength(word, font=font) + space
            index += 1
        cursor_y += line_h


LOGO_FILE = ROOT / "brand" / "logo.png"
LOGO_HEIGHT = 168
_LOGO: list = []


def _logo() -> Image.Image | None:
    """The BrewIQ logo, cut out, at corner size, with a soft shadow so it reads on bright and dark scenes."""
    if not _LOGO:
        try:
            with Image.open(LOGO_FILE) as picture:
                logo = picture.convert("RGBA")
        except OSError:
            _LOGO.append(None)
            return None
        logo = logo.resize((round(logo.width * LOGO_HEIGHT / logo.height), LOGO_HEIGHT), Image.LANCZOS)
        pad = 16
        layer = Image.new("RGBA", (logo.width + pad * 2, logo.height + pad * 2), (0, 0, 0, 0))
        shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 150), (pad, pad + 2), logo.getchannel("A"))
        layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
        layer.alpha_composite(logo, (pad, pad))
        _LOGO.append(layer)
    return _LOGO[0]


def _corner_mark(frame: Image.Image, accent: tuple, mark: str | None = None) -> None:
    """The account's mark tucked into the top-right corner: the BrewIQ logo, or another account's name in type.

    mark "none" draws nothing. Falls back to the BrewIQ wordmark when the logo file is missing.
    """
    if mark == "none":
        return
    if mark:
        font = _serif(34, True)
        text_w = ImageDraw.Draw(frame).textlength(mark, font=font)
        _glow_text(frame, (frame.width - text_w - 34, 64), mark, font, WHITE, 0.9)
        return
    logo = _logo()
    if logo is not None:
        frame.alpha_composite(logo, (frame.width - logo.width - 14, 30))
        return
    font = _serif(42, True)
    text_w = ImageDraw.Draw(frame).textlength(WORDMARK, font=font)
    _glow_text(frame, (frame.width - text_w - 30, 60), WORDMARK, font, WHITE, 0.92)


class _Backdrop:
    """The moving picture behind a story reel: frames of a clip, or stills with a slow push-in.

    A clip is read in order, one frame per output frame, and holds its last frame if it runs short.
    """

    PUSH = 0.07

    def __init__(self, spec: dict, width: int, height: int, fps: int, ffmpeg: str) -> None:
        self.size, self.fps, self.ffmpeg = (width, height), fps, ffmpeg
        self.fade = float(spec.get("fade") or 0)  # Seconds a shot dissolves into the one before it.
        self.push = float(spec.get("push") if spec.get("push") is not None else self.PUSH)
        self.video = str(spec.get("video") or "")
        self.stills = []
        for item in spec.get("stills") or spec.get("shots") or []:
            image = None
            if item.get("path"):
                with Image.open(item["path"]) as picture:
                    image = ImageOps.fit(picture.convert("RGB"), (width, height), Image.LANCZOS)
            # A shot without a picture plays the clip at that moment.
            self.stills.append((float(item.get("start") or 0), float(item.get("duration") or 1), image))
        self.process = None
        self.index = -1
        self.last: Image.Image | None = None

    def _open(self) -> None:
        width, height = self.size
        self.process = subprocess.Popen(
            [self.ffmpeg, "-loglevel", "error", "-i", self.video, "-an", "-vf",
             f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={self.fps}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.index = -1

    def frame(self, t: float) -> Image.Image:
        if self.video and not self.stills:
            return self._video_frame(max(0, round(t * self.fps)))
        index = 0
        for position, item in enumerate(self.stills):
            if item[0] <= t:
                index = position
        start, duration, image = self.stills[index]
        if image is None:
            return self._video_frame(max(0, round(t * self.fps)))
        current = self._still(self.stills[index], t)
        if self.fade and index > 0 and t - start < self.fade and self.stills[index - 1][2] is not None:
            # Dissolve from the previous shot, which keeps drifting while it fades out.
            blend = _ease_io((t - start) / self.fade)
            return Image.blend(self._still(self.stills[index - 1], t), current, blend)
        return current

    def _still(self, shot: tuple, t: float) -> Image.Image:
        start, duration, image = shot
        progress = min(1.0, max(0.0, (t - start) / max(0.01, duration)))
        scale = 1 + self.push * progress
        width, height = self.size
        crop_w, crop_h = width / scale, height / scale
        left, top = (width - crop_w) / 2, (height - crop_h) * 0.4
        return image.resize(self.size, Image.BILINEAR, box=(left, top, left + crop_w, top + crop_h)).convert("RGBA")

    def _video_frame(self, wanted: int) -> Image.Image:
        if self.process is None or wanted < self.index:
            self.close()
            self._open()
        size = self.size[0] * self.size[1] * 3
        while self.index < wanted:
            raw = self.process.stdout.read(size) if self.process and self.process.stdout else b""
            if len(raw) < size:
                break  # The clip ended: hold its last frame.
            self.last = Image.frombytes("RGB", self.size, raw)
            self.index += 1
        if self.last is None:
            return Image.new("RGBA", self.size, (0, 0, 0, 255))
        return self.last.convert("RGBA")

    def close(self) -> None:
        if self.process is not None:
            if self.process.stdout:
                self.process.stdout.close()
            self.process.kill()
            self.process.wait()
            self.process = None


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
    # Every reel uses the brand palette, whatever colors the plan asks for.
    colors = dict(BRAND_COLORS)
    radius = int(canvas.get("corner_radius") or 32)

    host = None
    library = load_pose_library()
    if not library and any(element.get("type") == "character" for scene in scenes for element in scene.get("elements") or []):
        host = _host_image(payload, out.parent, make_host)

    kinds = {element.get("type") for scene in scenes for element in scene.get("elements") or []}
    if data.get("format") == "brewiq-motion-explainer" or (
        "character" in kinds and "rail" not in kinds
    ):
        scenes = _stage_explainer(scenes)
    background = _background(width, height, colors)
    backdrop_spec = payload.get("backdrop") if isinstance(payload.get("backdrop"), dict) else None
    backdrop = _Backdrop(backdrop_spec, width, height, fps, ffmpeg) if backdrop_spec else None
    wordmark = _wordmark_layer(width, height, colors, pill=backdrop is not None)
    total = sum(float(scene.get("duration_seconds") or 0) for scene in scenes)
    prepared = []
    for scene in scenes:
        sprites = []
        scene_start = float(scene.get("start_seconds") or 0)
        for element in scene.get("elements") or []:
            element["_scene_start"] = scene_start
            element["_total"] = total
            if (element.get("type") == "character" and library) or element.get("type") in LIVE_TYPES:
                sprites.append((element, None))
                continue
            sprite = _sprite(element, colors, radius, host)
            if sprite is not None:
                sprites.append((element, sprite))
        prepared.append((
            scene_start,
            float(scene.get("duration_seconds") or 0),
            sprites,
            str(scene.get("camera") or "steady"),
            _focus(scene.get("elements") or [], width, height),
        ))
    frames = max(1, round(total * fps))

    def compose(t: float, last: bool = False) -> Image.Image:
        frame = backdrop.frame(t) if backdrop is not None else background.copy()
        for start, duration, sprites, camera, focus in prepared:
            if start <= t < start + duration or (last and start <= t):
                local = t - start
                # Host first, then cards and titles, then the camera, then the rail and lower third.
                # That keeps type readable and the chrome still while the stage moves.
                for element, sprite in sprites:
                    if sprite is None and element.get("type") not in LIVE_TYPES:
                        _draw_character(frame, element, library, local, duration, colors)
                for element, sprite in sprites:
                    if sprite is not None and not _is_chrome(element):
                        _place(frame, element, sprite, local, duration, colors)
                for element, sprite in sprites:
                    if element.get("type") in LIVE_TYPES:
                        _draw_live(frame, element, local, duration, last)
                frame = _camera(frame, camera, focus, local / max(0.01, duration))
                for element, sprite in sprites:
                    if sprite is not None and _is_chrome(element):
                        _place(frame, element, sprite, local, duration, colors)
        if backdrop is not None:
            _corner_mark(frame, _accent_at(backdrop_spec.get("accents") or [], t), backdrop_spec.get("mark"))
        else:
            frame.alpha_composite(wordmark)
        return frame

    preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else None
    if preview:
        # Stills for layout review. No video is encoded.
        folder = Path(str(preview.get("folder") or out.parent))
        paths = []
        for index, moment in enumerate(preview.get("times") or []):
            dest = folder / f"preview-{index + 1:02d}.png"
            compose(min(max(0.0, float(moment)), max(0.0, total - 0.001))).convert("RGB").save(dest)
            paths.append(str(dest))
        if backdrop is not None:
            backdrop.close()
        return {"ok": True, "previews": paths, "seconds": round(total, 2), "error": ""}

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
            frame = compose(index / fps, last=index == frames - 1)
            process.stdin.write(frame.convert("RGB").tobytes())
        process.stdin.close()
    except BrokenPipeError:
        pass
    stderr = process.stderr.read().decode("utf-8", "ignore") if process.stderr else ""
    process.wait()
    if backdrop is not None:
        backdrop.close()
    if process.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        detail = stderr.strip().splitlines()
        return {"ok": False, "error": (detail[-1] if detail else "ffmpeg could not render the explainer.")[:240]}
    cover = out.with_name("cover.jpg")
    hook_element = _first_hook(prepared[0][2] if prepared else [])
    try:
        # A story reel's cover is its first frame: the picture with the hook on it.
        cover_frame = compose(min(0.8, total)) if backdrop is not None else _opening_still(
            width, height, colors, radius,
            prepared[0][2] if prepared else [],
            None,  # The video frames draw no backdrop behind the host, so the cover matches them.
            hook_element,
        )
        cover_frame.convert("RGB").save(cover, quality=90)
    except OSError:
        cover = None
    if backdrop is not None:
        backdrop.close()
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
    frame.alpha_composite(_wordmark_layer(width, height, colors))
    return frame


def opening_still(canvas: dict, elements: list) -> Image.Image:
    """The cover frame: the hook label is visible even when its entrance is later than 0."""
    width = int(canvas.get("width") or 1080)
    height = int(canvas.get("height") or 1920)
    colors = dict(BRAND_COLORS)
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
    """A white page with a faint dot grid, like a notebook, so white cards still read as objects."""
    image = Image.new("RGBA", (width, height), colors["background"])
    draw = ImageDraw.Draw(image)
    dot = _rgb(colors.get("grid") or "#E6E6E1") + (255,)
    step = 48
    for y in range(step // 2, height, step):
        for x in range(step // 2, width, step):
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=dot)
    return image


def _wordmark_layer(width: int, height: int, colors: dict, pill: bool = False) -> Image.Image:
    """BrewIQ wordmark with a small cup, top right, below Instagram's top controls.

    Over a picture it sits on a white pill so it stays readable.
    """
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _serif(40)
    ink = _rgb(colors["text"]) + (255,)
    text_w = draw.textlength(WORDMARK, font=font)
    cup_w, cup_h, gap = 34, 30, 12
    right, top = 930, 196
    left = right - text_w - gap - cup_w - 10
    if pill:
        draw.rounded_rectangle((left - 20, top - 6, right + 20, top + 52), 29, fill=_rgb(colors["card"]) + (235,))
    # Cup: a yellow body with a dark outline and handle.
    body = (left, top + 8, left + cup_w, top + 8 + cup_h)
    draw.rounded_rectangle(body, 7, fill=_rgb(colors["highlight"]) + (255,), outline=ink, width=4)
    draw.arc((left + cup_w - 8, top + 14, left + cup_w + 12, top + 32), -90, 90, fill=ink, width=4)
    box = draw.textbbox((0, 0), WORDMARK, font=font)
    draw.text((right - text_w, top + 8 + cup_h / 2 - (box[1] + box[3]) / 2), WORDMARK, font=font, fill=ink)
    return layer


CHROME_TYPES = ("rail", "lower_third")


def _is_chrome(element: dict) -> bool:
    """Chrome stays still while the camera moves the stage."""
    return bool(element.get("chrome")) or element.get("type") in CHROME_TYPES


def _focus(elements: list, width: int, height: int) -> tuple:
    boxes = [element.get("box") or {} for element in elements
             if element.get("type") != "character" and not _is_chrome(element)]
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


def _draw_app_glyph(draw: ImageDraw.ImageDraw, kind: str, box: tuple, fill: tuple) -> None:
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
    _draw_app_glyph(
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


def _draw_step_rail(sprite: Image.Image, inner: tuple, label: str, text: tuple, accent: tuple) -> None:
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
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius, fill=card + (255,), outline=text + (255,), width=4)
        ImageDraw.Draw(sprite).rounded_rectangle(
            (pad + 28, pad + 26, pad + 28 + 64, pad + 26 + 12), 4, fill=_rgb(BRAND_COLORS["highlight"]) + (255,)
        )
        _write(sprite, label, (pad + 36, pad + 48, pad + w - 36, pad + h - 32), text, weight="Bold",
               max_size=72, serif=True)
    elif kind == "text":
        color = accent if element.get("tone") == "warning" else text
        _write(sprite, label, inner, color, weight="Bold", max_size=120)
    elif kind == "icon":
        size = min(w, h)
        left, top = pad + (w - size) // 2, pad + (h - size) // 2
        _shadow(sprite, (left, top, left + size, top + size), size // 5)
        _paint_tile(sprite, (left, top, left + size, top + size), _icon_kind(label))
    elif kind == "rail" and not element.get("chrome") and not element.get("chips"):
        # The planner's step rail. The layout's chapter-chip rail is drawn by _draw_rail below.
        _shadow(sprite, inner, radius)
        ImageDraw.Draw(sprite).rounded_rectangle(inner, radius, fill=card + (255,))
        _draw_step_rail(sprite, inner, label, text, accent)
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
    elif kind == "rail":
        _draw_rail(sprite, element, colors, pad, w, h)
    elif kind == "title":
        _draw_title(sprite, element, colors, pad, w, h)
    elif kind == "lower_third":
        _draw_lower_third(sprite, element, colors, pad, w, h)
    elif kind == "prompt_card":
        _draw_prompt_card(sprite, element, colors, pad, w, h, radius)
    elif kind == "sheet":
        _draw_sheet(sprite, element, colors, pad, w, h, radius)
    elif kind == "image":
        if not _prepare_image(element, w, h, pad, radius):
            return None
        return _image_sprite(element, 0.0, 0.0)
    elif kind == "screen":
        _draw_screen(sprite, element, colors, pad, w, h)
    elif kind == "summary":
        _draw_summary(sprite, element, colors, pad, w, h)
    elif kind == "tiles":
        if not _prepare_tiles(element, w, h, pad, colors):
            return None
    elif kind == "swatch":
        _draw_swatch(sprite, element, pad, w, h, radius)
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
        # Stay mostly on screen so the opening still is not an empty stage.
        state["dx"], state["walking"] = -(1 - _ease_io(raw)) * 160, raw < 1
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
    elif element.get("type") == "rail":
        image = _rail_frame(sprite, element, colors, float(element.get("_scene_start") or 0) + t)
    elif element.get("type") == "image":
        image = _image_sprite(element, t / max(0.01, duration), t)
    elif element.get("type") == "tiles" and element.get("_cells"):
        image = _tiles_sprite(element, t)
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
    foot_y = element.get("foot_y")
    if foot_y is None:
        foot_y = HOST_FOOT
    key = (pose, round(s, 3), foot_y is not None)
    if key not in _SIZED:
        resized = image.resize((round(image.width * s), round(image.height * s)), Image.LANCZOS)
        if foot_y is not None:
            resized = _fade_feet(resized, round(150 * s))
        _SIZED[key] = resized
    sized = _SIZED[key]
    settle = (1 - _ease(since / 0.35)) * 14 * s if element.get("settle", True) else 0.0
    breathe = math.sin(t * 2 * math.pi / 3.4) * 4 * s
    if state["walking"]:
        settle = -abs(math.sin(t * math.pi / 0.22)) * 10 * s
    x = float(box.get("x") or 0) - (POSE_HEAD[0] - FIGURE_WIDTH / 2) * s + state["dx"]
    if foot_y is not None:
        # The pose stills are cut off below the knees. Standing the figure on foot_y puts that edge
        # behind the lower third, and the fade softens it where the bar is not opaque.
        y = float(foot_y) - sized.height + state["dy"] + settle + breathe
    else:
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
           center: bool = False, serif: bool = False) -> None:
    if not label:
        return
    left, top, right, bottom = area
    width, height = right - left, bottom - top
    make = (lambda size: _serif(size, weight != "Medium")) if serif else (lambda size: _font(size, weight))
    font, lines, line_height, _size = _fit_lines(label, width, height, make, max_size, 22, leading=1.12)
    draw = ImageDraw.Draw(sprite)
    y = top + max(0, (height - line_height * len(lines)) // 2)
    for line in lines:
        x = left + (width - draw.textlength(line, font=font)) / 2 if center else left
        draw.text((x, y), line, font=font, fill=color + (255,))
        y += line_height


SERIF_BOLD = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
SERIF = "/System/Library/Fonts/Supplemental/Georgia.ttf"
_SERIFS: dict = {}


def _serif(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """The display face for headlines: Archivo Black, falling back to Georgia. The name is kept for callers."""
    key = (size, bold)
    if key not in _SERIFS:
        chosen = None
        for path in (DISPLAY_FONT, SERIF_BOLD, SERIF):
            try:
                chosen = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        _SERIFS[key] = chosen or _font(size, "Bold")
    return _SERIFS[key]


def _spaced(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill: tuple, spacing: float) -> float:
    """Draw letter-spaced text and return the x where it ended."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + spacing
    return x - spacing


def _spaced_width(draw: ImageDraw.ImageDraw, text: str, font, spacing: float) -> float:
    return sum(draw.textlength(char, font=font) for char in text) + spacing * max(0, len(text) - 1)


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> list:
    lines: list = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and draw.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def _fit_lines(text: str, width: float, height: float, make_font, max_size: int, min_size: int,
               max_lines: int | None = None, leading: float = 1.14) -> tuple:
    """Largest font that wraps the text inside the box. Returns font, lines, line height, size."""
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for size in range(max_size, min_size - 1, -2):
        font = make_font(size)
        lines = _wrap_pixels(measure, text, font, width)
        line_height = round(size * leading)
        if max_lines and len(lines) > max_lines:
            continue
        if line_height * len(lines) <= height and max(measure.textlength(line, font=font) for line in lines) <= width:
            return font, lines, line_height, size
    font = make_font(min_size)
    lines = _wrap_pixels(measure, text, font, width)
    line_height = round(min_size * leading)
    room = max(1, int(height // line_height))
    if len(lines) > room:
        lines = lines[:room]
        lines[-1] = textwrap.shorten(lines[-1] + " ...", width=max(8, len(lines[-1])), placeholder="...")
    return font, lines, line_height, min_size


def _centered_y(draw: ImageDraw.ImageDraw, font, top: float, height: float) -> float:
    box = draw.textbbox((0, 0), "Hg", font=font)
    return top + (height - (box[3] - box[1])) / 2 - box[1]


def _draw_rail(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int) -> None:
    """Section label, optional countdown, and a row of chapter chips that shows done, active, and next."""
    draw = ImageDraw.Draw(sprite)
    ink = _rgb(colors["text"])
    label = str(element.get("label") or "").upper()
    label_font = _font(24, "Demi Bold")
    top = pad
    if label or element.get("timer"):
        if label:
            _spaced(draw, (pad, _centered_y(draw, label_font, pad, 30)), label, label_font, ink + (200,), 3)
        top = pad + 50
    chips = [str(chip).upper() for chip in (element.get("chips") or [])]
    chip_h = 46
    if chips:
        active = max(0, min(len(chips) - 1, int(element.get("active") or 0)))
        gap = 8
        chip_w = (w - gap * (len(chips) - 1)) / len(chips)
        size = 22
        while size > 15 and max(_spaced_width(draw, chip, _font(size, "Demi Bold"), 1.5) for chip in chips) > chip_w - 14:
            size -= 1
        chip_font = _font(size, "Demi Bold")
        for index, chip in enumerate(chips):
            left = pad + index * (chip_w + gap)
            box = (left, top, left + chip_w, top + chip_h)
            if index == active:
                draw.rounded_rectangle(box, 10, fill=ink + (255,))
                color = (255, 255, 255, 255)
            elif index < active:
                draw.rounded_rectangle(box, 10, fill=ink + (26,))
                color = ink + (150,)
            else:
                draw.rounded_rectangle(box, 10, outline=ink + (90,), width=2)
                color = ink + (140,)
            width = _spaced_width(draw, chip, chip_font, 1.5)
            _spaced(draw, (left + (chip_w - width) / 2, _centered_y(draw, chip_font, top, chip_h)), chip, chip_font, color, 1.5)
    line_y = top + (chip_h + 18 if chips else 0)
    element["_rail"] = {
        "timer_y": pad, "right": pad + w,
        "line": (pad, line_y, pad + w, line_y + 6) if element.get("timeline") else None,
    }


def _rail_frame(sprite: Image.Image, element: dict, colors: dict, t: float) -> Image.Image:
    geometry = element.get("_rail") or {}
    total = float(element.get("_total") or 0)
    if not total or not (element.get("timer") or geometry.get("line")):
        return sprite
    image = sprite.copy()
    draw = ImageDraw.Draw(image)
    ink = _rgb(colors["text"])
    if element.get("timer") == "remaining" and "right" in geometry:
        # Only the chapter-chip rail lays out a countdown. A step rail has no timer geometry.
        seconds = max(0, math.ceil(total - t))
        text = f"{seconds // 60}:{seconds % 60:02d} LEFT"
        font = _font(24, "Demi Bold")
        width = _spaced_width(draw, text, font, 3)
        _spaced(draw, (geometry["right"] - width, _centered_y(draw, font, geometry["timer_y"], 30)), text, font,
                ink + (200,), 3)
    line = geometry.get("line")
    if line:
        left, top, right, bottom = line
        draw.rounded_rectangle(line, 3, fill=ink + (34,))
        filled = left + (right - left) * max(0.0, min(1.0, t / total))
        if filled - left >= 6:
            draw.rounded_rectangle((left, top, filled, bottom), 3, fill=_rgb(colors["accent_dark"]) + (255,))
    return image


def _draw_title(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int) -> None:
    """Serif headline with an optional big number and unit, like '30 MINUTES'."""
    draw = ImageDraw.Draw(sprite)
    ink = _rgb(colors["text"])
    headline = str(element.get("label") or "").strip()
    stat = element.get("stat") if isinstance(element.get("stat"), dict) else {}
    value, unit = str(stat.get("value") or "").strip(), str(stat.get("unit") or "").strip().upper()
    value_size = min(176, int(h * 0.34)) if value else 0
    stat_height = round(value_size * 1.12) + 22 if value else 0
    font, lines, line_height, _size = _fit_lines(
        headline, w, max(60, h - stat_height), lambda size: _serif(size, True), 104, 46, max_lines=4, leading=1.08
    )
    y = pad
    marker = _rgb(colors.get("highlight") or "#FFE14D") + (255,)
    if element.get("panel") and lines:
        # Over a picture, the headline sits on a white panel so the dark type stays readable.
        widest = max(draw.textlength(line, font=font) for line in lines)
        draw.rounded_rectangle(
            (pad - 26, pad - 20, pad + min(w, widest) + 30, pad + line_height * len(lines) + 14), 24,
            fill=_rgb(colors["card"]) + (255,), outline=ink + (255,), width=4,
        )
    for index, line in enumerate(lines):
        if index == len(lines) - 1 and line.strip():
            # The marker swipe sits on the lower half of the last line, like a highlighter pen.
            box = draw.textbbox((pad, y), line, font=font)
            draw.rounded_rectangle(
                (box[0] - 10, box[1] + (box[3] - box[1]) * 0.42, box[2] + 12, box[3] + 8), 6, fill=marker
            )
        draw.text((pad, y), line, font=font, fill=ink + (255,))
        y += line_height
    if value:
        y += 22
        value_font = _serif(value_size, True)
        draw.text((pad, y), value, font=value_font, fill=_rgb(colors["accent_dark"]) + (255,))
        if unit:
            value_box = draw.textbbox((pad, y), value, font=value_font)
            room = pad + w - (value_box[2] + 18)
            # The unit sits beside the number when it fits. Otherwise it drops below at the same size.
            size, spacing = 34, 5
            while size > 22 and _spaced_width(draw, unit, _font(size, "Demi Bold"), spacing) > room:
                size, spacing = size - 2, max(2, spacing - 0.5)
            unit_font = _font(size, "Demi Bold")
            unit_box = draw.textbbox((0, 0), unit, font=unit_font)
            if _spaced_width(draw, unit, unit_font, spacing) <= room:
                unit_y = value_box[3] - (unit_box[3] - unit_box[1]) - unit_box[1] - 6
                _spaced(draw, (value_box[2] + 18, unit_y), unit, unit_font, ink + (210,), spacing)
            else:
                _spaced(draw, (pad + 4, value_box[3] + 8), unit, _font(30, "Demi Bold"), ink + (210,), 4)


def _draw_lower_third(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int) -> None:
    inner = (pad, pad, pad + w, pad + h)
    draw = ImageDraw.Draw(sprite)
    ink = _rgb(colors["text"]) + (255,)
    draw.rounded_rectangle(inner, 22, fill=_rgb(colors["card"]) + (255,), outline=ink, width=4)
    draw.rounded_rectangle((pad + 20, pad + 24, pad + 34, pad + h - 24), 5, fill=_rgb(colors.get("highlight") or "#FFE14D") + (255,), outline=ink, width=2)
    area = (pad + 54, pad + 16, pad + w - 32, pad + h - 16)
    font, lines, line_height, _size = _fit_lines(
        str(element.get("label") or "").strip(), area[2] - area[0], area[3] - area[1],
        lambda size: _font(size, "Bold"), 50, 28, max_lines=2, leading=1.16,
    )
    y = area[1] + ((area[3] - area[1]) - line_height * len(lines)) / 2
    for line in lines:
        draw.text((area[0], y), line, font=font, fill=_rgb(colors["text"]) + (255,))
        y += line_height


def _draw_prompt_card(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int, radius: int) -> None:
    inner = (pad, pad, pad + w, pad + h)
    _shadow(sprite, inner, radius)
    draw = ImageDraw.Draw(sprite)
    draw.rounded_rectangle(inner, radius, fill=_rgb(colors["card"]) + (255,))
    ink = _rgb(colors["text"])
    head = _font(26, "Demi Bold")
    _spaced(draw, (pad + 34, pad + 26), str(element.get("label") or "PROMPT").upper(), head,
            _rgb(colors["accent_dark"]) + (255,), 4)
    meta = str(element.get("meta") or "").strip()
    if meta:
        meta_font = _font(24, "Medium")
        draw.text((pad + w - 34 - draw.textlength(meta, font=meta_font), pad + 28), meta, font=meta_font,
                  fill=(122, 118, 112, 255))
    draw.line((pad + 34, pad + 74, pad + w - 34, pad + 74), fill=ink + (40,), width=2)
    area = (pad + 34, pad + 92, pad + w - 34, pad + h - 26)
    font, lines, line_height, _size = _fit_lines(
        str(element.get("text") or "").strip(), area[2] - area[0], area[3] - area[1],
        lambda size: _font(size, "Medium"), 40, 22, leading=1.3,
    )
    y = area[1]
    for line in lines:
        draw.text((area[0], y), line, font=font, fill=ink + (255,))
        y += line_height


def _draw_sheet(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int, radius: int) -> None:
    """Character sheet: the same host in several poses, taken straight from the pose library."""
    inner = (pad, pad, pad + w, pad + h)
    _shadow(sprite, inner, radius)
    draw = ImageDraw.Draw(sprite)
    draw.rounded_rectangle(inner, radius, fill=_rgb(colors["card"]) + (255,))
    head = _font(26, "Demi Bold")
    _spaced(draw, (pad + 34, pad + 26), str(element.get("label") or "CHARACTER").upper(), head,
            _rgb(colors["accent_dark"]) + (255,), 4)
    library = load_pose_library()
    names = [name for name in (element.get("poses") or []) if name in library][:4]
    captions = element.get("captions") or []
    if not names:
        return
    gap = 18
    cell_w = (w - 68 - gap * (len(names) - 1)) / len(names)
    top, bottom = pad + 84, pad + h - 66
    caption_font = _font(22, "Demi Bold")
    for index, name in enumerate(names):
        figure = library[name][0]
        bounds = figure.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
        if bounds:
            figure = figure.crop(bounds)
        scale = min(cell_w / figure.width, (bottom - top) / figure.height)
        figure = figure.resize((max(1, round(figure.width * scale)), max(1, round(figure.height * scale))), Image.LANCZOS)
        left = pad + 34 + index * (cell_w + gap)
        sprite.alpha_composite(figure, (round(left + (cell_w - figure.width) / 2), round(bottom - figure.height)))
        caption = str(captions[index] if index < len(captions) else name.replace("_", " ")).upper()
        width = _spaced_width(draw, caption, caption_font, 2)
        _spaced(draw, (left + (cell_w - width) / 2, bottom + 18), caption, caption_font, _rgb(colors["text"]) + (200,), 2)


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color: tuple) -> float:
    red, green, blue = (_linear(part) for part in color[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: tuple, second: tuple) -> float:
    """WCAG contrast between two colors, from 1 (identical) to 21 (black on white)."""
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


MIN_SWATCH_CONTRAST = 3.0


def _swatch_ink(background: tuple, partner: tuple) -> tuple:
    """The partner color is the text color when it can be read; otherwise plain white or near-black."""
    if contrast_ratio(background, partner) >= MIN_SWATCH_CONTRAST:
        return partner
    return (255, 255, 255) if luminance(background) < 0.4 else (30, 30, 30)


def _draw_swatch(sprite: Image.Image, element: dict, pad: int, w: int, h: int, radius: int) -> None:
    """A color pair, stacked. Each half is one color, with its name in big type and its hex in a pill,
    and the text takes the other color of the pair."""
    pair = [dict(item) for item in (element.get("swatch") or []) if isinstance(item, dict)][:2]
    if len(pair) < 2:
        return
    rgb = [_rgb(str(item.get("hex") or "#888888")) for item in pair]
    inner = (pad, pad, pad + w, pad + h)
    _shadow(sprite, inner, radius)
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(body)
    half = h // 2
    for index, (item, fill) in enumerate(zip(pair, rgb)):
        top = index * half
        bottom = h if index == 1 else half
        draw.rectangle((0, top, w, bottom), fill=fill + (255,))
        ink = _swatch_ink(fill, rgb[1 - index])
        name = str(item.get("name") or "").strip().upper()
        _write(body, name, (28, top + round(half * 0.16), w - 28, top + round(half * 0.60)), ink, weight="Bold",
               max_size=170, center=True)
        hex_text = f"HEX : {str(item.get('hex') or '').upper()}"
        font = _font(max(22, round(half * 0.075)), "Medium")
        text_w = draw.textlength(hex_text, font=font)
        pill_h = round(font.size * 2.1)
        pill_w = round(text_w + font.size * 2.2)
        left, pill_top = (w - pill_w) // 2, top + round(half * 0.66)
        overlay = Image.new("RGBA", body.size, (0, 0, 0, 0))
        layer = ImageDraw.Draw(overlay)
        layer.rounded_rectangle((left, pill_top, left + pill_w, pill_top + pill_h), pill_h // 2,
                                fill=ink + (34,), outline=ink + (110,), width=2)
        layer.text((left + (pill_w - text_w) / 2, _centered_y(layer, font, pill_top, pill_h)), hex_text, font=font,
                   fill=ink + (255,))
        body.alpha_composite(overlay)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius, fill=255)
    sprite.paste(body, (pad, pad), mask)


TILE_GLYPHS = ("bars", "ring", "arrow", "dots", "line", "check", "pin", "card", "toggle")
TILE_TINTS = ((232, 245, 247), (247, 238, 224), (238, 235, 247), (229, 242, 233))
TILE_POP = 0.32
TILE_MARGIN = 16


def _tile_grid(count: int) -> tuple:
    columns = 2 if count <= 4 else 3 if count <= 9 else 4
    return columns, -(-count // columns)


def _draw_glyph(name: str, size: tuple, accent: tuple, ink: tuple, warning: tuple) -> Image.Image:
    """A small flat graphic for a tile. Drawn at twice the size and scaled down so the edges stay smooth."""
    width, height = size
    scale = 2
    layer = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = layer.size
    unit = min(w, h)
    cx, cy = w / 2, h / 2
    solid = accent + (255,)
    if name == "bars":
        heights = (0.32, 0.5, 0.42, 0.72, 0.95)
        gap = unit * 0.06
        bar = (min(w * 0.8, unit * 1.1) - gap * 4) / 5
        left = cx - (bar * 5 + gap * 4) / 2
        base = cy + unit * 0.42
        for index, rise in enumerate(heights):
            x = left + index * (bar + gap)
            draw.rounded_rectangle((x, base - unit * 0.84 * rise, x + bar, base), bar * 0.3, fill=solid)
    elif name == "ring":
        r = unit * 0.40
        thickness = round(unit * 0.12)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=accent + (60,), width=thickness)
        draw.arc((cx - r, cy - r, cx + r, cy + r), -90, 190, fill=solid, width=thickness)
    elif name == "arrow":
        r = unit * 0.40
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=solid)
        stroke = round(unit * 0.07)
        draw.line((cx, cy + r * 0.45, cx, cy - r * 0.40), fill=(255, 255, 255, 255), width=stroke)
        draw.line((cx - r * 0.34, cy - r * 0.08, cx, cy - r * 0.45, cx + r * 0.34, cy - r * 0.08),
                  fill=(255, 255, 255, 255), width=stroke, joint="curve")
    elif name == "dots":
        count = 6
        step = unit * 0.78 / count
        left, top = cx - step * count / 2, cy - step * count / 2
        for row in range(count):
            for col in range(count):
                fade = 255 - ((row * 7 + col * 13) % 5) * 38
                r = step * 0.34
                x, y = left + step * (col + 0.5), top + step * (row + 0.5)
                draw.ellipse((x - r, y - r, x + r, y + r), fill=accent + (fade,))
    elif name == "line":
        points = [(cx - unit * 0.38, cy + unit * 0.30), (cx - unit * 0.16, cy + unit * 0.05),
                  (cx + unit * 0.02, cy + unit * 0.16), (cx + unit * 0.36, cy - unit * 0.30)]
        draw.line(points, fill=solid, width=round(unit * 0.07), joint="curve")
        r = unit * 0.07
        x, y = points[-1]
        draw.ellipse((x - r * 1.4, y - r * 1.4, x + r * 1.4, y + r * 1.4), fill=solid)
    elif name == "check":
        r = unit * 0.40
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(47, 166, 106, 255))
        draw.line((cx - r * 0.42, cy + r * 0.02, cx - r * 0.1, cy + r * 0.34, cx + r * 0.46, cy - r * 0.30),
                  fill=(255, 255, 255, 255), width=round(unit * 0.08), joint="curve")
    elif name == "pin":
        r = unit * 0.24
        top = cy - unit * 0.18
        draw.polygon([(cx - r * 0.86, top + r * 0.5), (cx + r * 0.86, top + r * 0.5), (cx, cy + unit * 0.40)],
                     fill=warning + (255,))
        draw.ellipse((cx - r, top - r, cx + r, top + r), fill=warning + (255,))
        draw.ellipse((cx - r * 0.4, top - r * 0.4, cx + r * 0.4, top + r * 0.4), fill=(255, 255, 255, 255))
    elif name == "card":
        cw, ch = min(w * 0.82, unit * 1.3), unit * 0.62
        draw.rounded_rectangle((cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2), ch * 0.14, fill=solid)
        draw.rectangle((cx - cw / 2, cy - ch * 0.26, cx + cw / 2, cy - ch * 0.06), fill=(255, 255, 255, 70))
        draw.rounded_rectangle((cx - cw * 0.40, cy + ch * 0.18, cx - cw * 0.08, cy + ch * 0.26), 4, fill=(255, 255, 255, 190))
    elif name == "toggle":
        tw, th = min(w * 0.70, unit * 1.0), unit * 0.40
        draw.rounded_rectangle((cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2), th / 2, fill=solid)
        r = th * 0.40
        draw.ellipse((cx + tw / 2 - th / 2 - r, cy - r, cx + tw / 2 - th / 2 + r, cy + r), fill=(255, 255, 255, 255))
    return layer.resize((width, height), Image.LANCZOS)


def _tile_caption(cell: Image.Image, text: str, area: tuple, color: tuple, max_size: int, min_size: int = 12) -> None:
    """One line, shrunk until it fits. An arrow in the text ("A → B") is drawn as a shape, so it never depends on the font."""
    if not text:
        return
    left, top, right, bottom = area
    draw = ImageDraw.Draw(cell)
    parts = [part.strip() for part in text.split("→")]
    for size in range(max_size, min_size - 1, -1):
        font = _font(size, "Demi Bold")
        arrow = size * 0.95 if len(parts) > 1 else 0
        gap = size * 0.32 if len(parts) > 1 else 0
        widths = [draw.textlength(part, font=font) for part in parts]
        total = sum(widths) + (len(parts) - 1) * (arrow + gap * 2)
        if total <= right - left or size == min_size:
            break
    y = _centered_y(draw, font, top, bottom - top)
    x = left
    for index, part in enumerate(parts):
        draw.text((x, y), part, font=font, fill=color + (255,))
        x += widths[index]
        if index < len(parts) - 1:
            bounds = font.getbbox("x")
            mid = y + (bounds[1] + bounds[3]) / 2
            stroke = max(2, round(size / 9))
            start, end = x + gap, x + gap + arrow
            draw.line((start, mid, end - stroke / 2, mid), fill=color + (255,), width=stroke)
            head = size * 0.26
            draw.line((end - head, mid - head, end, mid, end - head, mid + head), fill=color + (255,), width=stroke, joint="curve")
            x = end + gap


def _tile_cell(tile: dict, index: int, size: tuple, card_h: int, caption_h: int, colors: dict, focused: bool) -> Image.Image:
    cell_w, cell_h = size
    margin = TILE_MARGIN
    cell = Image.new("RGBA", (cell_w + margin * 2, cell_h + margin * 2), (0, 0, 0, 0))
    radius = max(10, round(card_h * 0.14))
    card = (margin, margin, margin + cell_w, margin + card_h)
    _shadow(cell, card, radius)
    tint = TILE_TINTS[index % len(TILE_TINTS)]
    body = Image.new("RGBA", (cell_w, card_h), (255, 255, 255, 255))
    wash = Image.linear_gradient("L").resize((cell_w, card_h)).point(lambda v: round(255 - v * 0.55))
    body.paste(tint + (255,), mask=wash)
    mask = Image.new("L", (cell_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cell_w, card_h), radius, fill=255)
    cell.paste(body, (margin, margin), mask)
    accent = _rgb(colors["accent_dark"])
    ink = _rgb(colors["text"])
    warning = _rgb(colors["warning"])
    glyph = str(tile.get("glyph") or "").strip().lower()
    value = str(tile.get("value") or "").strip()
    if glyph not in TILE_GLYPHS:
        glyph = "" if value else TILE_GLYPHS[index % len(TILE_GLYPHS)]
    inset = round(card_h * 0.12)
    area = (margin + inset, margin + inset, margin + cell_w - inset, margin + card_h - inset)
    area_w, area_h = area[2] - area[0], area[3] - area[1]
    if glyph and value:
        art_h = round(area_h * 0.58)
        art = _draw_glyph(glyph, (area_w, art_h), accent, ink, warning)
        cell.alpha_composite(art, (area[0], area[1]))
        _write(cell, value, (area[0], area[1] + art_h, area[2], area[3]), ink, weight="Bold", max_size=90, center=True)
    elif glyph:
        art = _draw_glyph(glyph, (area_w, area_h), accent, ink, warning)
        cell.alpha_composite(art, (area[0], area[1]))
    else:
        _write(cell, value, area, ink, weight="Bold", max_size=140, center=True)
    if focused:
        ImageDraw.Draw(cell).rounded_rectangle(card, radius, outline=accent + (255,), width=max(4, round(card_h * 0.03)))
    # Caption under the card: a number, then the label.
    draw = ImageDraw.Draw(cell)
    number = f"{index + 1:02d}"
    number_font = _font(max(12, round(caption_h * 0.46)), "Demi Bold")
    top = margin + card_h
    y = _centered_y(draw, number_font, top, caption_h)
    end = _spaced(draw, (margin + 4, y), number, number_font, accent + (255,), 1.5)
    label_area = (round(end) + 10, top, margin + cell_w, top + caption_h)
    _tile_caption(cell, str(tile.get("label") or "").strip(), label_area, ink, max(14, round(caption_h * 0.56)))
    return cell


def _prepare_tiles(element: dict, w: int, h: int, pad: int, colors: dict) -> bool:
    tiles = [tile for tile in (element.get("tiles") or []) if isinstance(tile, dict)][:16]
    if not tiles:
        return False
    columns, rows = _tile_grid(len(tiles))
    gap = max(6, min(16, w // 40))
    cell_w = (w - gap * (columns - 1)) // columns
    caption_h = max(24, min(44, round(cell_w * 0.19)))
    card_h = round(min(cell_w * 1.0, (h - gap * (rows - 1)) / rows - caption_h))
    cell_h = card_h + caption_h
    grid_h = rows * cell_h + (rows - 1) * gap
    top = pad + max(0, (h - grid_h) // 2)
    focus = element.get("focus")
    cells = []
    for index, tile in enumerate(tiles):
        col, row = index % columns, index // columns
        cells.append({
            "x": pad + col * (cell_w + gap) - TILE_MARGIN,
            "y": top + row * (cell_h + gap) - TILE_MARGIN,
            "plain": _tile_cell(tile, index, (cell_w, cell_h), card_h, caption_h, colors, False),
            "ring": _tile_cell(tile, index, (cell_w, cell_h), card_h, caption_h, colors, True)
            if isinstance(focus, int) and focus == index + 1 else None,
        })
    element["_cells"] = cells
    element["_canvas"] = (w + pad * 2, h + pad * 2)
    return True


def _tiles_sprite(element: dict, t: float) -> Image.Image:
    """One frame of the grid: tiles pop in one after another, then every tile but the focused one dims."""
    canvas = Image.new("RGBA", element["_canvas"], (0, 0, 0, 0))
    cells = element["_cells"]
    enter_at = float(element.get("enter_at") or 0)
    stagger = float(element.get("stagger") if element.get("stagger") is not None else 0.08)
    since = t - enter_at
    focus = element.get("focus") if isinstance(element.get("focus"), int) else None
    focus_at = float(element.get("focus_at") or 0)
    dim = _ease((since - focus_at) / 0.35) if focus else 0.0
    late = None
    for index, cell in enumerate(cells):
        pop = _ease((since - index * stagger) / TILE_POP)
        if pop <= 0:
            continue
        if focus and index + 1 == focus:
            late = (cell, pop)
            continue
        _paste(canvas, cell["plain"], cell["x"], cell["y"], 0.86 + 0.14 * pop, pop * (1 - 0.66 * dim))
    if late:
        cell, pop = late
        scale = (0.86 + 0.14 * pop) * (1 + 0.14 * dim)
        _paste(canvas, cell["plain"], cell["x"], cell["y"], scale, pop)
        if cell["ring"] is not None and dim > 0:
            _paste(canvas, cell["ring"], cell["x"], cell["y"], scale, dim)
    return canvas


def _fade_feet(image: Image.Image, length: int) -> Image.Image:
    """Fade the bottom edge of a cut-off figure to transparent."""
    length = max(8, min(length, image.height))
    faded = image.copy()
    alpha = faded.getchannel("A")
    ramp = Image.linear_gradient("L").resize((image.width, length)).transpose(Image.FLIP_TOP_BOTTOM)
    mask = Image.new("L", image.size, 255)
    mask.paste(ramp, (0, image.height - length))
    faded.putalpha(ImageChops.multiply(alpha, mask))
    return faded


def _prepare_image(element: dict, w: int, h: int, pad: int, radius: int) -> bool:
    path = Path(str(element.get("path") or ""))
    if not path.is_file():
        return False
    if element.get("fit") == "contain":
        return _prepare_screenshot(element, path, w, h, pad, radius)
    with Image.open(path) as source:
        picture = source.convert("RGB")
    zoom = max(0.0, float(element.get("zoom") or 0))
    scale = 1 + zoom + 0.04
    big_w, big_h = round(w * scale), round(h * scale)
    ratio = max(big_w / picture.width, big_h / picture.height)
    resized = picture.resize((max(big_w, round(picture.width * ratio)), max(big_h, round(picture.height * ratio))), Image.LANCZOS)
    left, top = (resized.width - big_w) // 2, (resized.height - big_h) // 2
    element["_pic"] = resized.crop((left, top, left + big_w, top + big_h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius, fill=255)
    element["_mask"] = mask
    shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    _shadow(shadow, (pad, pad, pad + w, pad + h), radius)
    element["_shadow"] = shadow
    element["_pad"] = pad
    if element.get("sweep"):
        element["_band"] = _sweep_layer(w, h)
    return True


MAX_GIF_FRAMES = 90


def _contain(picture: Image.Image, w: int, h: int) -> Image.Image:
    """The whole picture on a white page, scaled to fit, so no part of a screenshot is cropped."""
    page = Image.new("RGB", (w, h), (255, 255, 255))
    if picture.mode in ("RGBA", "LA", "P"):
        # Transparent margins become white page, not black.
        rgba = picture.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        picture = flat
    scale = min(w / picture.width, h / picture.height)
    fitted = picture.convert("RGB").resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))), Image.LANCZOS)
    page.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    return page


def _prepare_screenshot(element: dict, path: Path, w: int, h: int, pad: int, radius: int) -> bool:
    """A product screenshot, shown whole. An animated one keeps its frames and plays across the beat."""
    frames: list[Image.Image] = []
    crop = element.get("crop")
    with Image.open(path) as source:
        count = int(getattr(source, "n_frames", 1))
        step = max(1, count // MAX_GIF_FRAMES)
        for index in range(0, count, step):
            source.seek(index)
            frame = source.convert("RGBA")
            if isinstance(crop, list) and len(crop) == 4:
                # Empty margins around the app are cut, so the interface fills the frame and stays readable.
                frame = frame.crop(tuple(int(value) for value in crop))
            frames.append(_contain(frame, w, h))
    element["_pic"] = frames[0]
    if len(frames) > 1:
        element["_frames"] = frames
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius, fill=255)
    element["_mask"] = mask
    shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    _shadow(shadow, (pad, pad, pad + w, pad + h), radius)
    ImageDraw.Draw(shadow).rounded_rectangle((pad - 3, pad - 3, pad + w + 3, pad + h + 3), radius + 3, fill=(17, 17, 17, 255))
    element["_shadow"] = shadow
    element["_pad"] = pad
    return True


def _sweep_layer(w: int, h: int) -> Image.Image:
    """A soft slanted band of light, wider than the picture, that slides across it."""
    band_w = max(80, round(w * 0.3))
    strip = Image.linear_gradient("L").rotate(90)
    triangle = ImageChops.darker(strip, ImageOps.mirror(strip)).point(lambda v: min(255, v * 2))
    triangle = triangle.resize((band_w, h), Image.BILINEAR)
    slant = round(h * 0.28)
    layer = Image.new("L", (w + band_w * 2 + slant, h), 0)
    layer.paste(triangle, (band_w, 0))
    return layer.transform(layer.size, Image.AFFINE, (1, 0.28, -slant / 2, 0, 1, 0), Image.BILINEAR)


def _image_sprite(element: dict, progress: float, t: float) -> Image.Image:
    pic, mask, shadow = element["_pic"], element["_mask"], element["_shadow"]
    pad = element["_pad"]
    w, h = mask.size
    frames = element.get("_frames")
    if frames:
        # An animated screenshot plays once across the beat, then holds its last frame.
        pic = frames[min(len(frames) - 1, int(max(0.0, min(1.0, progress)) * len(frames)))]
    zoom_gain = float(element.get("zoom") or 0)
    z = 1 + zoom_gain * _ease_io(max(0.0, min(1.0, progress)))
    # The stored picture is larger than the frame, so the centred window shrinks as the push-in deepens.
    window_w, window_h = pic.width / z, pic.height / z
    left, top = (pic.width - window_w) / 2, (pic.height - window_h) / 2
    frame = pic.crop((round(left), round(top), round(left + window_w), round(top + window_h))).resize((w, h), Image.BILINEAR)
    band = element.get("_band")
    if band is not None and progress > 0:
        sweep = _ease_io(min(1.0, progress / 0.8))
        offset = round(sweep * (band.width - w))
        light = band.crop((offset, 0, offset + w, h)).point(lambda v: round(v * 0.30))
        frame.paste((255, 255, 255), mask=light)
    sprite = shadow.copy()
    sprite.paste(frame, (pad, pad), mask)
    tag = str(element.get("tag") or "").strip()
    if tag:
        draw = ImageDraw.Draw(sprite)
        font = _font(22, "Demi Bold")
        width = _spaced_width(draw, tag.upper(), font, 3)
        if element.get("fit") == "contain":
            # A source credit sits bottom left, clear of the app's own header.
            box = (pad + 20, pad + h - 20 - 42, pad + 20 + width + 36, pad + h - 20)
            draw.rounded_rectangle(box, 21, fill=(17, 17, 17, 230))
            _spaced(draw, (box[0] + 18, _centered_y(draw, font, box[1], 42)), tag.upper(), font, (255, 255, 255, 255), 3)
        else:
            box = (pad + 24, pad + 24, pad + 24 + width + 36, pad + 24 + 42)
            draw.rounded_rectangle(box, 21, fill=(255, 255, 255, 235))
            _spaced(draw, (box[0] + 18, _centered_y(draw, font, box[1], 42)), tag.upper(), font, (43, 43, 43, 255), 3)
    return sprite


_FONTS: dict = {}


def _font(size: int, weight: str) -> ImageFont.FreeTypeFont:
    """Archivo at the named weight, or Avenir Next when the brand font is missing."""
    key = (size, weight)
    if key in _FONTS:
        return _FONTS[key]
    chosen = None
    try:
        chosen = ImageFont.truetype(FONT_FILE, size)
        chosen.set_variation_by_axes([FONT_WEIGHTS.get(weight, 600), 100])
    except (OSError, AttributeError):
        chosen = None
    if chosen is None:
        try:
            for index in range(16):
                candidate = ImageFont.truetype(FALLBACK_FONT_FILE, size, index=index)
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
    # A hard offset shadow, like a sticker on paper. Soft gray glows disappear on a white page.
    ImageDraw.Draw(layer).rounded_rectangle((left + 8, top + 8, right + 8, bottom + 8), radius, fill=(17, 17, 17, 255))
    sprite.alpha_composite(layer)


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


AVATAR_COLORS = ("#2F6BFF", "#E5484D", "#16A34A", "#F59E0B", "#8B5CF6")


def _clip_line(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    """One line of text, cut with an ellipsis when it is wider than the room."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


PHONE_FONT = "/System/Library/Fonts/SFNS.ttf"
PHONE_APPS = {"chat", "sms", "text", "messages", "message", "mail", "email", "inbox"}


def _phone_font(size: int, weight: str = "Regular"):
    """The phone's own system type, so the screen reads like a real phone. Falls back to the brand font."""
    try:
        font = ImageFont.truetype(PHONE_FONT, size)
        font.set_variation_by_name(weight)
        return font
    except (OSError, ValueError):
        return _font(size, "Bold" if weight in ("Semibold", "Bold") else "Medium")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: float, max_lines: int) -> list:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _clip_line(draw, lines[-1] + " …", font, width)
    return lines


def _draw_phone(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int) -> None:
    """A phone in the style people know: black bezel, dynamic island, the sender at the top, gray bubbles.

    Drawn from the research, in the look of the phone's own Messages and Mail apps. No company logos.
    """
    screen = element.get("screen") if isinstance(element.get("screen"), dict) else {}
    draw = ImageDraw.Draw(sprite)
    outer = (pad, pad, pad + w, pad + h)
    _shadow(sprite, outer, 70)
    draw.rounded_rectangle(outer, 70, fill=(22, 22, 24, 255))
    bezel = 16
    glass = (pad + bezel, pad + bezel, pad + w - bezel, pad + h - bezel)
    draw.rounded_rectangle(glass, 56, fill=(255, 255, 255, 255))
    left, top, right, bottom = glass
    cx = (left + right) / 2
    gray, label = (142, 142, 147, 255), (0, 0, 0, 255)
    # Status bar and dynamic island.
    draw.text((left + 44, top + 22), "9:41", font=_phone_font(26, "Semibold"), fill=label)
    draw.rounded_rectangle((cx - 66, top + 16, cx + 66, top + 54), 19, fill=(0, 0, 0, 255))
    for index in range(4):
        bar_h = 8 + index * 4
        x = right - 108 + index * 9
        draw.rounded_rectangle((x, top + 46 - bar_h, x + 6, top + 46), 2, fill=label)
    draw.rounded_rectangle((right - 62, top + 28, right - 28, top + 46), 5, outline=label, width=2)
    draw.rectangle((right - 58, top + 32, right - 36, top + 42), fill=label)

    app = str(screen.get("app") or "chat").lower()
    rows = [row for row in (screen.get("lines") or []) if isinstance(row, dict) and str(row.get("text") or "").strip()]
    mail = app in ("mail", "email", "inbox")
    # Back chevron.
    draw.line((left + 34, top + 92, left + 22, top + 104, left + 34, top + 116), fill=(0, 122, 255, 255), width=4, joint="curve")
    if mail:
        draw.text((left + 46, top + 86), "Inbox", font=_phone_font(26), fill=(0, 122, 255, 255))
        y = top + 136
        draw.text((left + 28, y), _clip_line(draw, str(screen.get("title") or "Inbox"), _phone_font(42, "Bold"), right - left - 56), font=_phone_font(42, "Bold"), fill=label)
        y += 66
        for row in rows[:4]:
            name_font, body_font = _phone_font(30, "Semibold"), _phone_font(27)
            text = str(row.get("text")).strip()
            body = _wrap(draw, text, body_font, right - left - 64, 2)
            if row.get("mark"):
                for index, line in enumerate(body):
                    box = draw.textbbox((left + 32, y + 40 + index * 34), line, font=body_font)
                    draw.rounded_rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 4), 4,
                                           fill=_rgb(colors.get("highlight") or "#FFE14D") + (255,))
            draw.ellipse((left + 12, y + 10, left + 22, y + 20), fill=(0, 122, 255, 255))
            draw.text((left + 32, y), _clip_line(draw, str(row.get("who") or "Sender"), name_font, right - left - 64),
                      font=name_font, fill=label)
            for index, line in enumerate(body):
                draw.text((left + 32, y + 40 + index * 34), line, font=body_font, fill=(60, 60, 67, 255))
            y += 48 + 34 * len(body) + 18
            draw.line((left + 32, y - 8, right, y - 8), fill=(229, 229, 234, 255), width=2)
            if y > bottom - 140:
                break
    else:
        sender = str((rows[0].get("who") if rows else "") or screen.get("title") or "Message").strip()
        # The contact at the top: a gray circle with initials, the name, then the thread's date line.
        avatar = 64
        draw.ellipse((cx - avatar / 2, top + 70, cx + avatar / 2, top + 70 + avatar), fill=(172, 174, 186, 255))
        initials = "".join(part[:1] for part in sender.replace("-", " ").split()[:2]).upper() or "?"
        font = _phone_font(28, "Semibold")
        box = draw.textbbox((0, 0), initials, font=font)
        draw.text((cx - (box[0] + box[2]) / 2, top + 70 + avatar / 2 - (box[1] + box[3]) / 2), initials, font=font,
                  fill=(255, 255, 255, 255))
        name_font = _phone_font(22)
        name = _clip_line(draw, sender, name_font, right - left - 80) + " ›"
        draw.text((cx - draw.textlength(name, font=name_font) / 2, top + 142), name, font=name_font, fill=label)
        draw.line((left, top + 186, right, top + 186), fill=(229, 229, 234, 255), width=2)
        meta_font = _phone_font(19, "Semibold")
        for index, meta in enumerate(("Text Message", "Today 9:29 AM")):
            meta_w = draw.textlength(meta, font=meta_font)
            draw.text((cx - meta_w / 2, top + 206 + index * 26), meta, font=meta_font, fill=gray)
        y = top + 272
        bubble_font = _phone_font(33)
        # A text thread from a sender shows the sender's messages, in full, the way the phone does.
        theirs = [row for row in rows if str(row.get("who") or "").strip() == sender] or rows[:1]
        for row in theirs[:2]:
            lines = _wrap(draw, str(row.get("text")).strip(), bubble_font, (right - left) * 0.74, 5)
            line_h = 42
            text_w = max(draw.textlength(line, font=bubble_font) for line in lines)
            bubble = (left + 22, y, left + 22 + text_w + 40, y + line_h * len(lines) + 26)
            draw.rounded_rectangle(bubble, 26, fill=(233, 233, 235, 255))
            if row.get("mark"):
                # The trap line gets the brand marker so the eye lands on it.
                for index, line in enumerate(lines):
                    box = draw.textbbox((bubble[0] + 20, y + 12 + index * line_h), line, font=bubble_font)
                    draw.rounded_rectangle((box[0] - 3, box[1] + (box[3] - box[1]) * 0.45, box[2] + 3, box[3] + 4), 4,
                                           fill=_rgb(colors.get("highlight") or "#FFE14D") + (255,))
            for index, line in enumerate(lines):
                draw.text((bubble[0] + 20, y + 12 + index * line_h), line, font=bubble_font, fill=label)
            y = bubble[3] + 14

    result = [str(item).strip() for item in (screen.get("result") or []) if str(item).strip()][:3]
    if result and element.get("show_result"):
        # The after state as the phone shows it: a card with a green check on each line.
        item_font, head_font = _phone_font(27), _phone_font(22, "Semibold")
        wrapped = [_wrap(draw, item, item_font, right - left - 130, 2) for item in result]
        card_h = 70 + sum(36 * len(lines) + 18 for lines in wrapped)
        card = (left + 22, min(y + 10, bottom - 170 - card_h), right - 22, min(y + 10, bottom - 170 - card_h) + card_h)
        draw.rounded_rectangle(card, 26, fill=(242, 242, 247, 255))
        draw.text((card[0] + 24, card[1] + 20), str(screen.get("result_label") or "Checked").upper(), font=head_font, fill=gray)
        cy = card[1] + 60
        for lines in wrapped:
            draw.ellipse((card[0] + 22, cy + 4, card[0] + 52, cy + 34), fill=(52, 199, 89, 255))
            draw.line((card[0] + 30, cy + 19, card[0] + 36, cy + 26, card[0] + 45, cy + 12), fill=(255, 255, 255, 255), width=4)
            for index, line in enumerate(lines):
                draw.text((card[0] + 68, cy + index * 36), line, font=item_font, fill=label)
            cy += 36 * len(lines) + 18
    action = str(screen.get("action") or "").strip()
    if action:
        button_font = _phone_font(26, "Semibold")
        label_w = draw.textlength(action, font=button_font)
        button = (cx - label_w / 2 - 34, bottom - 150, cx + label_w / 2 + 34, bottom - 92)
        draw.rounded_rectangle(button, 29, fill=(0, 122, 255, 255))
        box = draw.textbbox((0, 0), action, font=button_font)
        draw.text((cx - label_w / 2, (button[1] + button[3]) / 2 - (box[1] + box[3]) / 2), action, font=button_font,
                  fill=(255, 255, 255, 255))
    if not mail:
        # The input bar along the bottom.
        bar = (left + 76, bottom - 74, right - 24, bottom - 30)
        draw.ellipse((left + 22, bottom - 72, left + 62, bottom - 32), fill=(229, 229, 234, 255))
        draw.text((left + 34, bottom - 74), "+", font=_phone_font(32), fill=gray)
        draw.rounded_rectangle(bar, 22, outline=(209, 209, 214, 255), width=2)
        draw.text((bar[0] + 18, bar[1] + 9), "Text Message", font=_phone_font(22), fill=(180, 180, 186, 255))
    draw.rounded_rectangle((cx - 70, bottom - 14, cx + 70, bottom - 8), 3, fill=label)


def phone_screen(screen: dict, size: tuple = (620, 1340)) -> Image.Image:
    """Just the glass of the drawn phone, to lay onto the phone in a story picture."""
    width, height = size
    pad, bezel = 40, 16
    sprite = Image.new("RGBA", (width + 2 * (bezel + pad), height + 2 * (bezel + pad)), (0, 0, 0, 0))
    _draw_phone(sprite, {"screen": screen, "show_result": True}, dict(BRAND_COLORS), pad, width + 2 * bezel, height + 2 * bezel)
    glass = sprite.crop((pad + bezel, pad + bezel, pad + bezel + width, pad + bezel + height))
    flat = Image.new("RGBA", glass.size, (255, 255, 255, 255))
    flat.alpha_composite(glass)
    return flat


def _draw_screen(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int) -> None:
    """A sample app screen drawn from the research: a header, message rows, and an optional action button.

    Original drawing only. No company logo or real product screenshot.
    """
    screen = element.get("screen") if isinstance(element.get("screen"), dict) else {}
    if element.get("device") == "phone" and str(screen.get("app") or "chat").lower() in PHONE_APPS:
        _draw_phone(sprite, element, colors, pad, w, h)
        return
    draw = ImageDraw.Draw(sprite)
    ink = _rgb(colors["text"]) + (255,)
    inner = (pad, pad, pad + w, pad + h)
    _shadow(sprite, inner, 28)
    draw.rounded_rectangle(inner, 28, fill=_rgb(colors["card"]) + (255,), outline=ink, width=4)
    header_h = 104
    draw.rounded_rectangle((pad + 4, pad + 4, pad + w - 4, pad + header_h), 24, fill=(243, 243, 240, 255))
    draw.rectangle((pad + 4, pad + header_h - 24, pad + w - 4, pad + header_h), fill=(243, 243, 240, 255))
    draw.line((pad + 4, pad + header_h, pad + w - 4, pad + header_h), fill=ink, width=3)
    app = str(screen.get("app") or "chat")
    _paint_tile(sprite, (pad + 28, pad + 24, pad + 84, pad + 80), _icon_kind(app))
    title_font = _font(36, "Bold")
    draw.text((pad + 104, pad + 32), _clip_line(draw, str(screen.get("title") or ""), title_font, w - 140),
              font=title_font, fill=ink)

    action = str(screen.get("action") or "").strip()
    action_h = 112 if action else 0
    rows = [row for row in (screen.get("lines") or []) if isinstance(row, dict) and str(row.get("text") or "").strip()][:5]
    room = h - header_h - action_h - 24
    row_h = min(132, room // max(1, len(rows)))
    name_font, text_font = _font(28, "Bold"), _font(32, "Medium")
    y = pad + header_h + 16
    for index, row in enumerate(rows):
        who = str(row.get("who") or "").strip() or "Team"
        avatar = 64
        cy = y + (row_h - avatar) / 2
        color = _rgb(AVATAR_COLORS[index % len(AVATAR_COLORS)]) + (255,)
        draw.ellipse((pad + 28, cy, pad + 28 + avatar, cy + avatar), fill=color)
        initial = who[:1].upper()
        initial_font = _font(30, "Bold")
        box = draw.textbbox((0, 0), initial, font=initial_font)
        draw.text((pad + 28 + (avatar - (box[2] - box[0])) / 2 - box[0], cy + (avatar - (box[3] - box[1])) / 2 - box[1]),
                  initial, font=initial_font, fill=(255, 255, 255, 255))
        text_left = pad + 28 + avatar + 22
        if row.get("mark"):
            # The trap line gets the yellow marker, the same way headlines do.
            line = _clip_line(draw, str(row.get("text")).strip(), text_font, w - (text_left - pad) - 28)
            box = draw.textbbox((text_left, cy + 30), line, font=text_font)
            draw.rounded_rectangle((box[0] - 8, box[1] - 4, box[2] + 8, box[3] + 6), 6,
                                   fill=_rgb(colors.get("highlight") or "#FFE14D") + (255,))
        draw.text((text_left, cy - 6), _clip_line(draw, who, name_font, w - 160), font=name_font, fill=ink)
        draw.text((text_left, cy + 30), _clip_line(draw, str(row.get("text")).strip(), text_font, w - (text_left - pad) - 28),
                  font=text_font, fill=_rgb(colors["text"]) + (215,))
        y += row_h
    if action:
        button_font = _font(34, "Bold")
        label_w = draw.textlength(action, font=button_font)
        right, bottom = pad + w - 28, pad + h - 26
        button = (right - label_w - 72, bottom - 72, right, bottom)
        draw.rounded_rectangle((button[0] + 6, button[1] + 6, button[2] + 6, button[3] + 6), 36, fill=ink)
        draw.rounded_rectangle(button, 36, fill=_rgb(colors["highlight"]) + (255,), outline=ink, width=4)
        box = draw.textbbox((0, 0), action, font=button_font)
        draw.text((button[0] + 36 - box[0], button[1] + (72 - (box[3] - box[1])) / 2 - box[1]), action,
                  font=button_font, fill=ink)


def _draw_summary(sprite: Image.Image, element: dict, colors: dict, pad: int, w: int, h: int) -> None:
    """The after state of a sample screen: a short summary panel with a highlighted header."""
    items = [str(item).strip() for item in (element.get("items") or []) if str(item).strip()][:3]
    draw = ImageDraw.Draw(sprite)
    ink = _rgb(colors["text"]) + (255,)
    inner = (pad, pad, pad + w, pad + h)
    _shadow(sprite, inner, 24)
    draw.rounded_rectangle(inner, 24, fill=_rgb(colors["card"]) + (255,), outline=ink, width=4)
    head_font = _serif(44)
    label = str(element.get("label") or "Summary")
    box = draw.textbbox((pad + 36, pad + 30), label, font=head_font)
    draw.rounded_rectangle((box[0] - 8, box[1] + (box[3] - box[1]) * 0.45, box[2] + 10, box[3] + 6), 6,
                           fill=_rgb(colors["highlight"]) + (255,))
    draw.text((pad + 36, pad + 30), label, font=head_font, fill=ink)
    item_font = _font(31, "Bold")
    y = box[3] + 34
    step = (pad + h - 24 - y) / max(1, len(items))
    for item in items:
        draw.ellipse((pad + 40, y + 14, pad + 56, y + 30), fill=_rgb(colors["accent"]) + (255,))
        draw.text((pad + 76, y), _clip_line(draw, item, item_font, w - 112), font=item_font, fill=ink)
        y += min(step, 72)


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
