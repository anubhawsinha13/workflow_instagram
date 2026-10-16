"""A Reel with no narration still carries a silent audio track, so Instagram can attach a catalog song to it."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import explainer_render
from reel import ffmpeg_bin


def _streams(path: Path) -> list:
    ffprobe = str(Path(ffmpeg_bin()).with_name("ffprobe"))
    done = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, check=False)
    return done.stdout.split()


class SilentAudioTests(unittest.TestCase):
    def _payload(self, folder: Path) -> dict:
        still = folder / "still.png"
        Image.new("RGB", (90, 160), (180, 120, 80)).save(still)
        return {
            "renderer": {"canvas": {"width": 90, "height": 160, "fps": 6},
                         "scenes": [{"start_seconds": 0, "duration_seconds": 1.0, "camera": "steady", "elements": []}]},
            "output": str(folder / "reel.mp4"),
            "backdrop": {"shots": [{"start": 0, "duration": 1.0, "path": str(still)}], "mark": "none"},
        }

    def test_a_reel_without_narration_has_a_silent_audio_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = explainer_render.render_explainer(self._payload(Path(directory)))
            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(sorted(_streams(Path(result["path"]))), ["audio", "video"])
            self.assertFalse(result["has_audio"], "it is silent: has_audio still means narration")

    def test_a_narrated_reel_keeps_its_voice_and_gets_no_second_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            voice = folder / "voice.wav"
            subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(voice)], check=True)
            payload = self._payload(folder)
            payload["voiceover"] = str(voice)
            result = explainer_render.render_explainer(payload)
            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(_streams(Path(result["path"])).count("audio"), 1)
            self.assertTrue(result["has_audio"])


if __name__ == "__main__":
    unittest.main()
