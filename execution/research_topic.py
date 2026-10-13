#!/usr/bin/env python3
"""Stage 1: Research a topic into a narrative story (Perplexity or dry-run)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import requests

from utils import has_key, load_env, project_paths, save_json, slugify, utc_stamp

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"


def build_research_prompt(topic: str) -> str:
    return (
        f'Research "{topic}" and provide a compelling, narrative-style story of '
        "approximately 300 words suitable for a short Instagram video script. "
        "Keep it factual where possible, vivid, and easy to narrate aloud."
    )


def research_with_perplexity(topic: str) -> dict[str, Any]:
    api_key = os.getenv("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return {"success": False, "error": "PERPLEXITY_API_KEY is not set"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "sonar",
        "messages": [
            {
                "role": "system",
                "content": "You are a research storyteller for short-form video.",
            },
            {"role": "user", "content": build_research_prompt(topic)},
        ],
    }
    response = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=90)
    if response.status_code != 200:
        return {
            "success": False,
            "error": f"Perplexity API error {response.status_code}: {response.text[:400]}",
        }

    data = response.json()
    story = data["choices"][0]["message"]["content"].strip()
    return {
        "success": True,
        "provider": "perplexity",
        "topic": topic,
        "story": story,
        "raw": data,
    }


def research_dry_run(topic: str) -> dict[str, Any]:
    story = (
        f"{topic} begins as a quiet curiosity and becomes a vivid journey. "
        "Across centuries, people chased the idea, refined it, and shared it with the world. "
        "In this short film we move from origin myth, to breakthrough moment, to everyday impact. "
        "Each scene reveals one clear beat: the spark, the struggle, the discovery, the shift, "
        "and the lasting afterglow. The story stays concrete, visual, and spoken in a natural voice "
        "so viewers can follow every turn in under a minute."
    )
    return {
        "success": True,
        "provider": "dry-run",
        "topic": topic,
        "story": story,
        "raw": None,
    }


def research_topic(topic: str, project_name: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    load_env()
    project = project_name or slugify(topic)
    paths = project_paths(project)

    if dry_run or not has_key("PERPLEXITY_API_KEY"):
        result = research_dry_run(topic)
        if not dry_run and not has_key("PERPLEXITY_API_KEY"):
            result["warning"] = "PERPLEXITY_API_KEY missing; used dry-run research"
    else:
        result = research_with_perplexity(topic)

    if not result.get("success"):
        return result

    output = {
        "topic": topic,
        "project_name": project,
        "provider": result["provider"],
        "story": result["story"],
        "created_at": utc_stamp(),
        "warning": result.get("warning"),
    }
    out_path = paths["research"] / f"research_{utc_stamp()}.json"
    save_json(out_path, output)
    return {**result, "project_name": project, "path": str(out_path), "data": output}


def main() -> int:
    parser = argparse.ArgumentParser(description="Research a topic for Instagram video")
    parser.add_argument("topic", help="Topic to research")
    parser.add_argument("project_name", nargs="?", help="Optional project folder name")
    parser.add_argument("--dry-run", action="store_true", help="Skip live API calls")
    args = parser.parse_args()

    result = research_topic(args.topic, args.project_name, dry_run=args.dry_run)
    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1

    print(f"Topic: {args.topic}")
    print(f"Project: {result['project_name']}")
    print(f"Saved: {result['path']}")
    print()
    print(result["story"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
