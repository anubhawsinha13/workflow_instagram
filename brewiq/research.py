"""Live research through Perplexity, then one OpenAI browse attempt."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

from research_md import primary_urls, research_from_fields

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _usable_key(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or "your_" in value.lower() or value.endswith("_here") or len(value) < 12:
        return ""
    return value


def extract_json(text: str) -> dict:
    cleaned = _JSON_FENCE.sub("", (text or "").strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("The model did not return JSON.")
    return json.loads(cleaned[start : end + 1])


def _prompt(topic: str | None, category: str, history_titles: list[str], today: str) -> str:
    avoided = "\n".join(f"- {title}" for title in history_titles) or "- None yet"
    topic_line = (
        f"Research this topic only: {topic}"
        if topic
        else f"Choose one fresh topic in the category {category}."
    )
    return f"""You are the researcher for BrewIQ, an Instagram page about AI for curious nontechnical adults.

Today is {today} in America/New_York.
Preferred category: {category}
{topic_line}

Do not repeat these earlier topics:
{avoided}

Rules:
- Use accessible primary sources only: official documentation, original announcements, research papers, or public datasets. A social post is not sufficient evidence.
- Distinguish the publication date from the event date. Do not call an older story breaking or just released.
- Verify availability, rollout limits, and free versus paid access before mentioning them. If you cannot verify a detail, omit it.
- For research claims, note authorship, date, and a limitation. Do not turn correlation into causation.
- Do not invent sources, test results, or permissions. Do not invent numbers.
- If you cannot find a primary URL, return an empty claims array.
- Write for a clear, practical voice. No jargon, no guaranteed outcomes, no engagement bait.
- Paraphrase the source. Do not paste a sentence from the source, and do not put a quotation longer than a few words in any field.
- Headline under 8 words. Prefer a punchy data-led cover line when a verified number, dollar amount, percent, headcount, or date is central, for example "10,000 engineers to deploy AI". Otherwise a clear plain-language claim.
- stat is an optional cyan accent line under the cover headline, under 6 words, only when a second verified figure or commitment appears in the source, for example "$100M training commitment". Leave it empty if there is no second verified figure.
- why_title, point_title, try_title, and limit_title are short poster titles under 5 words each. Make them specific to this story, not generic labels like "Why it matters".
- Hook under 25 words. Why it matters under 40 words. The point under 45 words. Try it under 70 words. Limitations under 40 words. Takeaway under 16 words.
- visual_idea is one original cinematic scene for the carousel: dark premium setting, dramatic cyan or cool light, a clear subject or metaphor the viewer can read in one glance, and a dark empty lower third for type. No words, letters, numbers, logos, screenshots, celebrities, copyrighted characters, or copies of an existing photo or artwork. Prefer people from behind or in silhouette when people appear. Invent abstract tech metaphors such as glowing networks, glass tables, floating modules, or light paths, never branded products.

Return only JSON:
{{
  "topic": "",
  "category": "{category}",
  "timeliness": "timely or evergreen",
  "headline": "",
  "stat": "",
  "hook": "",
  "why_title": "",
  "why_it_matters": "",
  "point_title": "",
  "point": "",
  "try_title": "",
  "event_date": "",
  "publication_date": "",
  "claims": [
    {{
      "text": "",
      "source_url": "https://...",
      "source_title": "",
      "published": "",
      "event_date": ""
    }}
  ],
  "availability": "",
  "limitations": "",
  "limit_title": "",
  "try_it": "",
  "product": "",
  "takeaway": "",
  "visual_idea": "",
  "keywords": ["", ""]
}}
"""


def _perplexity(prompt: str) -> dict:
    key = _usable_key("PERPLEXITY_API_KEY")
    if not key:
        return {"ok": False, "error": "PERPLEXITY_API_KEY is not set."}
    try:
        from perplexity import Perplexity
    except ImportError as exc:
        return {"ok": False, "error": f"Perplexity client is not installed: {exc}"}
    try:
        client = Perplexity(api_key=key)
        response = client.chat.completions.create(
            model="sonar",
            messages=[
                {
                    "role": "system",
                    "content": "You return only JSON backed by primary sources. Never invent a URL.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        parsed = research_from_fields(extract_json(content), source="perplexity", live_verified=True)
        if not primary_urls(parsed):
            return {"ok": False, "error": "Perplexity returned no primary source URL."}
        return {"ok": True, "research": parsed}
    except Exception as exc:
        return {"ok": False, "error": f"Perplexity failed: {exc}"}


def _openai(prompt: str) -> dict:
    key = _usable_key("OPENAI_API_KEY")
    if not key:
        return {"ok": False, "error": "OPENAI_API_KEY is not set."}
    try:
        from openai import OpenAI
    except ImportError as exc:
        return {"ok": False, "error": f"OpenAI client is not installed: {exc}"}
    client = OpenAI(api_key=key, timeout=90)
    errors = []
    for tool_name in ("web_search_preview", "web_search"):
        try:
            response = client.responses.create(
                model="gpt-4o",
                tools=[{"type": tool_name}],
                input=prompt,
            )
            text = getattr(response, "output_text", "") or ""
            parsed = research_from_fields(extract_json(text), source="openai", live_verified=True)
            if not primary_urls(parsed):
                return {"ok": False, "error": "OpenAI browsed but returned no primary source URL."}
            return {"ok": True, "research": parsed}
        except Exception as exc:
            errors.append(f"{tool_name}: {exc}")
    return {
        "ok": False,
        "error": "OpenAI could not browse, so this run will not invent sources. " + " | ".join(errors),
    }


def research_live(topic: str | None, category: str, history_titles: list[str], today: datetime) -> dict:
    prompt = _prompt(topic, category, history_titles, today.strftime("%Y-%m-%d"))
    perplexity = _perplexity(prompt)
    if perplexity.get("ok"):
        return {"ok": True, "research": perplexity["research"], "errors": []}
    openai = _openai(prompt)
    errors = [perplexity.get("error") or "Perplexity failed.", openai.get("error") or "OpenAI failed."]
    if openai.get("ok"):
        return {"ok": True, "research": openai["research"], "errors": errors[:1]}
    return {"ok": False, "research": None, "errors": errors}
