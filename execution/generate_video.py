#!/usr/bin/env python3
"""Stage 3: Assemble the final video with Creatomate (+ ElevenLabs via template)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from utils import has_key, load_env, load_json, project_paths, save_json, utc_stamp

CREATOMATE_API_URL = "https://api.creatomate.com/v1"


def build_modifications(script: dict[str, Any], visuals: dict[str, Any] | None) -> dict[str, Any]:
    modifications: dict[str, Any] = {}
    visual_by_scene = {}
    if visuals:
        for item in visuals.get("images", []):
            visual_by_scene[int(item["scene_number"])] = item

    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "")

    for scene in script["scenes"]:
        n = int(scene["scene_number"])
        modifications[f"Primary-Text-{n}"] = scene.get("overlay_text", "")
        modifications[f"Voiceover-{n}"] = scene.get("voiceover_content", "")

        # Preferred Creatomate ElevenLabs settings format
        modifications[f"Voiceover-{n}.source"] = "elevenlabs"
        modifications[f"Voiceover-{n}.settings"] = {
            "text": scene.get("voiceover_content", ""),
            "voice_id": voice_id,
            "api_key": eleven_key,
        }

        visual = visual_by_scene.get(n, {})
        source = visual.get("public_url")
        if not source and visual.get("local_path"):
            # Local files need public hosting in production; keep explicit placeholder.
            keyword = quote(scene.get("background_keyword", "nature"))
            source = f"https://images.unsplash.com/source-404?sig={n}&q={keyword}"
        modifications[f"Background-Media-{n}.source"] = source or f"https://example.com/placeholder/{n}.jpg"

    return modifications


def create_render(modifications: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("CREATOMATE_API_KEY", "").strip()
    template_id = os.getenv("CREATOMATE_TEMPLATE_ID", "").strip()
    if not api_key or not template_id:
        return {"success": False, "error": "CREATOMATE_API_KEY / CREATOMATE_TEMPLATE_ID missing"}

    response = requests.post(
        f"{CREATOMATE_API_URL}/renders",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"template_id": template_id, "modifications": modifications},
        timeout=90,
    )
    if response.status_code not in (200, 201, 202):
        return {"success": False, "error": f"Creatomate error {response.status_code}: {response.text[:400]}"}

    payload = response.json()
    render = payload[0] if isinstance(payload, list) else payload
    return {"success": True, "render": render}


def poll_render(render_id: str, timeout_s: int = 300) -> dict[str, Any]:
    api_key = os.getenv("CREATOMATE_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.time()
    while time.time() - started < timeout_s:
        response = requests.get(f"{CREATOMATE_API_URL}/renders/{render_id}", headers=headers, timeout=60)
        if response.status_code != 200:
            return {"success": False, "error": f"Poll failed: {response.status_code}"}
        data = response.json()
        status = data.get("status")
        if status == "succeeded":
            return {"success": True, "render": data}
        if status in {"failed", "error"}:
            return {"success": False, "error": f"Render failed: {data}"}
        time.sleep(5)
    return {"success": False, "error": "Timed out waiting for Creatomate render"}


def generate_video(
    script_data: dict[str, Any],
    visuals_data: dict[str, Any] | None = None,
    project_name: str | None = None,
    dry_run: bool = False,
    download: bool = True,
) -> dict[str, Any]:
    load_env()
    script = script_data.get("script", script_data)
    topic = script_data.get("topic") or script.get("topic") or "Untitled"
    project = project_name or script_data.get("project_name") or "project"
    paths = project_paths(project)
    modifications = build_modifications(script, visuals_data)

    if dry_run or not (has_key("CREATOMATE_API_KEY") and has_key("CREATOMATE_TEMPLATE_ID")):
        output = {
            "topic": topic,
            "project_name": project,
            "status": "dry-run",
            "modifications": modifications,
            "url": None,
            "created_at": utc_stamp(),
            "warning": None
            if dry_run
            else "Creatomate credentials missing; skipped live render",
        }
        out_path = paths["video"] / f"video_{utc_stamp()}.json"
        save_json(out_path, output)
        return {"success": True, "path": str(out_path), "data": output, "dry_run": True}

    created = create_render(modifications)
    if not created.get("success"):
        return created

    render = created["render"]
    render_id = render.get("id")
    polled = poll_render(render_id) if render_id else {"success": True, "render": render}
    if not polled.get("success"):
        return polled

    final_render = polled["render"]
    url = final_render.get("url")
    local_video = None
    if download and url:
        local_video = paths["video"] / f"final_{utc_stamp()}.mp4"
        local_video.write_bytes(requests.get(url, timeout=180).content)

    output = {
        "topic": topic,
        "project_name": project,
        "status": final_render.get("status", "unknown"),
        "render_id": render_id,
        "url": url,
        "local_path": str(local_video) if local_video else None,
        "modifications": modifications,
        "created_at": utc_stamp(),
    }
    out_path = paths["video"] / f"video_{utc_stamp()}.json"
    save_json(out_path, output)
    return {"success": True, "path": str(out_path), "data": output, "dry_run": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Creatomate video from script")
    parser.add_argument("script_json")
    parser.add_argument("--visuals-json", help="Optional visuals JSON with image URLs/paths")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    script_data = load_json(args.script_json)
    visuals_data = load_json(args.visuals_json) if args.visuals_json else None
    result = generate_video(
        script_data,
        visuals_data=visuals_data,
        dry_run=args.dry_run,
        download=not args.no_download,
    )
    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1
    print(f"Saved: {result['path']}")
    print(f"Status: {result['data'].get('status')}")
    if result["data"].get("url"):
        print(f"URL: {result['data']['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
