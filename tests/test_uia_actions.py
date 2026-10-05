import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from chutku.app import create_runtime


WINDOW = {"window_id": 123, "process_id": 456, "title": "App",
          "image": r"C:\Windows\System32\notepad.exe", "minimized": False}
BUTTON = {"automation_id": "go", "control_type": "ControlType.Button"}


class UIActionTests(unittest.TestCase):
    def run_approved(self, runtime, tool, arguments, verified=True, foreground=123):
        pending = runtime.run(tool, arguments)
        self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
        desktop = MagicMock()
        desktop.windows.side_effect = [[WINDOW], [WINDOW]]
        desktop.responsive.return_value = True
        desktop.foreground.return_value = foreground
        with patch("chutku.tools.uia_actions.WindowsDesktop", return_value=desktop), \
                patch("chutku.tools.uia_actions._invoke",
                      return_value={"verified": verified, "action": tool.rsplit(".", 1)[1], "before": None}):
            return runtime.approve(pending["approval"]["token"])

    def test_all_actions_require_capability_review_and_verified_postcondition(self):
        cases = [
            ("uia.invoke", {"app": "notepad", "selector": BUTTON,
                            "expect": {"selector": BUTTON, "property": "exists", "expected": True}}),
            ("uia.expand", {"app": "notepad", "selector": BUTTON,
                            "expect": {"selector": BUTTON, "property": "exists", "expected": True}}),
            ("uia.set_value", {"app": "notepad",
                               "selector": {"automation_id": "text", "control_type": "ControlType.Edit"},
                               "value": "private value"}),
            ("uia.select", {"app": "notepad",
                            "selector": {"automation_id": "item", "control_type": "ControlType.ListItem"}}),
            ("uia.scroll", {"app": "notepad",
                            "selector": {"automation_id": "pane", "control_type": "ControlType.Pane"},
                            "axis": "vertical", "direction": "increment"}),
            ("input.type_text", {"app": "notepad",
                                 "selector": {"automation_id": "text", "control_type": "ControlType.Edit"},
                                 "text": "private typed value"}),
            ("input.click", {"app": "notepad", "selector": BUTTON,
                             "expect": {"selector": BUTTON, "property": "name", "expected": "done"}}),
        ]
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            for tool, arguments in cases:
                self.assertEqual(runtime.run(tool, arguments)["state"], "DENIED")
            runtime.capability_grants.grant("desktop.input")
            for tool, arguments in cases:
                with self.subTest(tool=tool):
                    self.assertEqual(self.run_approved(runtime, tool, arguments)["state"], "COMPLETED")
            rows = runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall()
            self.assertNotIn("private value", json.dumps(rows))

    def test_focus_loss_or_failed_postcondition_never_succeeds(self):
        args = {"app": "notepad", "selector": BUTTON,
                "expect": {"selector": BUTTON, "property": "exists", "expected": True}}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("desktop.input")
            self.assertEqual(self.run_approved(runtime, "uia.invoke", args, foreground=999)["state"], "FAILED")
            self.assertEqual(self.run_approved(runtime, "uia.invoke", args, verified=False)["state"], "FAILED")

    def test_invalid_selectors_actions_and_expectations_fail_before_adapter(self):
        invalid = [
            ("uia.invoke", {"app": "notepad", "selector": BUTTON, "expect": {}}),
            ("uia.set_value", {"app": "notepad", "selector": {"control_type": "ControlType.Edit"}, "value": "x"}),
            ("uia.select", {"app": "word", "selector": BUTTON}),
            ("uia.scroll", {"app": "notepad", "selector": BUTTON,
                            "axis": "diagonal", "direction": "increment"}),
            ("input.type_text", {"app": "notepad", "selector": BUTTON, "text": 3}),
        ]
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("desktop.input")
            with patch("chutku.tools.uia_actions._invoke") as invoke:
                for tool, args in invalid:
                    self.assertEqual(runtime.run(tool, args)["state"], "FAILED")
                invoke.assert_not_called()

    def test_exact_window_target_rebinds_hwnd_pid_and_executable_before_and_after(self):
        args = {"window": {"window_id": 123, "process_id": 456,
                           "executable": r"C:\Fixture\fixture.exe"},
                "selector": BUTTON,
                "expect": {"selector": BUTTON, "property": "exists", "expected": True}}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("desktop.input")
            pending = runtime.run("uia.invoke", args)
            desktop = MagicMock()
            desktop.exact_window.side_effect = [WINDOW, WINDOW]
            desktop.responsive.return_value = True
            desktop.foreground.return_value = 123
            with patch("chutku.tools.uia_actions.WindowsDesktop", return_value=desktop), \
                    patch("chutku.tools.uia_actions._invoke", return_value={"verified": True}):
                result = runtime.approve(pending["approval"]["token"])
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(desktop.exact_window.call_count, 2)
            desktop.exact_window.assert_called_with(123, 456, r"C:\Fixture\fixture.exe")


if __name__ == "__main__":
    unittest.main()
