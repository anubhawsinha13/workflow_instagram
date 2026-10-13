# Execution scripts

| Script | Stage | Purpose |
|--------|-------|---------|
| `agent.py` | Agent entrypoint | Trigger workflow and show topic + images |
| `research_topic.py` | 1 | Research/story generation |
| `generate_script.py` | 2 | 5-scene script JSON |
| `generate_visuals.py` | 2.5 | Plan/generate scene images |
| `generate_video.py` | 3 | Creatomate render |
| `generate_instagram_video.py` | All | End-to-end orchestration |
| `preview_report.py` | Preview | Markdown/HTML topic+image report |
| `verify_setup.py` | Setup | Dependency/key checks |

Primary command:

```bash
python3 execution/agent.py "Your topic" --dry-run
```
