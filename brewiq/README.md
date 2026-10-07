# BrewIQ carousel

Each run builds one Instagram package for BrewIQ (`@_brewiq`): a researched topic, six 1080×1350 slides, a caption, and music guidance. It posts only when you pass `--publish` or reply exactly `post it` to the agent.

## Run

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r brewiq/requirements.txt
.venv/bin/python brewiq/run.py
```

Optional topic:

```bash
.venv/bin/python brewiq/run.py --topic "A practical way to check an AI summary"
```

If Perplexity and OpenAI are unavailable, an interactive run asks once for a research markdown file. You can also skip the APIs:

```bash
.venv/bin/python brewiq/run.py --research brewiq/examples/sample_research.md
```

A scheduled run cannot ask a question. Put the file at `brewiq/inbox/research.md` before 8:00 a.m. local time, or the job writes a package marked not ready.

Copy `brewiq/research.template.md` when you write that file. A claim needs a real primary URL. Social links are not enough. The package says when the research came from markdown and was not re-checked live.

API keys are read from the repository `.env`. Research uses `PERPLEXITY_API_KEY`, then `OPENAI_API_KEY`. Illustrations try one provider at a time and wait up to 90 seconds: `gpt-image-2.5-sunburst` (quality medium), then Midjourney only if `MIDJOURNEY_API_URL` and `MIDJOURNEY_API_KEY` are both set, then `gemini-3.1-flash-image`. The first provider that returns an image is used for all six slides. `--art` skips the paid APIs. Missing keys do not invent sources or images.

Public JPEGs go to the YouTube Cloud Storage bucket at `instagram/brewiq/`. Instagram needs `IG_ACCESS_TOKEN` and `IG_USER_ID`. Without them, the script stops and does not claim a post.

## Package folder

`brewiq/output/YYYY-MM-DD/` contains:

- `research.md`
- `slide-01.png` through `slide-06.png`
- `caption.txt`
- `package.md`
- `package.json`

A second run on the same day uses a timestamped folder. `brewiq/history/index.jsonl` records ready posts so later runs can change category and skip repeats. If that file is missing, the run says history was not checked.

Phone review uses `brewiq/AGENT.md`. The Mac 8:00 a.m. login job stays until a Cursor cloud schedule is confirmed.

## Daily 8:00 a.m.

`brewiq/schedule/com.brewiq.daily.plist` is loaded on this Mac as `com.brewiq.daily`, at 8:00 in the Mac's local time. Check it with:

```bash
launchctl print gui/$(id -u)/com.brewiq.daily
```

If the Mac is asleep at 8:00, that morning's post is skipped. Run `python brewiq/run.py` yourself. The log is `brewiq/output/launchd.log`. Without API keys, the scheduled run stays not ready unless `brewiq/inbox/research.md` is in place.
