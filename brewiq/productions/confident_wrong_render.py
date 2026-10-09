"""Compositor for the 'confident and still wrong' explainer: graphics, character, camera, and audio."""

from __future__ import annotations

import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
BG = (247, 243, 236)
INK = (43, 43, 43)
MUTED = (120, 116, 110)
CYAN = (34, 195, 214)
WARN = (214, 98, 62)
CARD = (255, 255, 255)
FONT = "/System/Library/Fonts/Avenir Next.ttc"
FACE = {"bold": 0, "demi": 2, "medium": 5, "regular": 7, "heavy": 8}
FFMPEG = "/opt/homebrew/bin/ffmpeg"

ANSWER_LINE_1 = "The Eiffel Tower was"
ANSWER_LINE_2 = "completed in "
WRONG, RIGHT = "1899", "1889"


@lru_cache(maxsize=None)
def font(size: int, face: str = "demi") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size, index=FACE[face])


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_io(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def back(x: float) -> float:
    x = max(0.0, min(1.0, x))
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def prog(t: float, start: float, length: float) -> float:
    return max(0.0, min(1.0, (t - start) / max(length, 1e-6)))


def lerp(a: float, b: float, p: float) -> float:
    return a + (b - a) * p


def mix(a: tuple, b: tuple, p: float) -> tuple:
    return tuple(round(lerp(x, y, p)) for x, y in zip(a, b))


def with_alpha(image: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return image
    out = image.copy()
    out.putalpha(out.getchannel("A").point(lambda v: round(v * max(0.0, alpha))))
    return out


@lru_cache(maxsize=None)
def shadow(w: int, h: int, radius: int, blur: int = 22, alpha: int = 46) -> Image.Image:
    pad = blur * 3
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((pad, pad + blur // 2, pad + w, pad + h + blur // 2), radius, fill=INK + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def paste_card(canvas: Image.Image, sprite: Image.Image, x: float, y: float, scale: float, alpha: float, radius: int) -> None:
    if alpha <= 0.01:
        return
    w, h = max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))
    shade = shadow(w, h, max(4, round(radius * scale)))
    pad = (shade.width - w) // 2
    canvas.alpha_composite(with_alpha(shade, alpha), (round(x) - pad, round(y) - pad))
    image = sprite if scale == 1 else sprite.resize((w, h), Image.LANCZOS)
    canvas.alpha_composite(with_alpha(image, alpha), (round(x), round(y)))


@lru_cache(maxsize=1)
def background() -> Image.Image:
    image = Image.new("RGBA", (W, H), BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-300, -260, 640, 640), fill=CYAN + (40,))
    draw.ellipse((560, 420, 1400, 1260), fill=(242, 196, 160, 46))
    draw.ellipse((-200, 1300, 700, 2200), fill=CYAN + (22,))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dot_draw = ImageDraw.Draw(dots)
    for y in range(40, H, 46):
        for x in range(40, W, 46):
            dot_draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=INK + (14,))
    image.alpha_composite(dots)
    vignette = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vignette).ellipse((-400, -300, W + 400, H + 300), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(220))
    shade = Image.new("RGBA", (W, H), (120, 100, 80, 36))
    shade.putalpha(ImageChops.invert(vignette).point(lambda v: v * 36 // 255))
    image.alpha_composite(shade)
    return image


def sparkle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple) -> None:
    points = []
    for index in range(8):
        angle = math.pi / 4 * index - math.pi / 2
        radius = r if index % 2 == 0 else r * 0.32
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=color)


def answer_panel(state: dict) -> tuple[Image.Image, tuple]:
    """Illustrative AI answer card. Returns the sprite and the year token box in sprite coordinates."""
    pw, ph = 860, 440
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, pw, ph), 40, fill=CARD + (255,))
    draw.ellipse((40, 34, 104, 98), fill=CYAN + (255,))
    sparkle(draw, 72, 66, 20, (255, 255, 255, 255))
    draw.text((122, 42), "AI assistant", font=font(36, "demi"), fill=INK + (255,))
    tag = "Illustrative example"
    tag_font = font(26, "medium")
    tag_w = draw.textlength(tag, font=tag_font) + 36
    draw.rounded_rectangle((pw - 40 - tag_w, 44, pw - 40, 90), 23, outline=MUTED + (160,), width=2)
    draw.text((pw - 40 - tag_w + 18, 51), tag, font=tag_font, fill=MUTED + (255,))

    body = font(66, "demi")
    left, line1_y, line2_y = 48, 140, 222
    typed = state.get("typed", 1.0)
    full = f"{ANSWER_LINE_1} {ANSWER_LINE_2}{WRONG}."
    shown = round(len(full) * typed)
    highlight = state.get("highlight", 0.0)
    if highlight > 0:
        span = draw.textlength(ANSWER_LINE_1, font=body)
        band = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        band_draw = ImageDraw.Draw(band)
        band_draw.rounded_rectangle((left - 10, line1_y + 6, left - 10 + (span + 20) * highlight, line1_y + 84), 12, fill=CYAN + (56,))
        line2_span = draw.textlength(ANSWER_LINE_2 + WRONG + ".", font=body)
        second = max(0.0, highlight * 2 - 1) if highlight < 1 else 1
        band_draw.rounded_rectangle((left - 10, line2_y + 6, left - 10 + (line2_span + 20) * second, line2_y + 84), 12, fill=CYAN + (56,))
        image.alpha_composite(band)

    line1 = ANSWER_LINE_1[: max(0, min(len(ANSWER_LINE_1), shown))]
    draw.text((left, line1_y), line1, font=body, fill=INK + (255,))
    rest = max(0, shown - len(ANSWER_LINE_1) - 1)
    line2 = ANSWER_LINE_2[: min(len(ANSWER_LINE_2), rest)]
    draw.text((left, line2_y), line2, font=body, fill=INK + (255,))
    token_x = left + draw.textlength(ANSWER_LINE_2, font=body)
    token_w = draw.textlength(WRONG, font=body)
    token_box = (token_x, line2_y + 4, token_x + token_w, line2_y + 86)

    token_state = state.get("token", "normal")
    token_visible = rest > len(ANSWER_LINE_2)
    if token_visible and token_state in ("normal", "warning"):
        color = mix(INK, WARN, state.get("warn", 0.0)) if token_state == "warning" else INK
        draw.text((token_x, line2_y), WRONG, font=body, fill=color + (255,))
        if token_state == "warning" and state.get("warn", 0) > 0:
            underline_w = token_w * state["warn"]
            for step in range(0, int(underline_w), 14):
                draw.arc((token_x + step, line2_y + 78, token_x + step + 14, line2_y + 92), 0, 180, fill=WARN + (255,), width=4)
    if token_state == "corrected":
        drop = state.get("drop", 1.0)
        size = round(66 * lerp(1.35, 1.0, back(drop)))
        new_font = font(size, "bold")
        draw.rounded_rectangle((token_x - 8, line2_y + 6, token_x + token_w + 8, line2_y + 84), 12, fill=CYAN + (round(70 * drop),))
        offset = (size - 66) * 0.5
        draw.text((token_x - offset * 0.6, line2_y - offset), RIGHT, font=new_font, fill=mix(INK, (16, 120, 134), drop) + (255,))
    if token_visible or token_state == "corrected":
        period_x = token_x + token_w
        draw.text((period_x, line2_y), ".", font=body, fill=INK + (255,))

    meter_y = 340
    meter = state.get("meter", 1.0)
    checked = state.get("checked", 0.0)
    label = "Checked against the source" if checked > 0.5 else "Confidence: very high"
    label_color = mix(MUTED, (16, 120, 134), checked)
    draw.text((left, meter_y), label, font=font(30, "demi"), fill=label_color + (255,))
    bar_x = pw - 48 - 260
    draw.rounded_rectangle((bar_x, meter_y + 12, bar_x + 260, meter_y + 30), 9, fill=INK + (22,))
    if meter > 0:
        draw.rounded_rectangle((bar_x, meter_y + 12, bar_x + 260 * meter, meter_y + 30), 9, fill=CYAN + (255,))
    if checked > 0.5:
        cx, cy = bar_x - 30, meter_y + 21
        draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=CYAN + (255,))
        draw.line((cx - 7, cy, cx - 2, cy + 6, cx + 8, cy - 6), fill=(255, 255, 255, 255), width=4)
    return image, token_box


def tower(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, color: tuple) -> None:
    cx = x + w / 2
    top, base = y + 10, y + h - 6
    legs = [(cx - w * 0.36, base), (cx - w * 0.06, y + h * 0.18), (cx, top), (cx + w * 0.06, y + h * 0.18), (cx + w * 0.36, base)]
    draw.line(legs, fill=color, width=5, joint="curve")
    for level, spread in ((0.45, 0.16), (0.7, 0.26)):
        ly = y + h * level
        draw.line((cx - w * spread, ly, cx + w * spread, ly), fill=color, width=5)
    draw.arc((cx - w * 0.2, base - h * 0.22, cx + w * 0.2, base + h * 0.12), 180, 360, fill=color, width=5)


@lru_cache(maxsize=4)
def source_page(highlight_step: int) -> Image.Image:
    pw, ph = 480, 660
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, pw, ph), 30, fill=(253, 252, 249, 255))
    draw.rounded_rectangle((0, 0, pw, 64), 30, fill=(238, 234, 226, 255))
    draw.rectangle((0, 40, pw, 64), fill=(238, 234, 226, 255))
    for index, color in enumerate(((214, 98, 62), (230, 180, 70), (110, 180, 120))):
        draw.ellipse((24 + index * 26, 24, 40 + index * 26, 40), fill=color + (200,))
    draw.text((112, 18), "Source page · illustrative", font=font(22, "medium"), fill=MUTED + (255,))
    draw.text((32, 88), "Eiffel Tower", font=font(44, "bold"), fill=INK + (255,))
    draw.rounded_rectangle((32, 152, pw - 32, 342), 18, fill=CYAN + (34,))
    tower(draw, pw / 2 - 90, 162, 180, 172, (40, 120, 135, 255))
    y = 372
    for width in (0.92, 0.84, 0.9):
        draw.rounded_rectangle((32, y, 32 + (pw - 64) * width, y + 14), 7, fill=INK + (30,))
        y += 32
    line_y = y + 6
    excerpt = "Completed in March 1889"
    excerpt_font = font(30, "demi")
    span = draw.textlength(excerpt, font=excerpt_font)
    if highlight_step > 0:
        draw.rounded_rectangle((26, line_y - 4, 26 + (span + 14) * highlight_step / 3, line_y + 40), 10, fill=CYAN + (70,))
    draw.text((32, line_y), excerpt, font=excerpt_font, fill=INK + (255,))
    y = line_y + 62
    for width in (0.88, 0.95, 0.7, 0.86):
        draw.rounded_rectangle((32, y, 32 + (pw - 64) * width, y + 14), 7, fill=INK + (30,))
        y += 32
    return image


def excerpt_callout(match_state: str, glow: float) -> Image.Image:
    big = font(50, "bold")
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    pw, ph = round(measure.textlength(f"Completed in March {RIGHT}", font=big)) + 90, 190
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, pw, ph), 34, fill=CARD + (255,))
    draw.rounded_rectangle((0, 0, 14, ph), 7, fill=CYAN + (255,))
    draw.ellipse((40, 40, 84, 84), outline=CYAN + (255,), width=6)
    draw.line((78, 78, 96, 96), fill=CYAN + (255,), width=7)
    draw.text((112, 34), "From the source", font=font(26, "medium"), fill=MUTED + (255,))
    draw.text((40, 100), "Completed in March ", font=big, fill=INK + (255,))
    year_x = 40 + draw.textlength("Completed in March ", font=big)
    if glow > 0:
        draw.rounded_rectangle((year_x - 8, 104, year_x + draw.textlength(RIGHT, font=big) + 8, 168), 12, fill=CYAN + (round(80 * glow),))
    draw.text((year_x, 100), RIGHT, font=big, fill=mix(INK, (16, 120, 134), glow) + (255,))
    return image


def chip(text: str, kind: str, struck: float = 0.0) -> Image.Image:
    label = "Before" if kind == "before" else "After"
    color = WARN if kind == "before" else (16, 120, 134)
    pw, ph = 250, 132
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, pw, ph), 28, fill=CARD + (255,))
    draw.text((26, 16), label, font=font(26, "medium"), fill=MUTED + (255,))
    draw.text((26, 48), text, font=font(56, "bold"), fill=color + (255,))
    if struck > 0:
        width = draw.textlength(text, font=font(56, "bold"))
        draw.line((22, 84, 22 + (width + 8) * struck, 84), fill=WARN + (255,), width=6)
    if kind == "after":
        cx, cy = pw - 46, 82
        draw.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=CYAN + (255,))
        draw.line((cx - 10, cy, cx - 3, cy + 8, cx + 11, cy - 8), fill=(255, 255, 255, 255), width=5)
    return image


def likely_words(highlight_guess: float) -> Image.Image:
    pw, ph = 420, 300
    image = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, pw, ph), 30, fill=CARD + (255,))
    draw.text((28, 22), "Likely next words", font=font(28, "demi"), fill=MUTED + (255,))
    rows = (("1899", 0.82, True), ("1889", 0.78, False), ("1898", 0.41, False))
    for index, (word, share, guess) in enumerate(rows):
        y = 82 + index * 70
        active = guess and highlight_guess > 0
        color = mix(INK, WARN, highlight_guess) if guess else INK
        draw.text((28, y), word, font=font(40, "bold"), fill=color + (255,))
        draw.rounded_rectangle((150, y + 16, 150 + 230, y + 34), 9, fill=INK + (20,))
        fill = mix(CYAN, WARN, highlight_guess) if guess else CYAN
        draw.rounded_rectangle((150, y + 16, 150 + 230 * share, y + 34), 9, fill=fill + (255,))
        if active:
            draw.text((300, y - 18), "guess", font=font(24, "demi"), fill=WARN + (round(255 * highlight_guess),))
    return image


def badge(symbol: str, color: tuple, size: int = 92) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, size, size), fill=color + (255,))
    if symbol == "✓":
        points = [(size * 0.28, size * 0.52), (size * 0.44, size * 0.68), (size * 0.73, size * 0.36)]
        draw.line(points, fill=(255, 255, 255, 255), width=max(3, round(size * 0.11)), joint="curve")
        return image
    face = font(round(size * 0.66), "heavy")
    box = draw.textbbox((0, 0), symbol, font=face)
    draw.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]), symbol, font=face, fill=(255, 255, 255, 255))
    return image


def text_block(canvas: Image.Image, lines: list[tuple[str, tuple]], x: float, y: float, size: int, face: str,
               t: float, start: float, align: str = "left", width: float = 0, stagger: float = 0.08) -> None:
    draw = ImageDraw.Draw(canvas)
    word_font = font(size, face)
    line_height = round(size * 1.16)
    index = 0
    for row, (text, color) in enumerate(lines):
        words = text.split(" ")
        total = draw.textlength(text, font=word_font)
        cursor = x if align == "left" else (x + (width - total) / 2 if align == "center" else x + width - total)
        for word in words:
            p = ease(prog(t, start + index * stagger, 0.35))
            if p > 0:
                tint = color
                layer = Image.new("RGBA", (round(draw.textlength(word, font=word_font)) + 8, line_height + 10), (0, 0, 0, 0))
                ImageDraw.Draw(layer).text((0, 0), word, font=word_font, fill=tint + (255,))
                canvas.alpha_composite(with_alpha(layer, p), (round(cursor), round(y + row * line_height + (1 - p) * 24)))
            cursor += draw.textlength(word + " ", font=word_font)
            index += 1


def connector(canvas: Image.Image, a: tuple, b: tuple, drawn: float, gap: float, color: tuple) -> None:
    if drawn <= 0:
        return
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    c1 = (a[0] - 40, a[1] + 140)
    c2 = (b[0] - 60, b[1] - 120)
    points = []
    for step in range(61):
        s = step / 60
        x = (1 - s) ** 3 * a[0] + 3 * (1 - s) ** 2 * s * c1[0] + 3 * (1 - s) * s ** 2 * c2[0] + s ** 3 * b[0]
        y = (1 - s) ** 3 * a[1] + 3 * (1 - s) ** 2 * s * c1[1] + 3 * (1 - s) * s ** 2 * c2[1] + s ** 3 * b[1]
        points.append((x, y))
    shown = points[: max(2, round(len(points) * drawn))]
    if gap > 0:
        cut = int(len(points) * gap * 0.18)
        middle = len(points) // 2
        first = [p for i, p in enumerate(shown) if i < middle - cut]
        second = [p for i, p in enumerate(shown) if i > middle + cut]
        for part in (first, second):
            if len(part) > 1:
                draw.line(part, fill=color + (255,), width=7, joint="curve")
    else:
        draw.line(shown, fill=color + (255,), width=7, joint="curve")
    draw.ellipse((a[0] - 11, a[1] - 11, a[0] + 11, a[1] + 11), fill=color + (255,))
    if drawn >= 1:
        draw.ellipse((b[0] - 11, b[1] - 11, b[0] + 11, b[1] + 11), fill=color + (255,))
    canvas.alpha_composite(layer)


def key_green(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    r, g, b = rgb.split()
    other = ImageChops.lighter(r, b)
    spill = ImageChops.subtract(g, other)
    alpha = spill.point(lambda v: 255 if v < 28 else max(0, 255 - (v - 28) * 7))
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    g = ImageChops.darker(g, other.point(lambda v: min(255, v + 12)))
    out = Image.merge("RGBA", (r, g, b, alpha))
    return out


def align_pose(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    top_band = alpha.crop((0, 0, alpha.width, 420)).point(lambda v: 255 if v > 128 else 0)
    box = top_band.getbbox()
    if not box:
        return image
    head_top = box[1]
    row = alpha.crop((0, head_top + 90, alpha.width, head_top + 130)).point(lambda v: 255 if v > 128 else 0).getbbox()
    center = (row[0] + row[2]) / 2 if row else alpha.width / 2
    shifted = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shifted.paste(image, (round(330 - center), round(60 - head_top)), image)
    return shifted


class Character:
    """Pose-to-pose animation from keyed stills, or keyed Veo clips when they exist."""

    def __init__(self, folder: Path, scenes: list[dict]):
        self.folder = folder
        self.scenes = scenes
        self.poses: dict[str, Image.Image] = {}
        keyed = folder / "poses-keyed"
        keyed.mkdir(exist_ok=True)
        for path in sorted((folder / "poses").glob("*.png")):
            dest = keyed / path.name
            if not dest.is_file():
                align_pose(key_green(Image.open(path))).save(dest)
            self.poses[path.stem] = Image.open(dest).convert("RGBA")
        host = folder / "host-green.png"
        if host.is_file():
            dest = keyed / "neutral.png"
            if not dest.is_file():
                align_pose(key_green(Image.open(host))).save(dest)
            self.poses["neutral"] = Image.open(dest).convert("RGBA")
        self.clips = self._clip_frames()

    def _clip_frames(self) -> dict[int, list[Path]]:
        found = {}
        for index, scene in enumerate(self.scenes, start=1):
            clip = self.folder / f"clip-{index}.mp4"
            if not clip.is_file():
                continue
            frames = self.folder / f"clip-{index}-frames"
            if not frames.is_dir():
                frames.mkdir()
                length = float(subprocess.run(
                    ["/opt/homebrew/bin/ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                    capture_output=True, text=True).stdout.strip())
                factor = scene["duration"] / length
                subprocess.run([FFMPEG, "-loglevel", "error", "-i", str(clip), "-vf",
                                f"setpts={factor:.4f}*PTS,fps={FPS},scale=720:1280", str(frames / "%04d.png")], check=False)
            found[index] = sorted(frames.glob("*.png"))
        return found

    def frame(self, scene_index: int, t: float, schedule: list[tuple[float, str]]) -> tuple[Image.Image, float, float]:
        frames = self.clips.get(scene_index)
        if frames:
            image = key_green(Image.open(frames[min(len(frames) - 1, int(t * FPS))]))
            return image, 0.0, 0.0
        current, previous, since = schedule[0][1], None, t
        for start, name in schedule:
            if t >= start:
                previous = current if name != current else previous
                current, since = name, t - start
        image = self.poses.get(current) or self.poses["neutral"]
        settle = ease(since / 0.35)
        dy = (1 - settle) * 14 + math.sin(t * 2 * math.pi / 3.4) * 4
        if previous and since < 0.1 and previous in self.poses:
            blend = since / 0.1
            image = Image.blend(self.poses[previous], image, blend)
        return image, 0.0, dy


def render(folder: Path) -> dict:
    timing = json.loads((folder / "timing.json").read_text())
    scenes = {item["id"]: item for item in timing}
    starts = [item["start"] for item in timing]
    total = timing[-1]["start"] + timing[-1]["duration"]
    S1, S2, S3, S4, S5 = (scenes[key]["start"] for key in ("hook", "check", "mismatch", "fix", "takeaway"))
    character = Character(folder, timing)

    schedules = {
        1: [(0.0, "walk_a"), (0.22, "walk_b"), (0.44, "walk_a"), (0.66, "walk_b"), (0.88, "walk_a"), (1.1, "present"), (3.1, "eyebrow")],
        2: [(0.0, "reach"), (1.2, "hold")],
        3: [(0.0, "lean_point"), (4.2, "shrug")],
        4: [(0.0, "push"), (2.0, "relief")],
        5: [(0.0, "lean_point"), (1.5, "point_camera")],
    }

    video = folder / "video-only.mp4"
    encoder = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(video)],
        stdin=subprocess.PIPE,
    )
    frames = round(total * FPS)
    excerpt_cache: dict = {}
    for frame_index in range(frames):
        T = frame_index / FPS
        scene_index = max(index for index, start in enumerate(starts, start=1) if T >= start - 1e-6)
        canvas = background().copy()

        # Answer panel state
        state = {
            "typed": ease_io(prog(T, S1 + 0.5, 1.1)),
            "meter": ease(prog(T, S1 + 0.9, 0.8)),
            "highlight": ease_io(prog(T, S1 + 2.2, 0.8)) * (1 - ease(prog(T, S2, 0.4))),
            "token": "normal",
        }
        if T >= S3 + 0.9:
            state["token"], state["warn"] = "warning", ease(prog(T, S3 + 0.9, 0.4))
        if T >= S4 + 0.5:
            state["token"] = "lifted"
        if T >= S4 + 1.5:
            state["token"], state["drop"] = "corrected", ease(prog(T, S4 + 1.5, 0.45))
        state["checked"] = 1.0 if T >= S4 + 1.9 else 0.0
        panel, token = answer_panel(state)

        enter = ease(prog(T, S1 + 0.15, 0.6))
        to_check = ease_io(prog(T, S2, 0.75))
        to_final = ease_io(prog(T, S5, 0.8))
        ax = lerp(lerp(110, 40, to_check), 40, to_final)
        ay = lerp(lerp(320, 250, to_check), 260, to_final) + (1 - enter) * 90
        ascale = lerp(lerp(1.0, 0.82, to_check), 0.6, to_final)
        paste_card(canvas, panel, ax, ay, ascale, enter, 40)
        token_screen = (ax + token[0] * ascale, ay + token[1] * ascale, ax + token[2] * ascale, ay + token[3] * ascale)
        token_anchor = ((token_screen[0] + token_screen[2]) / 2, token_screen[3] + 6)

        # Source page
        doc_in = ease_io(prog(T, S2 + 0.25, 0.85))
        if doc_in > 0:
            step = 3 if T >= S2 + 1.5 else (2 if T >= S2 + 1.35 else (1 if T >= S2 + 1.2 else 0))
            page = source_page(step)
            dx = lerp(1180, 590, doc_in)
            dy = lerp(-200, 470, doc_in)
            dscale = 0.9
            make_room = ease_io(prog(T, S4 + 0.2, 0.7))
            dx = lerp(dx, 650, make_room)
            dy = lerp(dy, 330, make_room)
            dscale = lerp(dscale, 0.7, make_room)
            dx = lerp(dx, 600, to_final)
            dy = lerp(dy, 250, to_final)
            dscale = lerp(dscale, 0.66, to_final)
            paste_card(canvas, page, dx, dy, dscale, min(1.0, doc_in * 1.5), 30)
            doc_line = (dx + 32 * dscale, dy + (372 + 96 + 6 + 20) * dscale)
        else:
            doc_line = (0, 0)

        # Enlarged excerpt
        callout_in = back(prog(T, S2 + 1.55, 0.5))
        callout_out = ease(prog(T, S4 + 0.2, 0.45))
        glow = ease(prog(T, S3 + 1.4, 0.4))
        callout_box = (40, 700)
        if callout_in > 0 and callout_out < 1:
            key = round(glow, 1)
            if key not in excerpt_cache:
                excerpt_cache[key] = excerpt_callout("match", key)
            scale = lerp(0.6, 1.0, callout_in) * lerp(1.0, 0.6, callout_out)
            cx = lerp(doc_line[0], callout_box[0], min(1.0, callout_in)) if doc_line[0] else callout_box[0]
            cy = lerp(doc_line[1], callout_box[1], min(1.0, callout_in)) if doc_line[1] else callout_box[1]
            cx = lerp(cx, 640, callout_out)
            cy = lerp(cy, 760, callout_out)
            paste_card(canvas, excerpt_cache[key], cx, cy, scale, min(1.0, callout_in) * (1 - callout_out), 34)
            excerpt_anchor = (cx + 40 * scale + 300 * scale, cy)

            # Connector from the claim to the excerpt
            drawn = ease(prog(T, S2 + 2.2, 0.7))
            broken = ease(prog(T, S3 + 0.5, 0.4))
            color = mix(CYAN, WARN, broken)
            if T < S4 + 0.2:
                connector(canvas, token_anchor, excerpt_anchor, drawn, broken, color)

        # Question mark on the unsupported claim
        q_in = back(prog(T, S3 + 1.1, 0.45))
        q_out = ease(prog(T, S4 + 0.3, 0.3))
        if q_in > 0 and q_out < 1:
            mark = badge("?", WARN, 92)
            size = max(1, round(92 * q_in * (1 - q_out)))
            mark = mark.resize((size, size), Image.LANCZOS)
            canvas.alpha_composite(mark, (round(token_screen[2] + 34 - size / 2 + 46), round(token_screen[1] + 40 - size / 2)))

        # Likely next words demonstration
        lw_in = ease(prog(T, S3 + 3.4, 0.45))
        lw_out = ease(prog(T, S4 + 0.1, 0.35))
        if lw_in > 0 and lw_out < 1:
            guess = ease(prog(T, S3 + 5.3, 0.4))
            panel_words = likely_words(guess)
            paste_card(canvas, panel_words, 540, lerp(990, 940, lw_in), 1.0, lw_in * (1 - lw_out), 30)

        # Lifted token flying aside, then before/after chips
        if S4 + 0.5 <= T < S5 + 0.8:
            fly = ease_io(prog(T, S4 + 0.5, 0.9))
            target = (70, 690)
            fx = lerp(token_screen[0], target[0], fly)
            fy = lerp(token_screen[1], target[1], fly)
            struck = ease(prog(T, S4 + 1.3, 0.35))
            out = ease(prog(T, S5, 0.6))
            before = chip(WRONG, "before", struck)
            paste_card(canvas, before, fx, fy, lerp(0.75, 1.0, fly), 1 - out, 28)
            after_in = back(prog(T, S4 + 1.9, 0.45))
            if after_in > 0:
                paste_card(canvas, chip(RIGHT, "after"), 360, 690, lerp(0.7, 1.0, min(1, after_in)), min(1, after_in) * (1 - out), 28)
                arrow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                arrow_draw = ImageDraw.Draw(arrow)
                arrow_draw.line((326, 756, 350, 756), fill=INK + (round(140 * min(1, after_in) * (1 - out)),), width=5)
                canvas.alpha_composite(arrow)

        # Agreement line in the takeaway
        if T >= S5 + 0.8:
            drawn = ease(prog(T, S5 + 0.8, 0.5))
            connector(canvas, token_anchor, (doc_line[0] + 4, doc_line[1]), drawn, 0, CYAN)
            ok_in = back(prog(T, S5 + 1.25, 0.4))
            if ok_in > 0:
                mark = badge("✓", CYAN, 72).resize((max(1, round(72 * ok_in)),) * 2, Image.LANCZOS)
                canvas.alpha_composite(mark, (round(token_screen[2] + 64 - mark.width / 2), round(token_screen[1] + 22 - mark.height / 2)))

        # Character
        local = T - starts[scene_index - 1]
        person, _, bob = character.frame(scene_index, local, schedules[scene_index])
        walk = ease(prog(T, S1, 1.15))
        px = lerp(-620, -40, walk) if scene_index == 1 else -40
        step_bob = abs(math.sin(T * math.pi / 0.22)) * -10 if scene_index == 1 and T < S1 + 1.1 else 0
        breathe = 1 + math.sin(T * 2 * math.pi / 3.4) * 0.006
        if breathe != 1:
            size = (round(person.width * breathe), round(person.height * breathe))
            person = person.resize(size, Image.BILINEAR)
        canvas.alpha_composite(person, (round(px), round(930 + bob + step_bob)))

        # Camera
        zoom, focus = 1.0, (540, 560)
        if scene_index == 1:
            zoom = lerp(1.0, 1.12, ease_io(prog(T, S1 + 1.6, 1.4)))
        if scene_index == 2:
            zoom = lerp(1.12, 1.0, ease_io(prog(T, S2, 0.8)))
        if scene_index == 3:
            zoom = lerp(1.0, 1.06, ease_io(prog(T, S3 + 0.4, 1.5)))
            zoom = lerp(zoom, 1.0, ease_io(prog(T, S4 - 0.6, 0.6)))
            focus = (480, 700)
        if zoom > 1.001:
            cw, ch = W / zoom, H / zoom
            left = focus[0] - focus[0] / zoom
            top = focus[1] - focus[1] / zoom
            canvas = canvas.crop((round(left), round(top), round(left + cw), round(top + ch))).resize((W, H), Image.BILINEAR)

        # Captions and on-screen text sit above the camera move
        if scene_index == 1:
            fade = 1 - ease(prog(T, S2 - 0.3, 0.3))
            if fade > 0:
                layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                text_block(layer, [("Confident", INK), ("≠ correct", CYAN)], 540, 1010, 86, "heavy", T, S1 + 2.6, stagger=0.12)
                canvas.alpha_composite(with_alpha(layer, fade))
        elif scene_index == 2:
            text_block(canvas, [("Check the claim", INK), ("against the source", MUTED)], 560, 1110, 42, "demi", T, S2 + 0.9)
        elif scene_index == 3:
            fade = 1 - ease(prog(T, S3 + 3.2, 0.3))
            if fade > 0:
                layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                text_block(layer, [("Where's the", INK), ("evidence?", WARN)], 560, 1040, 70, "heavy", T, S3 + 1.6, stagger=0.1)
                canvas.alpha_composite(with_alpha(layer, fade))
        elif scene_index == 4:
            words = (("Check.", S4 + 4.3), ("Compare.", S4 + 4.9), ("Correct.", S4 + 5.5))
            measure = ImageDraw.Draw(canvas)
            size = 60
            total_w = sum(measure.textlength(word + " ", font=font(size, "heavy")) for word, _ in words)
            cursor = (W - total_w) / 2
            for word, at in words:
                lit = ease(prog(T, at, 0.25))
                if T >= at - 0.4:
                    color = mix(INK, (16, 120, 134), lit)
                    text_block(canvas, [(word, color)], cursor, 880, size, "heavy", T, at - 0.4, stagger=0)
                cursor += measure.textlength(word + " ", font=font(size, "heavy"))
        else:
            text_block(canvas, [("Check the source", INK), ("before you share.", INK)], 0, 700, 76, "heavy", T, S5 + 1.0,
                       align="center", width=W, stagger=0.09)
            brand = ease(prog(T, S5 + 1.9, 0.5))
            if brand > 0:
                layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                draw = ImageDraw.Draw(layer)
                name, handle = "BrewIQ", "  @_brewiq"
                name_w = draw.textlength(name, font=font(36, "bold"))
                full_w = name_w + draw.textlength(handle, font=font(28, "medium")) + 26
                left = (W - full_w) / 2
                draw.rounded_rectangle((left, 902, left + 12, 942), 6, fill=CYAN + (255,))
                draw.text((left + 26, 898), name, font=font(36, "bold"), fill=INK + (255,))
                draw.text((left + 26 + name_w, 906), handle, font=font(28, "medium"), fill=MUTED + (255,))
                canvas.alpha_composite(with_alpha(layer, brand))

        encoder.stdin.write(canvas.convert("RGB").tobytes())
    encoder.stdin.close()
    encoder.wait()
    return {"frames": frames, "seconds": round(total, 2), "events": {"S": [S1, S2, S3, S4, S5]}}


def sound(folder: Path) -> Path:
    sfx = folder / "sfx"
    sfx.mkdir(exist_ok=True)
    recipes = {
        "pop": "aevalsrc='0.6*sin(2*PI*(500+900*exp(-28*t))*t)*exp(-22*t)':d=0.18",
        "tick": "aevalsrc='0.5*sin(2*PI*1900*t)*exp(-70*t)':d=0.06",
        "thunk": "aevalsrc='0.8*sin(2*PI*(120+60*exp(-20*t))*t)*exp(-11*t)':d=0.35",
        "chime": "aevalsrc='0.35*(sin(2*PI*1318*t)+0.6*sin(2*PI*1976*t)+0.3*sin(2*PI*2637*t))*exp(-5*t)':d=1.0",
    }
    for name, recipe in recipes.items():
        dest = sfx / f"{name}.wav"
        if not dest.is_file():
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", recipe, "-ar", "48000", str(dest)], check=False)
    whoosh = sfx / "whoosh.wav"
    if not whoosh.is_file():
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=0.55:a=0.5",
                        "-af", "bandpass=f=900:width_type=o:w=1.4,afade=t=in:d=0.25,afade=t=out:st=0.25:d=0.3", "-ar", "48000", str(whoosh)], check=False)
    pad = sfx / "pad.wav"
    if not pad.is_file():
        chords = [(220.0, 277.18, 329.63), (185.0, 220.0, 277.18), (146.83, 185.0, 220.0), (164.81, 207.65, 246.94)]
        parts = []
        for index, (a, b, c) in enumerate(chords):
            part = sfx / f"pad-{index}.wav"
            expr = f"0.12*(sin(2*PI*{a}*t)+sin(2*PI*{b}*t)+0.8*sin(2*PI*{c}*t)+0.3*sin(2*PI*{a * 2}*t))*(0.75+0.25*sin(2*PI*0.3*t))"
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':d=8",
                            "-af", "lowpass=f=900,afade=t=in:d=1.2,afade=t=out:st=6.8:d=1.2", "-ar", "48000", str(part)], check=False)
            parts.append(part)
        inputs = sum((["-i", str(part)] for part in parts), [])
        delays = "".join(f"[{i}]adelay={i * 7500}|{i * 7500}[p{i}];" for i in range(len(parts)))
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex",
                        f"{delays}{''.join(f'[p{i}]' for i in range(len(parts)))}amix=inputs={len(parts)}:normalize=0", "-ar", "48000", str(pad)], check=False)
    return sfx


def mix_audio(folder: Path, total: float) -> Path:
    timing = json.loads((folder / "timing.json").read_text())
    S = [item["start"] for item in timing]
    sfx = sound(folder)
    cues = [
        ("whoosh", S[0] + 0.15, 0.5), ("tick", S[0] + 2.2, 0.6), ("pop", S[0] + 2.6, 0.5),
        ("whoosh", S[1] + 0.25, 0.6), ("pop", S[1] + 1.55, 0.6), ("tick", S[1] + 2.2, 0.5),
        ("thunk", S[2] + 0.5, 0.7), ("pop", S[2] + 1.1, 0.6), ("tick", S[2] + 3.4, 0.5), ("tick", S[2] + 5.3, 0.6),
        ("whoosh", S[3] + 0.5, 0.6), ("chime", S[3] + 1.5, 0.45), ("tick", S[3] + 4.3, 0.6), ("tick", S[3] + 4.9, 0.6),
        ("tick", S[3] + 5.5, 0.6), ("whoosh", S[4] + 0.05, 0.5), ("chime", S[4] + 1.25, 0.5),
    ]
    inputs, filters, labels = [], [], []
    for index, item in enumerate(timing, start=1):
        inputs += ["-i", str(folder / f"voice-{index}.wav")]
        delay = round(item["start"] * 1000 + 120)
        filters.append(f"[{len(inputs) // 2 - 1}]adelay={delay}|{delay},volume=1.0[v{index}]")
        labels.append(f"[v{index}]")
    for index, (name, at, gain) in enumerate(cues):
        inputs += ["-i", str(sfx / f"{name}.wav")]
        delay = round(at * 1000)
        filters.append(f"[{len(inputs) // 2 - 1}]adelay={delay}|{delay},volume={gain * 0.45}[s{index}]")
        labels.append(f"[s{index}]")
    inputs += ["-i", str(sfx / "pad.wav")]
    filters.append(f"[{len(inputs) // 2 - 1}]volume=0.09,afade=t=out:st={total - 1.5:.2f}:d=1.5[pad]")
    labels.append("[pad]")
    graph = ";".join(filters) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95,atrim=0:{total:.3f}[out]"
    dest = folder / "mix.wav"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[out]", "-ar", "48000", "-ac", "2", str(dest)], check=False)
    return dest


def main(folder: Path) -> dict:
    result = render(folder)
    audio = mix_audio(folder, result["seconds"])
    final = folder / "brewiq-confident-wrong.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(folder / "video-only.mp4"), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)], check=False)
    result["output"] = str(final)
    return result


if __name__ == "__main__":
    import sys

    print(json.dumps(main(Path(sys.argv[1]))))
