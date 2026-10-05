import json
import shutil
import tempfile
import types
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from chutku.voice import recognition, whisper_stt


def chunk(level):
    return array("h", [int(level * 32767)] * 1600).tobytes()


class FakeStream:
    def __init__(self, levels):
        self.levels = list(levels)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _frames):
        self.reads += 1
        return chunk(self.levels.pop(0) if self.levels else 0.0), False


class Control:
    def check(self):
        pass


def fake_sd(stream):
    return types.SimpleNamespace(RawInputStream=lambda **_: stream,
                                 default=types.SimpleNamespace(device=(1, 1)),
                                 query_devices=lambda *_: {"name": "mic", "hostapi": 0, "default_samplerate": 16000})


class EndpointingTests(unittest.TestCase):
    def capture(self, levels):
        stream = FakeStream(levels)
        with patch.dict("sys.modules", {"sounddevice": fake_sd(stream)}):
            result = recognition.capture(Control())
        return result, stream.reads

    def test_stops_shortly_after_speech_ends(self):
        result, reads = self.capture([0.0] * 5 + [0.2] * 15 + [0.0] * 30)
        self.assertEqual(reads, 5 + 15 + 9)
        self.assertTrue(result["activity"]["speech_detected"])
        self.assertEqual(len(result["pcm"]), reads * 3200)

    def test_gives_up_when_nobody_speaks(self):
        _, reads = self.capture([0.0] * 200)
        self.assertEqual(reads, recognition.WAIT_FOR_SPEECH_SECONDS * 10 + 1)

    def test_never_exceeds_maximum(self):
        _, reads = self.capture([0.3] * 500)
        self.assertEqual(reads, recognition.MAX_CAPTURE_SECONDS * 10)

    def test_single_click_is_not_speech(self):
        _, reads = self.capture([0.0, 0.5, 0.0] + [0.0] * 200)
        self.assertEqual(reads, recognition.WAIT_FOR_SPEECH_SECONDS * 10 + 1)


class TranscribeTests(unittest.TestCase):
    captured = {"pcm": chunk(0.2) * 20, "wav": "", "activity": {"speech_detected": True}}

    def test_whisper_preferred(self):
        with patch("chutku.voice.whisper_stt.transcribe_pcm",
                   return_value={"text": "Spotify kholo.", "confidence": 0.8, "engine": "whisper:small"}) as w:
            heard = recognition.transcribe(self.captured)
        self.assertEqual(heard["text"], "Spotify kholo.")
        w.assert_called_once()

    def test_falls_back_to_windows_dictation(self):
        with patch("chutku.voice.whisper_stt.transcribe_pcm", side_effect=whisper_stt.WhisperUnavailable("none")), \
                patch.object(recognition, "recognize", return_value={"text": "open spotify", "confidence": 0.9}) as r:
            heard = recognition.transcribe(self.captured)
        self.assertEqual(heard["text"], "open spotify")
        r.assert_called_once()

    def test_silence_never_reaches_a_recognizer(self):
        with patch("chutku.voice.whisper_stt.transcribe_pcm") as w, patch.object(recognition, "recognize") as r:
            heard = recognition.transcribe({**self.captured, "activity": {"speech_detected": False}})
        self.assertEqual(heard["text"], "")
        w.assert_not_called()
        r.assert_not_called()


class NoiseGuardTests(unittest.TestCase):
    def test_brief_noise_is_not_speech(self):
        frames = [chunk(0.2)[:640]] * 8 + [chunk(0.0)[:640]] * 100  # 160 ms burst
        self.assertFalse(recognition.analyze_pcm(frames)["speech_detected"])

    def test_known_hallucinations_are_discarded(self):
        segment = types.SimpleNamespace(text=" Thank you.", avg_logprob=-0.2, no_speech_prob=0.1)
        model = types.SimpleNamespace(transcribe=lambda *a, **k: (
            iter([segment]), types.SimpleNamespace(language="en", language_probability=0.9)))
        with patch.object(whisper_stt, "_load", return_value=(model, {"name": "test"})):
            heard = whisper_stt.transcribe_pcm(chunk(0.2) * 10)
        self.assertEqual(heard["text"], "")


class IntegrityTests(unittest.TestCase):
    def test_tampered_model_is_not_loaded(self):
        from chutku.app import PROJECT_ROOT
        real = PROJECT_ROOT / "models/faster-whisper-small"
        if not real.is_dir():
            self.skipTest("Whisper model not installed")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "models").mkdir()
            copy = base / "models/faster-whisper-small"
            copy.mkdir()
            for name in ("config.json", "vocabulary.txt"):
                shutil.copy(real / name, copy / name)
            manifest = json.loads((PROJECT_ROOT / "models/manifest.json").read_text(encoding="utf-8"))
            (base / "models/manifest.json").write_text(json.dumps({"stt": manifest["stt"]}), encoding="utf-8")
            whisper_stt._loaded.update(key=None, model=None)
            with self.assertRaisesRegex(whisper_stt.WhisperUnavailable, "integrity"):
                whisper_stt._load(base)


if __name__ == "__main__":
    unittest.main()


class PhraseScoringTests(unittest.TestCase):
    def test_case_and_punctuation_are_not_speech_errors_but_words_are(self):
        from chutku.voice.recognition import normalise_phrase as n
        self.assertEqual(n("Open Notepad."), n("open notepad"))
        self.assertEqual(n("GPU  status!"), "gpu status")
        self.assertNotEqual(n("What time it is?"), n("what time is it"))
        self.assertNotEqual(n("Open calculator now"), n("open calculator"))
