# Platform surfaces

One approved script can become more than one file. Each file is a surface in [`platforms.py`](platforms.py). The safe box is the part a viewer still sees after that platform's own buttons and its profile crop.

Checked on 2026-10-13. Where two guides disagreed, the stricter number is the one in code.

## Instagram

| Surface | File | Safe box | Why |
|---|---|---|---|
| Reel | 1080×1920 | x 64–960, y 250–1500 | Buttons cover the top 220px, the right 120px, and the bottom 420px. The profile grid keeps the centre 1080×1440, which starts at y 240. |
| Story | 1080×1920 | inset 250px top and bottom | The reply bar is not the Reel caption. |
| Feed carousel | 1080×1350 | x 64–1016, y 80–1190 | 4:5 is the feed default. Slide 1 sets the ratio for every later slide, up to 20. The grid trims about 36px off each side of a 4:5 frame. |
| Grid-native | 1080×1440 | inset as in code | 3:4 is the only feed ratio the profile grid shows without a crop. |
| Square | 1080×1080 | 64px inset | Cross-posts to Threads and a LinkedIn still. |
| Landscape | 1080×566 | 48px and 36px inset | 1.91:1. A 16:9 frame is not this size and gets cropped. |

Caption limit is 2,200 characters. The feed shows about the first 125, so the first sentence has to land inside those 125. Hashtags stay at five.

Reels that run past about 90 seconds stop being pushed to people who do not follow the account. The practical length for a hook is under 30 seconds.

## Other surfaces

These are checked before a file is posted. The Slack agent does not publish them yet.

| Surface | File | Text |
|---|---|---|
| LinkedIn feed | 1080×1350 | 3,000 characters, about 210 visible. Video autoplays muted, so the words are on the picture. |
| LinkedIn link | 1200×627 | Link-preview shape, not an explainer. |
| X | 1080×1350 image, or 1280×720 video | 280 characters, all of them visible. |
| Threads | 1080×1080 | 500 characters, all visible. |
| YouTube | 1920×1080 | Title 100 characters. Description 5,000. |
| YouTube Short | 1080×1920 | Up to 3 minutes. Title over the lower frame, so type stays above y 1520. |
| TikTok | 1080×1920 | Same safe box as the Reel, so one vertical master can go to both. Caption cap 2,200. |
| Facebook Reel | 1080×1920 | Same safe box as the Instagram Reel. |
| Facebook feed | 1080×1350 | Preview cuts off near 477 characters. |
| Pinterest | 1000×1500 | 2:3. Description 800. The title fits on one line. |

## What the code does with this

`reel_spec.py` places the Reel inside `INSTAGRAM_REEL`. The host is scaled so the opaque pixels of every standing pose stay between the safe left edge and the text column. `explainer_render.py` uses the same fit, so a wide pose is not pushed off the left edge. `caption.py` takes the 2,200 limit from the feed surface.

`text_problems` rejects a caption whose first visible characters do not finish a sentence. `carousel_problems` rejects a set of slides that are not all the feed size.
