import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from chutku.app import create_runtime
from chutku.core.execution_lock import ExecutionBusy, ExecutionLock
from chutku.tools.registry import Risk, Tool, ToolResult, Verification
from chutku.workflows import project_plan, run_project


class WindowsFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)
        self.window = {"window_id": 123, "process_id": 456, "title": "Private note - Notepad"}

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_only_named_allowed_apps_can_launch(self):
        with patch("chutku.tools.windows_apps.WindowsDesktop") as desktop:
            for arguments in ({"app": "powershell"}, {"app": "notepad.exe"}, {"app": "notepad", "command": "evil"}, {"app": "C:/notepad.exe"}):
                self.assertEqual(self.runtime.run("apps.open", arguments)["state"], "FAILED")
            desktop.assert_not_called()

    def test_launch_verifies_real_window_after_launcher_returns(self):
        desktop = MagicMock()
        desktop.windows.side_effect = [[], [self.window], [self.window], [self.window]]
        desktop.responsive.return_value = True
        desktop.foreground.return_value = 123
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop), patch("chutku.tools.windows_apps.time.monotonic", side_effect=[0, 0, 0, 0, 1, 1]):
            result = self.runtime.run("apps.open", {"app": "notepad"})
        self.assertEqual(result["state"], "COMPLETED")
        desktop.launch.assert_called_once_with("notepad")
        self.assertTrue(any(e["event_type"] == "verification_result" for e in self.runtime.event_log.safe_trace(result["task_id"])))
        self.assertNotIn(self.window["title"], json.dumps(self.runtime.event_log.safe_trace(result["task_id"])))

    def test_existing_window_does_not_launch_another_instance(self):
        desktop = MagicMock()
        desktop.windows.return_value = [self.window]
        desktop.responsive.return_value = True
        desktop.foreground.return_value = 123
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop):
            self.assertEqual(self.runtime.run("apps.open", {"app": "notepad"})["state"], "COMPLETED")
        desktop.launch.assert_not_called()

    def test_process_launch_without_window_cannot_report_success(self):
        desktop = MagicMock()
        desktop.windows.return_value = []
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop), patch("chutku.tools.windows_apps.time.monotonic", side_effect=[0, 11]):
            result = self.runtime.run("apps.open", {"app": "notepad"})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("no matching visible window", result["output"]["error"])

    def test_disappearing_or_hung_window_fails_verification(self):
        for observations, responsive in (([[self.window], [self.window], [self.window], []], True),
                                          ([[self.window], [self.window]], False)):
            desktop = MagicMock()
            desktop.windows.side_effect = observations
            desktop.responsive.return_value = responsive
            ticks = [0, 0, 0, 0, 1, 1] if responsive else [0, 0, 11]
            with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop), patch("chutku.tools.windows_apps.time.monotonic", side_effect=ticks):
                self.assertEqual(self.runtime.run("apps.open", {"app": "notepad"})["state"], "FAILED")

    def test_focus_refuses_ambiguous_windows(self):
        self.runtime.capability_grants.grant("desktop.input")
        desktop = MagicMock()
        desktop.windows.return_value = [self.window, self.window | {"window_id": 124}]
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop):
            self.assertEqual(self.runtime.run("apps.focus", {"app": "notepad"})["state"], "FAILED")
        desktop.focus.assert_not_called()

    def test_focus_reports_os_refusal_instead_of_false_success(self):
        self.runtime.capability_grants.grant("desktop.input")
        desktop = MagicMock()
        desktop.windows.return_value = [self.window]
        desktop.responsive.return_value = True
        desktop.foreground.return_value = 999
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop), patch("chutku.tools.windows_apps.time.monotonic", side_effect=[0, 2]):
            result = self.runtime.run("apps.focus", {"app": "notepad"})
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["verification"], "UNKNOWN")
        self.assertIn("foreground", result["output"]["error"])

    def test_graceful_close_requires_exact_capability_approval_and_reobservation(self):
        denied = self.runtime.run("apps.close", {"app": "notepad"})
        self.assertEqual(denied["state"], "DENIED")
        self.runtime.capability_grants.grant("desktop.input")
        pending = self.runtime.run("apps.close", {"app": "notepad"})
        self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
        desktop = MagicMock()
        desktop.windows.side_effect = [[self.window], []]
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop), \
                patch("chutku.tools.windows_apps.time.monotonic", return_value=0):
            result = self.runtime.approve(pending["approval"]["token"])
        self.assertEqual(result["state"], "COMPLETED")
        desktop.close.assert_called_once_with(self.window["window_id"])

    def test_graceful_close_refuses_ambiguous_windows_without_sending_close(self):
        self.runtime.capability_grants.grant("desktop.input")
        pending = self.runtime.run("apps.close", {"app": "notepad"})
        desktop = MagicMock()
        desktop.windows.return_value = [self.window, self.window | {"window_id": 124}]
        with patch("chutku.tools.windows_apps.WindowsDesktop", return_value=desktop):
            result = self.runtime.approve(pending["approval"]["token"])
        self.assertEqual(result["state"], "FAILED")
        desktop.close.assert_not_called()

    def test_verifier_can_reject_executor_success(self):
        self.runtime.registry.register(Tool("test.false_success", "fake", Risk.OBSERVATION,
            lambda a, c: ToolResult({}, Verification.PASS),
            verify=lambda a, r, c: ToolResult({"error": "Observed wrong state"}, Verification.FAIL)))
        self.assertEqual(self.runtime.run("test.false_success", {})["state"], "FAILED")

    def test_lock_blocks_other_runtime_and_releases_after_exception(self):
        with create_runtime(self.base) as second:
            try:
                with self.runtime.execution_lock:
                    self.assertEqual(second.run("filesystem.write_text", {"path": "blocked.txt", "content": "x"})["state"], "FAILED")
                    self.assertFalse((self.runtime.granted_root / "blocked.txt").exists())
                    raise ValueError("simulated failure")
            except ValueError:
                pass
            self.assertEqual(second.run("system.get_time", {})["state"], "COMPLETED")

    def test_a_step_waits_for_a_side_by_side_tasks_step_when_asked(self):
        """Y3: the dashboard's tasks set step_wait, so a step waits for the other task's step instead of failing."""
        import threading
        import time
        with create_runtime(self.base) as second:
            second.step_wait = 5
            self.runtime.execution_lock.__enter__()
            threading.Timer(0.5, self.runtime.execution_lock.__exit__).start()   # the other step ends in 0.5 s
            started = time.monotonic()
            result = second.run("filesystem.write_text", {"path": "waited.txt", "content": "x"})
            self.assertEqual(result["state"], "COMPLETED", result)
            self.assertGreaterEqual(time.monotonic() - started, 0.4)
            self.assertEqual((self.runtime.granted_root / "waited.txt").read_text(encoding="utf-8"), "x")

    def test_workflow_can_reenter_its_owned_execution_lock(self):
        with self.runtime.execution_lock:
            self.assertEqual(run_project(project_plan("Nested", self.runtime.granted_root), self.runtime)["state"], "COMPLETED")

    def test_lock_is_released_when_owner_process_is_killed(self):
        script = "import sys,time;from pathlib import Path;from chutku.core.execution_lock import ExecutionLock\nwith ExecutionLock(Path(sys.argv[1])):\n print('LOCKED',flush=True)\n time.sleep(30)"
        process = subprocess.Popen([sys.executable, "-c", script, str(self.runtime.execution_lock.path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "LOCKED")
            with self.assertRaises(ExecutionBusy):
                with self.runtime.execution_lock:
                    pass
        finally:
            process.kill()
            process.communicate(timeout=5)
        with self.runtime.execution_lock:
            self.assertEqual(self.runtime.run("system.get_time", {})["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
