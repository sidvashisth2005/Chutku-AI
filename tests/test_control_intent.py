"""Controlling Chutku in plain words: stop, pause, undo, repeat, help, presence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import control_intent
from chutku.quick_intents import quick_proposal


class ControlPhraseTests(unittest.TestCase):
    def test_kinds_in_english_and_hinglish(self):
        cases = {"stop": ["stop", "ruko", "cancel that", "bas karo", "sab band karo", "Chutku, ruk jao"],
                 "pause": ["pause actions", "pause everything", "sab rok do"],
                 "undo": ["undo that", "undo", "wapas karo", "revert it"],
                 "recent": ["what did you just do", "abhi kya kiya"],
                 "repeat": ["do it again", "phir se karo", "dobara karo", "again"],
                 "help": ["what can you do", "help", "tum kya kya kar sakte ho"],
                 "presence": ["are you there", "suno", "chutku?"]}
        for expected, phrases in cases.items():
            for phrase in phrases:
                self.assertEqual(control_intent.kind(phrase), expected, phrase)
        for phrase in ("stop the music", "undo the folder tidy-up in downloads", "help me write an email", "close spotify"):
            self.assertIsNone(control_intent.kind(phrase), phrase)

    def test_instant_answers(self):
        def tools(text):
            proposal = quick_proposal(text, apps=[])
            return [s["tool"] for s in proposal["next_steps"]] if proposal else None
        self.assertEqual(tools("undo that"), ["log.undo"])
        self.assertEqual(tools("abhi kya kiya"), ["log.recent"])
        self.assertIn("stop", quick_proposal("what can you do", apps=[])["reply"])
        self.assertEqual(quick_proposal("ruko", apps=[])["reply"], "Nothing is running right now.")
        self.assertEqual(tools("stop"), ["media.control"])        # nothing running: "stop" pauses the music
        self.assertIsNone(quick_proposal("close sab", apps=[]))   # never an app called "sab"

    def test_do_it_again_repeats_the_previous_request_not_itself(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "data").mkdir()
            (Path(temp) / "data" / "last-task.json").write_text(json.dumps({"goal": "what time is it"}), encoding="utf-8")
            with patch.object(control_intent, "PROJECT_ROOT", Path(temp)):
                self.assertEqual([s["tool"] for s in quick_proposal("do it again", apps=[])["next_steps"]],
                                 ["system.get_time"])
                (Path(temp) / "data" / "last-task.json").write_text(json.dumps({"goal": "do it again"}), encoding="utf-8")
                self.assertEqual(quick_proposal("do it again", apps=[])["reply"], "There is nothing to repeat yet.")

    def test_control_words_never_become_the_last_task(self):
        from chutku.dashboard import record_last_task
        with tempfile.TemporaryDirectory() as temp:
            record_last_task(temp, "open spotify", "done")
            record_last_task(temp, "do it again", "done")
            record_last_task(temp, "undo that", "done")
            saved = json.loads((Path(temp) / "data" / "last-task.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["goal"], "open spotify")


if __name__ == "__main__":
    unittest.main()
