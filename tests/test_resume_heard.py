"""Owner 2026-11-07: "the local model never detects my resume". Variants the local Whisper produced, and the ones
a person says, must lift the pause after the hotkey; nothing else may."""
import unittest

from chutku import control_intent


class HeardResumeTests(unittest.TestCase):
    def test_what_the_owner_says_and_what_whisper_writes(self):
        for heard in ("Resume.", "resume", "Resume karo.", "resume kar do bhai", "Resume chatku.", "Resume chat khol.",
                      "Rezoom.", "Re-zoom karo", "Rizume", "Chalu ho jao.", "Charlu ho jao.", "chalu karo", "Shuru karo",
                      "ok resume", "Haan, resume.", "Chutku resume", "रिज़्यूम करो", "रिज्यूम", "चालू हो जाओ",
                      "शुरू करो", "unpause"):
            self.assertTrue(control_intent.heard_resume(heard), heard)

    def test_other_words_do_not_resume(self):
        for heard in ("", "stop", "pause everything", "open spotify", "what is the time", "result", "assume",
                      "presume", "music chalao", "band karo"):
            self.assertFalse(control_intent.heard_resume(heard), heard)

    def test_typed_resume_karo_is_a_resume_command_too(self):
        self.assertEqual(control_intent.kind("resume karo"), "resume")
        self.assertEqual(control_intent.kind("resume kar do"), "resume")


if __name__ == "__main__":
    unittest.main()
