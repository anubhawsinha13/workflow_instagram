#!/usr/bin/env python3
"""Stage 2: Turn research into a 5-scene Instagram script (OpenAI/Gemini/dry-run)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from utils import env_bool, has_key, load_env, load_json, project_paths, save_json, slugify, utc_stamp

SYSTEM_PROMPT = (
    "Act as a video producer. Convert the provided research into a JSON object compatible "
    "with a video automation API. The JSON must contain: "
    '"title" (string), "topic" (string), and "scenes" (array of exactly 5 objects). '
    "Each scene must have: "
    '"scene_number" (1-5), "overlay_text" (max 10 words), '
    '"voiceover_content" (natural conversational narration), '
    '"background_keyword" (2-5 words for stock/AI search), '
    'and "image_prompt" (detailed visual prompt for image generation). '
    "Return ONLY valid JSON."
)


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def validate_script(script: dict[str, Any]) -> bool:
    if not isinstance(script, dict):
        return False
    if "scenes" not in script or "title" not in script:
        return False
    scenes = script["scenes"]
    if not isinstance(scenes, list) or len(scenes) != 5:
        return False
    required = {"overlay_text", "voiceover_content", "background_keyword", "image_prompt"}
    for idx, scene in enumerate(scenes, start=1):
        if not required.issubset(scene.keys()):
            return False
        scene.setdefault("scene_number", idx)
    return True


def script_dry_run(story: str, topic: str) -> dict[str, Any]:
    beats = [
        ("The spark", "origin story beginnings historical scene"),
        ("The struggle", "people working through challenge"),
        ("The breakthrough", "moment of discovery bright light"),
        ("The shift", "idea spreading through everyday life"),
        ("The afterglow", "modern impact cinematic wide shot"),
    ]
    scenes = []
    for i, (overlay, keyword) in enumerate(beats, start=1):
        scenes.append(
            {
                "scene_number": i,
                "overlay_text": overlay,
                "voiceover_content": (
                    f"Scene {i} of {topic}: {story.split('. ')[min(i - 1, len(story.split('. ')) - 1)]}."
                ),
                "background_keyword": keyword,
                "image_prompt": (
                    f"Cinematic vertical Instagram still for '{topic}', scene '{overlay}'. "
                    f"Subject: {keyword}. Soft natural light, shallow depth of field, "
                    "no text, no watermark, photorealistic."
                ),
            }
        )
    return {
        "success": True,
        "provider": "dry-run",
        "script": {
            "title": topic.title(),
            "topic": topic,
            "scenes": scenes,
        },
    }


def generate_script_with_openai(story: str, topic: str) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError:
        return {"success": False, "error": "openai package not installed"}

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Topic: {topic}\n\nStory:\n{story}",
            },
        ],
        temperature=0.7,
    )
    content = response.choices[0].message.content or ""
    script = extract_json(content)
    if not validate_script(script):
        return {"success": False, "error": "OpenAI returned invalid script structure"}
    script["topic"] = topic
    return {"success": True, "provider": "openai", "script": script}


def generate_script_with_gemini(story: str, topic: str) -> dict[str, Any]:
    try:
        import google.generativeai as genai
    except ImportError:
        return {"success": False, "error": "google-generativeai package not installed"}

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY is not set"}

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)
    prompt = f"{SYSTEM_PROMPT}\n\nTopic: {topic}\n\nStory:\n{story}"
    response = model.generate_content(prompt)
    content = getattr(response, "text", None) or ""
    script = extract_json(content)
    if not validate_script(script):
        return {"success": False, "error": "Gemini returned invalid script structure"}
    script["topic"] = topic
    return {"success": True, "provider": "gemini", "script": script}


def generate_script(
    story: str,
    topic: str,
    project_name: str | None = None,
    use_gemini: bool | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    load_env()
    project = project_name or slugify(topic)
    paths = project_paths(project)

    if dry_run:
        result = script_dry_run(story, topic)
    else:
        prefer_gemini = env_bool("USE_GEMINI", True) if use_gemini is None else use_gemini
        order = ["gemini", "openai"] if prefer_gemini else ["openai", "gemini"]
        result = {"success": False, "error": "No script provider available"}
        errors: list[str] = []

        for provider in order:
            if provider == "gemini" and has_key("GEMINI_API_KEY"):
                try:
                    result = generate_script_with_gemini(story, topic)
                except Exception as exc:  # noqa: BLE001
                    result = {"success": False, "error": f"Gemini error: {exc}"}
            elif provider == "openai" and has_key("OPENAI_API_KEY"):
                try:
                    result = generate_script_with_openai(story, topic)
                except Exception as exc:  # noqa: BLE001
                    result = {"success": False, "error": f"OpenAI error: {exc}"}
            else:
                continue

            if result.get("success"):
                break
            errors.append(str(result.get("error")))

        if not result.get("success"):
            if errors:
                result = script_dry_run(story, topic)
                result["warning"] = "Live providers failed; used dry-run script. " + " | ".join(errors)
            else:
                result = script_dry_run(story, topic)
                result["warning"] = "No script API keys found; used dry-run script"

    if not result.get("success"):
        return result

    output = {
        "topic": topic,
        "project_name": project,
        "provider": result["provider"],
        "script": result["script"],
        "created_at": utc_stamp(),
        "warning": result.get("warning"),
    }
    out_path = paths["script"] / f"script_{utc_stamp()}.json"
    save_json(out_path, output)
    return {**result, "project_name": project, "path": str(out_path), "data": output}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Instagram script from research JSON")
    parser.add_argument("research_json", help="Path to research JSON")
    parser.add_argument("topic", nargs="?", help="Topic override")
    parser.add_argument("project_name", nargs="?", help="Project folder name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--use-gemini", action="store_true")
    parser.add_argument("--use-openai", action="store_true")
    args = parser.parse_args()

    research = load_json(args.research_json)
    topic = args.topic or research.get("topic") or "Untitled"
    project = args.project_name or research.get("project_name")
    use_gemini = True if args.use_gemini else False if args.use_openai else None

    result = generate_script(
        story=research["story"],
        topic=topic,
        project_name=project,
        use_gemini=use_gemini,
        dry_run=args.dry_run,
    )
    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1

    print(f"Saved: {result['path']}")
    print(json.dumps(result["script"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
