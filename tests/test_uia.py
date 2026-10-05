import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from chutku.app import create_runtime


WINDOW = {"window_id": 123, "process_id": 456, "title": "Private note",
          "image": r"C:\Windows\System32\notepad.exe", "minimized": False}
ELEMENT = {"index": 0, "parent": -1, "depth": 0, "name": "Private note",
           "automation_id": "root", "class_name": "Notepad", "control_type": "ControlType.Window",
           "enabled": True, "offscreen": False, "patterns": [],
           "x": 10, "y": 20, "width": 800, "height": 600}


class UIAutomationTests(unittest.TestCase):
    def test_inspection_requires_capability_exact_window_and_redacts_audit(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("uia.inspect", {"app": "notepad"})["state"], "DENIED")
            runtime.capability_grants.grant("screen.observe")
            desktop = MagicMock()
            desktop.windows.side_effect = [[WINDOW], [WINDOW]]
            desktop.responsive.return_value = True
            raw = {"root_hwnd": 123, "elements": [ELEMENT], "truncated": False}
            with patch("chutku.tools.uia.WindowsDesktop", return_value=desktop), \
                    patch("chutku.tools.uia._invoke", return_value=raw):
                result = runtime.run("uia.inspect", {"app": "notepad"})
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["output"]["elements"], [ELEMENT])
            rows = runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall()
            self.assertNotIn("Private note", json.dumps(rows))

    def test_ambiguous_unresponsive_or_changed_window_fails_closed(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("screen.observe")
            for windows, responsive in (([WINDOW, {**WINDOW, "window_id": 999}], True), ([WINDOW], False)):
                desktop = MagicMock()
                desktop.windows.return_value = windows
                desktop.responsive.return_value = responsive
                with patch("chutku.tools.uia.WindowsDesktop", return_value=desktop), \
                        patch("chutku.tools.uia._invoke") as invoke:
                    self.assertEqual(runtime.run("uia.inspect", {"app": "notepad"})["state"], "FAILED")
                    invoke.assert_not_called()
            desktop = MagicMock()
            desktop.windows.side_effect = [[WINDOW], [{**WINDOW, "process_id": 999}]]
            desktop.responsive.return_value = True
            raw = {"root_hwnd": 123, "elements": [ELEMENT], "truncated": False}
            with patch("chutku.tools.uia.WindowsDesktop", return_value=desktop), \
                    patch("chutku.tools.uia._invoke", return_value=raw):
                self.assertEqual(runtime.run("uia.inspect", {"app": "notepad"})["state"], "FAILED")

    def test_malformed_or_oversized_results_and_arguments_fail_closed(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("screen.observe")
            for arguments in ({}, {"app": "word"}, {"app": "notepad", "max_depth": 6},
                              {"app": "notepad", "max_elements": 251},
                              {"app": "notepad", "extra": True}):
                self.assertEqual(runtime.run("uia.inspect", arguments)["state"], "FAILED")
            desktop = MagicMock()
            desktop.windows.return_value = [WINDOW]
            desktop.responsive.return_value = True
            malformed = {"root_hwnd": 999, "elements": [ELEMENT], "truncated": False}
            with patch("chutku.tools.uia.WindowsDesktop", return_value=desktop), \
                    patch("chutku.tools.uia._invoke", return_value=malformed):
                self.assertEqual(runtime.run("uia.inspect", {"app": "notepad"})["state"], "FAILED")


if __name__ == "__main__":
    unittest.main()
