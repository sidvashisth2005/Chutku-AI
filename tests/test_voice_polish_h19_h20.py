"""H19 (sentence-by-sentence speech) and H20 (voice polish): checks that pin what is already built, plus H20's exact
stop words (2026-11-06)."""
import unittest

from chutku import control_intent
from chutku.voice import tts
from chutku.voice.heard import meaningful


class SentenceSpeechTests(unittest.TestCase):
    def test_sentences_split_on_hinglish_and_devanagari_but_not_numbers_or_urls(self):
        text = "Ho gaya। Volume 3.5 pe hai. Open example.com/a.b now! Aur kuch?"
        self.assertEqual(tts.sentences(text), ["Ho gaya।", "Volume 3.5 pe hai.", "Open example.com/a.b now!",
                                               "Aur kuch?"])


class VoicePolishTests(unittest.TestCase):
    def test_whisper_phantoms_are_dropped_and_real_short_commands_pass(self):
        for phantom in ("Thank you for watching", "Please subscribe", ".", "you you you you"):
            self.assertFalse(meaningful(phantom), phantom)
        for real in ("haan", "volume 30", "youtube kholo"):
            self.assertTrue(meaningful(real) or meaningful(real, short_answers_ok=True), real)

    def test_exact_stop_words_end_it_but_a_task_with_stop_in_it_does_not(self):
        for said in ("bas", "chup", "chup karo", "that's all", "bas itna hi", "ruko", "stop"):
            self.assertEqual(control_intent.kind(said), "stop", said)
        for task in ("stop the music", "chup chap kaam karo", "that's all the files"):
            self.assertIsNone(control_intent.kind(task), task)


if __name__ == "__main__":
    unittest.main()
