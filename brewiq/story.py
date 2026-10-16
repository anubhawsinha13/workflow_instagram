"""The animated story behind the 8-second Reel: one original 3D character living the moment and doing the fix.

The story director writes a shot sheet, the way animation prompts are written: each shot has a title, its time,
and a full cinematic prompt (look, action, camera, lens, light). GPT Image draws one still per shot of the same
character. The insert shot is a close-up of the phone in their hand with a green screen, and the real sample
screen is keyed onto it, behind their thumb. Veo animates the opening shot when it has credits; otherwise each
still plays with a slow push-in. Nothing is published here.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

from PIL import Image

SHOTS = ("hook", "insert", "fix", "cta")
SIZE = (1080, 1920)

LOOK = (
    "Feature-film quality stylized 3D animation, Pixar-inspired, premium cinematic look, warm practical light, "
    "soft bokeh, shallow depth of field, expressive face, real materials and textures. "
)
FRAMING = (
    " Vertical 9:16. The character's head sits in the middle of the frame with open wall or ceiling above it, "
    "and the hands are in the lower half."
)
CLEAN = (
    " The phone or laptop screen faces away from the camera or is too soft to read. "
    "No text, no captions, no logos, no brand names, no watermark."
)
SAME = (
    "Keep the exact same character, face, hair, clothes, place, lighting, and 3D animated style as this image. "
    "This shot: "
)
INSERT = (
    " Close-up insert over the character's shoulder: their hand holds the phone toward the camera, thumb hovering "
    "just above the screen. The phone sits in the lower half of the frame, right of center, its top edge just below "
    "the middle of the picture, so the upper half stays open. The phone screen is lit solid flat pure chroma green (#00FF00) edge to edge, no "
    "reflections, no icons, no text. Their face is soft in the background. Vertical 9:16. No logos, no watermark."
)


def shots_of(story: dict) -> dict:
    """The story's shots by id. An older story with three moments gets a plain insert shot."""
    shots = {str(shot.get("id")): shot for shot in story.get("shots") or [] if isinstance(shot, dict)}
    moments = story.get("moments") if isinstance(story.get("moments"), dict) else {}
    for role in ("hook", "fix", "cta"):
        if role not in shots and str(moments.get(role) or "").strip():
            shots[role] = {"id": role, "prompt": moments[role]}
    if "insert" not in shots:
        shots["insert"] = {"id": "insert", "prompt": "They look down at the message, about to tap it."}
    return shots


def problems(story) -> list:
    """What is missing from a story. An empty list means it can be drawn."""
    if not isinstance(story, dict):
        return ["The story must be an object."]
    found = []
    for field in ("character", "setting"):
        if not str(story.get(field) or "").strip():
            found.append(f"The story needs a {field}.")
    shots = shots_of(story)
    for role in ("hook", "fix", "cta"):
        if not str((shots.get(role) or {}).get("prompt") or "").strip():
            found.append(f"The story needs a {role} shot.")
    return found


def frame_prompt(story: dict, role: str) -> str:
    shot = str(shots_of(story)[role].get("prompt") or "").strip()
    if role == "hook":
        return f"{LOOK}An original adult character: {story['character']}. Place: {story['setting']}. {shot}{FRAMING}{CLEAN}"
    if role == "insert":
        return f"{SAME}{shot}{INSERT}"
    return f"{SAME}{shot}{FRAMING}{CLEAN}"


def shot_sheet(story: dict, timing: dict | None = None) -> str:
    """The shot sheet as text, in the "Scene 1 | 0:00–0:02" form. Veo reads it, and the Slack draft shows it."""
    shots = shots_of(story)
    lines = [f"{LOOK.strip()} Character: {story['character']}. Place: {story['setting']}."]
    for number, role in enumerate(SHOTS, start=1):
        shot = shots[role]
        span = (timing or {}).get(role)
        when = f" | {_mmss(span[0])}–{_mmss(span[1])}" if span else ""
        lines.append(f"Scene {number} | {str(shot.get('title') or role.title()).strip()}{when}\n{str(shot.get('prompt')).strip()}")
    return "\n\n".join(lines)


def _mmss(seconds: float) -> str:
    return f"0:{int(round(seconds)):02d}"


def motion_prompt(story: dict) -> str:
    """One continuous shot that walks through the moments, for Veo."""
    shots = shots_of(story)
    return (
        f"{LOOK}The original adult character in the image: {story['character']}. Place: {story['setting']}. "
        "One continuous vertical shot with a gentle handheld push-in. No dialogue, no speech, no text, no subtitles. "
        f"First: {shots['hook']['prompt']} Then: {shots['fix']['prompt']} Finally: {shots['cta']['prompt']}{CLEAN}"
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
    """Draw one still per shot. Every shot after the first is an edit of it, so the character matches.

    The insert shot is optional: without it the reel lays the phone over the picture instead.
    """
    if generate is None or edit is None:
        from art import openai_edit_image, openai_image  # noqa: PLC0415 - loads the image client only when needed.

        generate = generate or openai_image
        edit = edit or openai_edit_image
    folder.mkdir(parents=True, exist_ok=True)
    paths = {role: folder / f"story-{role}.png" for role in SHOTS}
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        errors = dict(zip(SHOTS[1:], pool.map(draw, SHOTS[1:])))
    failed = [error for role, error in errors.items() if error and role != "insert"]
    if failed:
        return {"ok": False, "error": failed[0]}
    frames = {role: str(path) for role, path in paths.items() if path.is_file()}
    return {"ok": True, "frames": frames, "error": ""}


def scene_accent(path: str) -> str:
    """A bright color taken from the picture, for the key words and the logo, so the type belongs to the scene."""
    import colorsys  # noqa: PLC0415

    with Image.open(path) as picture:
        small = picture.convert("RGB").resize((96, 170))
    palette = small.quantize(colors=10).convert("RGB").getcolors(96 * 170) or []
    best, best_score = None, 0.0
    for count, (red, green, blue) in palette:
        hue, sat, val = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        # The color that fills the most of the picture wins, as long as it is a real color and not gray.
        score = sat * (0.4 + val) * count
        if sat > 0.35 and val > 0.3 and score > best_score:
            best, best_score = (hue, sat, val), score
    if best is None:
        return "#FFE14D"
    hue, sat, _val = best
    # Bright enough to read on the picture with a shadow under it.
    red, green, blue = colorsys.hsv_to_rgb(hue, max(0.55, min(0.85, sat)), 1.0)
    return "#{:02X}{:02X}{:02X}".format(round(red * 255), round(green * 255), round(blue * 255))


KEY_MIN_AREA = 0.03


def green_mask(image: Image.Image) -> Image.Image:
    """White where the picture shows the chroma-green phone screen."""
    red, green, blue = image.convert("RGB").split()
    from PIL import ImageChops, ImageFilter  # noqa: PLC0415

    # Green clearly above both red and blue, and bright enough to be the lit screen.
    over_red = ImageChops.subtract(green, red).point(lambda v: 255 if v > 70 else 0)
    over_blue = ImageChops.subtract(green, blue).point(lambda v: 255 if v > 70 else 0)
    bright = green.point(lambda v: 255 if v > 120 else 0)
    mask = ImageChops.multiply(ImageChops.multiply(over_red, over_blue), bright)
    # Grow a little to swallow the green fringe at the bezel and the thumb.
    return mask.filter(ImageFilter.MaxFilter(5))


def screen_corners(mask: Image.Image) -> list | None:
    """The four corners of the green screen: top-left, top-right, bottom-right, bottom-left."""
    small = mask.resize((mask.width // 4, mask.height // 4))
    points = [(x * 4, y * 4) for y in range(small.height) for x in range(small.width) if small.getpixel((x, y)) > 128]
    if len(points) < small.width * small.height * KEY_MIN_AREA:
        return None
    top_left = min(points, key=lambda p: p[0] + p[1])
    bottom_right = max(points, key=lambda p: p[0] + p[1])
    top_right = max(points, key=lambda p: p[0] - p[1])
    bottom_left = min(points, key=lambda p: p[0] - p[1])
    return [top_left, top_right, bottom_right, bottom_left]


def _solve(matrix: list, values: list) -> list:
    """Gaussian elimination for the 8 perspective coefficients."""
    size = len(values)
    rows = [row[:] + [value] for row, value in zip(matrix, values)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(size):
            if r != col and rows[col][col]:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col])]
    return [rows[i][size] / rows[i][i] for i in range(size)]


def _perspective(source: list, target: list) -> list:
    """Coefficients that map each output point in `target` back to its `source` point, for Image.transform."""
    matrix, values = [], []
    for (sx, sy), (tx, ty) in zip(source, target):
        matrix.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty])
        matrix.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty])
        values.extend([sx, sy])
    return _solve(matrix, values)


def lay_screen(photo: Path, content: Image.Image, dest: Path) -> list | None:
    """Put `content` on the green phone screen in `photo`, behind the thumb.

    Returns the screen's box (left, top, right, bottom) so words can stay off it, or None when no screen is found.
    """
    with Image.open(photo) as picture:
        base = picture.convert("RGBA")
    mask = green_mask(base)
    corners = screen_corners(mask)
    if corners is None:
        return None
    width, height = content.size
    coefficients = _perspective([(0, 0), (width, 0), (width, height), (0, height)], corners)
    warped = content.convert("RGBA").transform(base.size, Image.PERSPECTIVE, coefficients, Image.BICUBIC)
    from PIL import ImageFilter  # noqa: PLC0415

    # The screen glows a touch, the way a lit phone does in a dim room.
    soft = mask.filter(ImageFilter.GaussianBlur(1.2))
    base.paste(warped, (0, 0), soft)
    base.convert("RGB").save(dest)
    xs, ys = [x for x, _ in corners], [y for _, y in corners]
    return [min(xs), min(ys), max(xs), max(ys)]


def key_screens(frames: dict, screens: dict, folder: Path) -> dict:
    """Lay each beat's sample screen onto the phone in the insert shot. Beats whose screen can't be keyed are left out."""
    insert = frames.get("insert")
    if not insert:
        return {}
    from explainer_render import phone_screen  # noqa: PLC0415

    keyed = {}
    for role, screen in screens.items():
        if not isinstance(screen, dict):
            continue
        dest = folder / f"story-insert-{role}.png"
        box = lay_screen(Path(insert), phone_screen(screen, (370, 800)), dest)
        if box:
            keyed[role] = str(dest)
            keyed["_box"] = box
    return keyed


def make_backdrop(story: dict, folder: Path, screens: dict | None = None, *, generate=None, edit=None, animate=None) -> dict:
    """The pictures behind the reel: one still per shot, the real screen keyed into the insert, and a Veo clip
    of the opening when it can be made."""
    missing = problems(story)
    if missing:
        return {"ok": False, "error": " ".join(missing)}
    folder = Path(folder)
    drawn = make_frames(story, folder, generate=generate, edit=edit)
    if not drawn.get("ok"):
        return drawn
    frames = drawn["frames"]
    notes = []
    keyed = key_screens(frames, screens or {}, folder)
    if screens and not keyed:
        notes.append("The phone close-up could not be keyed, so the phone is laid over the picture.")
    # The insert's green screen would win the color pick, so the close-up takes the opening shot's color.
    accents = {role: scene_accent(path) for role, path in frames.items() if role != "insert"}
    accents["insert"] = accents["hook"]
    result = {"ok": True, "frames": frames, "keyed": keyed, "accents": accents}
    clip = folder / "story.mp4"
    if not (clip.is_file() and clip.stat().st_size > 0):
        if animate is None:
            import director_reel  # noqa: PLC0415

            animate = director_reel._generate_veo_clip
        made = animate(Path(frames["hook"]), motion_prompt(story), clip)
        if not (made.get("ok") and clip.is_file()):
            notes.append(f"{made.get('error') or 'Veo did not return a clip.'} The story plays as moving stills instead.")
            return {**result, "kind": "stills", "notes": notes}
    return {**result, "kind": "video", "video": str(clip), "notes": notes}
