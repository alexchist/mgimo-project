import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave


REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "docs" / "media-ux" / "fixtures"
HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
ASR_MODEL = os.environ.get("STRATEGIST_WHISPER_MODEL")


class MediaTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def call(self, script, *args, code=0, offline_path=False):
        env = os.environ.copy()
        if offline_path:
            env["PATH"] = str(self.root / "empty-bin")
        result = subprocess.run([sys.executable, "-B", str(REPO / "tools" / script), *map(str, args)],
                                capture_output=True, text=True, env=env, timeout=150)
        self.assertEqual(result.returncode, code, result.stderr or result.stdout)
        return result

    def prepare(self, fixture, bundle, *extra, **options):
        result = self.call("media.py", "prepare", FIXTURES / fixture, "--output", bundle,
                           "--origin", "synthetic", *extra, **options)
        return json.loads(result.stdout)

    def test_offline_image_can_be_cited_after_moving_case(self):
        case = self.root / "case"
        self.call("strategist.py", "init", case, "--slug", "media-test")
        bundle = case / "sources" / "media" / "screen"
        manifest = self.prepare("family-step-1.png", bundle, offline_path=True)
        self.assertEqual((bundle / "original.png").read_bytes(), (FIXTURES / "family-step-1.png").read_bytes())
        self.assertFalse(manifest["network_used"])
        self.call("media.py", "prepare", FIXTURES / "family-step-2.png", "--output", bundle,
                  "--origin", "synthetic", code=2)
        self.assertEqual(json.loads((bundle / "manifest.json").read_text(encoding="utf-8")), manifest)
        self.call("media.py", "ingest", case, bundle)
        self.call("media.py", "ingest", case, bundle, code=2)
        entries = json.loads((case / "sources" / "index.json").read_text(encoding="utf-8"))
        source, = entries
        self.assertEqual(source["source_id"], "S-001")
        self.assertTrue(source["synthetic"])
        with (case / "evidence" / "claims.csv").open("a", encoding="utf-8", newline="") as target:
            csv.writer(target).writerow(["E-001", "fact", "Первый экран показывает 300 ₽", "S-001",
                                         "S-001#image:1", "", "", "active", "", "Учебный макет"])
        moved = self.root / "moved"
        case.rename(moved)
        bundle = moved / "sources" / "media" / "screen"
        self.call("strategist.py", "check", moved)
        self.call("media.py", "check", bundle, "--project", moved)
        manifest["origin"] = "open-public"
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.call("media.py", "check", bundle, "--project", moved, code=2)

    def test_missing_media_tools_preserve_original(self):
        bundle = self.root / "missing"
        manifest = self.prepare("family-walkthrough.mp4", bundle, offline_path=True, code=2)
        self.assertEqual(manifest["frames"]["status"], "unavailable")
        self.assertEqual(manifest["audio"]["status"], "unavailable")
        self.assertEqual(manifest["transcript"]["status"], "not_requested")
        self.assertEqual((bundle / "original.mp4").read_bytes(), (FIXTURES / "family-walkthrough.mp4").read_bytes())
        self.call("media.py", "check", bundle)

    @unittest.skipUnless(HAS_FFMPEG, "Требуются ffmpeg и ffprobe")
    def test_sampled_pts_and_separate_sound_are_checkable(self):
        case = self.root / "case"
        self.call("strategist.py", "init", case, "--slug", "media-test")
        bundle = case / "sources" / "media" / "video"
        manifest = self.prepare("family-walkthrough.mp4", bundle)
        self.assertEqual(manifest["transcript"]["status"], "not_requested")
        self.assertEqual([frame["source_seconds"] for frame in manifest["frames"]["items"]], [0, 2.5, 5, 7.5])
        self.assertNotEqual(manifest["frames"]["items"][0]["sha256"], manifest["frames"]["items"][2]["sha256"])
        with wave.open(str(bundle / "audio.wav"), "rb") as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
            self.assertGreater(wav.getnframes(), 9 * 16000)
        self.call("media.py", "ingest", case, bundle)
        self.call("strategist.py", "check", case)
        extract = (case / "sources" / "extracts" / "S-001.md").read_text(encoding="utf-8")
        self.assertIn("`frame:5.000`", extract)
        self.assertIn("`audio:track`", extract)
        (bundle / "frames" / "003.png").write_bytes(b"changed")
        self.call("media.py", "check", bundle, code=2)

    @unittest.skipUnless(HAS_FFMPEG, "Требуются ffmpeg и ffprobe")
    def test_missing_stt_model_is_explicit(self):
        manifest = self.prepare("family-voice.wav", self.root / "audio",
                                "--whisper-model", self.root / "missing.bin", code=2)
        self.assertEqual(manifest["audio"]["status"], "ready")
        self.assertEqual(manifest["transcript"]["status"], "unavailable")
        self.assertNotIn("segments", manifest["transcript"])

    @unittest.skipUnless(HAS_FFMPEG and ASR_MODEL and shutil.which("whisper-cli"),
                         "Для подлинного STT нужны whisper-cli и STRATEGIST_WHISPER_MODEL")
    def test_real_asr_returns_timed_utterances_from_wav(self):
        bundle = self.root / "audio"
        manifest = self.prepare("family-voice-en.wav", bundle, "--whisper-model", ASR_MODEL, "--language", "en")
        transcript = manifest["transcript"]
        self.assertEqual(transcript["status"], "ready")
        self.assertEqual(transcript["engine"], "whisper-cli")
        self.assertTrue((bundle / "whisper.json").is_file())
        for segment in transcript["segments"]:
            self.assertLess(segment["start_ms"], segment["end_ms"])
            self.assertLessEqual(segment["end_ms"], manifest["duration_seconds"] * 1000)
            self.assertTrue(segment["text"])
        self.call("media.py", "check", bundle)

    def test_vision_needs_upload_opt_in_and_records_missing_cli(self):
        bundle = self.root / "image"
        self.prepare("family-step-1.png", bundle, offline_path=True)
        output = self.root / "review"
        self.call("media_vision.py", bundle, "--output", output, offline_path=True, code=2)
        self.assertFalse(output.exists())
        result = self.call("media_vision.py", bundle, "--output", output, "--allow-upload", offline_path=True, code=2)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "unavailable")
        self.assertEqual(receipt["attachments"][0]["bytes"], (FIXTURES / "family-step-1.png").stat().st_size)
        self.assertFalse((output / "review.md").exists())


if __name__ == "__main__":
    unittest.main()
