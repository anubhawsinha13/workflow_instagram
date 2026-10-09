"""Art-direct each carousel slide before the image model draws it."""

from __future__ import annotations

import json
import os

from pathlib import Path

from art import default_callers, generate_illustrations, openai_character_image, openai_image, scene_prompts
from brand import CYAN, GOLD, category_style
from character import CLAUSE, character_reference
from rights import original_scene_clause

ACCENTS = {"gold": GOLD, "cyan": CYAN}

ART_DIRECTION = """# BREWIQ IMAGE ART DIRECTION

For each slide, create a cinematic 3D editorial illustration that explains the idea through recognizable objects and visual action.

## Visual style
- Deep charcoal background (#10141C).
- Rich, realistic materials: paper, glass, brushed metal and folders.
- Dramatic lighting, soft shadows and subtle reflections.
- Strong foreground, middle-ground and background depth.
- Luminous connections and restrained particles where meaningful.
- Gold (#FFC76A) for practical workflows.
- Cyan (#35D5F4) for news, architecture and integration.
- Use one accent color per image, and the same accent across the whole carousel.

## Composition
Choose one dominant visual metaphor specific to the topic. Make the main subject large and immediately understandable. Use no more than three supporting groups of objects.

Examples:
- Document retrieval: a spotlight selecting a page from an archive.
- Integration: recognizable application objects exchanging data packets.
- A queue: requests waiting while workers process them.
- Agent memory: recent notes and a persistent archive.
- Verification: an answer connected to a highlighted source passage.
- Messy notes to actions: scattered paper pages streaming into one clean checklist card.

These are conceptual illustrations, not literal product interfaces or exact architecture diagrams.

Avoid generic glowing brains, random robots, meaningless circuitry and repeated laptop imagery. Do not turn every idea into text cards.

Every image is one continuous scene from one camera: no panels, split screens, step sequences or diagrams. Objects stay objects: no faces, limbs or personified props. Show labels and tags as blank shapes or color, never as words.

Each slide shows a different beat of the same story: the cover states the idea, then the why, the mechanism, the practical step, the limit, and a resolved close. Vary the camera and the arrangement so no two slides look alike, while keeping materials and lighting consistent.

## Character
CHARACTER_AVAILABLE tells you whether the BrewIQ character reference exists. When it does and a slide benefits from it, set use_character true for that slide and give him a purposeful role: sorting, inspecting, connecting, carrying or selecting objects, integrated into the scene's lighting and perspective. He is the person in the scene; describe him only by his action, pose and placement, never by appearance. Good fits are the mechanism and the practical step. Use him on at most two slides. Never add him as decoration.

## Post covers (4:5)
- Reserve the lower third as a dark, empty area for a short bold white headline that is added later.
- Keep the top-right corner clear for a small BrewIQ wordmark that is added later.
- Generous margins. Keep essential objects away from the extreme edges.
- The image itself contains no words, letters, numbers, logos, watermarks or readable interface text. Abstract lines on paper are fine.

## Accuracy
Never use decorative imagery as evidence of a product capability. Never depict a real company's logo or product. Use only the verified facts given.

## Output
Return only JSON:
{
  "accent": "gold or cyan",
  "accent_reason": "One short sentence",
  "images": [
    {
      "number": 1,
      "message": "The one idea this image communicates",
      "scene": "Subject + action + setting + composition + materials + lighting",
      "prompt": "A complete standalone image-generation prompt for this slide",
      "exclusions": "What must not appear",
      "use_character": false,
      "character_action": "When use_character is true: what he is doing with the scene's objects, e.g. pulling one glowing page from a falling stack"
    }
  ],
  "quality_check": "One sentence on relevance, clutter, lighting, consistency and cropping"
}
Return exactly one entry per slide, in order.
"""

PROMPT_SUFFIX = (
    " Cinematic 3D editorial illustration, 4:5 portrait. Deep charcoal #10141C background, {accent_name} {accent_hex} "
    "as the only accent light. Realistic paper, glass and brushed metal, dramatic light, soft shadows, subtle "
    "reflections, clear foreground, middle ground and background. The lower third stays dark and empty for a "
    "headline added later, and the top-right corner stays clear. One continuous scene, no panels. No words, letters "
    "or numbers anywhere in the image. {rights} Exclusions: {exclusions}."
)


def _facts(research: dict) -> str:
    lines = []
    for key in ("hook", "why_it_matters", "point", "try_it", "limitations", "takeaway", "availability"):
        value = (research.get(key) or "").strip()
        if value:
            lines.append(f"- {key}: {value}")
    for claim in research.get("claims") or []:
        text = (claim.get("text") or "").strip()
        if text:
            lines.append(f"- claim: {text}")
    return "\n".join(lines) or "- No extra facts."


def director_input(slides: list[dict], research: dict, character_available: bool) -> str:
    default = "gold" if category_style(research["category"])["accent"] == GOLD else "cyan"
    slide_lines = [
        f"{slide['number']}. {slide['role']}: headline \"{slide['headline']}\""
        + (f"; body: {' '.join(slide.get('body') or [])}" if slide.get("body") else "")
        for slide in slides
    ]
    return "\n".join(
        [
            f"TOPIC: {research.get('topic') or research.get('headline') or ''}",
            f"MAIN MESSAGE: {research.get('headline') or ''}",
            f"CATEGORY: {research['category']} (default accent {default})",
            f"VISUAL SEED: {research.get('visual_idea') or 'none'}",
            "VERIFIED FACTS:",
            _facts(research),
            "OUTPUT FORMAT: 4:5 post carousel",
            f"CHARACTER_AVAILABLE: {'yes' if character_available else 'no'}",
            "SLIDES:",
            *slide_lines,
        ]
    )


def parse_direction(raw: str, slides: list[dict], research: dict, character_available: bool) -> dict:
    data = json.loads(raw)
    images = data.get("images")
    if not isinstance(images, list) or len(images) != len(slides):
        raise ValueError("The art direction needs one image per slide.")
    accent = str(data.get("accent") or "").strip().lower()
    if accent not in ACCENTS:
        accent = "gold" if category_style(research["category"])["accent"] == GOLD else "cyan"
    directed = []
    characters = 0
    for slide, item in zip(slides, images):
        prompt = " ".join(str(item.get("prompt") or "").split())
        if len(prompt) < 40:
            raise ValueError(f"Slide {slide['number']} has no usable image prompt.")
        action = " ".join(str(item.get("character_action") or "").split()).rstrip(".")
        use_character = (
            bool(item.get("use_character")) and character_available and characters < 2 and len(action.split()) >= 3
        )
        characters += int(use_character)
        if use_character:
            prompt = (
                f"The man from the reference is {action}, absorbed in the task with his eyes on the objects, "
                "never looking at the camera, shown at mid-distance as part of the scene. " + prompt
            )
        exclusions = " ".join(str(item.get("exclusions") or "").split()) or (
            "words, letters, numbers, logos, watermarks, readable interfaces, glowing brains, robots, laptops"
        )
        directed.append(
            {
                "number": slide["number"],
                "message": " ".join(str(item.get("message") or "").split()),
                "scene": " ".join(str(item.get("scene") or "").split()),
                "prompt": prompt
                + PROMPT_SUFFIX.format(
                    accent_name=accent,
                    accent_hex=ACCENTS[accent],
                    rights=original_scene_clause(),
                    exclusions=exclusions,
                ),
                "exclusions": exclusions,
                "use_character": use_character,
                "character_action": action if use_character else "",
            }
        )
    return {
        "ok": True,
        "accent": accent,
        "accent_hex": ACCENTS[accent],
        "accent_reason": " ".join(str(data.get("accent_reason") or "").split()),
        "quality_check": " ".join(str(data.get("quality_check") or "").split()),
        "images": directed,
        "error": "",
    }


def _complete(system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(timeout=120)
    response = client.chat.completions.create(
        model=os.getenv("BREWIQ_ART_DIRECTOR_MODEL") or "gpt-4o",
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return response.choices[0].message.content or ""


def direct_slides(slides: list[dict], research: dict, character_available: bool = False, complete=None) -> dict:
    """Return per-slide art direction, or the plain scene prompts when the director is unavailable."""
    user = director_input(slides, research, character_available)
    errors = []
    if complete is None and not (os.getenv("OPENAI_API_KEY") or "").strip():
        errors.append("OPENAI_API_KEY is not set.")
    else:
        for attempt in range(2):
            try:
                note = "" if attempt == 0 else f"\n\nYour previous answer was rejected: {errors[-1]} Fix it."
                return parse_direction((complete or _complete)(ART_DIRECTION, user + note), slides, research,
                                       character_available)
            except Exception as exc:
                errors.append(" ".join(str(exc).split())[:200])
    accent = "gold" if category_style(research["category"])["accent"] == GOLD else "cyan"
    return {
        "ok": False,
        "accent": accent,
        "accent_hex": ACCENTS[accent],
        "accent_reason": "",
        "quality_check": "",
        "images": [
            {"number": slide["number"], "message": "", "scene": "", "prompt": prompt, "exclusions": "",
             "use_character": False, "character_action": ""}
            for slide, prompt in zip(slides, scene_prompts(slides, research))
        ],
        "error": "The art director was unavailable, so plain scene prompts were used. " + " | ".join(errors),
    }


def directed_illustrations(slides: list[dict], research: dict, folder: Path, complete=None, callers=None) -> tuple[dict, dict]:
    """Art-direct, save the direction beside the package, then generate one image per slide."""
    direction = direct_slides(slides, research, character_reference() is not None, complete=complete)
    prompts = []
    with_host = set()
    for item in direction["images"]:
        prompt = f"{CLAUSE}{item['prompt']}" if item["use_character"] else item["prompt"]
        if item["use_character"]:
            with_host.add(prompt)
        prompts.append(prompt)
    (folder / "art-direction.json").write_text(json.dumps(direction, indent=2), encoding="utf-8")

    def openai_directed(prompt: str) -> dict:
        return openai_character_image(prompt) if prompt in with_host else openai_image(prompt)

    if callers is None:
        callers = [openai_directed if caller is openai_image else caller for caller in default_callers()]
    return generate_illustrations(prompts, callers=callers), direction
