from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.app import create_runtime
from chutku.core.action_control import ActionControl
from chutku.core.execution_lock import ExecutionBusy
from chutku.tools.registry import Tool, ToolResult, Risk, Verification
from chutku.workflows import project_plan, run_project


class ActionControlTests(unittest.TestCase):
    def test_pause_survives_restart_and_blocks_writes_until_explicit_resume(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            control = ActionControl(base)
            control.pause()
            control.pause()
            with create_runtime(base) as runtime:
                result = runtime.run("filesystem.write_text", {"path": "blocked.txt", "content": "test"})
                self.assertEqual(result["state"], "FAILED")
                self.assertFalse((runtime.granted_root / "blocked.txt").exists())
                self.assertTrue(ActionControl(base).paused)
                control.resume()
                self.assertEqual(runtime.run("system.get_time", {})["state"], "COMPLETED")

    def test_pause_during_execution_records_failure_and_cannot_resume_early(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            control = ActionControl(Path(temp))
            def execute(args, context):
                control.pause()
                with self.assertRaises(ExecutionBusy):
                    control.resume()
                return ToolResult({"effect_may_have_completed": True}, Verification.PASS)
            runtime.registry.register(Tool("test.pause", "test", Risk.REVERSIBLE, execute))
            result = runtime.run("test.pause", {})
            self.assertEqual(result["state"], "FAILED")
            self.assertIn("in-flight", result["error"])
            control.resume()
            self.assertFalse(control.paused)

    def test_paused_workflow_cannot_create_files(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.action_control.pause()
            result = run_project(project_plan("Paused Project", runtime.granted_root), runtime)
            self.assertEqual(result["state"], "FAILED")
            self.assertFalse((runtime.granted_root / "Paused Project").exists())
