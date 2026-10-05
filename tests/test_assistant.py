import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.core.paths import MAX_TEXT_BYTES
from chutku.presentation import present
from chutku.router.catalog import CommandCatalog
from chutku.tools.registry import Risk, Tool, ToolResult, Verification
from chutku.workflows import project_plan, run_project


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)
        self.root = self.runtime.granted_root

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def run_tool(self, tool, **args):
        return self.runtime.run(tool, args)

    def test_undo_refuses_newer_user_edits_and_retains_journal(self):
        target = self.root / "note.txt"
        target.write_text("original", encoding="utf-8")
        self.run_tool("filesystem.write_text", path="note.txt", content="assistant")
        target.write_text("new user edit", encoding="utf-8")
        result = self.run_tool("filesystem.undo_last_write")
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("Undo conflict", present(result))
        self.assertEqual(target.read_text(), "new user edit")
        self.assertIsNotNone(self.runtime.journal.latest_completed("filesystem.write_text"))

    def test_undo_after_restart_preserves_exact_newlines(self):
        target = self.root / "note.txt"
        original = b"one\r\ntwo\n"
        target.write_bytes(original)
        self.run_tool("filesystem.write_text", path="note.txt", content="new\ntext\n")
        self.runtime.close()
        self.runtime = create_runtime(self.base)
        self.assertEqual(self.run_tool("filesystem.undo_last_write")["state"], "COMPLETED")
        self.assertEqual(target.read_bytes(), original)

    def test_deleted_target_is_an_undo_conflict(self):
        self.run_tool("filesystem.write_text", path="note.txt", content="assistant")
        (self.root / "note.txt").unlink()
        self.assertEqual(self.run_tool("filesystem.undo_last_write")["state"], "FAILED")

    def test_recovery_preserves_unrecognized_newer_contents(self):
        target = self.root / "note.txt"
        operation = self.runtime.journal.begin("interrupted", "filesystem.write_text", target,
            {"existed": False, "content": None, "planned_content": "planned"})
        target.write_text("user edit", encoding="utf-8")
        result = self.run_tool("filesystem.recover_incomplete_write", operation_id=operation)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(target.read_text(), "user edit")

    def test_legacy_recovery_without_expected_state_requires_review(self):
        target = self.root / "legacy.txt"
        operation = self.runtime.journal.begin("old", "filesystem.write_text", target, {"existed": False, "content": None})
        target.write_text("unknown", encoding="utf-8")
        self.assertEqual(self.run_tool("filesystem.recover_incomplete_write", operation_id=operation)["state"], "FAILED")
        self.assertTrue(target.exists())

    def test_oversized_new_or_existing_file_is_not_overwritten(self):
        target = self.root / "big.txt"
        data = b"a" * (MAX_TEXT_BYTES + 1)
        target.write_bytes(data)
        self.assertEqual(self.run_tool("filesystem.write_text", path="big.txt", content="small")["state"], "FAILED")
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(self.run_tool("filesystem.write_text", path="new.txt", content="a" * (MAX_TEXT_BYTES + 1))["state"], "FAILED")
        self.assertFalse((self.root / "new.txt").exists())

    def test_unsafe_windows_paths_are_denied_without_creating_files(self):
        for path in ("../outside", "C:/outside.txt", "\\\\server\\share\\a", "note.txt:secret", "NUL.txt", "con", "a.", "a ", "folder/../escape", "COM1", "LPT²"):
            with self.subTest(path=path):
                self.assertEqual(self.run_tool("filesystem.write_text", path=path, content="x")["state"], "DENIED")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_hardlink_alias_is_refused(self):
        outside = self.base / "outside.txt"
        outside.write_text("preserve", encoding="utf-8")
        os.link(outside, self.root / "alias.txt")
        self.assertEqual(self.run_tool("filesystem.write_text", path="alias.txt", content="changed")["state"], "DENIED")
        self.assertEqual(outside.read_text(), "preserve")

    def test_failed_atomic_replace_retains_before_state_and_recovery_record(self):
        target = self.root / "note.txt"
        target.write_text("original", encoding="utf-8")
        with patch("chutku.core.paths.os.replace", side_effect=PermissionError("locked")):
            result = self.run_tool("filesystem.write_text", path="note.txt", content="new")
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(target.read_text(), "original")
        operation = self.runtime.journal.incomplete("filesystem.write_text")[0]
        self.assertEqual(self.run_tool("filesystem.recover_incomplete_write", operation_id=operation["operation_id"])["state"], "COMPLETED")
        self.assertFalse(list(self.root.glob(".chutku-*.tmp")))

    def test_unverified_write_is_not_marked_completed_in_journal(self):
        with patch("chutku.tools.builtin.read_bounded_text", return_value="unexpected result"):
            result = self.run_tool("filesystem.write_text", path="mismatch.txt", content="intended")
        self.assertEqual(result["verification"], "UNKNOWN")
        self.assertEqual(result["state"], "FAILED")
        self.assertIsNone(self.runtime.journal.latest_completed("filesystem.write_text"))
        self.assertEqual(len(self.runtime.journal.incomplete("filesystem.write_text")), 1)

    def test_explicit_memory_survives_restart_and_can_be_forgotten(self):
        self.assertEqual(self.run_tool("memory.remember", key="Language", value="English")["state"], "COMPLETED")
        self.runtime.close()
        self.runtime = create_runtime(self.base)
        entries = self.run_tool("memory.search", query="ENGLISH")["output"]["memories"]
        self.assertEqual(entries[0]["key"], "language")
        self.assertEqual(entries[0]["provenance"], "user_stated")
        waiting = self.run_tool("memory.forget", key="language")
        self.assertEqual(waiting["state"], "WAITING_CONFIRMATION")  # deleting always asks first
        self.assertEqual(len(self.run_tool("memory.search")["output"]["memories"]), 1)
        self.assertEqual(self.runtime.approve(waiting["approval"]["token"])["state"], "COMPLETED")
        self.assertEqual(self.run_tool("memory.search")["output"]["memories"], [])

    def test_memory_values_and_queries_do_not_enter_audit_log(self):
        secret = "private-example-value"
        self.run_tool("memory.remember", key="note", value=secret)
        self.run_tool("memory.search", query=secret)
        rows = self.runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall()
        self.assertNotIn(secret, str(rows))

    def test_memory_rejects_missing_unknown_and_oversized_arguments(self):
        for args in ({"key": "a"}, {"key": "a", "value": "x", "risk": 0}, {"key": "../a", "value": "x"}, {"key": "a", "value": "x" * 2001}):
            self.assertEqual(self.runtime.run("memory.remember", args)["state"], "FAILED")
        self.assertEqual(self.runtime.memory.search(), [])

    def test_capabilities_are_generated_from_registry(self):
        self.runtime.registry.register(Tool("test.new", "New tool", Risk.OBSERVATION, lambda a, c: ToolResult({}, Verification.PASS)))
        names = {item["name"] for item in self.run_tool("assistant.capabilities")["output"]["capabilities"]}
        self.assertEqual(names, {tool.name for tool in self.runtime.registry.list()})

    def test_capability_manifests_expose_policy_and_verification_contract(self):
        manifests = {item["name"]: item for item in
                     self.run_tool("assistant.capabilities")["output"]["capabilities"]}
        launch = manifests["process.launch"]
        self.assertEqual(launch["required_capability"], "process.launch")
        self.assertEqual(launch["risk"], {"level": 3, "name": "external_side_effect"})
        self.assertEqual(launch["argument_schema"]["required"], ["executable"])
        self.assertFalse(launch["argument_schema"]["additionalProperties"])
        self.assertEqual(launch["sensitive_argument_names"], ["arguments"])
        self.assertEqual(launch["reversibility"], "compensatable")
        self.assertEqual(launch["success_predicate"],
                         "spawned_pid_image_matches_reviewed_executable")
        terminate = manifests["process.terminate"]
        self.assertEqual(terminate["reversibility"], "irreversible")
        self.assertEqual(terminate["required_capability"], "process.terminate")
        self.assertEqual(set(manifests), {tool.name for tool in self.runtime.registry.list()})
        for manifest in manifests.values():
            self.assertEqual(manifest["argument_schema"]["type"], "object")
            self.assertFalse(manifest["argument_schema"]["additionalProperties"])
            self.assertTrue(manifest["success_predicate"])
            self.assertTrue(manifest["reversibility"])

    def test_window_titles_are_redacted_in_audit(self):
        with patch("chutku.tools.assistant.visible_windows", return_value=[{"title": "private-window-title", "process_id": 42}]):
            result = self.run_tool("windows.list")
        self.assertEqual(result["state"], "COMPLETED")
        self.assertIn("private-window-title", present(result))
        self.assertNotIn("private-window-title", json.dumps(self.runtime.event_log.safe_trace(result["task_id"])))

    def test_project_recipe_is_verified_and_steps_are_traceable(self):
        plan = project_plan("Demo", self.root)
        self.assertFalse((self.root / "Demo").exists())
        result = run_project(plan, self.runtime)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(len(result["steps"]), 6)
        self.assertEqual({p.name for p in (self.root / "Demo").iterdir()}, {"README.md", "tasks.md"})
        trace = self.runtime.event_log.safe_trace(result["task_id"])
        self.assertEqual(sum(event["event_type"] == "workflow_step" for event in trace), 6)
        for step in result["steps"]:
            self.assertTrue(self.runtime.event_log.safe_trace(step["task_id"]))

    def test_project_rerun_preserves_existing_files(self):
        plan = project_plan("Demo", self.root)
        run_project(plan, self.runtime)
        target = self.root / "Demo" / "README.md"
        target.write_text("manual edit", encoding="utf-8")
        result = run_project(plan, self.runtime)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["steps"], [])
        self.assertEqual(target.read_text(), "manual edit")

    def test_recipe_rejects_tampering_before_any_mutation(self):
        plan = project_plan("Demo", self.root)
        plan["steps"][1]["arguments"]["path"] = "../escape.txt"
        self.assertEqual(run_project(plan, self.runtime)["state"], "FAILED")
        self.assertFalse((self.root / "Demo").exists())

    def test_workflow_stops_after_failed_step_and_records_partial_state(self):
        plan = project_plan("Demo", self.root)
        real_run = self.runtime.run
        def fail_second(tool, args):
            if tool == "filesystem.write_text":
                return {"task_id": "simulated", "state": "FAILED", "error": "disk full"}
            return real_run(tool, args)
        with patch.object(self.runtime, "run", side_effect=fail_second):
            result = run_project(plan, self.runtime)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(list((self.root / "Demo").iterdir()), [])

    def test_catalog_preserves_data_and_routes_new_commands(self):
        catalog = CommandCatalog()
        self.assertEqual(catalog.route("write two  spaces to note.txt").arguments["content"], "two  spaces")
        self.assertEqual(catalog.route("remember note = two  spaces").arguments["value"], "two  spaces")
        for text, tool in (("list windows", "windows.list"), ("capabilities", "assistant.capabilities"),
                           ("recall note", "memory.search"), ("forget note", "memory.forget"),
                           ("list files in Demo", "filesystem.list")):
            self.assertEqual(catalog.route(text).tool_name, tool)


if __name__ == "__main__":
    unittest.main()
