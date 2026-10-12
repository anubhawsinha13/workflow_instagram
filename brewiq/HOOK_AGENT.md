# BrewIQ — Hook Selection Agent

Stage 04a of the BrewIQ workflow, between the Research Agent and the Script Agent. Input: the research brief and its five hooks. Output: a ranked hook list, the selected hook, and an action-first opening visual, validated by `hook_agent.py`.

## Task

For the verified story, evaluate the five hooks (curiosity gap, surprising fact, everyday problem, future implication, contrarian).

Score each 1–10 on:

- **Curiosity:** would someone stop scrolling?
- **Clarity:** is it understood in two seconds without technical knowledge?
- **Relatability:** does it connect to everyday life?
- **Visual potential:** can the first two seconds show it as action?

Then judge **factual accuracy** as a gate, not a score:

- `supported`: every claim in the hook is backed by the brief's verified facts. Cite them in `supported_by` by index.
- `partial`: true in part, but it implies something the facts don't support. Explain in `accuracy_note`.
- `unsupported`: not backed by the facts.

Only `supported` hooks can win. Select the highest-scoring supported hook and explain why.

## Opening visual

Describe the first two seconds as action already in progress:

- `first_frame`: what is moving when the reel opens. Never a title slide, logo, greeting, or static pose.
- `action`, `camera`, `on_screen_text` (8 words or fewer), and `narration`.
- `character_in_first_frame`: true or false. The BrewIQ host is a recognizable guide and does not need to be in frame one. If he enters later, say when in `character_entrance`.

Return JSON in the shape of `research_runs/2026-10-11.hooks.json`.

## Hook pool (20 hooks, top 5)

Use this when you want more hook options than the five research approaches.

1. Write at least 20 opening hooks for the first 1–3 seconds. Use at least 8 of these techniques: `curiosity_gap`, `surprising_fact`, `surprising_contrast`, `everyday_problem`, `specific_mistake`, `transformation`, `bold_opinion`, `narrative_tension`, `useful_promise`, `future_implication`, `contrarian`.
2. Score each hook 1–10 on `clarity`, `curiosity`, `relevance` (to this audience and story) and `keeps_right_viewer` (would the people who care keep watching?).
3. Give each hook `accuracy` and `supported_by`, the same as above.
4. Avoid misleading clickbait and empty phrases. Words like "shocking", "secret", "this changes everything" and "guaranteed" are rejected, and so are duplicates.

`hook_agent.select_from_pool(evaluations, brief, technique_bonus=learnings["technique_bonus"])` ranks the pool. It returns the top five eligible hooks, which `pool_to_brief_hooks` turns into `research["brief_hooks"]`. The technique bonus comes from measured past posts (see `PERFORMANCE_AGENT.md`) and is capped at ±0.5.

## Best hook per post type

`best_hook_for_post(research, post_type, learnings=None)` chooses one hook research already wrote. It never invents a line.

Candidates, in order: eligible `hook_evaluations` (only when `verified_facts` exist; partial and unsupported are skipped), else `brief_hooks`, else a single non-weak `research["hook"]`.

A line that is not catchy and intuitive loses first: template phrases ("stop scrolling", "watch this"), two or more technical words, a label with no verb, or a clarity score below 7. Among the lines that pass, technique fit comes next, then the research score, then the capped learning bonus. The on-screen hook is the first sentence in at most 8 words, with no ellipsis and no "Watch this". `POST_TECHNIQUE_RANK` is the fit order:

- `cinematic_3d`: surprising contrast, narrative tension, curiosity gap, then the rest
- `interactive_explainer`: curiosity gap, surprising fact, specific mistake, then everyday problem. The first frame shows that line on the laptop, not a host walking in.
- `tech_storytelling`: narrative tension, transformation, curiosity gap
- `motion_graphics`: useful promise, specific mistake, surprising fact, everyday problem
- `utility_carousel`: useful promise, specific mistake, everyday problem
- `slides`: curiosity gap, useful promise, surprising fact, everyday problem

`hooks_for_post_types` returns that choice for every post type. The operator still picks the style. `hook N` overrides the research pick. If research wrote no hook, the director asks for a template hook. Nothing is posted without exact `post it`.
