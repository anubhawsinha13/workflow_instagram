"""Turn the finished slide images into one vertical reel. This does not publish."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REEL_WIDTH = 1080
REEL_HEIGHT = 1920
SLIDE_SECONDS = 3


def ffmpeg_bin() -> str:
    configured = shutil.which("ffmpeg")
    if configured:
        return configured
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(candidate).is_file():
            return candidate
    return ""


def _animate_slide(ffmpeg: str, slide: Path, dest: Path, seconds: float, zoom_in: bool) -> dict:
    frames = max(12, int(round(seconds * 30)))
    zoom = "min(zoom+0.0015,1.10)" if zoom_in else "if(eq(on,0),1.10,max(zoom-0.0015,1.0))"
    video_filter = ",".join(
        [
            f"scale={REEL_WIDTH}:1350:force_original_aspect_ratio=decrease",
            f"pad={REEL_WIDTH}:{REEL_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x10141C",
            "scale=2160:3840",
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={REEL_WIDTH}x{REEL_HEIGHT}:fps=30",
            "format=yuv420p",
        ]
    )
    command = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(slide),
        "-vf",
        video_filter,
        "-frames:v",
        str(frames),
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(dest),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return {"ok": False, "path": "", "error": "ffmpeg could not be started."}
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        detail = (completed.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else "ffmpeg did not animate a slide."
        return {"ok": False, "path": "", "error": reason[:240]}
    return {"ok": True, "path": str(dest), "error": ""}


def render_reel(folder: Path, seconds: float = SLIDE_SECONDS) -> dict:
    slides = sorted(folder.glob("slide-*.png"))
    if len(slides) < 2:
        return {"ok": False, "path": "", "error": "A reel needs the slide images."}
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return {"ok": False, "path": "", "error": "ffmpeg is not installed, so a reel cannot be assembled."}

    clips = folder / "reel-clips"
    clips.mkdir(exist_ok=True)
    clip_paths = []
    for index, slide in enumerate(slides):
        clip = clips / f"{slide.stem}.mp4"
        animated = _animate_slide(ffmpeg, slide, clip, seconds, zoom_in=index % 2 == 0)
        if not animated.get("ok"):
            return animated
        clip_paths.append(clip)

    listing = folder / "reel-concat.txt"
    listing.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clip_paths), encoding="utf-8")
    output = folder / "reel.mp4"
    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return {"ok": False, "path": "", "error": "ffmpeg could not be started."}
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        detail = (completed.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else "ffmpeg did not write a reel."
        return {"ok": False, "path": "", "error": reason[:240]}
    return {"ok": True, "path": str(output), "error": ""}
