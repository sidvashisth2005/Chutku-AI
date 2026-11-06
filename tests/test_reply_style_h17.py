"""H17 (Hermes personality presets): "formal ho jao", "chhota jawab do", "masti mode", "normal ho jao"."""
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from chutku import persona
from chutku.agent_loop import AgentSession, _reply_style
from chutku.core.preferences import Preferences
from chutku.daily_intent import parse_daily
from chutku.tools import mind_tools


class ReplyStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_phrases_set_the_style_and_bad_styles_are_refused(self):
        for said, style in (("formal ho jao", "formal"), ("chhota jawab do", "short"), ("masti mode", "masti"),
                            ("normal ho jao", "normal"), ("be brief", "short")):
            self.assertEqual(parse_daily(said)[:2], ("settings.reply_style", {"style": style}), said)
        with patch.object(mind_tools.mind, "PROJECT_ROOT", self.base):
            result = mind_tools._reply_style({"style": "formal"}, None)
            self.assertEqual((result.output["reply_style"], result.output["was"]), ("formal", "normal"))
            self.assertEqual(mind_tools._reply_style({"style": "rude"}, None).verification,
                             mind_tools.Verification.FAIL)
        self.assertEqual(Preferences(self.base).load()["reply_style"], "formal")
        with self.assertRaises(ValueError):
            Preferences(self.base).update({"reply_style": "rude"})

    def test_every_brain_sees_the_style_and_normal_adds_nothing(self):
        runtime = types.SimpleNamespace(granted_root=self.base / "sandbox")
        self.assertEqual(_reply_style(runtime), {})
        Preferences(self.base).update({"reply_style": "formal"})
        self.assertIn("no slang", _reply_style(runtime)["reply_style"])

    def test_short_is_one_sentence_and_still_female(self):
        session = AgentSession("what time is it", mode="owner", context={
            "reply_style": persona.style_note("short")})
        session._finish("done", "Main check kar raha hoon. It is 5 PM. Also it rains.")
        self.assertEqual(session.reply.split(" [Verified")[0], "Main check kar rahi hoon.")
        self.assertEqual(persona.styled("Ho gaya। Aur kuch?", "short"), "Ho gaya।")
        self.assertEqual(persona.styled("One. Two.", "formal"), "One. Two.")


if __name__ == "__main__":
    unittest.main()
