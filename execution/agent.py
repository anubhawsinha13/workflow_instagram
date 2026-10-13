#!/usr/bin/env python3
"""
Instagram workflow agent.

Triggers the research → script → visuals pipeline, then prints the topic and
the images that will be / were generated. Optionally continues to video render.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from generate_instagram_video import run_full_workflow
from utils import ARTIFACTS_DIR, ROOT, load_env, save_json, slugify

DEFAULT_TOPICS = [
    "The history of coffee",
    "How coral reefs protect coastlines",
    "The invention of the shipping container",
]


def pick_topic(topic: str | None, rotate: bool) -> str:
    if topic:
        return topic.strip()
    if not rotate:
        return DEFAULT_TOPICS[0]

    state_path = ARTIFACTS_DIR / "agent_topic_state.json"
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    index = 0
    if state_path.exists():
        try:
            index = int(json.loads(state_path.read_text(encoding="utf-8")).get("index", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            index = 0
    topic = DEFAULT_TOPICS[index % len(DEFAULT_TOPICS)]
    save_json(
        state_path,
        {
            "index": (index + 1) % len(DEFAULT_TOPICS),
            "last_topic": topic,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return topic


def print_topic_and_images(result: dict) -> None:
    print("=" * 72)
    print("INSTAGRAM WORKFLOW AGENT")
    print("=" * 72)
    print(f"Topic:   {result['topic']}")
    print(f"Project: {result['project_name']}")
    print(f"Preview: {result['preview']['html']}")
    print("-" * 72)
    print("Images to generate / generated:")
    for image in result.get("images", []):
        print(
            f"  [{image['scene_number']}] {image.get('overlay_text', '')}\n"
            f"      keyword : {image.get('background_keyword', '')}\n"
            f"      status  : {image.get('status', 'planned')} ({image.get('provider') or 'n/a'})\n"
            f"      file    : {image.get('local_path', '')}\n"
            f"      prompt  : {image.get('image_prompt', '')}"
        )
    print("-" * 72)
    if result.get("video"):
        print(f"Video status: {result['video'].get('status')}")
        if result["video"].get("url"):
            print(f"Video URL:    {result['video']['url']}")
        if result["video"].get("local_path"):
            print(f"Video file:   {result['video']['local_path']}")
    else:
        print("Video stage: skipped (preview-only mode)")
    print("=" * 72)


def run_agent(
    topic: str | None = None,
    project_name: str | None = None,
    dry_run: bool = False,
    render_video: bool = False,
    rotate_topic: bool = False,
) -> dict:
    load_env()
    chosen = pick_topic(topic, rotate=rotate_topic)
    project = project_name or slugify(chosen)

    result = run_full_workflow(
        topic=chosen,
        project_name=project,
        dry_run=dry_run,
        skip_video=not render_video,
    )
    if not result.get("success"):
        return result

    summary = {
        "topic": result["topic"],
        "project_name": result["project_name"],
        "images": [
            {
                "scene_number": img["scene_number"],
                "overlay_text": img.get("overlay_text"),
                "background_keyword": img.get("background_keyword"),
                "image_prompt": img.get("image_prompt"),
                "status": img.get("status"),
                "provider": img.get("provider"),
                "local_path": img.get("local_path"),
            }
            for img in result.get("images", [])
        ],
        "preview": result["preview"],
        "research_path": result.get("research_path"),
        "script_path": result.get("script_path"),
        "visuals_path": result.get("visuals_path"),
        "video_path": result.get("video_path"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = ARTIFACTS_DIR / f"{project}_agent_summary.json"
    save_json(summary_path, summary)
    result["summary_path"] = str(summary_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Agent that triggers the Instagram workflow and shows topic + images"
    )
    parser.add_argument("topic", nargs="?", help="Topic to generate. If omitted, uses a default.")
    parser.add_argument("--project-name", help="Optional project folder name")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use offline stubs when APIs are unavailable (also auto-enabled without keys)",
    )
    parser.add_argument(
        "--render-video",
        action="store_true",
        help="Continue through Creatomate video rendering after preview",
    )
    parser.add_argument(
        "--rotate-topic",
        action="store_true",
        help="When no topic is given, rotate through built-in defaults",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary instead of pretty text",
    )
    args = parser.parse_args()

    # Default to dry-run friendly behavior when .env is missing.
    dry_run = args.dry_run or not (ROOT / ".env").exists()

    result = run_agent(
        topic=args.topic,
        project_name=args.project_name,
        dry_run=dry_run,
        render_video=args.render_video,
        rotate_topic=args.rotate_topic,
    )
    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "topic": result["topic"],
            "project_name": result["project_name"],
            "images": result.get("images"),
            "preview": result.get("preview"),
            "summary_path": result.get("summary_path"),
            "video": result.get("video"),
        }
        print(json.dumps(payload, indent=2))
    else:
        print_topic_and_images(result)
        print(f"Summary JSON: {result.get('summary_path')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
