# BrewIQ — Learning loop and weekly test plan

Covers PROB-007, UC-007 (weekly learning loop), UC-008 (weekly test plan), PH-004 and EXP-006. The Performance Agent measures; this loop makes the agent remember and use what it measured. Validated by `learning_loop.py` and `weekly_planner.py`.

## The loop

```text
plan_week (5–7 posts, each an EXP-### test)
    → produce and post (operator still picks style and hook; nothing ships without `post it`)
    → 72h+ later: weekly_review(posts)
         → review_posts (performance_agent)
         → research_runs/learnings.json        ← memory, committed to the repo
         → research_runs/<date>.performance.json (one experiment_record per EXP)
         → rule proposals after 3 reviews in a row
    → next plans load learnings.json automatically
```

## Memory

`research_runs/learnings.json` holds the latest `technique_bonus`, `bonus_metric`, `preferred_format`, `preferred_style` and `priority_changes`, the experiments it came from, up to 26 weekly history entries and the rule proposals. It's committed, so every change to what the agent "believes" shows up in a diff.

- `load_learnings()` returns empty learnings when the file is missing.
- `update_learnings(previous, review, ...)` keeps the previous bonus, format and style when a review measured nothing new.
- A blocked review (too few reliable posts, missing experiment IDs) changes nothing.

## Applied automatically

Pass `learnings=load_learnings()` on every request:

| Where | What changes |
|---|---|
| `research_agent.build_research_prompt(today, recent, learnings=)` | Adds a "LEARNINGS FROM THE LAST PERFORMANCE REVIEW" block: priority changes, techniques that measured better or worse, the leading format and style. |
| `hook_agent.select_from_pool(..., learnings=)` | Uses the learned `technique_bonus` (capped at ±0.5) unless one is passed explicitly. |
| `cinematic_director.recommend_style(topic, research, learnings=)` | The learned style is recommended after the brief's suggested style and the architecture rule, before topic heuristics. |
| `cinematic_director.plan_reel(..., learnings=)` / `slack_director.start_or_continue(..., learnings=)` | `learnings_applied` lists what was applied; Slack shows it under "Applied from the last review". |

Learnings only adjust scores and recommendations. They never override the accuracy, clickbait, brand or posting gates, and the operator still picks the style and hook.

## Weekly test plan

`weekly_planner.plan_week(candidates, week_of=date, learnings=..., posts=5..7)` turns candidate topics into 5–7 posts. Each slot has a day, topic, format, style, hook technique, `EXP-###`, hypothesis, primary metric, role and a one-line test.

- Two utility carousels a week (EXP-003, send rate); three when the last review found carousels lead.
- With no learnings, every slot is a baseline that rotates technique and style.
- With learnings, reels alternate between **exploit** (EXP-006: the best technique in the learned style) and **explore** (EXP-004: an untested or weaker technique in another style). At least two explore slots, and at least one exploit reel.
- `week_problems(plan)` blocks the plan on: fewer than 5 or more than 7 posts, a missing topic, an unknown experiment or mismatched hypothesis, a metric that isn't a rate, a reel without a style, duplicate topics, fewer than 2 formats or 3 techniques, fewer than 2 explore slots, or identical consecutive slots.
- `post_labels(slot)` gives the labels for `performance_agent.from_graph_insights`, so the next review can group posts by experiment.
- `format_week_for_slack(plan)` is the Slack message. The plan is a proposal: each post still goes through the normal hook and style choice.

## Rule proposals

A signal (a priority area, a strong hook technique, a leading format or style) seen in 3 consecutive reviews becomes a proposal such as `technique:curiosity_gap`. It changes nothing by itself.

1. The weekly review lists it with `approve rule <id>` / `reject rule <id>`.
2. `slack_director.parse_rule_reply(text)` reads the reply; `set_rule_status(learnings, id, status)` records it and `save_learnings` writes the file.
3. An approved rule ships as a PR that edits the prompt or gate, with a `DEC-###` record in `docs/identifiers/REGISTRY.md`. Approved and rejected decisions are kept in later reviews.

## EXP-006

- **Hypothesis (PH-004):** applying stored learnings automatically raises the median send rate (and save rate) over four weekly cycles, against the first baseline week.
- **Metric:** median sends and saves per reach of reliable posts (reach ≥300), with the 3-second hold as a guard.
- **Kill criterion:** after four reviews, no improvement over the baseline week, or the 3-second hold falls more than 20%.
- **Record:** each weekly `experiment_record` under `research_runs/` and the EXP-006 row in the registry.
