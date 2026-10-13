# BrewIQ — Utility Carousel (prompt pack)

Covers UC-005 and EXP-003. It's a cheap, evergreen format built to be saved and sent: each slide gives the reader something to use straight away. It needs no Veo. Validated by `utility_carousel.py`.

## Task

Topic: one everyday job AI can help a nontechnical adult do better, for example checking an AI answer before trusting it.

Write:

- `cover_headline`: 2–6 words, a curiosity or benefit line. `cover_visual`: the BrewIQ host in a scene that shows the job. The image model never renders text.
- 5–8 `items`, each with:
  - `title`: 6 words or fewer;
  - `benefit`: 12 words or fewer, saying what the reader gets;
  - `prompt`: 70 words or fewer, copy-and-paste ready, with at least one `[PLACEHOLDER]` in capitals.
- `closing_line`: a reason to keep the post (for example "Save this for the next AI answer you're unsure about"). Never "share this with 3 friends", "tag a friend" or "follow for more".
- `save_reason` and `share_reason`: concrete, about who would come back to it or who it would be sent to.
- `search_keywords` (2–4) and at most 5 hashtags.

## Rules

- **Originality:** adapt a format, never another creator's words. Pass any prompts that inspired the pack as `reference_prompts`; one that is 60% or more the same words is rejected.
- **No overclaims:** "guaranteed", "secret", "go viral", "100%" and similar are rejected.
- **Layout:** 1080×1350 on a midnight-navy background. Each slide has a white bold title, a muted benefit line, and a chat-style card with a cyan border. Prompt text is white at 30–34px, with placeholders in bold warm amber. Everything meets 4.5:1 contrast and must fit the card without clipping.
- **Audio:** music, if any, comes from Instagram's licensed library, added in the app.

`plan_utility_carousel(...)` returns the slide layers for a programmatic renderer, the caption and `problems`. If there are any problems, the plan is blocked. Nothing is posted without `post it`.
