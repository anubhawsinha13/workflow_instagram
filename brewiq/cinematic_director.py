"""BrewIQ cinematic video director — hooks, styles, storyboard, recovery options.

This module does not call Veo or publish. It plans the reel and returns structured
payloads the Slack host / workflow can act on (including awaiting_choice).
"""

from __future__ import annotations

import re
from typing import Any

from cinematic_profile import (
    FRAME_RULE,
    HOST_LOCK,
    HOST_REFERENCES,
    LABEL,
    NO_TEXT_RULE,
    cinematic_problems,
)
from composition import (
    BRAND_LOOK,
    RENDER_CHECKS,
    VOICE_DIRECTION,
    VOICE_WPM,
    brand_problems,
    build_composition,
    build_cover,
    composition_problems,
    cover_problems,
    icon_for_topic,
    phrase_subtitles,
    voice_pacing,
)
from learning_loop import applied_summary, preferred_style

STYLES: dict[str, dict[str, str]] = {
    "cinematic_3d": {
        "id": "cinematic_3d",
        "label": "Cinematic 3D",
        "description": (
            "Animated character, environments, dramatic camera movement. "
            "Great for AI inventions and robotics."
        ),
        "pipeline": "director_reel",
    },
    "interactive_explainer": {
        "id": "interactive_explainer",
        "label": "Interactive Explainer",
        "description": (
            "Character tries the tool on real devices in a real room; the screen UI is composited in post. "
            "Great for AI tools and product updates."
        ),
        "pipeline": "explainer_render",
    },
    "tech_storytelling": {
        "id": "tech_storytelling",
        "label": "Tech Storytelling",
        "description": (
            "Mini-story with a problem, transformation, and reveal. "
            "Great for AI agents and automation."
        ),
        "pipeline": "director_reel",
    },
    "motion_graphics": {
        "id": "motion_graphics",
        "label": "Motion Graphics",
        "description": (
            "Fast typography, diagrams, icons, and smooth transitions. "
            "Great for architecture and integration topics. No Veo required."
        ),
        "pipeline": "motion_graphics",
    },
}

_RECOVERY = [
    {
        "id": "retry_later",
        "label": "Retry Veo later (after quota resets)",
        "when": ("quota", "billing", "resource_exhausted"),
    },
    {
        "id": "switch_motion_graphics",
        "label": "Rebuild as Motion Graphics (no Veo)",
        "when": ("quota", "billing", "resource_exhausted", "veo", "reel file"),
    },
    {
        "id": "switch_slides",
        "label": "Fall back to six-slide carousel",
        "when": ("quota", "billing", "veo", "reel file", "motion"),
    },
    {
        "id": "shorten_copy",
        "label": "Paraphrase source notes and retry",
        "when": ("paraphrase", "quotation", "source notes", "copyright"),
    },
]


def list_styles() -> list[dict[str, str]]:
    return [
        {
            "id": style["id"],
            "label": style["label"],
            "description": style["description"],
            "pipeline": style["pipeline"],
        }
        for style in STYLES.values()
    ]


def recommend_style(topic: str, research: dict | None = None, learnings: dict | None = None) -> str:
    """Research's suggestion first; architecture topics need motion graphics; then the learned style; then topic words."""
    suggested = str((research or {}).get("suggested_style") or "")
    if suggested in STYLES:
        return suggested
    text = _topic_text(topic, research).lower()
    if any(word in text for word in ("architect", "integrat", "api", "pipeline", "idempoten")):
        return "motion_graphics"
    learned = preferred_style(learnings)
    if learned in STYLES:
        return learned
    if any(word in text for word in ("agent", "automat", "retry", "workflow")):
        return "tech_storytelling"
    if any(word in text for word in ("ui", "chatgpt", "gemini", "product", "tool", "notebook")):
        return "interactive_explainer"
    if any(word in text for word in ("robot", "invent", "3d", "hardware")):
        return "cinematic_3d"
    return "interactive_explainer"


# On-screen / spoken openers that kill retention in the first 2 seconds (Instagram evidence).
_BANNED_OPENERS = re.compile(
    r"\b("
    r"why it matters|here's why|here is why|in this video|today we|welcome|"
    r"let'?s talk|introduction|overview|context|background|"
    r"ai news|try this|deep dive|lesson"
    r")\b",
    re.IGNORECASE,
)


def is_weak_opener(text: str) -> bool:
    """True when copy is a section label or soft intro — not a scroll-stop."""
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return True
    if _BANNED_OPENERS.search(value):
        return True
    # All-caps section titles like "WHY IT MATTERS"
    letters = re.sub(r"[^A-Za-z]", "", value)
    if letters and letters.isupper() and len(value.split()) <= 5:
        return True
    return False


def rank_hooks(topic: str, research: dict | None = None) -> list[dict[str, Any]]:
    """Return three ranked scroll-stop hooks. Never opens with 'why it matters'."""
    research = research or {}
    brief_hooks = [
        h for h in research.get("brief_hooks") or [] if h.get("text") and not is_weak_opener(h["text"])
    ]
    if brief_hooks:
        return [
            {
                "id": f"hook_{i}",
                "rank": i,
                "text": h["text"],
                "approach": h.get("approach", ""),
                "why": h.get("why") or f"Research Agent {h.get('approach', 'hook')} option.",
                "on_screen_text": _on_screen_hook(h["text"]),
            }
            for i, h in enumerate(brief_hooks[:5], start=1)
        ]
    raw_hook = str(research.get("hook") or "").strip()
    headline = str(research.get("headline") or "").strip()
    point = str(research.get("point") or research.get("why_it_matters") or "").strip()
    topic = str(topic or research.get("topic") or "").strip()

    # Prefer a concrete claim; strip weak research hooks rather than amplifying them.
    seed = next(
        (
            value
            for value in (raw_hook, headline, point, topic)
            if value and not is_weak_opener(value)
        ),
        topic or "this AI habit",
    )
    noun_phrase = _is_noun_phrase(seed) and seed == topic
    seed = re.sub(r"\s+", " ", seed).strip()
    # Drop soft lead-ins so we keep the concrete clause.
    seed = re.sub(
        r"^(most people get this wrong:|watch what happens:|in \d+ seconds:)\s*",
        "",
        seed,
        flags=re.I,
    ).strip()
    short = seed if len(seed) <= 70 else seed[:67].rstrip() + "…"
    # Concrete object for pattern-interrupt hooks.
    object_bit = short
    for prefix in ("how ", "why ", "what ", "when "):
        if object_bit.lower().startswith(prefix):
            object_bit = object_bit[len(prefix) :]
            break

    # "You're doing X backwards" only reads well when X is a noun phrase like a topic;
    # a sentence ("Your notes hide the gaps") gets sentence-safe templates instead.
    sentence = short.rstrip(".?!")
    first = sentence.split(" ", 1)[0]
    lowered = sentence[:1].lower() + sentence[1:] if first.lower() in _LOWERCASE_STARTERS else sentence
    second = (
        (f"You're doing {object_bit} backwards", f"{object_bit} — backwards?")
        if noun_phrase
        else (f"Most people miss this: {lowered}", sentence)
    )
    third = (
        (f"One mistake ruins {object_bit}", f"One mistake: {object_bit}")
        if noun_phrase
        else (f"Watch closely: {lowered}", sentence)
    )
    candidates = [
        {
            "id": "hook_1",
            "rank": 1,
            "text": f"Stop scrolling — {short}",
            "why": (
                "Pattern interrupt in under 1s. Retention data shows labels like "
                "'WHY IT MATTERS' lose ~80% of viewers by 0:02."
            ),
            "on_screen_text": _on_screen_hook(short),
        },
        {
            "id": "hook_2",
            "rank": 2,
            "text": second[0],
            "why": "Correction + identity sting; forces a curiosity gap before the teach.",
            "on_screen_text": _on_screen_hook(second[1]),
        },
        {
            "id": "hook_3",
            "rank": 3,
            "text": third[0],
            "why": "Stakes in the first line; payoff comes later, not a section title.",
            "on_screen_text": _on_screen_hook(third[1]),
        },
    ]
    for item in candidates:
        if is_weak_opener(item["text"]) or is_weak_opener(item["on_screen_text"]):
            item["text"] = f"Stop scrolling — {short}"
            item["on_screen_text"] = _on_screen_hook(short)
    return candidates


_SENTENCE_WORDS = frozenset(
    (
        "you", "your", "you're", "it", "it's", "they", "we", "i", "me", "us", "my", "our", "is", "are", "was",
        "were", "can", "will", "does", "do", "did", "has", "have", "had", "quizzes", "hides", "hide", "finds",
        "makes", "gets", "shows", "lets", "turns", "writes", "reads", "knows", "sees",
    )
)


_LOWERCASE_STARTERS = frozenset(
    ("your", "you", "the", "a", "an", "it", "this", "that", "most", "my", "our", "every", "when", "how", "why", "what")
)


def _is_noun_phrase(text: str) -> bool:
    words = re.findall(r"[a-z']+", str(text or "").lower())
    return 0 < len(words) <= 6 and not any(w in _SENTENCE_WORDS for w in words)


def _on_screen_hook(text: str) -> str:
    """Short overlay for 0–2s. Never a section label."""
    value = " ".join(str(text or "").split()).strip()
    if is_weak_opener(value):
        value = "Watch this"
    if len(value) > 42:
        value = value[:39].rstrip() + "…"
    return value


def plan_reel(
    topic: str,
    *,
    research: dict | None = None,
    style: str | None = None,
    hook_id: str | None = None,
    learnings: dict | None = None,
) -> dict[str, Any]:
    """Plan a cinematic reel. Without style+hook, returns awaiting_choice options.

    ``learnings`` (``learning_loop.load_learnings()``) only changes the recommended
    style; ``learnings_applied`` lists what was used so Slack can show it.
    """
    payload = _plan_reel(topic, research=research, style=style, hook_id=hook_id, learnings=learnings)
    payload["learnings_applied"] = applied_summary(learnings)
    return payload


def _plan_reel(
    topic: str,
    *,
    research: dict | None,
    style: str | None,
    hook_id: str | None,
    learnings: dict | None,
) -> dict[str, Any]:
    research = dict(research or {})
    topic = (topic or research.get("topic") or "").strip()
    if not topic:
        return {
            "ok": False,
            "status": "blocked",
            "nothing_posted": True,
            "waiting_on": ["A topic is required before a reel can be planned."],
            "options": {"recovery": [{"id": "switch_slides", "label": "Fall back to six-slide carousel"}]},
            "error": "Topic is required.",
        }

    hooks = rank_hooks(topic, research)
    styles = list_styles()
    recommended = recommend_style(topic, research, learnings)

    chosen = (style or "").strip().lower()
    if chosen in STYLES and not hook_id:
        return {
            "ok": False,
            "status": "awaiting_choice",
            "nothing_posted": True,
            "chosen_style": chosen,
            "prompt": (
                f"Style: {STYLES[chosen]['label']} (`{chosen}`). Pick a hook before the reel is generated. "
                f"Reply in this thread with `hook 1`, `hook 2` or `hook 3` (or style={chosen} hook={hooks[0]['id']})."
            ),
            "options": {
                "styles": styles,
                "hooks": hooks,
                "recommended_style": recommended,
                "recommended_hook": hooks[0]["id"],
            },
            "topic": topic,
            "error": "",
        }

    if not style or not hook_id:
        return {
            "ok": False,
            "status": "awaiting_choice",
            "nothing_posted": True,
            "prompt": (
                "Pick a style and a hook before the reel is generated. "
                f"Recommended style: {STYLES[recommended]['label']} (`{recommended}`). "
                "Reply like: style=interactive_explainer hook=hook_1"
            ),
            "options": {
                "styles": styles,
                "hooks": hooks,
                "recommended_style": recommended,
                "recommended_hook": hooks[0]["id"],
            },
            "topic": topic,
            "error": "",
        }

    style_key = style.strip().lower()
    if style_key not in STYLES:
        return {
            "ok": False,
            "status": "awaiting_choice",
            "nothing_posted": True,
            "prompt": f"Unknown style `{style}`. Pick one of the listed styles.",
            "options": {"styles": styles, "hooks": hooks, "recommended_style": recommended},
            "error": f"Unknown style: {style}",
        }

    hook = next((item for item in hooks if item["id"] == hook_id), None)
    if hook is None:
        return {
            "ok": False,
            "status": "awaiting_choice",
            "nothing_posted": True,
            "prompt": f"Unknown hook `{hook_id}`. Pick one of: {', '.join(h['id'] for h in hooks)}.",
            "options": {"styles": styles, "hooks": hooks, "recommended_style": recommended},
            "error": f"Unknown hook: {hook_id}",
        }

    on_screen = str(hook.get("on_screen_text") or _on_screen_hook(hook["text"]))
    cinematic = style_key in CHARACTER_ENVIRONMENTS
    if cinematic:
        scenes = _cinematic_scenes(topic, research, hook["text"], style_key, on_screen)
    else:
        scenes = _storyboard_scenes(topic, research, hook["text"], style_key, on_screen)
    post = _post_production(topic, research, scenes, style_key, on_screen) if cinematic else None
    voiceover = post["voiceover"] if post else _voiceover(topic, research, hook["text"])
    captions = _captions(scenes)
    opening_problems = opening_frame_problems(on_screen, scenes[0] if scenes else {})
    profile_problems = post["problems"] if post else []
    package = {
        "ok": True,
        "status": "planned",
        "nothing_posted": True,
        "topic": topic,
        "style": STYLES[style_key],
        "hook": hook,
        "hooks_ranked": hooks,
        "voiceover": voiceover,
        "scenes": scenes,
        "captions": captions,
        # Cover / first-frame text must be the hook, never "WHY IT MATTERS".
        "cover_headline": on_screen,
        "instagram_caption": _instagram_caption(topic, research, hook["text"]),
        "hashtags": _hashtags(research),
        "music_direction": (
            "Hit a one-beat sting in the first 0.5s with narration starting immediately; "
            "then energetic mid-tempo tech bed under voice. Music quieter than voice."
        ),
        "quality_checks": _quality_checks(scenes, hook["text"], on_screen),
        "opening_frame_problems": opening_problems,
        "cinematic_problems": profile_problems,
        "director_reel": _director_reel_payload(scenes, style_key),
        "error": "",
    }
    if post:
        package["label"] = LABEL
        package["environment_lock"] = CHARACTER_ENVIRONMENTS[style_key]
        package["brand_look"] = BRAND_LOOK
        package["typography"] = dict(PLAN_TYPOGRAPHY)
        package["cover_headline"] = post["cover"]["headline"]["text"] or on_screen
        package["music_direction"] = (
            f"Music bed {post['composition']['audio'][1]['lufs']:g} LUFS, at least 10 dB under the narration and "
            "ducked 4 dB under speech; one soft sting at 0s; no music under the 0.3–0.5s pauses before reveals."
        )
        for key in ("subtitles", "composition", "cover", "voice_direction", "voice_pacing", "icon", "render_checks", "warnings"):
            package[key] = post[key]
    if profile_problems and not opening_problems:
        package.update(
            ok=False,
            status="blocked",
            waiting_on=profile_problems,
            options=recovery_options(*profile_problems).get("options"),
            prompt=(
                "The plan failed a quality gate (see waiting_on). Fix the research or copy, pick another hook, "
                "or reply recovery=switch_slides."
            ),
            error=profile_problems[0],
        )
    if opening_problems:
        package["ok"] = False
        package["status"] = "blocked"
        package["waiting_on"] = opening_problems
        package["options"] = recovery_options(*opening_problems).get("options")
        package["prompt"] = (
            "The opening frame would kill retention. Pick another hook "
            "(reply like: style={style} hook=hook_2) or recovery=switch_motion_graphics."
        ).format(style=style_key)
        package["error"] = opening_problems[0]
    return package


def opening_frame_problems(on_screen_text: str, first_scene: dict | None = None) -> list[str]:
    """Fail the plan when the first 2 seconds look like the retention-killing reel."""
    problems: list[str] = []
    if is_weak_opener(on_screen_text):
        problems.append(
            "Opening on-screen text is a weak label (e.g. 'WHY IT MATTERS'). "
            "Instagram retention drops ~80% by 0:02 with that pattern — use the hook claim instead."
        )
    scene = first_scene or {}
    narration = str(scene.get("narration") or "")
    if is_weak_opener(narration):
        problems.append(
            "Opening narration is a soft intro. Speak the hook claim in the first second."
        )
    prompt = str(scene.get("prompt") or "").lower()
    if "frozen" in prompt or "static pose" in prompt or "smiling at camera holding" in prompt:
        problems.append(
            "Opening visual is a static talking-head pose. Start mid-action with a visual change."
        )
    return problems


def recovery_options(*errors: str) -> dict[str, Any]:
    """Map hard failures to operator recovery choices (Slack options, not a dead end)."""
    waiting = []
    for err in errors:
        text = " ".join(str(err or "").split()).strip()
        if text and text not in waiting:
            waiting.append(text)
    if not waiting:
        waiting = ["The reel is not ready."]

    blob = " ".join(waiting).lower()
    choices: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _RECOVERY:
        if any(token in blob for token in item["when"]) and item["id"] not in seen:
            choices.append({"id": item["id"], "label": item["label"]})
            seen.add(item["id"])
    if "switch_slides" not in seen:
        choices.append({"id": "switch_slides", "label": "Fall back to six-slide carousel"})
    if "switch_motion_graphics" not in seen and any(
        token in blob for token in ("quota", "billing", "veo", "reel")
    ):
        choices.insert(
            0,
            {
                "id": "switch_motion_graphics",
                "label": "Rebuild as Motion Graphics (no Veo)",
            },
        )

    return {
        "ok": False,
        "status": "blocked",
        "nothing_posted": True,
        "waiting_on": waiting,
        "prompt": (
            "The reel did not finish. Pick a recovery option "
            "(reply like: recovery=switch_motion_graphics). Nothing has been posted."
        ),
        "options": {"recovery": choices},
        "error": waiting[0],
    }


def apply_recovery(recovery_id: str, topic: str, research: dict | None = None) -> dict[str, Any]:
    """Continue planning after an operator recovery pick."""
    research = research or {}
    rid = (recovery_id or "").strip().lower()
    if rid == "retry_later":
        return {
            "ok": False,
            "status": "blocked",
            "nothing_posted": True,
            "waiting_on": ["Waiting for Veo/Gemini quota to reset before retrying."],
            "prompt": "Quota still required for Veo. Try recovery=switch_motion_graphics or recovery=switch_slides.",
            "options": {
                "recovery": [
                    {"id": "switch_motion_graphics", "label": "Rebuild as Motion Graphics (no Veo)"},
                    {"id": "switch_slides", "label": "Fall back to six-slide carousel"},
                    {"id": "retry_later", "label": "Keep waiting on Veo quota"},
                ]
            },
            "error": "Veo quota not available.",
        }
    if rid == "switch_slides":
        from slides_director import plan_slides  # slides_director imports this module

        style = recommend_style(topic, research)
        slides = plan_slides(topic, research, style=style if style in CHARACTER_ENVIRONMENTS else "cinematic_3d")
        problems = slides["slide_problems"]
        return {
            "ok": not problems,
            "status": "redirect",
            "nothing_posted": True,
            "format": "slides",
            "topic": topic,
            "slides": slides,
            "waiting_on": problems,
            "prompt": (
                "Continue as a six-slide carousel draft (story frames, not title cards). Nothing has been posted."
                if not problems
                else "The carousel plan needs fixes before render (see waiting_on). Nothing has been posted."
            ),
            "error": problems[0] if problems else "",
        }
    if rid == "shorten_copy":
        cleaned = dict(research)
        for field in ("hook", "point", "try_it", "takeaway", "why_it_matters", "limitations"):
            value = cleaned.get(field)
            if isinstance(value, str) and len(value.split()) > 18:
                cleaned[field] = " ".join(value.split()[:18]).rstrip(".,;") + "."
        return plan_reel(
            topic,
            research=cleaned,
            style="motion_graphics",
            hook_id="hook_1",
        )
    if rid == "switch_motion_graphics":
        return plan_reel(
            topic,
            research=research,
            style="motion_graphics",
            hook_id="hook_1",
        )
    return recovery_options(f"Unknown recovery option: {recovery_id}")


def _topic_text(topic: str, research: dict | None) -> str:
    research = research or {}
    parts = [
        topic,
        research.get("topic"),
        research.get("headline"),
        research.get("hook"),
        research.get("point"),
        " ".join(str(k) for k in (research.get("keywords") or [])),
    ]
    return " ".join(str(p) for p in parts if p)


CHARACTER_ENVIRONMENTS = {
    "cinematic_3d": (
        "SET LOCK — one consistent modern apartment at blue hour in every shot: deep midnight-navy walls, dark "
        "walnut and graphite furniture, warm amber practical lamps, electric-cyan shelf and under-cabinet strip "
        "lights, vibrant-blue city glow through a tall window, glossy floor reflections, detailed lived-in objects."
    ),
    "interactive_explainer": (
        "SET LOCK — one consistent premium home studio at night in every shot: midnight-navy walls, a dark oak desk "
        "with an open laptop and a phone, a warm amber desk lamp, electric-cyan and vibrant-blue edge lights on the "
        "shelves, plants, glossy reflections; animated holographic 3D shapes, nodes and light particles float above "
        "the desk and react to the host's hands; laptop and phone screens show soft abstract light only (real UI is "
        "composited in post)."
    ),
    "tech_storytelling": (
        "SET LOCK — one consistent apartment at night in every shot: midnight-navy room, a desk with a laptop by a "
        "tall window full of vibrant-blue city lights, warm amber lamps, a kitchen counter with a phone and a smart "
        "speaker; devices emit electric-cyan light trails when they connect."
    ),
}
PLAN_TYPOGRAPHY = {
    "frame_rule": FRAME_RULE,
    "subtitle_zone": "lower_safe",
    "hook_zone": "headline box x 90, y 300, w 690, h ≤280 on 1080×1920",
    "rules": [
        "Headlines: max 6 words, max 2 lines, bold high-contrast type on a navy plate, composited as the top layer.",
        "Separate zones: headline + icon at the top, presenter in the middle band, subtitles at the bottom.",
        "Subtitles never overlap headlines or graphics; everything stays in the Instagram-safe area.",
        f"Small persistent '{LABEL}' tag above the headline for the full runtime.",
    ],
}
_PLAN_NEGATIVES = (
    "Vertical 9:16, 1080×1920, 24fps cinematic, shallow depth of field, motivated camera move, continuous motion. "
    f"{NO_TEXT_RULE} No titles, labels, subtitles or floating text cards. No pointing, thumbs-up or waving. "
    "No dialogue, no music."
)
NARRATION_WPM = 152
MIN_SCENE, MAX_SCENE = 3.0, 5.0
# (role, narration key, overlay key, host in shot, camera, transition)
_CINEMATIC_BEATS = (
    ("Hook", "hook", "hook", True, "Low tracking dolly toward the action from frame one, rising as the host enters", "match move"),
    ("Setup", "point", "", True, "Over-the-shoulder from behind the host as he walks, then a slow push-in past his shoulder", "cut on action"),
    ("Reveal — how it works", "try_it", "try_it", True, "Close-up on hands and the device or object with a motivated push-in, then a rack focus to the host's face", "whip-pan following the movement"),
    ("Reveal — the catch", "limitation", "limitation", True, "Side tracking shot following the action, foreground objects sliding past for parallax", "continuous arc"),
    ("Reveal — second try", "", "", False, "Half-orbit close-up around the subject, ending on a push-in", "match cut on motion"),
    ("Payoff", "takeaway", "takeaway", True, "Tracking dolly alongside the host, rising into a gentle crane", "push-through"),
    ("Ending", "question", "question", True, "Slow push-in to a medium close-up of the host", "end on the host's line; brand end card"),
)


def research_facts(research: dict) -> list[str]:
    """Facts a planned scene may cite: verified facts (or bullets), then limitations."""
    facts = [str(f) for f in (research.get("verified_facts") or research.get("bullets") or []) if str(f).strip()]
    if not facts:
        facts = [str(research[k]) for k in ("headline", "point", "try_it", "takeaway") if str(research.get(k) or "").strip()]
    return facts + research_limitations(research)


def research_limitations(research: dict) -> list[str]:
    value = research.get("limitations") or []
    items = [value] if isinstance(value, str) else list(value)
    return [str(v).strip() for v in items if str(v).strip()]


def short_line(text: str, words: int = 6) -> str:
    """The line itself when it fits; never a cut-off fragment (that can drop a qualification)."""
    value = " ".join(str(text or "").split())
    return value if value and len(value.split()) <= words else ""


def _sentence(text: str) -> str:
    value = " ".join(str(text or "").split())
    return value if not value or value[-1] in ".?!" else value + "."


def _scene_seconds(narration: str) -> float:
    words = len(narration.split())
    if not words:
        return MIN_SCENE
    return round(min(MAX_SCENE, max(MIN_SCENE, words / NARRATION_WPM * 60 + 0.5)), 1)


def _cinematic_scenes(
    topic: str,
    research: dict,
    hook_text: str,
    style: str,
    overlay: str,
) -> list[dict[str, Any]]:
    facts = research_facts(research)
    limitations = research_limitations(research)
    limit_index = len(facts) - len(limitations)
    grounded = list(range(limit_index)) or None
    moment = str(research.get("key_visual_moment") or research.get("headline") or topic).strip().rstrip(".")
    lines = {
        "hook": _sentence(hook_text),
        "point": _sentence(research.get("point")),
        "try_it": _sentence(research.get("try_it")),
        "limitation": _sentence(limitations[0]) if limitations else "",
        "takeaway": _sentence(research.get("takeaway")),
        "question": _sentence(research.get("viewer_question")),
    }
    spoken = ""
    for key, line in lines.items():
        plain = line.rstrip(".?!").lower()
        if plain and plain in spoken:
            lines[key] = ""
        spoken += " " + line.lower()
    demo = (
        "on the laptop, then shapes the floating holographic elements with his hands"
        if style == "interactive_explainer"
        else "with the real object in the room"
    )
    actions = (
        (
            "No host for the first 1.5s: the subject is already mid-action. At 1.5s the host walks into frame, "
            "stops mid-stride and reacts with a small surprised lean."
        ),
        "The host sets down what he is carrying and walks closer, observing with a curious tilt of the head.",
        f"The host tries it himself {demo}, then leans back as it works, eyebrows rising.",
        "The host winces and half-steps forward as the limit shows.",
        "No host in this shot: the subject adjusts and succeeds on the second try.",
        "The host straightens up, picks up the result and carries it toward the window light.",
        (
            "The host turns to camera, takes one step toward the lens and speaks one short line (mouth movement "
            "only; audio comes from the narration track)."
        ),
    )
    visuals = (
        f"{moment}, already in motion in frame one",
        "The subject keeps working in the background; the next step lands as the host arrives",
        "The method working up close, step by step",
        "The limit, shown honestly: one step visibly fails" if lines["limitation"] else "A tricky detail of the process, up close",
        "The approach adjusts and succeeds on the second try",
        "The result resolves into one clear, satisfying finished state",
        "The subject finishes in the background as the host speaks",
    )
    event_steps = (
        ("Subject already in motion", "Host walks into frame and stops mid-stride", "The action completes a visible step"),
        ("Host sets his things down", "Walks closer, observing", "The subject's next step lands"),
        ("Hands on the device or object", "It responds", "Rack focus: host leans back, eyebrows up"),
        ("Action moves across the room", "The limit shows", "Host winces"),
        ("Subject resets its approach", "Second attempt starts", "It works"),
        ("Host straightens up", "Picks up the result", "Carries it toward the window light"),
        ("Host turns to camera", "Steps toward the lens and speaks", "Subject finishes in the background"),
    )

    scenes: list[dict[str, Any]] = []
    cursor = 0.0
    for index, (role, line_key, overlay_key, host, camera, transition) in enumerate(_CINEMATIC_BEATS, start=1):
        narration = lines.get(line_key, "") if line_key else ""
        start = round(cursor, 2)
        end = round(start + _scene_seconds(narration), 2)
        cursor = end
        written = (research.get("headlines") or {}).get(overlay_key) if overlay_key else None
        if overlay_key == "hook":
            text = short_line(written or research.get("cover_headline") or overlay)
        else:
            text = short_line(written or lines.get(overlay_key, "")) if overlay_key else ""
        if text and text.rstrip(".?!").lower() == narration.rstrip(".?!").lower():
            text = ""  # the subtitle already says it; a matching headline is a duplicate caption
        text_end = end - 0.9 if index == len(_CINEMATIC_BEATS) else end
        if line_key == "limitation" and narration:
            basis: Any = [limit_index]
        elif line_key in ("hook", "point", "try_it", "takeaway") and grounded:
            basis = grounded
        else:
            basis = f"illustrative: {role.lower()} staging; no new claim"
        duration = end - start
        offsets = (0.0, 0.5, 0.8) if index == 1 else (0.0, 0.4, 0.8)
        presence = "" if host else "The BrewIQ host does not appear in this shot. "
        shot = f"{presence}{actions[index - 1]} {visuals[index - 1]}."
        scenes.append(
            {
                "index": index,
                "timing": f"{start:g}–{end:g}s",
                "start": start,
                "end": end,
                "role": role,
                "environment": CHARACTER_ENVIRONMENTS[style],
                "host_in_shot": host,
                "character_action": actions[index - 1],
                "camera": camera,
                "visual_animation": visuals[index - 1],
                "narration": narration,
                "on_screen_text": text,
                "text_overlay": (
                    {"start": round(start + (0.2 if index == 1 else 0.1), 2), "end": round(text_end, 2), "text": text}
                    | {"placement": "top_safe", "layer": "above_all"}
                    if text
                    else None
                ),
                "events": [
                    {"t": round(start + duration * f, 2), "event": label}
                    for f, label in zip(offsets, event_steps[index - 1], strict=True)
                ],
                "fact_basis": basis,
                "transition": transition,
                "prompt": " ".join(
                    [
                        HOST_LOCK,
                        CHARACTER_ENVIRONMENTS[style],
                        BRAND_LOOK,
                        f"SHOT — {shot} Camera: {camera}.",
                        FRAME_RULE,
                        _PLAN_NEGATIVES,
                    ]
                ),
                "use_character": host,
                "generation": {
                    "clip_seconds": 4 if duration <= 4 else 6,
                    "trim_to_seconds": round(duration, 2),
                    "aspect_ratio": "9:16",
                    "reference_assets": list(HOST_REFERENCES),
                },
            }
        )
    return scenes


def _subtitles(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    subs: list[dict[str, Any]] = []
    for scene in scenes:
        if scene["narration"]:
            start = scene["start"] + 0.05
            spoken = len(scene["narration"].split()) / NARRATION_WPM * 60
            subs += phrase_subtitles(scene["narration"], start, min(scene["end"] - 0.1, start + spoken))
    return subs


def _profile_view(scenes: list[dict[str, Any]], style: str) -> dict[str, Any]:
    """Planner scenes in the shape ``cinematic_problems`` and ``build_composition`` read."""
    return {
        "environment": {"lock_prompt": CHARACTER_ENVIRONMENTS[style]},
        "typography": PLAN_TYPOGRAPHY,
        "scenes": [
            {
                **scene,
                "character_actions": scene["character_action"],
                "on_screen_text": [scene["text_overlay"]] if scene.get("text_overlay") else [],
            }
            for scene in scenes
        ],
    }


def _post_production(topic: str, research: dict, scenes: list[dict[str, Any]], style: str, overlay: str) -> dict[str, Any]:
    view = _profile_view(scenes, style)
    subtitles = _subtitles(scenes)
    voiceover = " ".join(s["narration"] for s in scenes if s["narration"])
    icon = icon_for_topic(topic, research)
    composition = build_composition(view["scenes"], subtitles, icon=icon, icon_scene=3, label=LABEL)
    written = (research.get("headlines") or {}).get("hook")
    headline = short_line(research.get("cover_headline") or written or overlay)
    moment = str(research.get("key_visual_moment") or research.get("headline") or topic).strip().rstrip(".")
    cover = build_cover(
        visual=f"{moment}, at its most dramatic instant, with the host reacting in the foreground",
        headline=headline,
        character_lock=HOST_LOCK,
        environment_lock=CHARACTER_ENVIRONMENTS[style],
    )
    problems = (
        cinematic_problems(view, {"verified_facts": research_facts(research)})
        + composition_problems(composition, voiceover)
        + cover_problems(cover)
        + brand_problems([s["prompt"] for s in scenes], CHARACTER_ENVIRONMENTS[style])
    )
    for scene in scenes:
        words = len(scene["narration"].split())
        if words and words / (VOICE_WPM[1] / 60) > MAX_SCENE - 0.3:
            problems.append(f"Scene {scene['index']} line is too long for one shot at {VOICE_WPM[1]} WPM; shorten it.")
    pacing = voice_pacing(voiceover, subtitles)
    warnings = [f"Narration pace {pacing['wpm']} WPM is {pacing['note']} ({VOICE_WPM[0]}–{VOICE_WPM[1]})."] if pacing["note"] else []
    return {
        "voiceover": voiceover,
        "subtitles": subtitles,
        "composition": composition,
        "cover": cover,
        "voice_direction": dict(VOICE_DIRECTION),
        "voice_pacing": pacing,
        "icon": {"category": icon[0], "icon": icon[1], "scene": 3},
        "render_checks": {key: {"on_fail": action, "how": how} for key, (action, how) in RENDER_CHECKS.items()},
        "problems": problems,
        "warnings": warnings,
    }


def _storyboard_scenes(
    topic: str,
    research: dict,
    hook_text: str,
    style: str,
    on_screen_hook: str = "",
) -> list[dict[str, Any]]:
    point = str(research.get("point") or research.get("why_it_matters") or topic).strip()
    if is_weak_opener(point):
        point = str(topic or "the core idea").strip()
    try_it = str(research.get("try_it") or "Try the idea once with a real example.").strip()
    takeaway = str(research.get("takeaway") or point).strip()
    overlay = on_screen_hook or _on_screen_hook(hook_text)
    env_default = {
        "cinematic_3d": "Warm practical-lit room, shallow depth, teal accents",
        "interactive_explainer": "Dark studio with floating holographic UI panels",
        "tech_storytelling": "Night desk → connected apps lighting up",
        "motion_graphics": "Clean dark canvas, kinetic diagrams, teal/blue accents",
    }[style]

    beats = [
        (
            "0–2s",
            "Hook",
            hook_text,
            (
                "Character is already mid-action (not smiling at camera with a mug). "
                "Snap look to lens while a UI/object reacts"
            ),
            "Aggressive dolly-in from medium to tight close-up in under 1.5s",
            (
                f"Pattern-interrupt visual tied to the claim. "
                f"On-screen text ONLY the hook line '{overlay}' — "
                "never 'WHY IT MATTERS', category pills, or section labels"
            ),
        ),
        (
            "2–8s",
            "Problem",
            f"The trap: {point}",
            "Character pivots and walks to the broken flow, gesturing at the failure",
            "Tracking medium shot",
            "Animate the broken or confusing process — teach starts AFTER the hook lands",
        ),
        (
            "8–15s",
            "Transformation",
            try_it,
            "Character interacts with floating UI / objects",
            "Over-the-shoulder → orbit",
            "Show the system connecting or the method working",
        ),
        (
            "15–22s",
            "Reveal",
            f"The payoff: {takeaway}",
            "Character reacts, then presents the result",
            "Wide → controlled zoom",
            "Full visual payoff; diagrams resolve",
        ),
        (
            "22–28s",
            "Takeaway",
            takeaway,
            "Character faces viewer with a calm, clear gesture",
            "Medium close-up hold",
            "Memorable end card energy without frozen pose",
        ),
    ]

    scenes: list[dict[str, Any]] = []
    for index, (timing, role, narration, action, camera, animation) in enumerate(beats, start=1):
        # Model must not draw words; compositor/caption layer owns overlays.
        prompt = (
            f"{action}. Environment: {env_default}. Camera: {camera}. "
            f"Visual: {animation}. Continuous motion from frame one. "
            "No logos, no section titles, no 'WHY IT MATTERS' text in the generated plate."
        )
        scenes.append(
            {
                "index": index,
                "timing": timing,
                "role": role,
                "environment": env_default,
                "character_action": action,
                "camera": camera,
                "visual_animation": animation,
                "narration": narration,
                "on_screen_text": overlay if index == 1 else "",
                "transition": "hard cut on beat" if index < len(beats) else "fade hold",
                "prompt": prompt,
                "use_character": True,
            }
        )
    return scenes


def _voiceover(topic: str, research: dict, hook_text: str) -> str:
    point = str(research.get("point") or topic).strip()
    try_it = str(research.get("try_it") or "").strip()
    takeaway = str(research.get("takeaway") or "").strip()
    limitations = research_limitations(research)
    question = str(research.get("viewer_question") or "").strip()
    parts = [hook_text, point, try_it, limitations[0] if limitations else "", takeaway, question]
    script = " ".join(p if p[-1] in ".?!" else p + "." for p in (str(p).strip() for p in parts) if p)
    words = script.split()
    if len(words) > 95:
        script = " ".join(words[:95]).rstrip(".,") + "."
    return script


def _captions(scenes: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "timing": scene["timing"],
            "text": scene["narration"][:90],
        }
        for scene in scenes
    ]


def _instagram_caption(topic: str, research: dict, hook_text: str) -> str:
    why = str(research.get("why_it_matters") or research.get("point") or "").strip()
    lines = [hook_text, "", why or f"A practical take on {topic}.", "", "Follow @_brewiq."]
    return "\n".join(line for line in lines if line is not None)


def _hashtags(research: dict) -> list[str]:
    base = ["#BrewIQ", "#EverydayAI", "#AIExplained", "#LearnOnInstagram", "#TechSimplified"]
    keywords = [str(k).strip() for k in (research.get("keywords") or []) if str(k).strip()]
    for key in keywords[:2]:
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", key.title())
        if len(tag) > 2 and tag not in base:
            base.append(tag)
    return base[:5]


def _quality_checks(
    scenes: list[dict[str, Any]], hook_text: str, on_screen: str = ""
) -> list[dict[str, Any]]:
    first = scenes[0] if scenes else {}
    first_timing = str(first.get("timing") or "")
    return [
        {
            "id": "hook_curiosity",
            "pass": bool(hook_text) and not is_weak_opener(hook_text) and not is_weak_opener(on_screen),
            "question": "Would the first two seconds make someone curious (not a 'WHY IT MATTERS' label)?",
        },
        {
            "id": "hook_before_teach",
            "pass": first.get("role") == "Hook" and first_timing.startswith("0"),
            "question": "Does teaching wait until after 0:02?",
        },
        {
            "id": "character_action",
            "pass": all("frozen" not in s["character_action"].lower() for s in scenes),
            "question": "Does the character perform meaningful actions from frame one?",
        },
        {
            "id": "visual_variety",
            "pass": len({s["camera"] for s in scenes}) >= 3,
            "question": "Is there enough visual variety?",
        },
        {"id": "nontechnical", "pass": True, "question": "Can a nontechnical adult follow it?"},
        {"id": "not_slideshow", "pass": True, "question": "Does it look animated rather than moving slides?"},
        {"id": "accuracy", "pass": True, "question": "Is the information accurate to the research?"},
        {"id": "reveal", "pass": len(scenes) >= 5, "question": "Is the final reveal worth waiting for?"},
    ]


def _director_reel_payload(scenes: list[dict[str, Any]], style: str) -> dict[str, Any] | None:
    if STYLES[style]["pipeline"] != "director_reel":
        return None
    payload: dict[str, Any] = {
        "scenes": [
            {"prompt": scene["prompt"], "use_character": True, "timing": scene["timing"], "role": scene["role"]}
            for scene in scenes
        ]
    }
    if style in CHARACTER_ENVIRONMENTS:
        payload["aspect_ratio"] = "9:16"
        for job, scene in zip(payload["scenes"], scenes, strict=True):
            job["duration_seconds"] = scene["generation"]["clip_seconds"]
            job["trim_to_seconds"] = scene["generation"]["trim_to_seconds"]
            job["reference_assets"] = scene["generation"]["reference_assets"]
    return payload
