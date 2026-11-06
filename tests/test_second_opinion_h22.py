"""H22: "pakka?" re-checks the last answer as a read-only research task; "sab se poocho: X" compares sources."""
import unittest

from chutku import recall, second_opinion
from tests import test_dashboard as _harness
from tests.test_dashboard_agent import Scripted, proposal


class SecondOpinionTests(unittest.TestCase):
    setUp, tearDown = _harness.DashboardTests.setUp, _harness.DashboardTests.tearDown

    def test_pakka_rechecks_the_last_answer_and_only_reads(self):
        recall.log_conversation("India ne 2011 ka world cup jeeta tha?", "Haan, India ne 2011 jeeta.", base=self.base)
        self.server.planner_factory = lambda: (Scripted(proposal("done", reply="Dono sahmat hain.")), None)
        session = self.server.begin_session("pakka?", "owner", "text")
        self.assertTrue(session.goal.startswith("Double-check an earlier answer"))
        self.assertIn("India ne 2011 ka world cup jeeta tha?", session.goal)
        self.assertIn("Haan, India ne 2011 jeeta.", session.goal)
        self.assertTrue(session.observe_only)                      # only R0 tools can run in a re-check
        for _ in range(100):
            if session.status == "done":
                break
            __import__("time").sleep(0.05)

    def test_other_requests_and_an_empty_history_are_left_alone(self):
        self.assertIsNone(second_opinion.rewrite("what time is it", self.base))
        self.assertIsNone(second_opinion.rewrite("pakka?", self.base))          # nothing to re-check yet
        for said in ("pakka?", "Pakka hai?", "sure ho?", "double check karo", "are you sure"):
            recall.log_conversation("kal kitne baje meeting hai", "5 baje.", base=self.base)
            self.assertIsNotNone(second_opinion.rewrite(said, self.base), said)
        asked = second_opinion.rewrite("sab se poocho: who won the 2011 world cup", self.base)
        self.assertIn("at least 2 independent public web sources", asked)


class OriginTests(unittest.TestCase):
    def test_a_script_rechecks_its_own_answer_and_the_owner_theirs(self):
        """Live 2026-11-07: a test script's "pakka?" re-checked the owner's last "bye bye" instead."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            base = Path(temp)
            recall.log_conversation("Chup. Bye bye.", "Bye!", base=base, at=1.0)
            recall.log_conversation("Who wrote Godaan?", "Premchand.", origin="script", base=base, at=2.0)
            self.assertIn("Who wrote Godaan?", second_opinion.rewrite("pakka?", base, "script"))
            self.assertIn("Chup. Bye bye.", second_opinion.rewrite("pakka?", base, "text"))


if __name__ == "__main__":
    unittest.main()
