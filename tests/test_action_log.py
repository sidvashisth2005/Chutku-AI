"""Append-only, hash-chained action log (plan Phase 1, item 7)."""
import json
from pathlib import Path
import tempfile
import unittest

from chutku.app import create_runtime
from chutku.core.action_log import ActionLog


class ActionLogStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "actions.log.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_chain_survives_reopen_and_verifies(self):
        log = ActionLog(self.path)
        first = log.append({"tool": "a", "state": "COMPLETED"})
        second = ActionLog(self.path).append({"tool": "b", "state": "DENIED"})
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        self.assertEqual(second["prev"], first["hash"])
        self.assertEqual(ActionLog(self.path).verify(), {"ok": True, "entries": 2, "broken_at": None})

    def test_edited_or_removed_line_is_detected(self):
        log = ActionLog(self.path)
        for name in ("a", "b", "c"):
            log.append({"tool": name, "state": "COMPLETED"})
        lines = self.path.read_text(encoding="utf-8").splitlines()
        edited = json.loads(lines[1])
        edited["tool"] = "innocent"
        self.path.write_text("\n".join([lines[0], json.dumps(edited), lines[2]]) + "\n", encoding="utf-8")
        self.assertEqual(ActionLog(self.path).verify()["broken_at"], 2)
        self.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
        self.assertFalse(ActionLog(self.path).verify()["ok"])

    def test_garbage_line_breaks_the_chain(self):
        ActionLog(self.path).append({"tool": "a", "state": "COMPLETED"})
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write("not json\n")
        self.assertFalse(ActionLog(self.path).verify()["ok"])


class RuntimeActionLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)
        self.root = self.runtime.granted_root

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def entries(self):
        return self.runtime.action_log.recent(50)

    def test_changes_and_denials_are_logged_but_plain_reads_are_not(self):
        self.runtime.run("filesystem.write_text", {"path": "a.txt", "content": "secret words"})
        self.runtime.run("filesystem.list", {"path": "."})
        self.runtime.run("filesystem.write_text", {"path": "../escape.txt", "content": "x"})
        tools = [(entry["tool"], entry["state"]) for entry in self.entries()]
        self.assertIn(("filesystem.write_text", "COMPLETED"), tools)
        self.assertIn(("filesystem.write_text", "DENIED"), tools)
        self.assertNotIn("filesystem.list", [tool for tool, _ in tools])
        raw = (self.base / "data" / "actions.log.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("secret words", raw)  # sensitive arguments (content) are redacted
        written = next(e for e in self.entries() if e["state"] == "COMPLETED")
        self.assertEqual(written["paths"], ["a.txt"])
        self.assertEqual(written["undo"], "filesystem.undo_last_write")

    def test_waiting_for_a_yes_is_logged(self):
        (self.root / "b.txt").write_text("x", encoding="utf-8")
        self.runtime.run("filesystem.recycle", {"path": "b.txt"})
        self.assertEqual(self.entries()[0]["state"], "WAITING_CONFIRMATION")

    def test_log_recent_tool_answers_what_did_you_do(self):
        self.runtime.run("filesystem.create_directory", {"path": "made"})
        result = self.runtime.run("log.recent", {"limit": 5})
        self.assertEqual(result["state"], "COMPLETED", result)
        self.assertEqual(result["output"]["actions"][0]["tool"], "filesystem.create_directory")
        self.assertTrue(result["output"]["chain_ok"])

    def test_log_undo_reverses_the_latest_write_only(self):
        self.runtime.run("filesystem.write_text", {"path": "first.txt", "content": "1"})
        self.runtime.run("filesystem.write_text", {"path": "second.txt", "content": "2"})
        older, newer = [e for e in reversed(self.entries()) if e["tool"] == "filesystem.write_text"]
        refused = self.runtime.run("log.undo", {"id": older["seq"]})
        self.assertEqual(refused["state"], "FAILED")
        self.assertIn("most recent", refused["output"]["error"])
        self.assertTrue((self.root / "first.txt").exists())
        undone = self.runtime.run("log.undo", {"id": newer["seq"]})
        self.assertEqual(undone["state"], "COMPLETED", undone)
        self.assertFalse((self.root / "second.txt").exists())
        self.assertEqual(self.entries()[0]["tool"], "log.undo")

    def test_undo_that_without_a_number_reverses_the_newest_change_once(self):
        self.runtime.run("filesystem.write_text", {"path": "note.txt", "content": "1"})
        undone = self.runtime.run("log.undo", {})
        self.assertEqual(undone["state"], "COMPLETED", undone)
        self.assertFalse((self.root / "note.txt").exists())
        again = self.runtime.run("log.undo", {})                     # nothing left: never the same one twice
        self.assertEqual(again["state"], "FAILED")
        self.assertIn("nothing recent", again["output"]["error"])

    def test_log_undo_refuses_entries_without_undo(self):
        self.runtime.run("filesystem.write_text", {"path": "../escape.txt", "content": "x"})
        denied = next(e for e in self.entries() if e["state"] == "DENIED")
        result = self.runtime.run("log.undo", {"id": denied["seq"]})
        self.assertEqual(result["state"], "FAILED")
        missing = self.runtime.run("log.undo", {"id": 999})
        self.assertEqual(missing["state"], "FAILED")

    def test_doctor_reports_a_tampered_log(self):
        from chutku.doctor import inspect_foundation
        self.runtime.run("filesystem.write_text", {"path": "a.txt", "content": "1"})
        self.runtime.run("filesystem.write_text", {"path": "b.txt", "content": "2"})
        path = self.base / "data" / "actions.log.jsonl"
        self.assertTrue(next(c for c in inspect_foundation(self.base)["checks"] if c["name"] == "Action log")["ready"])
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[-1] + "\n", encoding="utf-8")
        check = next(c for c in inspect_foundation(self.base)["checks"] if c["name"] == "Action log")
        self.assertFalse(check["ready"])


if __name__ == "__main__":
    unittest.main()
