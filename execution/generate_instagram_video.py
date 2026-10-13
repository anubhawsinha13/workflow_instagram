#!/usr/bin/env python3
"""Run the full Instagram video workflow end-to-end."""

from __future__ import annotations

import argparse
import sys

from generate_script import generate_script
from generate_video import generate_video
from generate_visuals import plan_and_generate_visuals
from preview_report import write_preview_report
from research_topic import research_topic
from utils import load_env, slugify


def run_full_workflow(
    topic: str,
    project_name: str | None = None,
    dry_run: bool = False,
    no_download: bool = False,
    skip_video: bool = False,
) -> dict:
    load_env()
    project = project_name or slugify(topic)

    research = research_topic(topic, project_name=project, dry_run=dry_run)
    if not research.get("success"):
        return research

    script = generate_script(
        story=research["story"],
        topic=topic,
        project_name=project,
        dry_run=dry_run,
    )
    if not script.get("success"):
        return script

    visuals = plan_and_generate_visuals(
        script["data"],
        project_name=project,
        dry_run=dry_run,
        generate_images=True,
    )
    if not visuals.get("success"):
        return visuals

    preview = write_preview_report(
        topic=visuals["data"]["topic"],
        title=visuals["data"]["title"],
        images=visuals["data"]["images"],
        project_name=project,
    )

    video = None
    if not skip_video:
        video = generate_video(
            script["data"],
            visuals_data=visuals["data"],
            project_name=project,
            dry_run=dry_run,
            download=not no_download,
        )
        if not video.get("success"):
            return video

    return {
        "success": True,
        "topic": topic,
        "project_name": project,
        "research_path": research.get("path"),
        "script_path": script.get("path"),
        "visuals_path": visuals.get("path"),
        "preview": preview,
        "video_path": None if video is None else video.get("path"),
        "video": None if video is None else video.get("data"),
        "images": visuals["data"]["images"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a full Instagram video from a topic")
    parser.add_argument("topic", help='Topic, e.g. "The history of coffee"')
    parser.add_argument("--project-name", help="Optional project folder name")
    parser.add_argument("--dry-run", action="store_true", help="Skip live API calls")
    parser.add_argument("--no-download", action="store_true", help="Do not download final video")
    parser.add_argument("--skip-video", action="store_true", help="Stop after topic/image preview")
    args = parser.parse_args()

    result = run_full_workflow(
        topic=args.topic,
        project_name=args.project_name,
        dry_run=args.dry_run,
        no_download=args.no_download,
        skip_video=args.skip_video,
    )
    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1

    print(f"Topic: {result['topic']}")
    print(f"Project: {result['project_name']}")
    print(f"Preview: {result['preview']['markdown']}")
    if result.get("video_path"):
        print(f"Video metadata: {result['video_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
