"""Narration for reels. The speech provider lives behind one function so a model swap touches this file only."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from reel import ffmpeg_bin

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# OpenAI lists dated gpt-4o-mini-tts snapshots as shutting down on 2027-01-06 and names
# gpt-realtime-2.1-mini as the replacement. The alias still works today. Set BREWIQ_VOICE_MODEL
# to change the model without editing code.
MODEL = (os.getenv("BREWIQ_VOICE_MODEL") or "gpt-4o-mini-tts").strip()
VOICE = (os.getenv("BREWIQ_VOICE") or "ash").strip()
INSTRUCTIONS = (
    "Adult male voice, warm and conversational, like a man in his thirties explaining something "
    "to a friend. Brisk, energetic social-video pace with short pauses, slight smile, "
    "clear emphasis on the key words."
)
# The 8-second signature Reel needs a punchier read with almost no pauses.
QUICK_INSTRUCTIONS = INSTRUCTIONS + " Fast, punchy delivery, almost no pauses between sentences."
QUICK_TRIM_FILTER = (
    "silenceremove=start_periods=1:start_threshold=-45dB:"
    "stop_periods=-1:stop_duration=0.12:stop_threshold=-45dB:stop_silence=0.06,atempo=1.18"
)
WORDS_PER_SECOND = 2.7
TRIM_FILTER = (
    "silenceremove=start_periods=1:start_threshold=-45dB:"
    "stop_periods=-1:stop_duration=0.25:stop_threshold=-45dB:stop_silence=0.18,atempo=1.08"
)


def _secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or "your_" in value or value.endswith("_here"):
        return ""
    return value


def _ffprobe() -> str:
    ffmpeg = ffmpeg_bin()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe")
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe") or ""


def estimate_seconds(text: str) -> float:
    """Spoken length when no audio exists yet."""
    return round(max(1.0, len(text.split()) / WORDS_PER_SECOND), 3)


def duration(path: Path) -> float:
    probe = _ffprobe()
    if not probe or not path.is_file():
        return 0.0
    completed = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return 0.0


def _request(client, text: str, dest: Path, instructions: str = INSTRUCTIONS) -> None:
    speech = client.audio.speech.create(
        model=MODEL,
        voice=VOICE,
        instructions=instructions,
        input=text,
        response_format="mp3",
    )
    dest.write_bytes(speech.read())


def speak(text: str, dest: Path, client=None, pace: str = "normal") -> dict:
    """Write one narration line to dest as a trimmed wav. Skips work that is already on disk."""
    if dest.is_file() and dest.stat().st_size > 0:
        return {"ok": True, "path": dest, "seconds": duration(dest), "cached": True, "error": ""}
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg is not installed, so narration could not be prepared."}
    if client is None:
        key = _secret("OPENAI_API_KEY")
        if not key:
            return {"ok": False, "error": "OPENAI_API_KEY is not set, so narration was not created."}
        from openai import OpenAI

        client = OpenAI(api_key=key, timeout=90)
    raw = dest.with_suffix(".mp3")
    try:
        _request(client, text, raw, QUICK_INSTRUCTIONS if pace == "quick" else INSTRUCTIONS)
    except Exception as exc:
        return {"ok": False, "error": _public(exc)}
    completed = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-af", QUICK_TRIM_FILTER if pace == "quick" else TRIM_FILTER, "-ar", "48000", "-ac", "1", str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        return {"ok": False, "error": "The narration could not be trimmed."}
    return {"ok": True, "path": dest, "seconds": duration(dest), "cached": False, "error": ""}


def build_track(segments: list, dest: Path) -> dict:
    """Join narration files into one track. Each segment is (path or None, seconds) and fills exactly that long."""
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg is not installed, so the narration track could not be built."}
    command = [ffmpeg, "-y", "-loglevel", "error"]
    chains = []
    labels = []
    for index, (path, seconds) in enumerate(segments):
        if path is not None and Path(path).is_file():
            command += ["-i", str(path)]
            chains.append(f"[{index}:a]apad=whole_dur={seconds:.3f},atrim=0:{seconds:.3f},asetpts=PTS-STARTPTS[a{index}]")
        else:
            command += ["-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=mono"]
            chains.append(f"[{index}:a]atrim=0:{seconds:.3f},asetpts=PTS-STARTPTS[a{index}]")
        labels.append(f"[a{index}]")
    chains.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    command += ["-filter_complex", ";".join(chains), "-map", "[out]", "-ar", "48000", "-ac", "1", str(dest)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        detail = completed.stderr.strip().splitlines()
        return {"ok": False, "error": (detail[-1] if detail else "The narration track could not be built.")[:240]}
    return {"ok": True, "path": dest, "error": ""}


def _public(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    lowered = text.lower()
    if not text or len(text) > 240 or any(word in lowered for word in ("api_key", "sk-", "secret", "bearer")):
        return "The speech request failed."
    return text
