"""Causal Rewind (master plan S18): one undo for everything Chutku did, newest first, never over the owner's edits."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import rewind
from chutku.app import create_runtime
from chutku.quick_intents import quick_proposal
from chutku.tools.registry import ExecutionContext


class RewindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.runtime = create_runtime(self.base)
        self.sandbox = self.runtime.granted_root
        self.start = datetime.now().astimezone() - timedelta(seconds=2)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def run_tool(self, name, arguments):
        result = self.runtime.run(name, arguments)
        self.assertEqual(result["state"], "COMPLETED", result)
        return result

    def plan(self, **scope):
        return rewind.plan(self.runtime, scope or {"since": self.start.isoformat()})

    def execute(self, items):
        context = ExecutionContext("rewind-test", self.runtime.journal, self.sandbox, approved=True)
        return rewind.execute(self.runtime, items, context)

    def test_move_then_rename_is_undone_newest_first(self):
        self.run_tool("filesystem.write_text", {"path": "a.txt", "content": "hello"})
        self.run_tool("filesystem.move", {"source": "a.txt", "destination": "b.txt"})
        self.run_tool("filesystem.move", {"source": "b.txt", "destination": "c.txt"})
        items = self.plan()
        self.assertEqual([i.what.split("(")[0] for i in items],
                         ["filesystem.move", "filesystem.move", "filesystem.write_text"])
        self.assertEqual(items[0].entry["arguments"]["destination"], "c.txt")   # the rename goes back first
        self.assertTrue(all(i.status == "ok" for i in items), [(i.what, i.status, i.why) for i in items])
        report = self.execute(items)
        self.assertEqual((len(report["undone"]), report["failed"]), (3, []))
        self.assertEqual(sorted(p.name for p in self.sandbox.iterdir() if p.suffix == ".txt"), [])

    def test_a_file_the_owner_edited_afterwards_is_kept(self):
        self.run_tool("filesystem.write_text", {"path": "x.txt", "content": "chutku wrote this"})
        (self.sandbox / "x.txt").write_text("the owner's own edit", encoding="utf-8")
        items = self.plan()
        self.assertEqual(items[0].status, "conflict")
        report = self.execute(items)
        self.assertEqual(report["undone"], [])
        self.assertEqual((self.sandbox / "x.txt").read_text(encoding="utf-8"), "the owner's own edit")

    def test_a_change_after_a_conflict_on_the_same_file_is_blocked(self):
        self.run_tool("filesystem.write_text", {"path": "y.txt", "content": "one"})
        self.run_tool("filesystem.move", {"source": "y.txt", "destination": "z.txt"})
        (self.sandbox / "z.txt").write_text("edited after the move", encoding="utf-8")
        statuses = [i.status for i in self.plan()]
        self.assertEqual(statuses, ["conflict", "blocked"])
        self.execute(self.plan())
        self.assertEqual((self.sandbox / "z.txt").read_text(encoding="utf-8"), "edited after the move")

    def test_scope_pulls_in_a_later_change_that_depends_on_it(self):
        first = self.run_tool("filesystem.write_text", {"path": "n.txt", "content": "v1"})
        self.run_tool("filesystem.write_text", {"path": "other.txt", "content": "unrelated"})
        self.run_tool("filesystem.write_text", {"path": "n.txt", "content": "v2"})
        items = rewind.plan(self.runtime, {"task_id": first["task_id"]})
        self.assertEqual([i.entry["arguments"]["path"] for i in items], ["n.txt", "n.txt"])
        report = self.execute(items)
        self.assertEqual(len(report["undone"]), 2)
        self.assertFalse((self.sandbox / "n.txt").exists())
        self.assertTrue((self.sandbox / "other.txt").exists())   # outside the scope and independent: untouched

    def log(self, **entry):
        base = {"task_id": "T-x", "risk": 1, "state": "COMPLETED", "provenance": "delegated", "autonomy": "owner",
                "approved_on_screen": False, "arguments": {}, "paths": [], "message": None, "operation_id": None,
                "undo_id": None, "undo": None}
        self.runtime.action_log.append(base | entry)

    def test_volume_is_restored_and_a_message_is_listed_as_irreversible(self):
        before, after = {"level": 50, "muted": False}, {"level": 20, "muted": False}
        self.log(tool="audio.volume", arguments={"action": "set", "level": 20}, state_before=before, state_after=after)
        self.log(tool="message.send", risk=3, arguments={"app": "whatsapp", "to": "AK", "text": "[REDACTED]"})
        current = {"value": dict(after)}
        with patch.object(rewind, "read_setting", side_effect=lambda name: current["value"]), \
                patch.object(rewind, "write_setting", side_effect=lambda name, value: current.update(value=value)), \
                patch.object(self.runtime, "current_capability"):
            items = self.plan()
            self.assertEqual([i.status for i in items], ["irreversible", "ok"])
            report = self.execute(items)
        self.assertEqual(current["value"], before)
        self.assertEqual((len(report["undone"]), len(report["irreversible"])), (1, 1))

    def test_a_setting_changed_again_by_the_owner_is_left_alone(self):
        self.log(tool="display.brightness", arguments={"action": "set", "level": 30}, state_before=70, state_after=30)
        with patch.object(rewind, "read_setting", return_value=55), \
                patch.object(rewind, "write_setting") as write, patch.object(self.runtime, "current_capability"):
            items = self.plan()
            self.assertEqual(items[0].status, "conflict")
            self.execute(items)
        write.assert_not_called()

    def test_no_grant_no_undo(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        grant = self.runtime.resource_grants.grant(outside, {"observe", "modify"})
        with create_runtime(self.base, grant.grant_id) as other:
            self.assertEqual(other.run("filesystem.write_text", {"path": str(outside / "g.txt"),
                                                                 "content": "x"})["state"], "COMPLETED")
        self.runtime.resource_grants.revoke(grant.grant_id)
        report = self.execute(self.plan())
        self.assertIn("No folder access grant", report["failed"][0])
        self.assertTrue((outside / "g.txt").exists())   # fail closed: nothing touched without a grant

    def test_a_second_rewind_finds_it_already_undone(self):
        self.run_tool("filesystem.write_text", {"path": "once.txt", "content": "x"})
        self.execute(self.plan())
        self.assertEqual([i.status for i in self.plan()], ["done_before"])

    def test_the_tool_asks_once_with_the_full_list(self):
        self.run_tool("filesystem.write_text", {"path": "q.txt", "content": "x"})
        arguments = {"since": self.start.isoformat(), "until": datetime.now().replace(microsecond=0).isoformat()}
        tool = self.runtime.registry.get("rewind.run")
        question = self.runtime.step_question(tool, arguments)
        self.assertIn("Undo 1 change(s)", question)
        self.assertIn("q.txt", question)
        decision = self.runtime.authorize(tool, arguments, provenance="delegated", autonomy="owner")
        self.assertEqual(decision.decision.name, "CONFIRM")
        self.assertEqual(self.runtime.run("rewind.preview", arguments)["output"]["can_undo"], 1)
        self.assertTrue((self.sandbox / "q.txt").exists())   # previewing changes nothing

    def test_phrases(self):
        self.assertEqual(quick_proposal("pichhle 5 minute ka sab wapas karo")["next_steps"][0]["tool"], "rewind.run")
        since = quick_proposal("undo everything from the last 10 minutes")["next_steps"][0]["arguments"]["since"]
        self.assertAlmostEqual((datetime.now() - datetime.fromisoformat(since)).total_seconds(), 600, delta=5)
        today = quick_proposal("aaj jo kiya sab wapas karo")["next_steps"][0]["arguments"]
        self.assertEqual((today["today"], len(today["until"])), (True, 19))   # frozen at the moment of asking
        self.assertTrue(quick_proposal("last task undo karo")["next_steps"][0]["arguments"]["last_task"])
        self.assertEqual(quick_proposal("undo that")["next_steps"][0]["tool"], "log.undo")


if __name__ == "__main__":
    unittest.main()
