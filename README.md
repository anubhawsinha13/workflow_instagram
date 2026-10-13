# Instagram Video Generation Workflow

Automated workflow for generating Instagram videos using AI-powered research, scriptwriting, and video assembly.

## Architecture

The workflow consists of 3 stages:

1. **Research (Perplexity API)**: Generates a compelling narrative-style story (~300 words) based on a topic
2. **Scripting (OpenAI API)**: Transforms the story into a structured script with 5 scenes, text overlays, background prompts, and voiceover cues
3. **Video Assembly (Creatomate API with ElevenLabs)**: Merges script components into final video using Creatomate's ElevenLabs integration

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

3. **Set up Creatomate template:**
   - Create a template in Creatomate dashboard
   - Configure ElevenLabs integration in the template
   - Note the Template ID and element names (e.g., "Primary-Text-1", "Voiceover-1", "Background-Media-1")
   - Update `CREATOMATE_TEMPLATE_ID` in `.env`

## Usage

### Agent (Recommended): trigger workflow + show topic/images

```bash
python3 execution/agent.py "The history of coffee" --dry-run
```

This runs research → script → visuals, then prints the topic and the images to be generated. It also writes:

- `projects/<project>/preview/preview.md`
- `projects/<project>/preview/preview.html`
- `artifacts/<project>_agent_summary.json`

Options:
- `--rotate-topic`: cycle built-in topics when none is provided (good for automations)
- `--render-video`: continue through Creatomate after the preview
- `--json`: emit a machine-readable summary

See `AGENTS.md` and `automations/instagram-topic-image-agent.md` for Cursor Automation setup.

### Full Workflow

Run all stages in sequence:

```bash
python3 execution/generate_instagram_video.py "The history of coffee"
```

Options:
- `--project-name`: Specify project name (auto-generated from topic if not provided)
- `--no-download`: Skip downloading the final video
- `--skip-video`: Stop after topic/image preview
- `--dry-run`: Use offline stubs when APIs are unavailable

### Individual Stages

**Stage 1: Research**
```bash
python execution/research_topic.py "The history of coffee" "coffee_history"
```

**Stage 2: Script Generation**
```bash
python execution/generate_script.py projects/coffee_history/research/research_*.json
```

**Stage 3: Video Generation**
```bash
python execution/generate_video.py projects/coffee_history/script/script_*.json
```

## Project Structure

```
workflow_instagram/
├── execution/
│   ├── agent.py                    # Agent: trigger + show topic/images
│   ├── research_topic.py           # Stage 1: Research with Perplexity
│   ├── generate_script.py          # Stage 2: Script generation (OpenAI/Gemini)
│   ├── generate_visuals.py         # Stage 2.5: Plan/generate scene images
│   ├── generate_video.py           # Stage 3: Video generation with Creatomate
│   ├── generate_instagram_video.py # Full workflow script
│   └── preview_report.py           # Topic + image preview (md/html)
├── automations/
│   └── instagram-topic-image-agent.md
├── projects/{project_name}/...
├── artifacts/                      # Agent summaries + shared previews
├── AGENTS.md
├── requirements.txt
├── .env.example
└── README.md
```

## API Keys Required

- **Perplexity API**: For research and story generation
- **OpenAI API**: For script generation
- **ElevenLabs API**: For voiceover (used via Creatomate)
- **Creatomate API**: For video rendering

## Creatomate Template Configuration

Your Creatomate template should include:

- **Text Elements**: For on-screen captions (e.g., "Primary-Text-1", "Text-1")
- **Background Media Elements**: For visuals (e.g., "Background-Media-1", "Image-1", "Video-1")
- **Audio Elements**: Configured with ElevenLabs provider (e.g., "Voiceover-1")

The script will pass:
- Text directly to voiceover elements (Creatomate calls ElevenLabs internally)
- URLs to background media elements
- Text to overlay elements

## Notes

- The workflow automatically creates project folders and saves all outputs
- Each stage can be run independently for debugging or manual review
- Video rendering may take 1-5 minutes depending on complexity
- Background media URLs are placeholders - in production, integrate with stock footage APIs (Pexels, Unsplash) or AI image generation
