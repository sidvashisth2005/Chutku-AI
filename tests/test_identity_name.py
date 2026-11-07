"""The assistant's name and personality chosen at install (.env) reach the prompts and the wake word; without .env it
is exactly the original Chutku."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import identity, persona
from chutku.voice import handsfree, live


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = Path(self.temp.name) / ".env"

    def test_without_env_it_is_chutku_unchanged(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in identity.DEFAULTS:
                os.environ.pop(key, None)
            values = identity.load(self.env)
        self.assertEqual(values["ASSISTANT_NAME"], "Chutku")
        self.assertEqual(live.personalize(live._BASE_PERSONA, values), live._BASE_PERSONA)
        self.assertTrue(identity.identity_line(values).startswith('You are Chutku (छुटकू, said "Chhutku")'))

    def test_saving_keeps_other_lines_and_bad_values_are_refused(self):
        self.env.write_text("# mine\nOTHER=1\nASSISTANT_NAME=Old\n", encoding="utf-8")
        identity.save({"ASSISTANT_NAME": "Jarvis", "ASSISTANT_GENDER": "male"}, self.env)
        text = self.env.read_text(encoding="utf-8")
        self.assertIn("# mine", text)
        self.assertIn("OTHER=1", text)
        self.assertEqual(identity.load(self.env)["ASSISTANT_NAME"], "Jarvis")
        for key, bad in (("ASSISTANT_NAME", "1abc"), ("ASSISTANT_NAME", "x" * 30), ("ASSISTANT_GENDER", "robot"),
                         ("CHUTKU_RELAY_URL", "https://relay.example.com/path")):
            with self.assertRaises(ValueError):
                identity.check(key, bad)
        self.env.write_text("ASSISTANT_GENDER=robot   # typo\nASSISTANT_STYLE=witty  # inline comment\n",
                            encoding="utf-8")
        values = identity.load(self.env)
        self.assertEqual((values["ASSISTANT_GENDER"], values["ASSISTANT_STYLE"]), ("female", "witty"))   # bad -> default

    def test_a_custom_name_reaches_the_persona_and_only_it_wakes(self):
        values = dict(identity.DEFAULTS, ASSISTANT_NAME="Jarvis", ASSISTANT_GENDER="male", ASSISTANT_LANGUAGE="english")
        text = live.personalize(live._BASE_PERSONA, values)
        self.assertNotIn("Chutku", text)
        self.assertIn("You are Jarvis, the owner's own MALE AI companion", text)
        self.assertIn("clear, simple English", text)
        # Owner 2026-11-07: English means English only, no Hindi self-forms ("kar raha hoon") in the persona.
        self.assertIn("Always speak English", text)
        self.assertNotIn('"kar raha hoon"', text)
        hinglish = live.personalize(live._BASE_PERSONA, dict(values, ASSISTANT_LANGUAGE="hinglish"))
        self.assertIn('"kar raha hoon"', hinglish)   # a male Hinglish assistant keeps its own words
        with patch.object(identity, "name", lambda: "Jarvis"):
            self.assertEqual(handsfree.split_wake("Hey Jarvis, open notepad"), (True, "open notepad"))
            self.assertEqual(handsfree.split_wake("Oye Chutku youtube kholo"), (False, ""))   # the old name no longer
            self.assertEqual(handsfree.split_wake("Jarvisx open"), (False, ""))
        self.assertEqual(handsfree.split_wake("Oye Chutku youtube kholo")[0], True)            # default install

    def test_a_male_or_neutral_assistant_keeps_its_own_words(self):
        with patch.object(persona, "FEMALE", False):
            self.assertEqual(persona.feminine("main kar raha hoon"), "main kar raha hoon")
        self.assertEqual(persona.feminine("main kar raha hoon"), "main kar rahi hoon")


if __name__ == "__main__":
    unittest.main()
