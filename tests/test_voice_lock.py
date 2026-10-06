"""Owner Voice Lock (master plan S19): a voice that is not the owner's cannot change anything without a click."""
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from chutku import mind
from chutku.agent_loop import VOICE_LOCK_REASON
from chutku.app import create_runtime
from chutku.core.preferences import Preferences
from chutku.policy.kernel import Decision
from chutku.voice import speaker

ROOT = Path(__file__).resolve().parents[1]


def unit(seed):
    vector = np.random.default_rng(seed).normal(size=256)
    return (vector / np.linalg.norm(vector)).astype(np.float32)


OWNER, STRANGER = unit(1), unit(2)
SPEECH = (np.random.default_rng(0).normal(size=16000 * 3) * 3000).astype(np.int16).tobytes()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.mind_root = patch.object(mind, "PROJECT_ROOT", self.base)
        self.mind_root.start()
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def enroll(self):
        path = speaker.voiceprint_path(self.base)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, OWNER)

    def lock(self, on=True):
        Preferences(self.base).update({"voice_lock": on})


class VerdictTests(Base):
    def test_off_or_not_enrolled_changes_nothing(self):
        with patch.object(speaker, "embed", return_value=STRANGER):
            self.assertEqual(speaker.is_owner(self.base, SPEECH), (None, None))   # off by default
            self.lock()
            self.assertEqual(speaker.is_owner(self.base, SPEECH), (None, None))   # on, but nobody enrolled

    def test_owner_and_stranger(self):
        self.enroll()
        self.lock()
        with patch.object(speaker, "embed", return_value=OWNER * 0.9 + STRANGER * 0.1):
            self.assertTrue(speaker.is_owner(self.base, SPEECH)[0])
        with patch.object(speaker, "embed", return_value=STRANGER):
            verified, score = speaker.is_owner(self.base, SPEECH)
            self.assertFalse(verified)
            self.assertLess(score, 0.55)

    def test_too_little_speech_is_not_the_owner(self):
        self.enroll()
        self.lock()
        self.assertEqual(speaker.is_owner(self.base, b"\x00\x00" * 8000), (False, None))   # fail closed

    def test_the_recent_utterance_is_what_gets_checked(self):
        self.enroll()
        self.lock()
        speaker.note_utterance(SPEECH)
        with patch.object(speaker, "embed", return_value=STRANGER) as embed:
            self.assertFalse(speaker.verify_recent(self.base)[0])
        self.assertEqual(embed.call_args[0][0], SPEECH)

    def test_enrollment_needs_six_clear_clips(self):
        with patch.object(speaker, "embed", return_value=OWNER), \
                patch.object(speaker, "voiced_seconds", side_effect=[3.0] * 5 + [0.5] * 3):
            with self.assertRaises(ValueError):
                speaker.enroll(self.base, [SPEECH] * 8)
        with patch.object(speaker, "embed", return_value=OWNER), patch.object(speaker, "voiced_seconds",
                                                                              return_value=3.0):
            self.assertEqual(speaker.enroll(self.base, [SPEECH] * 8), 8)
        self.assertAlmostEqual(speaker.cosine(speaker.load_voiceprint(self.base), OWNER), 1.0, places=5)

    def test_features_match_the_kaldi_layout(self):
        features = speaker.fbank(np.random.default_rng(3).normal(size=16000).astype(np.float32) * 0.1)
        self.assertEqual(features.shape, (98, 80))                      # 25 ms frames every 10 ms, 80 mel bands
        self.assertLess(float(np.abs(features.mean(axis=0)).max()), 1e-4)   # mean-normalised per band


class PolicyTests(Base):
    def decide(self, name, arguments, suspicious):
        tool = self.runtime.registry.get(name)
        with patch.object(self.runtime, "current_capability"):
            return self.runtime.authorize(tool, arguments, provenance="delegated_microphone", autonomy="owner",
                                          suspicious=suspicious)

    def test_a_stranger_voice_asks_for_every_change_in_owner_mode(self):
        result = self.decide("apps.launch", {"name": "Spotify"}, VOICE_LOCK_REASON)
        self.assertEqual(result.decision, Decision.CONFIRM)
        self.assertIn("did not sound like the owner", result.reason)
        self.assertEqual(self.decide("system.get_time", {}, VOICE_LOCK_REASON).decision, Decision.ALLOW)   # questions
        self.assertEqual(self.decide("apps.launch", {"name": "Spotify"}, False).decision, Decision.ALLOW)  # owner

    def test_only_the_owner_can_switch_the_lock_and_only_after_enrolling(self):
        tool = self.runtime.registry.get("settings.voice_lock")
        delegated = self.runtime.authorize(tool, {"on": False}, provenance="delegated_microphone", autonomy="owner")
        self.assertEqual(delegated.decision, Decision.DENY)   # a voice (anyone's) or the agent can never turn it off
        self.assertEqual(self.runtime.run("settings.voice_lock", {"on": True})["state"], "FAILED")   # not enrolled
        self.enroll()
        self.assertEqual(self.runtime.run("settings.voice_lock", {"on": True})["state"], "COMPLETED")
        self.assertTrue(speaker.settings(self.base)[0])

    def test_a_stranger_cannot_approve_by_voice_in_a_live_conversation(self):
        from chutku.voice.live import LiveConversation
        live = LiveConversation.__new__(LiveConversation)
        live._snapshot = lambda: {"status": "waiting_confirmation", "speaker_verified": False}
        self.assertIn("approved on screen", live._answer_approval(True)["error"])


class PrivacyTests(unittest.TestCase):
    def test_the_voiceprint_is_only_read_by_local_code(self):
        readers = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "chutku").rglob("*.py")
                         if re.search(r"load_voiceprint|voiceprint_path|voiceprint\.npy", p.read_text(encoding="utf-8")))
        self.assertEqual(readers, [str(Path("chutku/cli.py")), str(Path("chutku/dashboard.py")),
                                   str(Path("chutku/tools/voice_lock_tools.py")), str(Path("chutku/voice/speaker.py"))])
        for module in ("chutku/cloud_planner.py", "chutku/voice/live.py", "chutku/tools/internet.py"):
            self.assertNotIn("voiceprint", (ROOT / module).read_text(encoding="utf-8"))

    def test_threshold_preference_is_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            prefs = Preferences(Path(temp))
            with self.assertRaises(ValueError):
                prefs.update({"voice_lock_threshold": 1.5})
            self.assertEqual(prefs.update({"voice_lock_threshold": 0.6})["voice_lock_threshold"], 0.6)


if __name__ == "__main__":
    unittest.main()
