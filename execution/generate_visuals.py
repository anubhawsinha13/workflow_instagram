#!/usr/bin/env python3
"""Stage 2.5: Plan and optionally generate images for each script scene."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path
from typing import Any

import requests

from utils import has_key, load_env, load_json, project_paths, save_json, utc_stamp


def placeholder_svg(scene_number: int, title: str, keyword: str) -> bytes:
    safe_title = title.replace("&", "&amp;")[:40]
    safe_keyword = keyword.replace("&", "&amp;")[:48]
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1f2a24"/>
      <stop offset="55%" stop-color="#3d5a45"/>
      <stop offset="100%" stop-color="#c4a35a"/>
    </linearGradient>
  </defs>
  <rect width="1080" height="1920" fill="url(#g)"/>
  <circle cx="860" cy="320" r="180" fill="#f2e8cf" fill-opacity="0.18"/>
  <text x="80" y="260" fill="#f7f2e8" font-family="Georgia, serif" font-size="54">Scene {scene_number}</text>
  <text x="80" y="360" fill="#f7f2e8" font-family="Georgia, serif" font-size="72">{safe_title}</text>
  <text x="80" y="470" fill="#e7d7b1" font-family="Helvetica, Arial, sans-serif" font-size="40">{safe_keyword}</text>
</svg>
"""
    return svg.encode("utf-8")


def write_placeholder_image(path: Path, scene_number: int, title: str, keyword: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(placeholder_svg(scene_number, title, keyword))
    return path


def generate_with_openai(prompt: str, out_path: Path) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError:
        return {"success": False, "error": "openai package not installed"}

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.images.generate(
        model=os.getenv("OPENAI_IMAGE_MODEL", "dall-e-3"),
        prompt=prompt,
        size="1024x1792",
        n=1,
    )
    image = response.data[0]
    if getattr(image, "b64_json", None):
        out_path.write_bytes(base64.b64decode(image.b64_json))
        return {"success": True, "provider": "openai", "path": str(out_path), "url": None}
    if getattr(image, "url", None):
        content = requests.get(image.url, timeout=90).content
        out_path.write_bytes(content)
        return {"success": True, "provider": "openai", "path": str(out_path), "url": image.url}
    return {"success": False, "error": "OpenAI image response missing data"}


def generate_with_gemini(prompt: str, out_path: Path) -> dict[str, Any]:
    try:
        import google.generativeai as genai
    except ImportError:
        return {"success": False, "error": "google-generativeai package not installed"}

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY is not set"}

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-exp")
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(
        [
            "Generate a single vertical Instagram image. No text overlays.",
            prompt,
        ]
    )

    # Gemini image APIs vary; fall back if no inline image parts.
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                data = inline.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                out_path.write_bytes(data)
                return {"success": True, "provider": "gemini", "path": str(out_path), "url": None}

    return {"success": False, "error": "Gemini response did not include image bytes"}


def fetch_unsplash(keyword: str, out_path: Path) -> dict[str, Any]:
    key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not key:
        return {"success": False, "error": "UNSPLASH_ACCESS_KEY missing"}
    response = requests.get(
        "https://api.unsplash.com/photos/random",
        params={"query": keyword, "orientation": "portrait"},
        headers={"Authorization": f"Client-ID {key}"},
        timeout=60,
    )
    if response.status_code != 200:
        return {"success": False, "error": f"Unsplash error {response.status_code}"}
    data = response.json()
    url = data["urls"]["regular"]
    out_path.write_bytes(requests.get(url, timeout=60).content)
    return {"success": True, "provider": "unsplash", "path": str(out_path), "url": url}


def plan_and_generate_visuals(
    script_data: dict[str, Any],
    project_name: str | None = None,
    dry_run: bool = False,
    generate_images: bool = True,
) -> dict[str, Any]:
    load_env()
    script = script_data.get("script", script_data)
    topic = script_data.get("topic") or script.get("topic") or "Untitled"
    project = project_name or script_data.get("project_name") or "project"
    paths = project_paths(project)
    visuals_dir = paths["visuals"]

    planned: list[dict[str, Any]] = []
    for scene in script["scenes"]:
        scene_number = int(scene.get("scene_number") or len(planned) + 1)
        image_prompt = scene.get("image_prompt") or (
            f"Vertical cinematic photo for {topic}: {scene.get('background_keyword', '')}"
        )
        filename = f"scene_{scene_number:02d}.svg" if dry_run or not generate_images else f"scene_{scene_number:02d}.png"
        out_path = visuals_dir / filename

        item: dict[str, Any] = {
            "scene_number": scene_number,
            "overlay_text": scene.get("overlay_text", ""),
            "background_keyword": scene.get("background_keyword", ""),
            "image_prompt": image_prompt,
            "voiceover_content": scene.get("voiceover_content", ""),
            "local_path": str(out_path),
            "public_url": None,
            "provider": None,
            "status": "planned",
        }

        if not generate_images:
            planned.append(item)
            continue

        if dry_run or (
            not has_key("OPENAI_API_KEY")
            and not has_key("GEMINI_API_KEY")
            and not has_key("UNSPLASH_ACCESS_KEY")
        ):
            write_placeholder_image(
                out_path.with_suffix(".svg"),
                scene_number,
                scene.get("overlay_text", topic),
                scene.get("background_keyword", "visual"),
            )
            item["local_path"] = str(out_path.with_suffix(".svg"))
            item["provider"] = "placeholder"
            item["status"] = "generated"
            planned.append(item)
            continue

        result: dict[str, Any] = {"success": False}
        if has_key("OPENAI_API_KEY"):
            try:
                result = generate_with_openai(image_prompt, out_path)
            except Exception as exc:  # noqa: BLE001
                result = {"success": False, "error": str(exc)}
        if not result.get("success") and has_key("GEMINI_API_KEY"):
            try:
                result = generate_with_gemini(image_prompt, out_path)
            except Exception as exc:  # noqa: BLE001
                result = {"success": False, "error": str(exc)}
        if not result.get("success") and has_key("UNSPLASH_ACCESS_KEY"):
            result = fetch_unsplash(scene.get("background_keyword", topic), out_path)

        if result.get("success"):
            item["provider"] = result.get("provider")
            item["public_url"] = result.get("url")
            item["local_path"] = result.get("path", str(out_path))
            item["status"] = "generated"
        else:
            write_placeholder_image(
                out_path.with_suffix(".svg"),
                scene_number,
                scene.get("overlay_text", topic),
                scene.get("background_keyword", "visual"),
            )
            item["local_path"] = str(out_path.with_suffix(".svg"))
            item["provider"] = "placeholder"
            item["status"] = "fallback"
            item["error"] = result.get("error")

        planned.append(item)

    output = {
        "topic": topic,
        "project_name": project,
        "title": script.get("title", topic),
        "created_at": utc_stamp(),
        "images": planned,
    }
    out_path = visuals_dir / f"visuals_{utc_stamp()}.json"
    save_json(out_path, output)
    return {"success": True, "project_name": project, "path": str(out_path), "data": output}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan/generate visuals for a script")
    parser.add_argument("script_json", help="Path to script JSON")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Do not write image files")
    args = parser.parse_args()

    script_data = load_json(args.script_json)
    result = plan_and_generate_visuals(
        script_data,
        dry_run=args.dry_run,
        generate_images=not args.plan_only,
    )
    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1

    print(f"Topic: {result['data']['topic']}")
    print(f"Saved: {result['path']}")
    for image in result["data"]["images"]:
        print(
            f"  Scene {image['scene_number']}: {image['overlay_text']} "
            f"| {image['background_keyword']} | {image['status']} | {image['local_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
