# BrewIQ — Performance Agent

Covers UC-004 and EXP-005. It runs weekly, after posts have had at least 72 hours of reach. Input: the recent BrewIQ posts and their insights. Output: what we can confidently conclude, what we can't know, the three highest-priority changes, and measured learnings for the next plan. Validated by `performance_agent.py`.

## Inputs

For each post:

- `post_id` and `published`;
- `experiment` (`EXP-###`; required, so the result is recorded);
- `format` (`reel`, `carousel`, `utility_carousel`), `style` and `hook_technique`;
- `hook_text` and `duration_seconds`;
- `metrics`: `reach`, `saves`, `sends`, `comments`, `follows`, `avg_watch_seconds` and `hold_3s` (0–1).

`from_graph_insights(media, insights, ...)` maps Graph API media insights (`reach`, `saved`, `shares`, `comments`, `follows`, `ig_reels_avg_watch_time`) to these fields. The API doesn't report a 3-second hold, so enter it from the in-app insights screen when you have it.

## Rules

- Posts with reach under 300 are listed, but their rates aren't used.
- With fewer than three reliable posts there is no baseline and no conclusion.
- Each post is compared with the account's own median. A rate 1.25 times the median or more is a strength; 0.8 times or less is a weakness.
- Formats are compared with each other. Styles and hook techniques are only compared within one format, so a carousel's high send rate is never credited to a hook technique.
- Every comparison is labelled **Directional**, with post counts. Nothing is called significant at these sample sizes.
- The review always says what can't be separated: topic, timing, audio and distribution.

## Outputs

- `priority_changes`: up to three, ordered by how many reliable posts fall below the median on each metric. They cover the opening, pacing, share value, save value, conversation or series.
- `learnings`:
  - `technique_bonus`, capped at ±0.5, which feeds `hook_agent.select_from_pool`;
  - `preferred_format`;
  - `preferred_style`.
- `experiment_record(review, "EXP-###", decision=...)`: store it as `research_runs/<date>.performance.json` and update the experiment row in `docs/identifiers/REGISTRY.md`.
