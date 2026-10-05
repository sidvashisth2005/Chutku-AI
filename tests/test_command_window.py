"""Typing into a command window, opening the Run box or a command-line app asks first (master plan S1)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.policy.kernel import Decision
from chutku.tools import desktop_controls, free_input
from chutku.tools.registry import ExecutionContext, Verification


def window(exe, title="Window"):
    return {"window_id": 1, "process_id": 2, "executable": f"C:/Somewhere/{exe}", "title": title}


class CommandWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "mind")
        self.mind_root.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def front(self, exe, title="Window"):
        info = window(exe, title)
        return patch.object(free_input, "_foreground", return_value=(None, info, exe))

    def decide(self, name, arguments, mode):
        tool = self.runtime.registry.get(name)
        return self.runtime.policy.authorize(
            tool, arguments, provenance="delegated", resource_access=frozenset({"observe", "modify"}),
            capability_allowed=True, autonomy=mode, tainted=False, exposed=False,
            owner_question=self.runtime.step_question(tool, arguments)).decision

    def test_detects_command_windows(self):
        for exe in ("cmd.exe", "powershell.exe", "pwsh.exe", "WindowsTerminal.exe"):
            self.assertIsNotNone(desktop_controls.command_window_reason(window(exe)), exe)
        self.assertIsNotNone(desktop_controls.command_window_reason(window("explorer.exe", "Run")))
        self.assertIsNone(desktop_controls.command_window_reason(window("explorer.exe", "Downloads")))
        self.assertIsNone(desktop_controls.command_window_reason(window("notepad.exe", "Untitled - Notepad")))

    def test_typing_into_a_command_window_asks_in_every_mode(self):
        with self.front("cmd.exe"):
            for mode in ("owner", "auto_edits", "auto_safe"):
                self.assertEqual(self.decide("keyboard.type_text", {"text": "dir"}, mode), Decision.CONFIRM, mode)
                self.assertEqual(self.decide("keyboard.press_enter", {}, mode), Decision.CONFIRM, mode)
        with self.front("notepad.exe", "Untitled - Notepad"):
            self.assertEqual(self.decide("keyboard.type_text", {"text": "hello"}, "owner"), Decision.ALLOW)

    def test_run_box_and_command_apps_ask(self):
        self.assertEqual(self.decide("keyboard.shortcut", {"action": "run_dialog"}, "owner"), Decision.CONFIRM)
        self.assertEqual(self.decide("keyboard.shortcut", {"action": "new_tab"}, "owner"), Decision.ALLOW)
        self.assertEqual(self.decide("apps.launch", {"name": "Command Prompt"}, "owner"), Decision.CONFIRM)
        self.assertEqual(self.decide("apps.launch", {"name": "Windows PowerShell"}, "owner"), Decision.CONFIRM)
        self.assertEqual(self.decide("apps.launch", {"name": "Spotify"}, "owner"), Decision.ALLOW)

    def test_cannot_check_the_window_asks(self):
        with patch.object(free_input, "_foreground", side_effect=OSError("no desktop")):
            self.assertEqual(self.decide("keyboard.type_text", {"text": "x"}, "owner"), Decision.CONFIRM)

    def test_typing_is_refused_at_execution_when_the_window_turned_into_a_terminal(self):
        context = ExecutionContext("t", None, Path(self.temp.name))
        info = window("powershell.exe")
        with patch.object(desktop_controls, "target_window", return_value=(None, info)), \
                patch.object(desktop_controls, "type_unicode") as typed:
            result = desktop_controls._type_text({"text": "dir"}, context)
        self.assertEqual(result.verification, Verification.FAIL)
        typed.assert_not_called()
        approved = ExecutionContext("t", None, Path(self.temp.name), approved=True)
        desktop = type("FakeDesktop", (), {"foreground": lambda self: 1})()
        with patch.object(desktop_controls, "target_window", return_value=(desktop, info)), \
                patch.object(desktop_controls, "type_unicode") as typed, \
                patch.object(desktop_controls.time, "sleep"):
            desktop_controls._type_text({"text": "dir"}, approved)
        typed.assert_called_once()

    def test_keys_are_refused_in_a_command_window_without_the_click(self):
        context = ExecutionContext("t", None, Path(self.temp.name))
        with self.front("cmd.exe"), patch.object(desktop_controls, "press_combo") as pressed:
            result = free_input._keys({"keys": "enter"}, context)
        self.assertEqual(result.verification, Verification.FAIL)
        pressed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
