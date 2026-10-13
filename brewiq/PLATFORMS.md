# Platform surfaces

One approved script becomes five files. Thirteen platforms share those files. Each file is composed for its own ratio. A 16:9 frame is not a crop of the 9:16 frame.

The ratios are the ones in the one-post diagram. Caption limits are the 2026 posting rules gathered on 2026-10-13. Where two guides disagreed, the stricter number is the one in [`platforms.py`](platforms.py).

| Shape | File | Platforms | Safe box |
|---|---|---|---|
| 4:5 | 1080×1350 | Instagram, Facebook, Reddit | x 64–1016, y 80–1190 |
| 16:9 | 1920×1080 | YouTube, Google Business | 64px inset |
| 1:1 | 1080×1080 | LinkedIn, X, Telegram | 64px inset |
| 9:16 | 1080×1920 | TikTok, Threads, Discord | x 64–960, y 250–1500 |
| 2:3 | 1080×1620 | Pinterest, WhatsApp | x 48–1032, y 64–1500 |

`PACK` is these five shapes. `post it` names the piece. The Instagram file is the 4:5 frame.

## Why the vertical safe box is smaller

Buttons cover the top of a 9:16 video, the right edge, and the bottom. The host and the hook stay inside x 64–960 and y 250–1500. `reel_spec.py` and `explainer_render.py` still draw the motion explainer on this canvas. The surface is `VERTICAL`. It is the TikTok, Threads, and Discord file. It is not the Instagram file.

## Captions

| Platform | Limit | What the viewer sees first |
|---|---|---|
| Instagram | 2,200 | about 125 characters, so the first sentence lands inside that |
| Facebook | 63,206 | about 477 |
| Reddit | 40,000 | about 300 |
| YouTube | 5,000 | the title, about 100 |
| Google Business | 1,500 | about 150 |
| LinkedIn | 3,000 | about 210 |
| X | 280 | all of it |
| Telegram | 1,024 | about 200 |
| TikTok | 2,200 | about 80 |
| Threads | 500 | all of it |
| Discord | 2,000 | about 200 |
| Pinterest | 800 | the title, about 100 |
| WhatsApp | 700 | about 140 |

Hashtags on the Instagram caption stay at five. The feed carousel uses the 4:5 file, up to 20 slides, and slide 1 sets the ratio.

## What the code does with this

`shape_pack.py` draws the five stills from one script and rejects a frame whose ink leaves the safe box or the outer 24px. `caption.py` takes the 2,200 limit from the Instagram 4:5 surface. `text_problems` rejects a caption whose first visible characters do not finish a sentence. `carousel_problems` rejects a set of slides that are not all the 4:5 size.

The host on the motion explainer is scaled so the opaque pixels of every standing pose stay between the safe left edge and the text column.
