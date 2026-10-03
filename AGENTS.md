# Instagram Workflow Agent

This repository contains an agent that triggers the Instagram video workflow and surfaces the **topic** plus the **images to be generated** before (or instead of) final video rendering.

## What the agent does

1. Chooses or accepts a topic
2. Runs research → script → visuals
3. Prints / writes a preview of:
   - the topic
   - each scene overlay
   - image prompts / generated image files
4. Optionally continues to Creatomate video render

## Run it

```bash
# Preview-first (recommended): shows topic + images
python3 execution/agent.py "The history of coffee" --dry-run

# Rotate built-in topics (useful for scheduled automations)
python3 execution/agent.py --rotate-topic --dry-run

# Continue through video rendering
python3 execution/agent.py "The history of coffee" --render-video

# Machine-readable summary
python3 execution/agent.py "The history of coffee" --dry-run --json
```

## Outputs to inspect

- `projects/<project>/preview/preview.md` — topic + image plan
- `projects/<project>/preview/preview.html` — visual preview
- `projects/<project>/visuals/` — image files (placeholder SVG in dry-run)
- `artifacts/<project>_agent_summary.json` — compact agent summary

## Cloud / automation instructions

When this agent is triggered (schedule, webhook, or chat):

1. Run `python3 execution/agent.py --rotate-topic` (or use a provided topic).
2. Prefer preview-first: do **not** pass `--render-video` unless credentials and template are confirmed.
3. In the final response, always show:
   - Topic
   - Scene list with overlay text
   - Image prompts and local image paths
   - Links/paths to `preview.md` / `preview.html`
4. If API keys are missing, rerun with `--dry-run` and still show the topic + planned images.
5. Do not invent Creatomate render URLs. Only report video status when the video stage actually ran.

## Full workflow stages

```bash
python3 execution/research_topic.py "Topic" [project_name]
python3 execution/generate_script.py projects/<project>/research/research_*.json
python3 execution/generate_visuals.py projects/<project>/script/script_*.json
python3 execution/generate_video.py projects/<project>/script/script_*.json --visuals-json projects/<project>/visuals/visuals_*.json
```

Or all at once:

```bash
python3 execution/generate_instagram_video.py "Topic"
```
