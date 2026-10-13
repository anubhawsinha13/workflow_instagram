"""Draw the five platform frames from one script. Nothing here publishes.

Each frame is composed for its own ratio. A 16:9 file is not a crop of the 9:16 frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from platforms import (
    PLATFORMS, SHAPE_1_1, SHAPE_16_9, SHAPE_2_3, SHAPE_4_5, SHAPE_9_16, SHAPES, Surface, text_problems,
)

POSES = Path(__file__).resolve().parent / "brand" / "poses"
BG = (247, 243, 236, 255)
INK = (43, 43, 43, 255)
MUTED = (92, 86, 78, 255)
CYAN = (34, 195, 214, 255)
WHITE = (255, 255, 255, 255)

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/macos/Inter-SemiBold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
SERIF_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
)


@dataclass(frozen=True)
class PackScript:
    hook: str
    support: str
    steps: str
    keep: str


SAMPLE = PackScript(
    hook="It agreed with a wrong date",
    support="The date was wrong.",
    steps="Ask. Open. Read. Drop.",
    keep="If the source does not say it, drop the answer.",
)


def _font(candidates: tuple[str, ...], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
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


def _fit(draw, text, candidates, width, height, start, minimum) -> tuple:
    size = start
    while size >= minimum:
        font = _font(candidates, size)
        lines = _wrap(draw, text, font, width)
        line_h = int(size * 1.15)
        if len(lines) * line_h <= height:
            return font, lines, line_h
        size -= 2
    font = _font(candidates, minimum)
    return font, _wrap(draw, text, font, width), int(minimum * 1.15)


def _paste(frame: Image.Image, pose: str, region: tuple[int, int, int, int]) -> None:
    image = Image.open(POSES / f"{pose}.png").convert("RGBA")
    mask = image.getchannel("A").point(lambda value: 255 if value > 24 else 0)
    box = mask.getbbox()
    if box is None:
        return
    image = image.crop(box)
    x0, y0, x1, y1 = region
    bw, bh = image.size
    scale = min((x1 - x0) / bw, (y1 - y0) / bh)
    sized = image.resize((max(1, round(bw * scale)), max(1, round(bh * scale))), Image.LANCZOS)
    start = sized.height * 0.78
    column = Image.new("L", (1, sized.height))
    column.putdata([
        255 if y <= start else int(255 * (1 - (y - start) / max(1, sized.height - start)) ** 2)
        for y in range(sized.height)
    ])
    sized.putalpha(ImageChops.multiply(sized.getchannel("A"), column.resize(sized.size)))
    dest_x = round(x0 + ((x1 - x0) - sized.width) / 2)
    dest_y = round(y0 + ((y1 - y0) - sized.height) / 2)
    frame.alpha_composite(sized, (dest_x, dest_y))


def _frame(surface: Surface, pose: str, kicker: str, headline: str, body: str) -> Image.Image:
    left, top, right, bottom = surface.critical()
    image = Image.new("RGBA", (surface.width, surface.height), BG)
    gap = 28
    host_w = int((right - left) * 0.42)
    host_box = (left, top, left + host_w, bottom)
    card = (left + host_w + gap, top, right, bottom)
    _paste(image, pose, host_box)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(card, 28, fill=WHITE)
    inner_left = card[0] + 36
    inner_right = card[2] - 36
    inner_w = inner_right - inner_left
    draw.text((inner_left, card[1] + 36), kicker.upper(), font=_font(FONT_CANDIDATES, 22), fill=CYAN)
    headline_font, lines, line_h = _fit(draw, headline, SERIF_CANDIDATES, inner_w, int((bottom - top) * 0.46), 64, 28)
    y = card[1] + 80
    for line in lines:
        draw.text((inner_left, y), line, font=headline_font, fill=INK)
        y += line_h
    if body:
        body_font, body_lines, body_h = _fit(
            draw, body, FONT_CANDIDATES, inner_w, max(40, card[3] - y - 36), 32, 18,
        )
        y += 12
        for line in body_lines:
            draw.text((inner_left, y), line, font=body_font, fill=MUTED)
            y += body_h
    return image


def ink_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    minx, miny, maxx, maxy = width, height, 0, 0
    for y in range(height):
        for x in range(0, width, 2):
            red, green, blue = rgb.getpixel((x, y))
            if red + green + blue < 680:
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
    return minx, miny, maxx, maxy


def edge_problems(surface: Surface, image: Image.Image) -> list[str]:
    minx, miny, maxx, maxy = ink_bounds(image)
    left, top, right, bottom = surface.critical()
    problems = []
    if minx < left - 1 or miny < top - 1 or maxx > right + 1 or maxy > bottom + 1:
        problems.append(
            f"{surface.id} ink {minx},{miny}-{maxx},{maxy} leaves the safe area "
            f"{left},{top}-{right},{bottom}."
        )
    if minx < 24 or miny < 24 or maxx > image.width - 24 or maxy > image.height - 24:
        problems.append(f"{surface.id} ink touches the frame edge.")
    return problems


def captions(script: PackScript) -> dict[str, str]:
    """One set of words, cut to the platform that will show them."""
    feed = f"{script.support} {script.steps} {script.keep}"
    short = f"{script.hook}. {script.keep}"
    vertical = f"{script.hook}. {script.steps}"
    return {
        "instagram.post": feed,
        "facebook.post": feed,
        "reddit.post": feed,
        "youtube.video": script.hook,
        "google_business.post": short,
        "linkedin.post": f"{script.support} {script.keep} {script.steps}",
        "x.post": short,
        "telegram.post": short,
        "tiktok.video": vertical,
        "threads.post": vertical,
        "discord.post": vertical,
        "pinterest.pin": script.keep,
        "whatsapp.status": script.keep,
    }


def caption_problems(script: PackScript) -> list[str]:
    written = captions(script)
    problems = []
    for surface in PLATFORMS:
        text = written.get(surface.id, "")
        if not text:
            problems.append(f"{surface.id} has no caption.")
            continue
        problems.extend(text_problems(surface, text))
    return problems


def render_shapes(script: PackScript) -> dict[str, Image.Image]:
    """Five pictures. Same hook. Each one is drawn for its ratio."""
    frames = {
        SHAPE_4_5.id: _frame(SHAPE_4_5, "magnify", "BrewIQ", script.hook, f"{script.support} {script.steps}"),
        SHAPE_1_1.id: _frame(SHAPE_1_1, "magnify", "BrewIQ", script.hook, script.steps),
        SHAPE_16_9.id: _frame(SHAPE_16_9, "hold", "BrewIQ", script.hook, script.support),
        SHAPE_9_16.id: _frame(SHAPE_9_16, "magnify", "BrewIQ", script.hook, script.steps),
        SHAPE_2_3.id: _frame(SHAPE_2_3, "hold", "BrewIQ", script.keep, script.steps),
    }
    problems = []
    for shape in SHAPES:
        problems.extend(edge_problems(shape, frames[shape.id]))
    if problems:
        raise ValueError(" ".join(problems))
    return frames


def write_pack(folder: Path, script: PackScript = SAMPLE) -> dict[str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    written = {}
    for key, image in render_shapes(script).items():
        path = folder / f"{key.replace('.', '-')}.jpg"
        image.convert("RGB").save(path, quality=92)
        written[key] = str(path)
    lines = [f"{key}: {value}" for key, value in captions(script).items()]
    caption_path = folder / "captions.txt"
    caption_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written["captions"] = str(caption_path)
    return written
