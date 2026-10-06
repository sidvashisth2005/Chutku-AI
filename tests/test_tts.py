"""Chutku's neural voice (master plan S10 service): Kokoro first, Windows SAPI as the never-silent fallback."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from chutku import mind
from chutku.core.preferences import Preferences
from chutku.tools import speech
from chutku.voice import tts


class SentenceTests(unittest.TestCase):
    def test_split_on_full_stops_questions_and_the_danda(self):
        self.assertEqual(tts.sentences("Ho gaya! Aur kuch? ठीक है। मैं देखती हूँ।"),
                         ["Ho gaya!", "Aur kuch?", "ठीक है।", "मैं देखती हूँ।"])

    def test_a_very_long_sentence_is_cut_at_commas_for_quick_first_audio(self):
        long = ", ".join(["yeh ek lamba hissa hai"] * 20) + "."
        parts = tts.sentences(long)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 220 for p in parts))
        self.assertEqual(" ".join(parts).replace(" ,", ","), long)


class SpeakTests(unittest.TestCase):
    def tearDown(self):
        tts.stop_event.clear()

    def test_sentences_are_made_while_the_previous_one_plays(self):
        events = []

        def make(sentence):
            events.append(("make", sentence))
            return np.zeros(10, dtype=np.float32), 24000

        def play(samples, rate):
            events.append(("play", None))
            time.sleep(0.05)
            return True
        result = tts.speak("Ek. Do. Teen.", make=make, play=play)
        self.assertEqual(result["sentences"], 3)
        self.assertFalse(result["stopped"])
        first_play = events.index(("play", None))
        self.assertLess(first_play, len(events) - 1)                   # playing began before all were made
        self.assertIn(("make", "Do."), events[:first_play + 2])

    def test_stop_ends_playback_within_a_fifth_of_a_second(self):
        class Backend:
            stopped = False

            def play(self, samples, rate):
                pass

            def stop(self):
                Backend.stopped = True

            def wait(self):
                pass
        ten_seconds = np.zeros(24000 * 10, dtype=np.float32)
        threading.Timer(0.1, tts.stop).start()
        started = time.perf_counter()
        finished = tts._play(ten_seconds, 24000, backend=Backend())
        self.assertFalse(finished)
        self.assertTrue(Backend.stopped)
        self.assertLess(time.perf_counter() - started, 0.3)

    def test_a_failure_before_any_sound_is_raised_for_the_fallback(self):
        def broken(_sentence):
            raise RuntimeError("model broken")
        with self.assertRaises(RuntimeError):
            tts.speak("Hello.", make=broken, play=lambda *a: True)


class EngineChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = patch.object(mind, "PROJECT_ROOT", self.base)
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.temp.cleanup()

    def speak(self, text="Ho gaya. Aur kuch?"):
        spoken = []
        fake_sapi = lambda request: spoken.append(request["text"]) or {"speech_completed": True}
        with patch.object(speech, "sapi", side_effect=fake_sapi):
            result = speech._speak({"text": text}, None)
        return result.output, spoken

    def test_kokoro_is_the_default_voice(self):
        with patch.object(tts, "available", return_value=True), \
                patch.object(tts, "speak", return_value={"sentences": 2, "stopped": False, "first_audio_s": 0.4}):
            output, sapi_said = self.speak()
        self.assertEqual((output["engine"], sapi_said), ("kokoro", []))
        self.assertEqual(Preferences(self.base).load()["voice_engine"], "kokoro")

    def test_missing_model_files_fall_back_to_the_windows_voice(self):
        with patch.object(tts, "available", return_value=False):
            output, sapi_said = self.speak()
        self.assertEqual(output["engine"], "sapi")
        self.assertEqual(sapi_said, ["Ho gaya.", "Aur kuch?"])

    def test_a_kokoro_error_still_speaks_with_the_windows_voice(self):
        with patch.object(tts, "available", return_value=True), \
                patch.object(tts, "speak", side_effect=RuntimeError("onnx failed")):
            output, sapi_said = self.speak()
        self.assertEqual(output["engine"], "sapi")
        self.assertIn("onnx failed", output["kokoro_failed"])
        self.assertTrue(sapi_said)

    def test_the_owner_can_choose_the_windows_voice(self):
        Preferences(self.base).update({"voice_engine": "sapi"})
        with patch.object(tts, "available", return_value=True), \
                patch.object(tts, "speak", side_effect=AssertionError("Kokoro must not be used")):
            output, _said = self.speak()
        self.assertEqual(output["engine"], "sapi")

    def test_long_answers_are_no_longer_cut_at_200_characters(self):
        text = "Yeh ek lamba jawab hai. " * 30          # ~720 characters
        speech.validate_speech({"text": text.strip()})
        with patch.object(tts, "available", return_value=False):
            _output, sapi_said = self.speak(text.strip())
        self.assertEqual(" ".join(sapi_said), " ".join(text.split()))
        self.assertTrue(all(len(part) <= 200 for part in sapi_said))


if __name__ == "__main__":
    unittest.main()
