"""Product screenshots from the research's official source pages, for the reel's hero picture.

Images come only from the pages the research cited, such as a product's help center. Logos, icons and
navigation art are skipped. Each image keeps its source host so the reel can credit it on screen.
This module downloads files. It does not publish anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageChops

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
MIN_WIDTH = 480
MAX_IMAGES = 6
MAX_BYTES = 8_000_000
# Navigation and brand art that sits on every page and says nothing about the topic.
SKIP_ALT = re.compile(r"\b(logo|help center|close navigation|avatar|icon|badge|download)\b", re.IGNORECASE)
SKIP_SRC = re.compile(r"(\.svg($|\?)|/logo|/nav/|/icons?/|favicon|sprite|avatar)", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
# Words every screenshot description shares, which would match any beat.
_FILLER = set(
    "a an the and or of to in on for with your you it its is are this that by from at as be how what "
    "static image picture cursor click clicking tap app screen menu".split()
)


class _ImageFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag != "img":
            return
        values = {name: value or "" for name, value in attrs}
        src = values.get("src") or values.get("data-src") or ""
        if src:
            self.images.append({"src": src, "alt": values.get("alt", "").strip()})


def host_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _get(url: str, limit: int = MAX_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(limit + 1)[:limit]


def candidates(page_url: str, html: str) -> list[dict]:
    """Content images on a page: described, not a logo, icon, or navigation art."""
    finder = _ImageFinder()
    finder.feed(html)
    found: list[dict] = []
    seen: set[str] = set()
    for image in finder.images:
        src = urljoin(page_url, image["src"])
        alt = image["alt"]
        if not alt or SKIP_ALT.search(alt) or SKIP_SRC.search(src) or src in seen:
            continue
        if not src.startswith(("http://", "https://")):
            continue
        seen.add(src)
        found.append({"src": src, "alt": alt, "page": page_url, "credit": host_of(page_url)})
    return found


def collect(source_urls: list[str], folder: Path, *, fetch=_get, limit: int = MAX_IMAGES) -> list[dict]:
    """Download up to `limit` usable screenshots from the cited pages. Failures are skipped, not raised."""
    folder.mkdir(parents=True, exist_ok=True)
    index = folder / "sources.json"
    if index.is_file():
        try:
            cached = json.loads(index.read_text(encoding="utf-8"))
            if all(Path(item["path"]).is_file() for item in cached):
                return cached
        except (OSError, ValueError, KeyError, TypeError):
            pass
    images: list[dict] = []
    for page in dict.fromkeys(url for url in source_urls if str(url).startswith(("http://", "https://"))):
        if len(images) >= limit:
            break
        try:
            html = fetch(page).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001 - one unreachable page should not stop the reel.
            continue
        for item in candidates(page, html):
            if len(images) >= limit:
                break
            if any(existing["src"] == item["src"] for existing in images):
                continue
            try:
                data = fetch(item["src"])
            except Exception:  # noqa: BLE001
                continue
            name = hashlib.sha1(item["src"].encode()).hexdigest()[:16]
            path = folder / f"{name}.img"
            path.write_bytes(data)
            try:
                with Image.open(path) as picture:
                    width = picture.width
                    animated = bool(getattr(picture, "is_animated", False))
            except Exception:  # noqa: BLE001 - not an image.
                path.unlink(missing_ok=True)
                continue
            if width < MIN_WIDTH:
                path.unlink(missing_ok=True)
                continue
            images.append({**item, "path": str(path), "animated": animated, "crop": content_box(path)})
    index.write_text(json.dumps(images, indent=2), encoding="utf-8")
    return images


def _words(text: str) -> set[str]:
    return {word[:5] for word in _WORD.findall(str(text).lower()) if len(word) > 2 and word not in _FILLER}


def assign(beats: list[dict], images: list[dict]) -> list[dict | None]:
    """Pick the screenshot whose description matches each beat's words.

    A screenshot that shares no words with the beat would show the wrong step, so a beat without a match
    keeps the previous beat's screenshot, or borrows the next one at the start. Beats with their own still,
    tiles, or swatch get None.
    """
    hosts = {image.get("credit", "").split(".")[-2] for image in images if "." in image.get("credit", "")}
    product = {word[:5] for word in hosts}
    open_beats: list[bool] = []
    matched: list[dict | None] = []
    used: list[str] = []
    for beat in beats:
        on_screen = beat.get("on_screen") if isinstance(beat.get("on_screen"), dict) else {}
        shot = beat.get("shot") if isinstance(beat.get("shot"), dict) else {}
        is_open = bool(images) and shot.get("mode") != "still" and not on_screen.get("tiles") and not on_screen.get("swatch")
        open_beats.append(is_open)
        if not is_open:
            matched.append(None)
            continue
        said = _words(" ".join([str(beat.get("voice") or ""), str(on_screen.get("headline") or "")])) - product
        scored = [(len(said & (_words(image["alt"]) - product)), image) for image in images]
        best_score = max(score for score, _ in scored)
        if best_score == 0:
            matched.append(None)
            continue
        best = min(
            (image for score, image in scored if score == best_score),
            key=lambda image: (used.count(image["src"]), images.index(image)),
        )
        used.append(best["src"])
        matched.append(best)
    chosen: list[dict | None] = []
    for index, is_open in enumerate(open_beats):
        if not is_open:
            chosen.append(None)
            continue
        pick = matched[index]
        if pick is None:
            earlier = next((item for item in reversed(chosen) if item is not None), None)
            later = next((item for item in matched[index + 1:] if item is not None), None)
            pick = earlier or later
        chosen.append(pick)
    return chosen


def content_box(path: Path) -> list[int] | None:
    """The app window inside a screenshot: everything that differs from the background around it.

    Looks at a few frames of an animated screenshot so moving parts stay inside the box.
    """
    try:
        with Image.open(path) as picture:
            count = int(getattr(picture, "n_frames", 1))
            box = None
            for index in sorted({0, count // 2, count - 1}):
                picture.seek(index)
                frame = picture.convert("RGBA")
                corner = frame.getpixel((2, 2))
                backdrop = Image.new("RGBA", frame.size, corner)
                diff = ImageChops.difference(frame, backdrop).convert("L").point(lambda value: 255 if value > 24 else 0)
                found = diff.getbbox()
                if found:
                    box = found if box is None else (min(box[0], found[0]), min(box[1], found[1]),
                                                     max(box[2], found[2]), max(box[3], found[3]))
            width, height = picture.size
    except Exception:  # noqa: BLE001 - a crop is an improvement, never a requirement.
        return None
    if not box:
        return None
    pad = 12
    left, top, right, bottom = max(0, box[0] - pad), max(0, box[1] - pad), min(width, box[2] + pad), min(height, box[3] + pad)
    if (right - left) * (bottom - top) > width * height * 0.92:
        return None  # Nothing worth cutting.
    return [left, top, right, bottom]


def trim(picture: Image.Image) -> Image.Image:
    """Crop to the screenshot itself: drop transparent margins, black bands, and the speckled drop shadow."""
    rgba = picture.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (0, 0, 0))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    gray = flat.convert("L")
    width, height = gray.size
    pixels = gray.load()

    def bright(values: list[int]) -> bool:
        return sum(1 for value in values if value > 150) > len(values) * 0.5

    rows = [y for y in range(height) if bright([pixels[x, y] for x in range(0, width, 4)])]
    if not rows:
        return flat
    # Columns are judged only within the screenshot's rows, so a short screenshot still counts.
    # A dark sidebar is still screenshot, so columns only need to be clearly not black. The speckled
    # shadow around the window is mostly black, so it stays out.
    cols = [
        x for x in range(width)
        if sum(1 for y in range(min(rows), max(rows) + 1, 4) if pixels[x, y] > 22) > (max(rows) - min(rows)) / 4 * 0.9
    ]
    if not cols:
        return flat
    return flat.crop((min(cols), min(rows), max(cols) + 1, max(rows) + 1))


INVENTED_PEOPLE = ("Priya Shah", "Marcus Lee", "Ana Ruiz", "Sam Okafor", "Lena Park")


def rewrite_prompt(screen: dict | None) -> str:
    """Ask the image model to keep the real interface and swap in the reel's invented names and messages.

    Without a screen plan, only the names and photos change, so no real person appears in the reel.
    """
    if not isinstance(screen, dict) or not screen.get("lines"):
        names = ", ".join(f'"{name}"' for name in INVENTED_PEOPLE)
        return (
            "Edit this product screenshot. Keep the app interface exactly as it is: the layout, colors, logo, icons, "
            "fonts, spacing, buttons, messages, and any cursor.\n"
            f"Change only the people: give each person shown a new name from this list, in order: {names}. "
            "Replace every profile photo with a flat colored circle holding that person's initials. No photos of people.\n"
            "If the screenshot shows no people or photos, return it unchanged. Every word must stay sharp and legible."
        )
    lines = [line for line in (screen.get("lines") or []) if isinstance(line, dict)]
    people = "\n".join(f'- Person {index + 1}: name "{line.get("who")}", message "{line.get("text")}"' for index, line in enumerate(lines))
    title = str(screen.get("title") or "").split("·")[0].strip()
    channel = f'- The channel or page name becomes "{title}" everywhere it appears.\n' if title else ""
    return (
        "Edit this product screenshot. Keep the app interface exactly as it is: the layout, colors, logo, icons, fonts, "
        "spacing, buttons, and any cursor.\n"
        "Change only the people and their words, in the order they appear on screen:\n"
        f"{channel}{people}\n"
        "- Replace every profile photo with a flat colored circle holding that person's initials. No photos of people.\n"
        "If the screenshot shows fewer people than listed, use the first ones. Keep times and counts. "
        "Every word must be spelled exactly as written, sharp and legible."
    )


def rewrite(image: dict, screen: dict | None, folder: Path, *, edit=None) -> dict:
    """Swap the screenshot's names and messages for the reel's invented ones. Returns the original on failure."""
    if image.get("animated"):
        return image
    key = hashlib.sha1((image["src"] + json.dumps(screen or {}, sort_keys=True)).encode()).hexdigest()[:16]
    out = folder / f"{key}-edited.png"
    if out.is_file():
        return {**image, "path": str(out), "edited": True}
    if edit is None:
        from art import openai_edit_image as edit  # noqa: PLC0415 - loads the image client only when needed.
    source = folder / f"{key}-source.png"
    try:
        with Image.open(image["path"]) as picture:
            picture.convert("RGBA").save(source)
        result = edit(source, rewrite_prompt(screen))
    except Exception:  # noqa: BLE001 - an edit failure falls back to the official screenshot.
        return image
    edited = result.get("image") if isinstance(result, dict) and result.get("ok") else None
    if edited is None:
        return image
    trim(edited).save(out)
    return {**image, "path": str(out), "edited": True}

