"""2026-11-06: "bina puche kar do" / "approval mat maangna" -> a trusted task: basic steps run, very risky ones ask."""
import tempfile
import unittest
from pathlib import Path

from chutku.app import create_runtime
from chutku.intents.tone import autonomy_for
from chutku.policy.kernel import Decision, PolicyKernel
from chutku.voice.approval import decide


class KernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.runtime = create_runtime(Path(cls.temp.name) / "state")
        cls.tool = cls.runtime.registry.get

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()
        cls.temp.cleanup()

    def decide(self, name, mode, **kwargs):
        tool = self.tool(name)
        return PolicyKernel().authorize(tool, {}, provenance="delegated", resource_access=tool.resource_access,
                                        capability_allowed=True, autonomy=mode, exposed=False,
                                        **{"tainted": False, **kwargs}).decision

    def test_basic_undoable_changes_run_by_themselves_in_a_trusted_task(self):
        for name in ("filesystem.write_text", "filesystem.move", "filesystem.recycle", "files.organize"):
            with self.subTest(name=name):
                self.assertEqual(self.decide(name, "owner"), Decision.CONFIRM)     # owner mode still asks
                self.assertEqual(self.decide(name, "trusted"), Decision.ALLOW)
        self.assertEqual(self.decide("apps.launch", "trusted"), Decision.ALLOW)

    def test_very_risky_steps_still_ask_in_a_trusted_task(self):
        self.assertEqual(self.decide("power.schedule", "trusted"), Decision.CONFIRM)        # R4
        self.assertEqual(self.decide("code.run_python", "trusted"), Decision.CONFIRM)       # running code (D5)
        self.assertEqual(self.decide("message.send", "trusted", owner_question="Send to an unknown number?"),
                         Decision.CONFIRM)                                                   # unknown recipient
        self.assertEqual(self.decide("filesystem.write_text", "trusted", tainted=True), Decision.CONFIRM)  # outside text
        self.assertEqual(self.decide("filesystem.recycle", "trusted", tainted=True), Decision.CONFIRM)
        self.assertEqual(self.decide("filesystem.write_text", "trusted", suspicious=True), Decision.CONFIRM)
        self.assertNotEqual(self.decide("filesystem.delete_permanent", "trusted"), Decision.ALLOW)   # user only
        self.assertNotEqual(self.decide("filesystem.write_text", "trusted", protected_reason="Windows"), Decision.ALLOW)

    def test_the_web_page_cannot_ask_for_a_trusted_task(self):
        from chutku.dashboard import _mode
        with self.assertRaises(ValueError):
            _mode({"mode": "trusted"})


class WordsTests(unittest.TestCase):
    def test_pre_approval_and_caution_from_the_owners_words(self):
        for goal in ("organise my downloads bina puche kar do", "rename these files without asking",
                     "main abhi approval de raha hoon, report bana do", "बार-बार परमिशन मत मांगना, sab kar do",
                     "main coffee break pe ja raha hoon, ye kar dena"):
            self.assertEqual(autonomy_for(goal, "owner"), "trusted", goal)
        self.assertEqual(autonomy_for("dhyan se downloads organise karo", "owner"), "auto_safe")
        self.assertEqual(autonomy_for("open spotify", "owner"), "owner")
        self.assertEqual(autonomy_for("mat bhejo message", "owner"), "owner")
        self.assertEqual(autonomy_for("bina puche kar do", "review"), "review")   # review is never raised

    def test_the_spoken_answers_from_the_failed_live_session_now_approve(self):
        """Live 2026-11-05: every answer below was refused; "mat" in "approval mat maangna" counted as no."""
        for said in ("हां।", "यस", "Haan bhai, yes.", "पागल है क्या? यस बोल तो दिया।", "अभी बोला था अप्रूवल मत मांगना।"):
            self.assertIs(decide(said), True, said)
        for said in ("nahi", "mat bhejo", "haan mat karo", "ruko", "no"):
            self.assertIs(decide(said), False, said)


class LiveAnswerTests(unittest.TestCase):
    def test_after_an_unclear_answer_the_next_one_is_judged_alone_and_dont_ask_trusts_the_task(self):
        from chutku.voice.live import LiveConversation

        class Gate:
            speech_seconds = 5.0

        class Server:
            def __init__(self):
                self.confirmed, self.trusted = [], []

            def confirm_session(self, task_id, approve):
                self.confirmed.append(approve)

            def trust_session(self, task_id):
                self.trusted.append(task_id)

        live = LiveConversation.__new__(LiveConversation)
        live.server, live.gate, live.task_id = Server(), Gate(), "t1"
        live.speech_at_question = 0.0
        live._snapshot = lambda: {"status": "waiting_confirmation"}
        live._log_heard = lambda *a: None
        live._follow = lambda *a: None
        live.heard_since_question = " Ah! hmm kuch aur bolo tum"      # unclear
        self.assertIn("error", live._answer_approval(True))
        self.assertEqual(live.heard_since_question, "")               # the next answer starts fresh
        live.gate.speech_seconds = 6.0
        live.heard_since_question = " हां, aur approval mat maangna"
        self.assertEqual(live._answer_approval(True)["status"], "approved")
        self.assertEqual((live.server.confirmed, live.server.trusted), ([True], ["t1"]))


if __name__ == "__main__":
    unittest.main()
