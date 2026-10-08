#!/usr/bin/env python3
"""Build one BrewIQ carousel for Slack. This script never publishes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["BREWIQ_NONINTERACTIVE"] = "1"

from art import generate_illustrations, openai_character_image, openai_edit_image, scene_prompts  # noqa: E402
from character import character_reference, with_character, with_scene  # noqa: E402
from caption import build_caption, caption_problems  # noqa: E402
from host import to_jpeg, upload_jpegs, write_review  # noqa: E402
from image import render_posters  # noqa: E402
from history import append_history, is_repeat, load_history, next_category  # noqa: E402
from music import music_guidance  # noqa: E402
from research_md import primary_urls, render_research_markdown  # noqa: E402
from run import (  # noqa: E402
    allocate_output,
    image_disclosure,
    now_local,
    resolve_research,
    write_not_ready,
    write_package,
)
from reel import render_reel  # noqa: E402
from rights import copyright_problems  # noqa: E402
from single_image import _host_file, _host_public  # noqa: E402
from slides import build_slides  # noqa: E402


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0 if payload.get("ok") else 1


def _host_slides(folder: Path) -> dict:
    hosted = upload_jpegs(folder, folder.name)
    if hosted.get("ok") and hosted.get("urls"):
        return {"ok": True, "urls": hosted["urls"], "host": "gcs", "error": ""}
    urls = []
    for png in sorted(folder.glob("slide-*.png")):
        jpeg = png.with_suffix(".jpg")
        to_jpeg(png, jpeg)
        result = _host_public(jpeg)
        if not result.get("ok") or not result.get("url"):
            return {
                "ok": False,
                "urls": [],
                "host": "public",
                "error": result.get("error") or "A slide could not be hosted.",
            }
        urls.append(result["url"])
    if len(urls) < 2:
        return {
            "ok": False,
            "urls": urls,
            "host": "public",
            "error": "The carousel needs at least two hosted slides.",
        }
    return {"ok": True, "urls": urls, "host": "public", "error": ""}


def build_slack_draft(topic: str, post_format: str = "slides", reference_path: str = "") -> dict:
    records, history_available = load_history(ROOT)
    category = next_category(records, history_available)
    resolved = resolve_research(topic, None, category, records)
    folder = allocate_output()
    folder.mkdir(parents=True, exist_ok=True)
    if not resolved.get("ok"):
        reason = resolved.get("error") or "Research did not pass."
        write_not_ready(folder, reason, history_available, resolved.get("text") or "")
        return {"ok": False, "error": reason}

    research = resolved["research"]
    research["topic"] = topic or research.get("topic")
    if history_available and is_repeat(
        research.get("headline") or research.get("topic") or "",
        research.get("keywords") or [],
        records,
    ):
        reason = "This topic repeats a recent history entry, so no carousel was made."
        write_not_ready(folder, reason, history_available, resolved.get("text") or "")
        return {"ok": False, "error": reason}
    if not primary_urls(research):
        reason = "No primary source URL was available, so the package is not ready to publish."
        write_not_ready(folder, reason, history_available, resolved.get("text") or "")
        return {"ok": False, "error": reason}

    research_text = resolved.get("text") or render_research_markdown(research)
    blocked = copyright_problems(research)
    if blocked:
        reason = " ".join(blocked)
        write_not_ready(folder, reason, history_available, research_text)
        return {"ok": False, "error": reason}
    slides = build_slides(research)
    prompts = scene_prompts(slides, research)
    callers = None
    attached = Path(reference_path).expanduser() if reference_path else None
    if post_format == "reel" and attached is not None and attached.is_file():
        prompts = with_scene(prompts)
        callers = [lambda prompt, image=attached: openai_edit_image(image, prompt)]
    elif post_format == "reel" and character_reference() is not None:
        prompts = with_character(prompts)
        callers = [openai_character_image]
    generated = generate_illustrations(prompts, callers=callers)
    if not generated.get("ok"):
        reason = generated.get("error") or "Illustration was not generated."
        write_not_ready(folder, reason, history_available, research_text)
        return {"ok": False, "error": reason}

    provider = generated.get("model") or generated.get("provider") or "ai_generated"
    rendered = render_posters(slides, research, folder, generated["images"], provider)
    if not rendered.get("ok"):
        reason = rendered.get("error") or "Image not generated."
        write_not_ready(folder, reason, history_available, research_text)
        return {"ok": False, "error": reason}

    caption = build_caption(research, image_disclosure(rendered["image_status"]))
    problems = caption_problems(caption) + copyright_problems(research, [caption])
    if problems:
        reason = " ".join(problems)
        write_not_ready(folder, reason, history_available, research_text)
        return {"ok": False, "error": reason}

    music = music_guidance(research["category"])
    write_package(
        folder,
        research,
        rendered["slides"],
        caption,
        music,
        history_available,
        research_text,
        rendered["image_status"],
    )
    append_history(
        ROOT,
        {
            "date": now_local().strftime("%Y-%m-%d"),
            "category": research["category"],
            "title": research.get("headline") or research.get("topic"),
            "keywords": research.get("keywords") or [],
            "source_urls": primary_urls(research),
            "carousel_status": "ready",
            "output": str(folder),
        },
    )
    if post_format == "reel":
        video = render_reel(folder)
        if not video.get("ok"):
            return {"ok": False, "error": video.get("error") or "The reel could not be assembled."}
        hosted_file = _host_file(Path(video["path"]), "brewiq-reel.mp4", "video/mp4")
        hosted = {
            "ok": bool(hosted_file.get("ok")),
            "urls": [hosted_file["url"]] if hosted_file.get("url") else [],
            "host": "public",
            "error": hosted_file.get("error") or "",
        }
    else:
        hosted = _host_slides(folder)
    write_review(
        folder,
        caption,
        hosted.get("urls") or [],
        rendered["image_status"],
        bool(hosted.get("ok")),
        hosted.get("error") or "",
    )
    if not hosted.get("ok"):
        return {"ok": False, "error": hosted.get("error") or "The slides could not be hosted."}
    return {
        "ok": True,
        "caption": caption,
        "comment": "Follow @_brewiq.",
        "format": "reel" if post_format == "reel" else "slides",
        "media_urls": hosted["urls"],
        "music_query": music.get("search_terms") or "",
        "provider": provider,
        "host": hosted.get("host") or "",
        "error": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a BrewIQ carousel draft without posting")
    parser.add_argument("topic")
    parser.add_argument("--format", choices=("slides", "reel"), default="slides")
    parser.add_argument("--reference", default="")
    args = parser.parse_args()
    topic = args.topic.strip()
    if not topic:
        return _emit({"ok": False, "error": "Topic is required."})
    return _emit(build_slack_draft(topic, args.format, args.reference))


if __name__ == "__main__":
    raise SystemExit(main())
