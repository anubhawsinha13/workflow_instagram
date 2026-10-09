"""One-off BrewIQ explainer: why AI can sound confident and still be wrong.

Steps: voice -> clips -> key -> sfx -> render. Each step skips work already on disk.
Run: python confident_wrong.py <step> [<out folder>]
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

HERE = Path(__file__).resolve().parent
BREWIQ = HERE.parent
sys.path.insert(0, str(BREWIQ))
load_dotenv(BREWIQ.parent / ".env")
load_dotenv(Path.home() / "Developer/agents/aegis-agent-platform/.env", override=False)

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "Developer/agents/aegis-agent-platform/runtime/explainers/confident-wrong"
VEO_MODEL = os.getenv("VEO_MODEL") or "veo-3.1-lite-generate-preview"
SCENE_PAD = 0.35
MIN_SCENE = {"check": 4.6, "takeaway": 4.9}

SCENES = [
    {
        "id": "hook",
        "voice": "This AI answer sounds sure. But confident isn't correct.",
        "clip_seconds": 6,
        "from_empty": True,
        "action": (
            "He walks into the frame from the left side and stops in the center. He turns toward the upper right "
            "and confidently presents with his open right palm raised toward the upper right of the frame. "
            "Then he notices something, tilts his head, and raises one eyebrow with a skeptical look, "
            "and finishes relaxed with his hands loosely together at his waist."
        ),
    },
    {
        "id": "check",
        "voice": "Let's check. Here's the claim, and here's the source.",
        "clip_seconds": 6,
        "action": (
            "He reaches up and to the right with his right hand, takes hold of the edge of an invisible floating page, "
            "and pulls it down beside his shoulder. He looks back and forth between that spot and the upper right, "
            "nods once, and returns his hands loosely together at his waist."
        ),
    },
    {
        "id": "mismatch",
        "voice": "They don't match. AI predicts likely words. When it doesn't check a source, it can fill gaps with guesses.",
        "clip_seconds": 8,
        "action": (
            "He leans in toward the upper right and narrows his eyes, looking quickly between two points as if comparing them. "
            "He frowns slightly, points his right index finger firmly at a spot in the upper right, "
            "then gives a small puzzled shrug and returns his hands loosely together at his waist."
        ),
    },
    {
        "id": "fix",
        "voice": "Many tests reward guessing over I don't know. So: check, compare, correct.",
        "clip_seconds": 8,
        "action": (
            "With a sweeping motion of his left hand he pushes something invisible away to his left. "
            "Then he makes a small precise tapping gesture in the air with his right index finger, "
            "his expression changes from concentration to relief, he smiles and gives a short satisfied nod, "
            "and returns his hands loosely together at his waist."
        ),
    },
    {
        "id": "takeaway",
        "voice": "Before you share a confident answer, check the source.",
        "clip_seconds": 6,
        "action": (
            "He points up toward the upper right with his right index finger and holds the point for a moment. "
            "Then he turns his head and looks straight into the camera with a warm, knowing smile and a small nod, "
            "and relaxes with his hands loosely together at his waist."
        ),
    },
]

CHARACTER = (
    "Stylized 3D animated film character: the same man as in the supplied frames, with the same face, short dark hair, "
    "light stubble, medium-brown complexion, black zip jacket over a charcoal t-shirt, and the same rendering style. "
    "Waist-up medium shot with a static locked-off camera. The background stays perfectly flat solid chroma-key green "
    "for the whole shot, with no shadows, props, objects, screens, text, or other people. "
    "Smooth, natural, deliberate body and hand movement. He does not speak; his mouth stays closed or in a slight smile. "
)


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def seconds(path: Path) -> float:
    probe = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(probe.stdout.strip())


def step_voice() -> None:
    from openai import OpenAI

    client = OpenAI()
    timing = []
    for index, scene in enumerate(SCENES, start=1):
        dest = OUT / f"voice-{index}.mp3"
        if not dest.is_file():
            speech = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="ash",
                instructions=(
                    "Adult male voice, warm and conversational, like a man in his thirties explaining something "
                    "to a friend. Brisk, energetic social-video pace with short pauses, slight smile, "
                    "clear emphasis on the key words."
                ),
                input=scene["voice"],
                response_format="mp3",
            )
            dest.write_bytes(speech.read())
        tight = OUT / f"voice-{index}.wav"
        run([
            FFMPEG, "-y", "-loglevel", "error", "-i", str(dest), "-af",
            "silenceremove=start_periods=1:start_threshold=-45dB:"
            "stop_periods=-1:stop_duration=0.25:stop_threshold=-45dB:stop_silence=0.18,atempo=1.08",
            "-ar", "48000", "-ac", "1", str(tight),
        ])
        timing.append({"id": scene["id"], "voice_seconds": round(seconds(tight), 3)})
    start = 0.0
    for item in timing:
        item["start"] = round(start, 3)
        item["duration"] = round(max(item["voice_seconds"] + SCENE_PAD, MIN_SCENE.get(item["id"], 0)), 3)
        start += item["duration"]
    (OUT / "timing.json").write_text(json.dumps(timing, indent=2))
    print(json.dumps({"total": round(start, 2), "scenes": timing}))


def _green_color(image: Image.Image) -> tuple:
    corners = [image.getpixel((8, 8)), image.getpixel((image.width - 8, 8)), image.getpixel((8, image.height // 3))]
    return tuple(sum(channel) // len(corners) for channel in zip(*corners))


def step_clips() -> None:
    from google import genai
    from google.genai import types

    host = OUT / "host-green.png"
    if not host.is_file():
        raise SystemExit("Required asset missing: host-green.png (the BrewIQ character on green).")
    empty = OUT / "empty-green.png"
    if not empty.is_file():
        Image.new("RGB", (720, 1280), _green_color(Image.open(host).convert("RGB"))).save(empty)
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    def image(path: Path):
        return types.Image(image_bytes=path.read_bytes(), mime_type="image/png")

    def make(index: int, scene: dict) -> str:
        dest = OUT / f"clip-{index}.mp4"
        if dest.is_file():
            return f"{scene['id']}: already made"
        config = types.GenerateVideosConfig(
            aspect_ratio="9:16",
            duration_seconds=scene["clip_seconds"],
            last_frame=image(host),
            negative_prompt="text, captions, props, papers, screens, background scenery, shadows, extra people, talking",
        )
        operation = client.models.generate_videos(
            model=VEO_MODEL,
            prompt=f"{CHARACTER}{scene['action']}",
            image=image(empty if scene.get("from_empty") else host),
            config=config,
        )
        deadline = time.monotonic() + 10 * 60
        while not operation.done:
            if time.monotonic() > deadline:
                return f"{scene['id']}: timed out"
            time.sleep(10)
            operation = client.operations.get(operation)
        if getattr(operation, "error", None):
            return f"{scene['id']}: {operation.error}"
        videos = getattr(operation.response, "generated_videos", None) if operation.response else None
        if not videos:
            return f"{scene['id']}: no video returned"
        client.files.download(file=videos[0].video, destination=str(dest))
        return f"{scene['id']}: saved {dest.name}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(make, index, scene) for index, scene in enumerate(SCENES, start=1)]
        for future in futures:
            try:
                print(future.result())
            except Exception as exc:  # report every clip, including quota errors
                print(f"error: {' '.join(str(exc).split())[:300]}")


POSES = {
    "walk_a": "walking mid-stride toward the right of the frame, body three-quarters to the right, left arm swinging forward and right arm back, friendly expression",
    "walk_b": "walking mid-stride toward the right of the frame, body three-quarters to the right, right arm swinging forward and left arm back, friendly expression",
    "present": "standing turned toward the upper right, proudly raising his open right palm toward the upper right of the frame as if presenting something, confident smile",
    "eyebrow": "standing and looking toward the upper right, one eyebrow raised high in doubt, the corner of his mouth pulled slightly down, right hand lifted to his chin",
    "reach": "reaching his right arm up and out toward the upper right with his fingers curled as if grabbing the edge of a floating page, focused expression",
    "hold": "holding his right hand up beside his right shoulder as if holding a page there, looking toward the upper right, attentive expression",
    "lean_point": "leaning forward toward the upper right with narrowed eyes and a slight frown, pointing his right index finger firmly toward the upper right",
    "shrug": "giving a puzzled shrug with both palms turned up, eyebrows raised, mouth slightly turned down, looking at the viewer",
    "push": "sweeping his left hand out to his left side with the palm out as if pushing something away, decisive expression, looking toward his left hand",
    "relief": "relieved and satisfied, smiling, giving a small thumbs up with his right hand at chest height, looking toward the upper right",
    "point_camera": "pointing his right index finger toward the upper right while looking straight at the viewer with a warm, knowing smile",
    "magnify": "holding a large round magnifying glass up in his left hand, on the right side of the image beside his face, the lens a bit larger than his head, peering toward it with curious, focused eyes. The lens is perfectly clear empty glass inside a thin black rim, so the flat green background shows straight through it with no reflection, tint, or highlight",
    "magnify_doubt": "holding a large round magnifying glass up in his left hand, on the right side of the image beside his face, the lens a bit larger than his head, eyebrows raised in doubt and mouth pulled to one side, looking toward it. The lens is perfectly clear empty glass inside a thin black rim, so the flat green background shows straight through it with no reflection, tint, or highlight",
    "pinch": "holding his left hand up at shoulder height on the right side of the image, pinching a tiny object between his thumb and index finger with the other fingers curled, looking at his fingertips with a skeptical frown. His fingertips hold nothing visible",
    "toss": "flicking his left hand up and out toward the upper right of the image with his fingers spread open as if he just tossed something away over his shoulder, playful satisfied smirk, looking at the viewer",
}

POSE_FRAME = (
    "Same character as this image: same face, hair, stubble, complexion, black zip jacket, charcoal t-shirt, "
    "colors, rendering style, and lighting. Same waist-up framing, same size in the frame, and the same perfectly "
    "flat chroma-key green background with no shadows, props, or text. New pose: "
)


def step_poses() -> None:
    from art import openai_edit_image

    host = OUT / "host-green.png"
    folder = OUT / "poses"
    folder.mkdir(exist_ok=True)

    def make(name: str, pose: str) -> str:
        dest = folder / f"{name}.png"
        if dest.is_file():
            return f"{name}: already made"
        result = openai_edit_image(host, f"{POSE_FRAME}{pose}.", require_reference=True)
        if not result.get("ok"):
            return f"{name}: {result.get('error')}"
        image = result["image"]
        width, height = image.size
        target = round(height * 9 / 16)
        left = (width - target) // 2
        image.crop((left, 0, left + target, height)).resize((720, 1280)).save(dest)
        return f"{name}: saved"

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for line in pool.map(lambda item: make(*item), POSES.items()):
            print(line)


LIBRARY_FRAME = (
    "Same character as this image: same face, hair, stubble, complexion, black zip jacket, charcoal t-shirt, "
    "colors, rendering style, and lighting. Waist-up framing with his head near the top, and generous empty space "
    "on both sides so his hands, elbows, and any prop stay fully inside the image. Perfectly flat chroma-key green "
    "background with no shadows, props, or text. New pose: "
)


def step_library() -> None:
    """Uncropped pose stills for the reusable explainer pose library in brand/poses."""
    from art import openai_edit_image
    from explainer_render import build_pose_library

    host = OUT / "host-green.png"
    folder = BREWIQ / "brand" / "poses-source"
    folder.mkdir(parents=True, exist_ok=True)
    poses = {"host-green": "standing relaxed and facing the viewer with both arms at his sides, friendly smile", **POSES}

    def make(name: str, pose: str) -> str:
        dest = folder / f"{name}.png"
        if dest.is_file():
            return f"{name}: already made"
        result = openai_edit_image(host, f"{LIBRARY_FRAME}{pose}.", require_reference=True)
        if not result.get("ok"):
            return f"{name}: {result.get('error')}"
        result["image"].convert("RGB").save(dest)
        return f"{name}: saved"

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for line in pool.map(lambda item: make(*item), poses.items()):
            print(line)
    print(json.dumps(build_pose_library(folder)))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    steps = {"voice": step_voice, "clips": step_clips, "poses": step_poses, "library": step_library}
    if step not in steps:
        raise SystemExit(f"Choose a step: {', '.join(steps)}")
    steps[step]()
