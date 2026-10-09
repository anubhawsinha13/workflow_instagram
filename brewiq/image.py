"""Render a six-slide 1080×1350 carousel. Text is drawn in code."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from research_md import primary_urls
from rights import original_scene_clause
from brand import (
    BG,
    BRAND,
    HANDLE,
    HEIGHT,
    MARGIN_X,
    MARGIN_Y,
    MUTED,
    SLIDE_COUNT,
    WHITE,
    WIDTH,
    category_style,
    hex_rgb,
)

BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
DISPLAY = "/System/Library/Fonts/Supplemental/Impact.ttf"
CONTENT_WIDTH = WIDTH - (MARGIN_X * 2)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_width: int,
    max_lines: int,
    start: int,
    minimum: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    size = start
    while size >= minimum:
        font = _font(font_path, size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines, int(size * 1.18)
        size -= 2
    font = _font(font_path, minimum)
    return font, _wrap(draw, text, font, max_width)[:max_lines], int(minimum * 1.18)


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font_path: str,
    max_width: int,
    start: int,
    minimum: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    size = start
    while size >= minimum:
        font = _font(font_path, size)
        if all(draw.textlength(line, font=font) <= max_width for line in lines):
            return font, lines, int(size * 1.28)
        size -= 1
    font = _font(font_path, minimum)
    fitted = []
    for line in lines:
        clipped = line
        while clipped and draw.textlength(clipped, font=font) > max_width:
            clipped = clipped[:-1].rstrip()
        fitted.append(clipped)
    return font, fitted, int(minimum * 1.28)


def _usable_key(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or "your_" in value.lower() or len(value) < 12:
        return ""
    return value


def _illustration_prompt(visual_idea: str) -> str:
    idea = visual_idea or "a single charcoal abstract form with one cyan highlight"
    return (
        "Premium cinematic advertising still, photoreal, sharp, dramatic light. "
        f"{original_scene_clause()} "
        f"Scene: {idea}. Deep charcoal atmosphere, one cyan or warm highlight, dark empty space across the bottom third."
    )


def fetch_cover_illustration(visual_idea: str) -> tuple[Image.Image | None, str]:
    """Return a text-free cover image, or None when the model is unavailable."""
    prompt = _illustration_prompt(visual_idea)
    openai_key = _usable_key("OPENAI_API_KEY")
    if openai_key:
        image = _openai_image(openai_key, prompt)
        if image is not None:
            return image, "ai_generated"
        return None, "not_model_generated"
    gemini_key = _usable_key("GEMINI_API_KEY") or _usable_key("GOOGLE_API_KEY")
    if gemini_key:
        image = _gemini_image(gemini_key, prompt)
        if image is not None:
            return image, "ai_generated"
        return None, "not_model_generated"
    return None, "not_model_generated"


def _openai_image(key: str, prompt: str) -> Image.Image | None:
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(api_key=key, timeout=90)
    for model, size in (("gpt-image-1", "1024x1536"), ("dall-e-3", "1024x1792")):
        try:
            result = client.images.generate(model=model, prompt=prompt, size=size, n=1)
            data = result.data[0]
            raw = getattr(data, "b64_json", None)
            if raw:
                import base64

                return Image.open(BytesIO(base64.b64decode(raw))).convert("RGB")
            url = getattr(data, "url", None)
            if url:
                import requests

                response = requests.get(url, timeout=60)
                response.raise_for_status()
                return Image.open(BytesIO(response.content)).convert("RGB")
        except Exception:
            continue
    return None


def _gemini_image(key: str, prompt: str) -> Image.Image | None:
    try:
        import google.generativeai as genai
    except ImportError:
        return None
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.5-flash-image")
        response = model.generate_content(prompt)
        for candidate in response.candidates or []:
            for part in candidate.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return Image.open(BytesIO(inline.data)).convert("RGB")
    except Exception:
        return None
    return None


def _paste_cover(base: Image.Image, photo: Image.Image) -> None:
    photo = photo.convert("RGB")
    band_h = 860
    scale = max(WIDTH / photo.width, band_h / photo.height)
    resized = photo.resize((int(photo.width * scale), int(photo.height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - WIDTH) // 2)
    top = max(0, (resized.height - band_h) // 2)
    crop = resized.crop((left, top, left + WIDTH, top + band_h))
    base.paste(crop, (0, 0))
    fade = Image.new("RGBA", (WIDTH, 220))
    pixels = fade.load()
    charcoal = hex_rgb(BG)
    for y in range(220):
        alpha = int(255 * (y / 219))
        for x in range(WIDTH):
            pixels[x, y] = (*charcoal, alpha)
    base.alpha_composite(fade, (0, 640))
    panel = Image.new("RGBA", (WIDTH, HEIGHT - 860), (*charcoal, 255))
    base.alpha_composite(panel, (0, 860))
    top_fade = Image.new("RGBA", (WIDTH, 280))
    top_pixels = top_fade.load()
    for y in range(280):
        alpha = int(210 * (1 - y / 279))
        for x in range(WIDTH):
            top_pixels[x, y] = (*charcoal, alpha)
    base.alpha_composite(top_fade, (0, 0))


def _paint_mark(base: Image.Image, accent: str) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    color = hex_rgb(accent)
    draw.ellipse((640, 220, 1220, 800), outline=(*color, 230), width=14)
    base.alpha_composite(overlay)


class _Placements:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], font, fill: str) -> None:
        if not text:
            return
        draw.text(xy, text, font=font, fill=fill)
        left, top = xy
        ink_left, ink_top, ink_right, ink_bottom = font.getbbox(text)
        self.items.append(
            {
                "text": text,
                "left": left + ink_left,
                "top": top + ink_top,
                "right": left + ink_right,
                "bottom": top + ink_bottom,
            }
        )


def _within_margins(placements: _Placements) -> bool:
    for item in placements.items:
        if item["left"] < MARGIN_X - 1:
            return False
        if item["right"] > WIDTH - MARGIN_X + 1:
            return False
        if item["top"] < MARGIN_Y - 1:
            return False
        if item["bottom"] > HEIGHT - MARGIN_Y + 1:
            return False
    return bool(placements.items)


def _origin_x(font: ImageFont.FreeTypeFont, text: str, left_edge: int) -> int:
    return left_edge - font.getbbox(text)[0]


def _right_origin(font: ImageFont.FreeTypeFont, text: str, right_edge: int) -> int:
    return right_edge - font.getbbox(text)[2]


def _cover_fill(photo: Image.Image) -> Image.Image:
    photo = photo.convert("RGB")
    scale = max(WIDTH / photo.width, HEIGHT / photo.height)
    resized = photo.resize((int(photo.width * scale), int(photo.height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - WIDTH) // 2)
    top = max(0, (resized.height - HEIGHT) // 2)
    return resized.crop((left, top, left + WIDTH, top + HEIGHT)).convert("RGBA")


def _darken_for_type(base: Image.Image) -> None:
    charcoal = hex_rgb(BG)
    fade_top, fade_h = 600, 300
    fade = Image.new("L", (1, fade_h))
    fade.putdata([int(250 * (y / (fade_h - 1)) ** 1.4) for y in range(fade_h)])
    layer = Image.new("RGBA", (WIDTH, fade_h), (*charcoal, 255))
    layer.putalpha(fade.resize((WIDTH, fade_h)))
    base.alpha_composite(layer, (0, fade_top))
    base.alpha_composite(Image.new("RGBA", (WIDTH, HEIGHT - fade_top - fade_h), (*charcoal, 250)), (0, fade_top + fade_h))
    top_h = 230
    top = Image.new("L", (1, top_h))
    top.putdata([int(150 * (1 - y / (top_h - 1)) ** 1.6) for y in range(top_h)])
    top_layer = Image.new("RGBA", (WIDTH, top_h), (*charcoal, 255))
    top_layer.putalpha(top.resize((WIDTH, top_h)))
    base.alpha_composite(top_layer, (0, 0))


def paint_poster(
    art: Image.Image,
    *,
    number: int,
    label: str,
    accent: str,
    lines: list[tuple[str, str]],
    footers: list[str],
    body: list[str] | None = None,
    handle: str = HANDLE,
) -> tuple[Image.Image, list[str], bool]:
    """Full-bleed illustration with a poster headline. Text is drawn, not invented by the image model."""
    base = _cover_fill(art)
    _darken_for_type(base)
    draw = ImageDraw.Draw(base)
    placed = _Placements()
    body = [line for line in (body or []) if line][:3]
    headline = [text for text, color in lines if color == WHITE]
    accent_lines = [text for text, color in lines if color != WHITE]
    right = WIDTH - MARGIN_X

    label_font = _font(BOLD, 30)
    placed.add(draw, label, (_origin_x(label_font, label, MARGIN_X), MARGIN_Y + 2), label_font, accent)
    brand_font = _font(BOLD, 40)
    placed.add(draw, BRAND, (_right_origin(brand_font, BRAND, right), MARGIN_Y - 2), brand_font, WHITE)

    handle_font = _font(BOLD, 26)
    footer_font = _font(REGULAR, 21)
    body_font = _font(REGULAR, 32)
    footer_h = 40 + 27 * len(footers)
    body_h = 42 * len(body) + (36 if body else 0)
    max_block = HEIGHT - MARGIN_Y - 760 - footer_h - body_h
    display = _fit_display(draw, headline, CONTENT_WIDTH, max_block)
    line_h = int(display.size * 0.98)
    stat_font = _font(DISPLAY, max(44, int(display.size * 0.5)))
    stat_h = int(stat_font.size * 1.1) * len(accent_lines) + (10 if accent_lines else 0)

    footer_top = HEIGHT - MARGIN_Y - footer_h
    cursor = footer_top - 34 - body_h - stat_h - line_h * len(headline)
    for text in headline:
        placed.add(draw, text, (_origin_x(display, text, MARGIN_X), cursor), display, WHITE)
        cursor += line_h
    if accent_lines:
        cursor += 10
        for text in accent_lines:
            placed.add(draw, text, (_origin_x(stat_font, text, MARGIN_X), cursor), stat_font, accent)
            cursor += int(stat_font.size * 1.1)
    if body:
        cursor += 36
        for line in body:
            placed.add(draw, line, (_origin_x(body_font, line, MARGIN_X), cursor), body_font, MUTED)
            cursor += 42

    placed.add(draw, handle, (_origin_x(handle_font, handle, MARGIN_X), footer_top + 4), handle_font, accent)
    footer_y = footer_top + 44
    for footer in footers:
        placed.add(draw, footer, (_origin_x(footer_font, footer, MARGIN_X), footer_y), footer_font, MUTED)
        footer_y += 27

    on_image = [item["text"] for item in placed.items]
    return base.convert("RGB"), on_image, _within_margins(placed)


def _fit_display(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    max_width: int,
    max_block: int | None = None,
) -> ImageFont.FreeTypeFont:
    size = 150
    while size >= 68:
        font = _font(DISPLAY, size)
        line_h = int(size * 0.98)
        fits_width = all(draw.textlength(line, font=font) <= max_width for line in lines)
        fits_height = max_block is None or line_h * len(lines) <= max_block
        if fits_width and fits_height:
            return font
        size -= 2
    return _font(DISPLAY, 68)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    placed: _Placements,
    slide: dict,
    accent: str,
    label: str,
) -> int:
    brand_font = _font(BOLD, 40)
    handle_font = _font(REGULAR, 22)
    counter_font = _font(REGULAR, 22)
    label_font = _font(BOLD, 26)
    y = MARGIN_Y
    placed.add(draw, BRAND, (_origin_x(brand_font, BRAND, MARGIN_X), y), brand_font, WHITE)
    counter = f"{slide['number']} / {SLIDE_COUNT}"
    placed.add(
        draw,
        counter,
        (_right_origin(counter_font, counter, WIDTH - MARGIN_X), y + 14),
        counter_font,
        MUTED,
    )
    y += 52
    placed.add(draw, HANDLE, (_origin_x(handle_font, HANDLE, MARGIN_X), y), handle_font, MUTED)
    y += 46
    placed.add(draw, label, (_origin_x(label_font, label, MARGIN_X), y), label_font, accent)
    rule_y = y + 40
    draw.rectangle((MARGIN_X, rule_y, MARGIN_X + 72, rule_y + 4), fill=accent)
    return rule_y + 36


def render_slide(
    slide: dict,
    category: str,
    illustration: Image.Image | None,
    image_status: str,
) -> tuple[Image.Image, list[str], bool]:
    style = category_style(category)
    accent = style["accent"]
    label = style["label"]
    base = Image.new("RGBA", (WIDTH, HEIGHT), (*hex_rgb(BG), 255))
    if slide["role"] == "cover" and illustration is not None:
        _paste_cover(base, illustration)
    elif slide["role"] == "cover":
        _paint_mark(base, accent)
    draw = ImageDraw.Draw(base)
    placed = _Placements()
    cursor = _draw_header(draw, placed, slide, accent, label)

    if slide["role"] == "cover":
        font, lines, line_h = _fit_wrapped(draw, slide["headline"], BOLD, CONTENT_WIDTH, 3, 68, 40)
        block_h = line_h * max(1, len(lines))
        cursor = max(cursor, HEIGHT - MARGIN_Y - 150 - block_h)
    else:
        font, lines, line_h = _fit_wrapped(draw, slide["headline"], BOLD, CONTENT_WIDTH, 2, 54, 34)
        cursor += 24
    for line in lines:
        placed.add(draw, line, (_origin_x(font, line, MARGIN_X), cursor), font, WHITE)
        cursor += line_h

    if slide["body"]:
        cursor += 28
        body_font, body_lines, body_h = _fit_lines(draw, slide["body"], REGULAR, CONTENT_WIDTH, 34, 24)
        for line in body_lines:
            placed.add(draw, line, (_origin_x(body_font, line, MARGIN_X), cursor), body_font, MUTED)
            cursor += body_h

    credit = ""
    if slide["role"] == "cover" and image_status == "ai_generated":
        credit = "AI-generated concept illustration"
        credit_font = _font(REGULAR, 18)
        credit_y = HEIGHT - MARGIN_Y - 78
        placed.add(draw, credit, (_origin_x(credit_font, credit, MARGIN_X), credit_y), credit_font, MUTED)

    if slide.get("next_cue"):
        cue_font = _font(BOLD, 22)
        cue_y = HEIGHT - MARGIN_Y - 36
        cue_x = _right_origin(cue_font, slide["next_cue"], WIDTH - MARGIN_X)
        if cue_x < MARGIN_X:
            cue_x = _origin_x(cue_font, slide["next_cue"], MARGIN_X)
        placed.add(draw, slide["next_cue"], (cue_x, cue_y), cue_font, accent)

    on_image = [item["text"] for item in placed.items]
    return base.convert("RGB"), on_image, _within_margins(placed)


def fallback_prompt(slide: dict, category: str, image_status: str) -> str:
    style = category_style(category)
    body = "\n".join(slide["body"]) or "(no body text)"
    cue = slide.get("next_cue") or "(none)"
    credit = "AI-generated concept illustration" if image_status == "ai_generated" and slide["role"] == "cover" else "(none)"
    return "\n".join(
        [
            "Image not generated",
            f"Slide {slide['number']} of {SLIDE_COUNT}, role {slide['role']}",
            "Dimensions: 1080 × 1350 pixels, 4:5 portrait",
            f"Background: {BG}",
            f"Main text: {WHITE}",
            f"Accent ({style['label']}): {style['accent']}",
            "Margins: at least 86 px left and right, 108 px top and bottom",
            "Layout: BrewIQ and @_brewiq at the top left, slide counter at the top right, category label under the handle, headline in the upper-middle, body under the headline, next cue at the lower right.",
            "Exact on-image text:",
            BRAND,
            HANDLE,
            f"{slide['number']} / {SLIDE_COUNT}",
            style["label"],
            slide["headline"],
            body,
            credit,
            cue,
            "Exclusions: no extra words, no logos beyond the BrewIQ wordmark, no clutter, no claim that a concept illustration is a product screenshot or event photo.",
        ]
    )


def render_carousel(
    slides: list[dict],
    research: dict,
    destination: Path,
    cover_path: Path | None = None,
) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    illustration, image_status = (None, "not_model_generated")
    if cover_path is not None and Path(cover_path).exists():
        illustration = Image.open(cover_path).convert("RGB")
        image_status = "ai_generated"
    else:
        try:
            illustration, image_status = fetch_cover_illustration(research.get("visual_idea") or "")
        except Exception:
            illustration, image_status = None, "not_model_generated"

    written = []
    prompts = []
    try:
        for slide in slides:
            image, on_image, inside = render_slide(slide, research["category"], illustration, image_status)
            if image.size != (WIDTH, HEIGHT) or not inside:
                raise RuntimeError(f"Slide {slide['number']} failed the size or margin check.")
            path = destination / f"slide-{slide['number']:02d}.png"
            image.save(path, format="PNG")
            confirmed = Image.open(path)
            if confirmed.size != (WIDTH, HEIGHT):
                raise RuntimeError(f"Saved slide {slide['number']} is {confirmed.size[0]}×{confirmed.size[1]}.")
            written.append(
                {
                    "number": slide["number"],
                    "role": slide["role"],
                    "path": str(path),
                    "filename": path.name,
                    "width": confirmed.size[0],
                    "height": confirmed.size[1],
                    "on_image_text": on_image,
                    "headline": slide["headline"],
                    "body": slide["body"],
                }
            )
    except Exception as exc:
        for path in destination.glob("slide-*.png"):
            path.unlink()
        prompt_path = destination / "image_prompt.txt"
        prompt_path.write_text(
            "\n\n".join(fallback_prompt(slide, research["category"], image_status) for slide in slides),
            encoding="utf-8",
        )
        return {
            "ok": False,
            "status": "Image not generated",
            "error": str(exc),
            "slides": [],
            "prompt_path": str(prompt_path),
            "image_status": image_status,
        }

    if len(written) != SLIDE_COUNT:
        return {
            "ok": False,
            "status": "Image not generated",
            "error": "The carousel is missing slides.",
            "slides": [],
            "image_status": image_status,
        }
    return {
        "ok": True,
        "status": "ready",
        "slides": written,
        "image_status": image_status,
        "error": "",
    }


def poster_lines(headline: str, accent: str, accent_line: str = "") -> list[tuple[str, str]]:
    """White headline lines, plus an optional accent-colored stat line drawn smaller underneath."""
    words = [word for word in headline.upper().replace("—", " ").rstrip(".").split() if word]
    if not words:
        words = ["BREWIQ"]
    chunks = _wrap_poster_words(words)
    lines = [(line, WHITE) for line in chunks]
    if accent_line:
        lines.append((accent_line.upper(), accent))
    return lines


def _wrap_poster_words(words: list[str]) -> list[str]:
    """Break a long headline on word boundaries that fit the safe width at the smallest display size."""
    draw = ImageDraw.Draw(Image.new("RGB", (WIDTH, HEIGHT)))
    font = _font(DISPLAY, 112)
    chunks: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if not current or draw.textlength(trial, font=font) <= CONTENT_WIDTH:
            current = trial
            continue
        chunks.append(current)
        current = word
    if current:
        chunks.append(current)
    return chunks


def render_posters(
    slides: list[dict],
    research: dict,
    destination: Path,
    arts: list[Image.Image],
    provider_label: str,
    accent: str | None = None,
) -> dict:
    """Paint the poster layout on illustrations. The image model does not draw the words."""
    destination.mkdir(parents=True, exist_ok=True)
    if len(arts) < SLIDE_COUNT:
        return {"ok": False, "error": "Six illustrations are required.", "slides": [], "image_status": provider_label}
    style = category_style(research["category"])
    accent = accent or style["accent"]
    source = ""
    urls = primary_urls(research)
    if urls:
        host = urlparse(urls[0]).netloc.removeprefix("www.")
        title = next(
            (
                (claim.get("source_title") or "").strip()
                for claim in research.get("claims") or []
                if (claim.get("source_url") or "").strip().rstrip(".,)") == urls[0]
            ),
            "",
        )
        name = title if title and len(title) <= 28 else host
        date = (research.get("publication_date") or "").strip()
        source = f"Source: {name}" if name else "Source listed in the caption"
        if name and date and date.lower() != "not stated":
            source = f"Source: {name} • {date}"
    note = "Supplied concept illustration" if provider_label == "uploaded" else "AI-generated concept illustration"
    written = []
    for slide, art in zip(slides, arts):
        footers = []
        if slide["number"] == 1 and source:
            footers.append(source)
        footers.append(note)
        image, on_image, margins_ok = paint_poster(
            art,
            number=slide["number"],
            label=style["label"],
            accent=accent,
            lines=poster_lines(slide["headline"], accent, slide.get("accent_line") or ""),
            footers=footers,
            body=[] if slide["role"] == "cover" else slide.get("body") or [],
        )
        filename = f"slide-{slide['number']:02d}.png"
        path = destination / filename
        image.convert("RGB").save(path, "PNG")
        written.append(
            {
                "number": slide["number"],
                "role": slide["role"],
                "path": str(path),
                "filename": filename,
                "headline": slide["headline"],
                "on_image_text": on_image,
                "body": slide["body"],
                "width": WIDTH,
                "height": HEIGHT,
                "margins_ok": margins_ok,
            }
        )
    if not all(item["margins_ok"] for item in written):
        return {"ok": False, "error": "Poster type crossed the safe margin.", "slides": written, "image_status": provider_label}
    return {"ok": True, "slides": written, "image_status": provider_label, "error": ""}
