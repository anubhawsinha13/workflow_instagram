#!/usr/bin/env python3
"""Build a human-readable preview showing topic + images to generate."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from utils import ARTIFACTS_DIR, project_paths


def build_markdown(topic: str, title: str, images: list[dict[str, Any]], project_name: str) -> str:
    lines = [
        f"# Instagram Preview: {title}",
        "",
        f"**Topic:** {topic}",
        f"**Project:** `{project_name}`",
        f"**Images planned:** {len(images)}",
        "",
        "## Scenes & Images",
        "",
    ]
    for image in images:
        lines.extend(
            [
                f"### Scene {image['scene_number']}: {image.get('overlay_text', '')}",
                "",
                f"- **Keyword:** {image.get('background_keyword', '')}",
                f"- **Status:** {image.get('status', 'planned')}",
                f"- **Provider:** {image.get('provider') or 'n/a'}",
                f"- **File:** `{image.get('local_path', '')}`",
                "",
                "**Image prompt:**",
                "",
                f"> {image.get('image_prompt', '')}",
                "",
                "**Voiceover:**",
                "",
                f"> {image.get('voiceover_content', '')}",
                "",
            ]
        )
        local = image.get("local_path")
        if local and Path(local).exists():
            lines.append(f"![Scene {image['scene_number']}]({local})")
            lines.append("")
    return "\n".join(lines)


def build_html(
    topic: str,
    title: str,
    images: list[dict[str, Any]],
    project_name: str,
    html_path: Path | None = None,
) -> str:
    cards = []
    for image in images:
        local = image.get("local_path") or ""
        media = ""
        if local and Path(local).exists():
            src = Path(local)
            if html_path is not None:
                try:
                    src = Path(os.path.relpath(src, html_path.parent))
                except ValueError:
                    src = Path(local)
            media = f'<img src="{html.escape(src.as_posix())}" alt="Scene {image["scene_number"]}" />'
        cards.append(
            f"""
            <article class="scene">
              <div class="meta">Scene {image['scene_number']}</div>
              <h2>{html.escape(str(image.get('overlay_text', '')))}</h2>
              <p class="keyword">{html.escape(str(image.get('background_keyword', '')))}</p>
              <p class="prompt">{html.escape(str(image.get('image_prompt', '')))}</p>
              <p class="vo"><strong>VO:</strong> {html.escape(str(image.get('voiceover_content', '')))}</p>
              <p class="status">{html.escape(str(image.get('status', 'planned')))} · {html.escape(str(image.get('provider') or 'n/a'))}</p>
              {media}
            </article>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} · Preview</title>
  <style>
    :root {{
      --bg0: #14201b;
      --bg1: #24362d;
      --ink: #f4efe4;
      --muted: #d3c5a8;
      --accent: #d2a85c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Palatino, serif;
      color: var(--ink);
      background:
        radial-gradient(1200px 700px at 10% -10%, #3f5b49 0%, transparent 55%),
        radial-gradient(900px 600px at 100% 0%, #8b6b2f 0%, transparent 45%),
        linear-gradient(160deg, var(--bg0), var(--bg1));
      min-height: 100vh;
    }}
    main {{
      width: min(1100px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 3rem 0 4rem;
    }}
    .hero {{
      margin-bottom: 2rem;
      animation: rise 700ms ease-out both;
    }}
    .brand {{
      letter-spacing: 0.18em;
      text-transform: uppercase;
      font-size: 0.8rem;
      color: var(--accent);
      margin-bottom: 0.75rem;
    }}
    h1 {{
      font-size: clamp(2rem, 5vw, 3.4rem);
      line-height: 1.05;
      margin: 0 0 0.75rem;
      max-width: 14ch;
    }}
    .lede {{
      color: var(--muted);
      font-size: 1.1rem;
      max-width: 42ch;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1.5rem;
    }}
    .scene {{
      padding: 0.25rem 0 1.25rem;
      border-top: 1px solid rgba(244, 239, 228, 0.25);
      animation: rise 800ms ease-out both;
    }}
    .scene:nth-child(2) {{ animation-delay: 80ms; }}
    .scene:nth-child(3) {{ animation-delay: 160ms; }}
    .scene:nth-child(4) {{ animation-delay: 240ms; }}
    .scene:nth-child(5) {{ animation-delay: 320ms; }}
    .meta {{
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.72rem;
      margin-bottom: 0.5rem;
    }}
    .scene h2 {{
      margin: 0 0 0.4rem;
      font-size: 1.45rem;
    }}
    .keyword, .status {{
      color: var(--muted);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      font-size: 0.9rem;
    }}
    .prompt, .vo {{
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      font-size: 0.92rem;
      line-height: 1.45;
      color: #efe6d4;
    }}
    img {{
      width: 100%;
      aspect-ratio: 9 / 16;
      object-fit: cover;
      margin-top: 0.75rem;
      border: 0;
    }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(14px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="brand">Workflow Instagram</div>
      <h1>{html.escape(title)}</h1>
      <p class="lede">Topic: {html.escape(topic)} · Project: {html.escape(project_name)} · {len(images)} images ready for generation</p>
    </section>
    <section class="grid">
      {''.join(cards)}
    </section>
  </main>
</body>
</html>
"""


def write_preview_report(
    topic: str,
    title: str,
    images: list[dict[str, Any]],
    project_name: str,
) -> dict[str, str]:
    paths = project_paths(project_name)
    preview_dir = paths["preview"]
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    md_path = preview_dir / "preview.md"
    html_path = preview_dir / "preview.html"
    artifact_md = ARTIFACTS_DIR / f"{project_name}_preview.md"
    artifact_html = ARTIFACTS_DIR / f"{project_name}_preview.html"

    md = build_markdown(topic, title, images, project_name)
    html_doc = build_html(topic, title, images, project_name, html_path=html_path)
    artifact_html_doc = build_html(topic, title, images, project_name, html_path=artifact_html)

    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html_doc, encoding="utf-8")
    artifact_md.write_text(md, encoding="utf-8")
    artifact_html.write_text(artifact_html_doc, encoding="utf-8")

    return {
        "markdown": str(md_path),
        "html": str(html_path),
        "artifact_markdown": str(artifact_md),
        "artifact_html": str(artifact_html),
    }
