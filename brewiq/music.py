"""Background-music guidance. No track is named as cleared."""

from __future__ import annotations

_GUIDE = {
    "ai_news": {
        "mood": "Restrained electronic, curious, and unhurried.",
        "tempo": "about 90–108 BPM",
        "search": "minimal electronic underscore, soft synth pulse, no lyrics",
    },
    "ai_research": {
        "mood": "Calm and thoughtful, closer to a short documentary than a trailer.",
        "tempo": "about 70–90 BPM",
        "search": "ambient piano and soft electronic bed, no lyrics",
    },
    "try_this": {
        "mood": "Warm, light, and practical.",
        "tempo": "about 100–115 BPM",
        "search": "light acoustic electronic, gentle groove, no lyrics",
    },
}


def music_guidance(category: str) -> dict:
    guide = _GUIDE.get(category, _GUIDE["ai_news"])
    return {
        "mood": guide["mood"],
        "tempo": guide["tempo"],
        "search_terms": guide["search"],
        "track_status": "Exact track not cleared.",
        "scope": (
            "A song that is allowed in an Instagram post, a paid ad, and a cross-post "
            "are different permissions. This note does not clear any of them."
        ),
        "silent_option": "Posting the carousel with no music is a fine option.",
    }


def format_music(guide: dict) -> str:
    return "\n".join(
        [
            f"Mood: {guide['mood']}",
            f"Tempo: {guide['tempo']}",
            f"Search terms: {guide['search_terms']}",
            guide["track_status"],
            guide["scope"],
            guide["silent_option"],
        ]
    )
