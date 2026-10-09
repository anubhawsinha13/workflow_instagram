#!/usr/bin/env python3
"""Build one BrewIQ Instagram carousel package. Posts only when --publish is passed."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(REPO / ".env")
load_dotenv()

from art import generate_illustrations, load_uploaded, scene_prompts  # noqa: E402
from brand import HANDLE, category_style  # noqa: E402
from caption import build_caption, caption_problems  # noqa: E402
from host import load_review, mark_published, upload_jpegs, write_review  # noqa: E402
from image import render_posters  # noqa: E402
from instagram_publish import publish_carousel  # noqa: E402
from history import (  # noqa: E402
    append_history,
    history_note,
    is_repeat,
    load_history,
    next_category,
)
from music import format_music, music_guidance  # noqa: E402
from research import research_live  # noqa: E402
from rights import copyright_problems, prepare_post_copy  # noqa: E402
from research_md import (  # noqa: E402
    load_research_file,
    primary_urls,
    render_research_markdown,
)
from slides import build_slides  # noqa: E402

ZONE = ZoneInfo("America/New_York")
QUESTION = "Perplexity and OpenAI are unavailable. Path to a research markdown file?"


def now_local() -> datetime:
    return datetime.now(ZONE)


def allocate_output() -> Path:
    stamp = now_local()
    day = ROOT / "output" / stamp.strftime("%Y-%m-%d")
    if not day.exists():
        return day
    return ROOT / "output" / stamp.strftime("%Y-%m-%d-%H%M%S")


def image_disclosure(image_status: str) -> str:
    if image_status == "uploaded":
        return (
            "The illustrations were supplied for this post. They are concept illustrations, "
            "not product photos or event photographs. The words were added afterward."
        )
    if image_status and image_status not in {"original_graphic", "ai_generated"}:
        return (
            f"All six slides use concept illustrations from {image_status}, not product photos or event photographs. "
            "The words on the slides were added afterward."
        )
    if image_status == "ai_generated":
        return (
            "Cover image: AI-generated concept illustration, not a product photo or an event photograph. "
            "The other slides are original graphics."
        )
    return "Images are original graphics, not product photos or event photographs. The cover illustration was not model-generated."


def ask_for_research_file() -> Path | None:
    inbox = ROOT / "inbox" / "research.md"
    interactive = sys.stdin.isatty() and os.getenv("BREWIQ_NONINTERACTIVE") != "1"
    if interactive:
        answer = input(QUESTION + " ").strip().strip('"').strip("'")
        if answer:
            return Path(answer).expanduser()
    if inbox.exists():
        return inbox
    return None


def write_not_ready(folder: Path, reason: str, history_available: bool, research_text: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if research_text:
        (folder / "research.md").write_text(research_text, encoding="utf-8")
    checked = history_note(history_available)
    body = "\n".join(
        [
            "# BrewIQ package",
            "",
            "Status: not ready to publish.",
            "",
            "## Topic and category",
            "",
            "No topic was cleared for a post.",
            "",
            "## Finished post image",
            "",
            "Image not generated. Slides were not created because the research gate did not pass.",
            "",
            "## Ready-to-copy caption",
            "",
            "No caption. This package is not ready to publish.",
            "",
            "## Background music",
            "",
            "No music guidance. Exact track not cleared.",
            "",
            "## Evidence and production note",
            "",
            f"Verification date: {now_local().strftime('%Y-%m-%d')} (America/New_York).",
            reason,
            checked,
            "Live research did not produce a publishable package.",
            f"To continue, fill {ROOT / 'research.template.md'} and run:",
            "python brewiq/run.py --research path/to/research.md",
            f"A scheduled run looks for {ROOT / 'inbox' / 'research.md'} and cannot ask a question.",
            "Nothing was posted to Instagram.",
            "",
        ]
    )
    (folder / "package.md").write_text(body, encoding="utf-8")
    (folder / "package.json").write_text(
        json.dumps(
            {
                "ready": False,
                "status": "not_ready",
                "reason": reason,
                "history_checked": history_available,
                "posted_to_instagram": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return folder


def write_package(
    folder: Path,
    research: dict,
    slides_meta: list[dict],
    caption: str,
    music: dict,
    history_available: bool,
    research_text: str,
    image_status: str,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research.md").write_text(research_text, encoding="utf-8")
    (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
    style = category_style(research["category"])
    slide_lines = []
    for slide in slides_meta:
        text = " | ".join(slide["on_image_text"])
        slide_lines.append(
            f"- {slide['filename']} ({slide['width']}×{slide['height']}) role {slide['role']}: {text}"
        )
    if research["source"] == "markdown":
        origin = research.get("origin_path") or "the supplied markdown file"
        source_note = (
            f"Research supplied from markdown ({origin}). "
            "Live Perplexity/OpenAI verification did not run."
        )
    elif research.get("live_verified"):
        source_note = f"Research source: {research['source']}. Claims below are the URLs returned by that call."
    else:
        source_note = "Current facts could not be verified with a live source check."
    product = research.get("product") or "the product you use"
    evidence = "\n".join(
        [
            f"Verification date: {now_local().strftime('%Y-%m-%d')} (America/New_York).",
            source_note,
            history_note(history_available),
            f"Prompt testing: Original suggested prompt; not tested in {product}.",
            "Limitations: " + (research.get("limitations") or "None stated."),
            "Primary sources:",
            "\n".join(f"- {url}" for url in primary_urls(research)),
            (
                "Copyright check: automated only. A logo, screenshot, copied artwork, or long quotation blocks the post. This note is not a legal clearance. "
                "Visuals: original graphics composed for BrewIQ. "
                + (
                    "Cover uses an AI-generated concept illustration, not a product interface or event photograph."
                    if image_status == "ai_generated"
                    else "Cover illustration was not model-generated."
                )
            ),
            "Music rights: Exact track not cleared. No outside audio file is included.",
            "Nothing was posted to Instagram.",
        ]
    )
    timeliness = "timely news" if research.get("timeliness") == "timely" else "evergreen"
    package = "\n".join(
        [
            "# BrewIQ package",
            "",
            "Status: ready to post locally. Not sent to Instagram.",
            "",
            "## Topic and category",
            "",
            f"Topic: {research.get('topic')}",
            f"Category: {style['label']} ({research.get('category')})",
            f"Hook: {research.get('hook')}",
            f"Why it is useful: {research.get('why_it_matters')}",
            f"Timeliness: {timeliness}.",
            "",
            "## Finished post image",
            "",
            "Six-slide carousel, in post order:",
            "\n".join(slide_lines),
            "",
            "## Ready-to-copy caption",
            "",
            "```",
            caption,
            "```",
            "",
            "## Background music",
            "",
            format_music(music),
            "",
            "## Evidence and production note",
            "",
            evidence,
            "",
        ]
    )
    (folder / "package.md").write_text(package, encoding="utf-8")
    payload = {
        "ready": True,
        "topic": research.get("topic"),
        "category": research.get("category"),
        "category_label": style["label"],
        "timeliness": research.get("timeliness"),
        "hook": research.get("hook"),
        "headline": research.get("headline"),
        "keywords": research.get("keywords"),
        "source_urls": primary_urls(research),
        "research_source": research.get("source"),
        "live_verified": research.get("live_verified"),
        "history_checked": history_available,
        "image_status": image_status,
        "caption": caption,
        "caption_characters": len(caption),
        "music": music,
        "slides": slides_meta,
        "posted_to_instagram": False,
        "handle": HANDLE,
    }
    (folder / "package.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_research(topic: str | None, research_path: str | None, category: str, records: list[dict]) -> dict:
    if research_path:
        loaded = load_research_file(Path(research_path).expanduser())
        loaded["via"] = "argument"
        return loaded
    titles = [record.get("title") or "" for record in records]
    live = research_live(topic, category, titles, now_local())
    if live.get("ok"):
        return {"ok": True, "research": live["research"], "text": "", "error": "", "via": "api"}
    fallback = ask_for_research_file()
    if fallback is None:
        detail = " ".join(live.get("errors") or [])
        return {
            "ok": False,
            "error": "Perplexity and OpenAI are unavailable, and no research markdown file was provided. " + detail,
            "research": None,
            "text": "",
            "via": "none",
        }
    loaded = load_research_file(fallback)
    loaded["via"] = "fallback"
    if not loaded.get("ok"):
        loaded["error"] = (loaded.get("error") or "The research file could not be used.") + " API notes: " + " ".join(
            live.get("errors") or []
        )
    return loaded


def publish_saved() -> int:
    review = load_review()
    if not review or not review.get("ready"):
        print(review.get("error") or "No hosted carousel is waiting. Nothing was posted.")
        return 1
    if review.get("published"):
        print(f"Already posted. Media id: {review.get('media_id')}")
        return 0
    result = publish_carousel(review.get("jpeg_urls") or [], review.get("caption") or "")
    if not result.get("ok"):
        print(result.get("error") or "Instagram did not publish the carousel.")
        return 1
    mark_published(result["media_id"])
    print(f"Posted. Media id: {result['media_id']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one BrewIQ Instagram carousel package.")
    parser.add_argument("--topic", default=None, help="Optional topic. Otherwise the next category is chosen.")
    parser.add_argument("--research", default=None, help="Markdown research file. Skips Perplexity and OpenAI.")
    parser.add_argument("--art", default=None, help="One image, or a folder of six. Skips paid image APIs.")
    parser.add_argument("--publish", action="store_true", help="Post the hosted carousel. Requires the exact approval path.")
    args = parser.parse_args()

    if args.publish and not args.topic and not args.research and not args.art:
        return publish_saved()

    records, history_available = load_history(ROOT)
    category = next_category(records, history_available)
    resolved = resolve_research(args.topic, args.research, category, records)
    folder = allocate_output()
    folder.mkdir(parents=True, exist_ok=True)

    if not resolved.get("ok"):
        text = resolved.get("text") or ""
        write_not_ready(folder, resolved.get("error") or "Research did not pass.", history_available, text)
        print(f"Package: {folder}")
        print("Ready: no")
        print(resolved.get("error"))
        return 1

    research = resolved["research"]
    if args.topic and not research.get("topic"):
        research["topic"] = args.topic
    explicit_file = bool(args.research)
    if history_available and not explicit_file and is_repeat(research.get("headline") or research.get("topic") or "", research.get("keywords") or [], records):
        write_not_ready(
            folder,
            "This topic repeats a recent history entry, so no carousel was made.",
            history_available,
            resolved.get("text") or render_research_markdown(research),
        )
        print(f"Package: {folder}")
        print("Ready: no")
        return 1

    if not primary_urls(research):
        write_not_ready(
            folder,
            "No primary source URL was available, so the package is not ready to publish.",
            history_available,
            resolved.get("text") or "",
        )
        print(f"Package: {folder}")
        print("Ready: no")
        return 1

    research = prepare_post_copy(research)
    research_text = resolved.get("text") or render_research_markdown(research)
    blocked = copyright_problems(research)
    if blocked:
        write_not_ready(folder, " ".join(blocked), history_available, research_text)
        print(f"Package: {folder}")
        print("Ready: no")
        print(" ".join(blocked))
        return 1
    slides = build_slides(research)
    if args.art:
        try:
            arts = load_uploaded(Path(args.art))
        except (FileNotFoundError, ValueError, OSError) as exc:
            write_not_ready(folder, str(exc), history_available, research_text)
            print(f"Package: {folder}")
            print("Ready: no")
            print(exc)
            return 1
        provider_label = "uploaded"
        rendered = render_posters(slides, research, folder, arts, provider_label)
    else:
        generated = generate_illustrations(scene_prompts(slides, research))
        (folder / "image_attempts.txt").write_text(
            "\n".join(
                f"{item['provider']} {item['model']}: {'skipped' if item['skipped'] else 'called'} {item['error']}".strip()
                for item in generated.get("attempts") or []
            ),
            encoding="utf-8",
        )
        if not generated.get("ok"):
            write_not_ready(folder, generated.get("error") or "Illustration was not generated.", history_available, research_text)
            print(f"Package: {folder}")
            print("Ready: no")
            print(generated.get("error"))
            return 1
        provider_label = generated.get("model") or generated.get("provider") or "ai_generated"
        rendered = render_posters(slides, research, folder, generated["images"], provider_label)
    if not rendered.get("ok"):
        note = rendered.get("error") or "Image not generated"
        package = (folder / "package.md").read_text(encoding="utf-8") if (folder / "package.md").exists() else ""
        extra = "\n".join(
            [
                "# BrewIQ package",
                "",
                "Status: not ready to publish.",
                "",
                "## Topic and category",
                "",
                f"Topic: {research.get('topic')}",
                "",
                "## Finished post image",
                "",
                "Image not generated.",
                note,
                f"Fallback prompt: {rendered.get('prompt_path', folder / 'image_prompt.txt')}",
                "",
                "## Ready-to-copy caption",
                "",
                "No caption. This package is not a finished carousel.",
                "",
                "## Background music",
                "",
                "Exact track not cleared.",
                "",
                "## Evidence and production note",
                "",
                "The slide set was omitted because a finished carousel needs all six images.",
                "Nothing was posted to Instagram.",
                "",
            ]
        )
        (folder / "package.md").write_text(extra if not package else package + "\n" + extra, encoding="utf-8")
        if research_text and not (folder / "research.md").exists():
            (folder / "research.md").write_text(research_text, encoding="utf-8")
        print(f"Package: {folder}")
        print("Ready: no")
        print("Image not generated")
        return 1

    caption = build_caption(research, image_disclosure(rendered["image_status"]))
    problems = caption_problems(caption) + copyright_problems(research, [caption])
    if problems:
        write_not_ready(folder, " ".join(problems), history_available, research_text)
        print(f"Package: {folder}")
        print("Ready: no")
        return 1

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
    print(f"Package: {folder}")
    print("Ready: yes")
    for slide in rendered["slides"]:
        print(f"  {slide['filename']} {slide['width']}x{slide['height']}")
    print(f"Caption characters: {len(caption)}")
    print(f"Image: {rendered['image_status']}")

    hosted = upload_jpegs(folder, folder.name)
    write_review(
        folder,
        caption,
        hosted.get("urls") or [],
        rendered["image_status"],
        bool(hosted.get("ok")),
        hosted.get("error") or "",
    )
    if not hosted.get("ok"):
        print(hosted.get("error"))
        print("Nothing was posted.")
        return 1 if args.publish else 0
    for url in hosted["urls"]:
        print(url)
    if not args.publish:
        print('Nothing was posted. Reply exactly "post it" when you want it on Instagram.')
        return 0
    return publish_saved()


if __name__ == "__main__":
    raise SystemExit(main())
