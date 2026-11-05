import unittest
from types import SimpleNamespace
from unittest.mock import patch

from chutku.voice.approval import decide, spoken_question


class VoiceApprovalTests(unittest.TestCase):
    def test_clear_short_yes_approves(self):
        for heard in ("haan", "Haan, bhej do.", "yes", "hnn", "Hmm.", "ok kar do", "haan ji", "theek hai"):
            self.assertIs(decide(heard), True, heard)

    def test_no_or_stop_always_cancels(self):
        for heard in ("nahi", "no", "ruko", "cancel", "haan nahi", "yes but wait", "mat bhejo"):
            self.assertIs(decide(heard), False, heard)

    def test_unclear_or_long_speech_is_not_a_yes(self):
        for heard in ("", "   ", "what time is it", "hmm let me think about the weather tomorrow",
                      "okay so then the match went on and everyone said yes yes it was great"):
            self.assertIsNone(decide(heard), heard)

    def test_questions_say_exactly_what_will_happen(self):
        self.assertEqual(spoken_question({"tool": "message.send", "arguments": {"app": "whatsapp", "to": "Ak", "text": "hi"}}),
                         "Send “hi” to Ak on WhatsApp? Haan ya na?")
        self.assertIn("Recycle Bin", spoken_question({"tool": "filesystem.recycle", "arguments": {"path": r"D:\a\report.pdf"}}))
        self.assertIn("cannot be undone", spoken_question({"tool": "filesystem.delete_permanent", "arguments": {"path": "x"}}))
        self.assertTrue(spoken_question({"tool": "web.open", "consequence": "Open a website."}).endswith("Haan ya na?"))


class FakeSession:
    def __init__(self):
        self.id, self.status = "s1", "waiting_confirmation"

    def snapshot(self):
        approval = {"tool": "message.send", "arguments": {"app": "whatsapp", "to": "Ak", "text": "hi"}}
        return {"status": self.status, "pending": {"approval": approval} if self.status == "waiting_confirmation" else None}


class HandsFreeApprovalFlowTests(unittest.TestCase):
    def run_flow(self, answers):
        from chutku.dashboard import DashboardServer
        session, spoken, decided = FakeSession(), [], []
        server = SimpleNamespace(hud_state={}, _hud_set=lambda *a, **k: None, _speak=spoken.append,
                                 _listen_once=lambda: answers.pop(0) if answers else "")

        def confirm(session_id, approve):
            decided.append(approve)
            session.status = "done"
        server.confirm_session = confirm
        with patch("chutku.voice.handsfree.chime"):
            result = DashboardServer._approve_by_voice(server, session, session.snapshot())
        return result, spoken, decided

    def test_spoken_yes_approves_the_exact_step(self):
        result, spoken, decided = self.run_flow(["haan bhej do"])
        self.assertTrue(result)
        self.assertEqual(decided, [True])
        self.assertEqual(spoken[0], "Send “hi” to Ak on WhatsApp? Haan ya na?")

    def test_spoken_no_cancels(self):
        result, spoken, decided = self.run_flow(["nahi"])
        self.assertEqual(decided, [False])
        self.assertIn("cancel", spoken[-1])

    def test_unclear_is_asked_again_then_left_to_the_screen(self):
        result, spoken, decided = self.run_flow(["what?", "the weather is nice today and tomorrow too maybe"])
        self.assertFalse(result)
        self.assertEqual(decided, [])          # nothing approved or cancelled
        self.assertEqual(len(spoken), 3)       # question, "haan ya na?" again, then "button is on the screen"
        result, _spoken, decided = self.run_flow(["umm", "haan"])
        self.assertEqual(decided, [True])      # second try works


if __name__ == "__main__":
    unittest.main()
