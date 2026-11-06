"""The trained "Oye Chutku" detector (2026-10-11) and its use by the wake listener. Uses tiny hand-made weights
(always-yes / always-no), so the tests check the plumbing, not the trained model (scripts/train_wake.py tests that)."""
import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import numpy as np
import openwakeword

from chutku.voice import wakeword
from chutku.voice.handsfree import WakeListener
from chutku.voice.session import voice_session
from tests.test_handsfree import FakeStream


def model(folder, bias, two_stage=False):
    path = Path(folder) / "m.npz"
    np.savez(path, w1=np.zeros((1536, 4), np.float32), b1=np.zeros(4, np.float32), w2=np.zeros((4, 1), np.float32),
             b2=np.array([bias], np.float32), mean=np.zeros(1536, np.float32), std=np.ones(1536, np.float32),
             threshold=np.float32(0.7), meta=np.array(json.dumps({"trained": "test", "owner_clips": 0,
                                                                   "threshold": 0.7, "two_stage": two_stage})))
    return path


_FEATURES = Path(openwakeword.__file__).parent / "resources" / "models"
needs_features = unittest.skipUnless(
    all((_FEATURES / name).is_file() for name in ("melspectrogram.onnx", "embedding_model.onnx")),
    "openWakeWord's feature models are not installed (downloaded, not pip-installed); runs on a full install")


class DetectorTests(unittest.TestCase):
    @needs_features
    def test_fires_once_then_waits_two_seconds(self):
        with tempfile.TemporaryDirectory() as temp:
            detector = wakeword.Detector(model(temp, 10.0))
            silence = np.zeros(1600, np.int16).tobytes()
            fired = [detector.feed(silence) for _ in range(20)]     # 2 s of audio in 100 ms chunks
        self.assertEqual(fired.count(True), 1)

    @needs_features
    def test_never_fires_below_threshold(self):
        with tempfile.TemporaryDirectory() as temp:
            detector = wakeword.Detector(model(temp, -10.0))
            self.assertFalse(any(detector.feed(np.zeros(1600, np.int16).tobytes()) for _ in range(30)))
            self.assertLess(detector.best_score, 0.01)

    def test_model_file_holds_no_code(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.npz"
            np.savez(path, w1=np.array([object()], dtype=object))
            with self.assertRaises((ValueError, KeyError)):
                wakeword.Detector(path)   # allow_pickle=False: an object array is refused, never unpickled

    def test_available(self):
        self.assertFalse(wakeword.available(Path("does/not/exist.npz")))


class GateTests(unittest.TestCase):
    def test_a_model_that_fails_the_gate_is_never_chosen(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from train_wake import pick_threshold
        row = lambda owner, fph, near=0: {"recall_near": 0.95, "recall_far": 0.8, "owner_recall": owner,
                                           "false_wakes_per_hour": fph, "false_near_phrases": near}
        # 2026-10-12: this model (owner 44%, 69 false wakes/hour) was installed anyway and woke Chutku every minute.
        self.assertIsNone(pick_threshold({"0.8": row(0.444, 68.6, 1), "0.9": row(0.444, 44.4, 1)}))
        self.assertIsNone(pick_threshold({"0.9": row(0.95, 3.0)}))       # too many false wakes
        self.assertIsNone(pick_threshold({"0.9": row(0.8, 0.5)}))        # misses the owner too often
        self.assertEqual(pick_threshold({"0.7": row(0.9, 1.0), "0.9": row(1.0, 0.0)}), "0.9")


class ListenerTests(unittest.TestCase):
    def run_listener(self, model_path, seconds=1.5, heard_text=""):
        done, woke, transcribed = threading.Event(), [], []
        backend = types.SimpleNamespace(RawInputStream=lambda **_: FakeStream([0.05] * int(seconds * 10), done))
        listener = WakeListener(lambda command: woke.append(command),
                                lambda pcm: transcribed.append(pcm) or {"text": heard_text, "confidence": 0.8},
                                backend=backend)
        listener.detector_model = model_path
        with patch.object(voice_session, "quiet_for", return_value=5.0), \
                patch("chutku.voice.heard.log_heard") as logged:
            listener.start()
            done.wait(5)
            time.sleep(0.3)
            listener.stop()
            listener.join(2)
        return woke, transcribed, listener, logged

    @needs_features
    def test_detector_wakes_without_whisper(self):
        with tempfile.TemporaryDirectory() as temp:
            woke, transcribed, listener, logged = self.run_listener(model(temp, 10.0))
        self.assertEqual(listener.engine, "detector")
        self.assertTrue(woke)
        self.assertEqual(set(woke), {""})                # empty command: she beeps and listens
        self.assertEqual(transcribed, [])                # Whisper never ran
        self.assertEqual(logged.call_args[0][:3], ("wake", "(Oye Chutku)", "wake"))

    @needs_features   # without them the listener falls back to Whisper and these two pass without the detector
    def test_two_stage_wakes_only_when_whisper_hears_the_name(self):
        with tempfile.TemporaryDirectory() as temp:
            woke, transcribed, listener, _logged = self.run_listener(model(temp, 10.0, two_stage=True),
                                                                     heard_text="Oye Chutku")
        self.assertTrue(transcribed)                     # the second stage ran on the detector's own audio
        self.assertTrue(all(0 < len(pcm) <= wakeword.CONTEXT_SAMPLES * 2 for pcm in transcribed))
        self.assertTrue(woke)

    @needs_features
    def test_two_stage_rejects_a_look_alike(self):
        with tempfile.TemporaryDirectory() as temp:
            woke, transcribed, _listener, _logged = self.run_listener(model(temp, 10.0, two_stage=True),
                                                                      heard_text="Chotu, idhar aao")
        self.assertTrue(transcribed)
        self.assertEqual(woke, [])

    def test_broken_model_falls_back_to_whisper(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "bad.npz"
            bad.write_bytes(b"not a model")
            _woke, _t, listener, _l = self.run_listener(bad)
        self.assertEqual(listener.engine, "whisper")
        self.assertIn("wake detector", listener.error)


if __name__ == "__main__":
    unittest.main()
