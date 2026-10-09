"""One paid image provider at a time.

The first provider that returns a usable image is the only one used for the
rest of that carousel. A failed provider is not retried, and slides already
made are not regenerated on the next provider.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

from character import character_reference
from rights import original_scene_clause

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TIMEOUT = 90
SUNBURST = "gpt-image-2.5-sunburst"
SUNBURST_FALLBACK = "gpt-image-2.5-flare"
GEMINI = "gemini-3.1-flash-image"
GEMINI_FALLBACK = "gemini-2.5-flash-image"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or "your_" in value or value.endswith("_here"):
        return ""
    return value


_ROLE_BEATS = {
    "cover": (
        "Wide establishing shot. People or silhouettes gather around a glowing abstract interface or metaphor "
        "in a dark premium room with cool cyan light and a soft city glow in the distance. The subject fills "
        "the upper two thirds."
    ),
    "why": (
        "Tighter shot on the same world. Emphasize the stakes with stronger light on the central object and "
        "softer figures at the edge of frame."
    ),
    "point": (
        "Clearer close view of the mechanism inside the metaphor: modules, light paths, or interlocking pieces "
        "that show how the idea works."
    ),
    "try": (
        "Hands-on practical beat in the same visual world: a person reaches toward or arranges the glowing object, "
        "as if taking a simple next step."
    ),
    "limit": (
        "The same scene under more tension: one connection flickers, a panel dims, or a gap appears in the "
        "network, without becoming scary or gory."
    ),
    "close": (
        "Resolved, calmer reprise of the opening motif. Soft cyan light, balanced composition, a sense of "
        "clarity after the check."
    ),
}


def scene_prompts(slides: list[dict], research: dict) -> list[str]:
    idea = (
        research.get("visual_idea")
        or "a glowing glass table of abstract cyan modules in a dark high-rise room at night"
    ).strip()
    prompts = []
    for slide in slides:
        beat = _ROLE_BEATS.get(slide["role"], _ROLE_BEATS["cover"])
        prompts.append(
            "Premium cinematic advertising still for Instagram, 4:5 portrait, photoreal concept art. "
            f"{original_scene_clause()} "
            f"Core scene: {idea}. "
            f"Beat for slide {slide['number']} ({slide['role']}): {beat} "
            "Dark charcoal and deep navy palette with cyan highlights. High contrast, shallow depth of field, "
            "editorial lighting. Keep the lower third dark, empty, and simple so typography can be added later. "
            "No interface screens with readable UI, no charts with numbers, and no brand marks."
        )
    return prompts


def load_uploaded(path: Path) -> list[Image.Image]:
    path = path.expanduser()
    if path.is_dir():
        files = sorted(item for item in path.iterdir() if item.suffix.lower() in IMAGE_SUFFIXES)
    elif path.is_file():
        files = [path]
    else:
        raise FileNotFoundError(f"No illustration file at {path}")
    if not files:
        raise FileNotFoundError(f"No images in {path}")
    images = [Image.open(item).convert("RGB") for item in files]
    if len(images) == 1:
        return images * 6
    if len(images) < 6:
        raise ValueError("Provide one image, or a folder with six images.")
    return images[:6]


def _skip(provider: str, model: str, error: str) -> dict:
    return {"image": None, "provider": provider, "model": model, "ok": False, "skipped": True, "error": error}


def _fail(provider: str, model: str, error: str) -> dict:
    return {"image": None, "provider": provider, "model": model, "ok": False, "skipped": False, "error": error}


def _ok(provider: str, model: str, image: Image.Image) -> dict:
    return {"image": image, "provider": provider, "model": model, "ok": True, "skipped": False, "error": ""}


def _model_rejected(exc: Exception) -> bool:
    text = str(exc).lower()
    return "model" in text and any(word in text for word in ("not found", "does not exist", "invalid", "unknown"))


def _unsupported_fidelity(exc: Exception) -> bool:
    return "input_fidelity" in str(exc).lower()


def _reference_error(detail: str) -> str:
    text = " ".join(str(detail).split())
    lowered = text.lower()
    if not text or len(text) > 240 or any(word in lowered for word in ("api_key", "sk-", "secret", "bearer")):
        return "The character reference could not be applied, so a different character was not generated."
    return text


def _edit_request(client, reference: Path, prompt: str, model: str, fidelity: bool):
    kwargs = {
        "model": model,
        "prompt": prompt,
        "size": "1024x1536",
        "quality": "medium",
        "n": 1,
    }
    if fidelity:
        kwargs["input_fidelity"] = "high"
    with reference.open("rb") as handle:
        return client.images.edit(image=handle, **kwargs)


def _image_from_bytes(raw: bytes) -> Image.Image:
    return Image.open(io.BytesIO(raw)).convert("RGB")


def openai_image(prompt: str) -> dict:
    key = _secret("OPENAI_API_KEY")
    if not key:
        return _skip("openai", SUNBURST, "OPENAI_API_KEY is not set.")
    from openai import OpenAI

    client = OpenAI(api_key=key, timeout=TIMEOUT)
    last_error = "OpenAI did not return an image."
    for model in (SUNBURST, SUNBURST_FALLBACK):
        try:
            response = client.images.generate(
                model=model,
                prompt=prompt,
                size="1024x1536",
                quality="medium",
                n=1,
            )
            data = response.data[0]
            if getattr(data, "b64_json", None):
                raw = base64.b64decode(data.b64_json)
            elif getattr(data, "url", None):
                raw = requests.get(data.url, timeout=TIMEOUT).content
            else:
                last_error = f"{model} returned no image."
                continue
            return _ok("openai", model, _image_from_bytes(raw))
        except Exception as exc:
            last_error = str(exc)
            if model == SUNBURST and _model_rejected(exc):
                continue
            return _fail("openai", model, last_error)
    return _fail("openai", SUNBURST_FALLBACK, last_error)


def openai_edit_image(reference: Path, prompt: str, *, require_reference: bool = False) -> dict:
    """Build a new frame from a reference image."""
    if not reference.is_file():
        if require_reference:
            return _fail(
                "openai",
                SUNBURST,
                "The approved BrewIQ character reference is missing, so this scene was not generated.",
            )
        return openai_image(prompt)
    key = _secret("OPENAI_API_KEY")
    if not key:
        return _skip("openai", SUNBURST, "OPENAI_API_KEY is not set.")
    from openai import OpenAI

    client = OpenAI(api_key=key, timeout=TIMEOUT)
    last_error = "OpenAI did not return an edited image."
    for model in (SUNBURST, SUNBURST_FALLBACK):
        for fidelity in (True, False):
            try:
                response = _edit_request(client, reference, prompt, model, fidelity)
                data = response.data[0]
                if getattr(data, "b64_json", None):
                    raw = base64.b64decode(data.b64_json)
                elif getattr(data, "url", None):
                    raw = requests.get(data.url, timeout=TIMEOUT).content
                else:
                    last_error = f"{model} returned no edited image."
                    if fidelity:
                        continue
                    break
                return _ok("openai", model, _image_from_bytes(raw))
            except Exception as exc:
                last_error = str(exc)
                if fidelity and _unsupported_fidelity(exc):
                    continue
                break
        if model == SUNBURST and _model_rejected(Exception(last_error)):
            continue
        break
    if require_reference:
        return _fail("openai", SUNBURST, _reference_error(last_error))
    fallback = openai_image(prompt)
    if fallback.get("ok"):
        return fallback
    return _fail("openai", SUNBURST, last_error)


def openai_character_image(prompt: str) -> dict:
    """Edit the saved face reference so a reel uses the same person."""
    reference = character_reference()
    if reference is None:
        return openai_image(prompt)
    return openai_edit_image(reference, prompt)


def midjourney_image(prompt: str) -> dict:
    url = (os.getenv("MIDJOURNEY_API_URL") or "").strip()
    key = _secret("MIDJOURNEY_API_KEY")
    if not url or not key:
        return _skip(
            "midjourney",
            "v8.2",
            "Midjourney has no official public API. This step is skipped unless both "
            "MIDJOURNEY_API_URL and MIDJOURNEY_API_KEY are set. Unofficial wrappers are not used.",
        )
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"prompt": prompt, "version": "8.2"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return _fail("midjourney", "v8.2", str(exc))
    if response.status_code >= 400:
        return _fail("midjourney", "v8.2", f"Midjourney API returned {response.status_code}.")
    payload = response.json() if response.content else {}
    if payload.get("b64_json"):
        return _ok("midjourney", "v8.2", _image_from_bytes(base64.b64decode(payload["b64_json"])))
    image_url = payload.get("image_url") or payload.get("url")
    if image_url:
        raw = requests.get(image_url, timeout=TIMEOUT).content
        return _ok("midjourney", "v8.2", _image_from_bytes(raw))
    return _fail("midjourney", "v8.2", "Midjourney API responded without an image.")


def _gemini_bytes(response) -> bytes | None:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    return None


def gemini_image(prompt: str) -> dict:
    key = _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")
    if not key:
        return _skip("gemini", GEMINI, "GEMINI_API_KEY is not set.")
    import google.generativeai as genai

    genai.configure(api_key=key)
    last_error = "Gemini did not return an image."
    for model_name in (GEMINI, GEMINI_FALLBACK):
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt, request_options={"timeout": TIMEOUT})
            raw = _gemini_bytes(response)
            if raw:
                return _ok("gemini", model_name, _image_from_bytes(raw))
            last_error = f"{model_name} returned no image."
        except Exception as exc:
            last_error = str(exc)
            if model_name == GEMINI and _model_rejected(exc):
                continue
            return _fail("gemini", model_name, last_error)
    return _fail("gemini", GEMINI_FALLBACK, last_error)


def default_callers():
    return [openai_image, midjourney_image, gemini_image]


def generate_illustrations(prompts: list[str], callers=None) -> dict:
    """Call providers in order. Stop at the first image, then use that caller for every later slide."""
    callers = list(callers or default_callers())
    images: list[Image.Image] = []
    attempts: list[dict] = []
    locked = None
    for prompt in prompts:
        order = [locked] if locked else callers
        winner = None
        for caller in order:
            result = caller(prompt)
            attempts.append({key: result[key] for key in ("provider", "model", "ok", "skipped", "error")})
            if result["skipped"]:
                continue
            if result["ok"] and result["image"] is not None:
                winner = result
                locked = caller
                break
            if locked:
                break
        if winner is None:
            detail = attempts[-1]["error"] if attempts else "No image provider returned an image."
            return {
                "ok": False,
                "images": [],
                "attempts": attempts,
                "provider": "",
                "model": "",
                "error": (
                    "Illustration was not generated. "
                    + detail
                    + " A Cursor agent can create the art, or pass --art with one image or six."
                ),
            }
        images.append(winner["image"])
    return {
        "ok": True,
        "images": images,
        "attempts": attempts,
        "provider": attempts[-1]["provider"] if attempts else "",
        "model": attempts[-1]["model"] if attempts else "",
        "error": "",
    }
