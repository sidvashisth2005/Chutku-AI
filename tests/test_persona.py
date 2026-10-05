"""Chutku is female and her name is छुटकू (owner, 2026-10-05)."""
import unittest

from chutku.persona import IDENTITY, feminine


class PersonaTests(unittest.TestCase):
    def test_her_own_hinglish_is_feminine(self):
        cases = {"Ho jayega, kar raha hoon": "Ho jayega, kar rahi hoon",
                 "Main bhej dunga, samajh gaya hoon": "Main bhej dungi, samajh gayi hoon",
                 "Haan main kar sakta hoon": "Haan main kar sakti hoon",
                 "Main kar raha tha": "Main kar rahi thi",
                 "Ruko, dekh rha hu": "Ruko, dekh rhi hu"}
        for said, expected in cases.items():
            self.assertEqual(feminine(said), expected)

    def test_quoted_owner_words_and_english_are_untouched(self):
        for text in ('Sent "main late aaunga" to Pita Shri.', "Pita Shri ko bhej diya: “main kal aaunga”",
                     "I will open Spotify.", "Opened Downloads.", ""):
            self.assertEqual(feminine(text), text)

    def test_every_prompt_that_speaks_for_her_says_who_she_is(self):
        from chutku.agent_loop import AGENT_SYSTEM, ANSWER_SYSTEM
        from chutku.voice.live import PERSONA
        for prompt in (AGENT_SYSTEM, ANSWER_SYSTEM):
            self.assertIn(IDENTITY, prompt)
        self.assertIn("FEMALE", PERSONA)
        self.assertIn("छुटकू", PERSONA)
        self.assertNotIn("kar raha hoon\"", PERSONA)

    def test_final_replies_pass_through_the_guard(self):
        from chutku.agent_loop import AgentSession
        session = AgentSession("hi", mode="owner")
        session._finish("done", "Theek hai, main kar dunga.")
        self.assertEqual(session.reply, "Theek hai, main kar dungi.")


if __name__ == "__main__":
    unittest.main()
