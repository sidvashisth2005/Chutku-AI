"""Earned Autonomy (master plan S16): outcomes ledger, calibrated trust, add-only policy, owner-only relax."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.core.ledger import Ledger, Reliability, target_key, unreliable, wilson_lower
from chutku.core.preferences import Preferences
from chutku.policy.kernel import Decision


class MathTests(unittest.TestCase):
    def test_wilson_lower_bound(self):
        self.assertAlmostEqual(wilson_lower(12, 13), 0.667, places=3)
        self.assertAlmostEqual(wilson_lower(5, 5), 0.566, places=3)
        self.assertLess(wilson_lower(2, 5), 0.2)
        self.assertEqual(wilson_lower(0, 0), 0.0)

    def test_target_keys(self):
        self.assertEqual(target_key("apps.launch", {"name": "Spotify"}), "app:spotify")
        self.assertEqual(target_key("web.open", {"url": "https://www.youtube.com/x"}), "site:youtube.com")
        self.assertEqual(target_key("filesystem.move", {"source": r"D:\Notes\a.txt"}), r"file:d:\notes\a.txt")   # the exact file
        self.assertTrue(target_key("message.send", {"to": "Mammi"}).startswith("contact:"))
        self.assertNotIn("mammi", target_key("message.send", {"to": "Mammi"}))   # names are hashed
        self.assertEqual(target_key("system.volume_set", {}), "tool")

    def test_perfect_records_never_count_as_unreliable(self):
        self.assertFalse(unreliable(Reliability(5, 5, wilson_lower(5, 5), "k")))     # 0.566 < 0.7, but no failures
        self.assertFalse(unreliable(Reliability(10, 9, wilson_lower(9, 10), "k")))   # one failure is not a pattern
        self.assertTrue(unreliable(Reliability(5, 2, wilson_lower(2, 5), "k")))
        self.assertFalse(unreliable(Reliability(4, 0, None, "k")))                   # n < 5: no opinion


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "state")
        self.mind_root.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def record(self, tool, arguments, verdicts):
        for verdict in verdicts:
            self.runtime.ledger.record(tool, target_key(tool, arguments), expected="x", observed="y", verdict=verdict)

    def decide(self, name, arguments, mode="owner", provenance="delegated"):
        return self.runtime.authorize(self.runtime.registry.get(name), arguments, provenance=provenance,
                                      autonomy=mode if provenance == "delegated" else None).decision

    def test_an_easy_to_undo_step_that_keeps_failing_no_longer_asks(self):
        # Owner order 2026-10-08: only data-changing steps ask for keeping failing.
        args = {"name": "Spotify"}
        with patch.object(self.runtime, "current_capability"):
            self.record("apps.launch", args, ["FAIL", "FAIL", "FAIL", "PASS", "PASS"])
            self.assertEqual(self.decide("apps.launch", args), Decision.ALLOW)

    def test_a_data_changing_step_that_keeps_failing_still_asks(self):
        from chutku.core.ledger import Reliability
        from chutku.policy.kernel import PolicyKernel
        from chutku.tools.registry import Risk, Tool, ToolResult, Verification
        tool = Tool("test.change", "x", Risk.DATA_MODIFICATION, lambda a, c: ToolResult({}, Verification.PASS),
                    reversibility="journaled")
        failing = Reliability(10, 2, 0.05, "tool", 8)
        decide = PolicyKernel().authorize(tool, {}, provenance="delegated", autonomy="owner", tainted=False,
                                          exposed=False, reliability=failing)
        self.assertEqual(decide.decision, Decision.CONFIRM)
        self.assertIn("worked 2 of the last 10", decide.reason)

    def test_unverifiable_results_are_neither_pass_nor_fail(self):
        args = {"query": "Afterparty"}
        self.record("spotify.search", args, ["UNKNOWN"] * 7)
        stats = self.runtime.reliability(self.runtime.registry.get("spotify.search"), args)
        self.assertEqual(stats.n, 0)

    def test_fewer_than_five_trials_change_nothing(self):
        args = {"name": "Spotify"}
        self.record("apps.launch", args, ["FAIL"] * 4)
        with patch.object(self.runtime, "current_capability"):
            self.assertEqual(self.decide("apps.launch", args), Decision.ALLOW)

    def test_relax_is_off_by_default(self):
        self.assertFalse(Preferences(Path(self.temp.name) / "state").load()["earned_autonomy_relax"])
        args = {"path": "notes.txt", "content": "x"}
        self.record("filesystem.write_text", args, ["PASS"] * 25)
        self.assertEqual(self.decide("filesystem.write_text", args), Decision.CONFIRM)

    def test_the_agent_can_never_switch_relax_on(self):
        self.assertEqual(self.decide("settings.earned_autonomy", {"on": True}), Decision.DENY)
        self.assertEqual(self.decide("settings.earned_autonomy", {"on": True}, provenance="user_stated"),
                         Decision.ALLOW)

    def test_relax_on_skips_only_proven_undoable_file_changes(self):
        Preferences(Path(self.temp.name) / "state").update({"earned_autonomy_relax": True})
        args = {"path": "notes.txt", "content": "x"}
        self.assertEqual(self.decide("filesystem.write_text", args), Decision.CONFIRM)      # no record yet
        self.record("filesystem.write_text", args, ["PASS"] * 25)
        self.assertEqual(self.decide("filesystem.write_text", args), Decision.ALLOW)
        recycle = {"path": "old.txt"}
        self.record("filesystem.recycle", recycle, ["PASS"] * 25)
        self.assertEqual(self.decide("filesystem.recycle", recycle), Decision.CONFIRM)      # deletes always ask

    def test_runs_are_recorded_with_their_verdict(self):
        self.runtime.run("filesystem.create_directory", {"path": "made"})
        rows = self.runtime.ledger.table()
        self.assertEqual(rows[0]["tool"], "filesystem.create_directory")
        self.assertEqual(rows[0]["passes"], 1)


class LedgerFileTests(unittest.TestCase):
    def test_no_file_stays_locked(self):
        temp = tempfile.TemporaryDirectory()
        ledger = Ledger(Path(temp.name) / "ledger.db")
        ledger.record("t", "k", expected="e", observed="o", verdict="PASS")
        self.assertEqual(ledger.stats("t", "k").n, 1)
        temp.cleanup()   # would fail on Windows if a connection were still open


if __name__ == "__main__":
    unittest.main()
