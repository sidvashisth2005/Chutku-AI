import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from chutku.app import create_runtime


class ProcessToolTests(unittest.TestCase):
    @staticmethod
    def _completed():
        class Completed:
            returncode = 0
            stdout = json.dumps([
                {"ProcessId": 10, "Name": "alpha.exe", "ExecutablePath": r"C:\Apps\alpha.exe"},
                {"ProcessId": 20, "Name": "beta.exe", "ExecutablePath": None},
            ])
        return Completed()

    def test_observation_requires_exact_capability_and_redacts_audit(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            with patch("chutku.tools.processes.subprocess.run", return_value=self._completed()):
                self.assertEqual(runtime.run("process.list", {})["state"], "DENIED")
                runtime.capability_grants.grant("process.observe")
                result = runtime.run("process.list", {})
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["output"]["processes"][0]["pid"], 10)
            events = runtime.event_log.events_for(result["task_id"])
            tool_result = next(payload for name, payload in events if name == "tool_result")
            self.assertEqual(tool_result["output"]["processes"], "[REDACTED]")

    def test_status_is_exact_and_arguments_are_bounded(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("process.observe")
            with patch("chutku.tools.processes.subprocess.run", return_value=self._completed()):
                self.assertTrue(runtime.run("process.status", {"pid": 20})["output"]["running"])
                self.assertFalse(runtime.run("process.status", {"pid": 99})["output"]["running"])
            self.assertEqual(runtime.run("process.status", {"pid": "20"})["state"], "FAILED")

    def test_status_uses_exact_pid_query_not_truncated_inventory(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("process.observe")
            with patch("chutku.tools.processes.subprocess.run", return_value=self._completed()) as run:
                runtime.run("process.status", {"pid": 20})
            command = run.call_args.args[0][-1]
            self.assertIn('ProcessId = 20', command)
            self.assertNotIn('First 200', command)

    def test_query_failure_is_not_reported_as_empty_success(self):
        class Failed:
            returncode = 1
            stdout = ""
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("process.observe")
            with patch("chutku.tools.processes.subprocess.run", return_value=Failed()):
                result = runtime.run("process.list", {})
            self.assertEqual(result["state"], "FAILED")

    def test_launch_requires_capability_and_approval_then_verifies_image(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            executable = Path(temp) / "test.exe"
            executable.write_bytes(b"fixture")
            process = Mock(pid=321)
            process.poll.return_value = None
            # Windows reports the full long path, never an 8.3 alias like the CI runner's C:\Users\RUNNER~1\...
            observed = [{"pid": 321, "name": "test.exe", "executable": str(executable.resolve())}]
            denied = runtime.run("process.launch", {"executable": str(executable)})
            self.assertEqual(denied["state"], "DENIED")
            runtime.capability_grants.grant("process.launch")
            pending = runtime.run("process.launch", {"executable": str(executable), "arguments": []})
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.processes.subprocess.Popen", return_value=process), \
                    patch("chutku.tools.processes._snapshot", return_value=observed), \
                    patch("chutku.tools.processes.time.sleep"):
                result = runtime.approve(pending["approval"]["token"])
            self.assertEqual(result["state"], "COMPLETED")

    def test_termination_rechecks_exact_identity_and_protected_processes(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            executable = Path(temp) / "worker.exe"
            other = Path(temp) / "other.exe"
            executable.write_bytes(b"fixture")
            other.write_bytes(b"fixture")
            runtime.capability_grants.grant("process.terminate")
            pending = runtime.run("process.terminate", {"pid": 222, "expected_executable": str(executable)})
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.processes._snapshot", return_value=[
                    {"pid": 222, "name": "other.exe", "executable": str(other)}]), \
                    patch("chutku.tools.processes.subprocess.run") as terminate:
                result = runtime.approve(pending["approval"]["token"])
            self.assertEqual(result["state"], "FAILED")
            terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
