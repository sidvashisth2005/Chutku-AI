import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.tools import desktop_controls as dc
from chutku.tools.registry import Risk


class FakeDesktop:
    def __init__(self, windows, foreground):
        self.info = {w["window_id"]: w for w in windows}
        self.order = [w["window_id"] for w in windows]
        self.front = foreground

    def foreground(self):
        return self.front

    def describe(self, hwnd):
        return self.info[hwnd]

    def windows(self):
        return self.order

    def exact(self, window_id, process_id, executable):
        return self.info.get(window_id)


def window(hwnd, title, exe, minimized=False):
    return {"window_id": hwnd, "process_id": hwnd, "title": title, "executable": exe, "minimized": minimized,
            "maximized": False}


class TargetWindowTests(unittest.TestCase):
    def resolve(self, desktop, arguments=None):
        class Focus:
            def focus(self, hwnd):
                desktop.front = hwnd
        with patch("chutku.tools.everyday.Desktop", return_value=desktop), \
                patch("chutku.tools.windows_apps.WindowsDesktop", return_value=Focus()):
            return dc.target_window(arguments or {})[1]

    def test_uses_foreground_app(self):
        desktop = FakeDesktop([window(1, "notes.txt - Notepad", r"C:\x\Notepad.exe")], 1)
        self.assertEqual(self.resolve(desktop)["window_id"], 1)

    def test_skips_chutku_chat_page_to_previous_window(self):
        desktop = FakeDesktop([window(9, "Chutku - Personal - Microsoft Edge", r"C:\e\msedge.exe"),
                               window(5, "Minimized", r"C:\x\a.exe", minimized=True),
                               window(4, "YouTube - Brave", r"C:\b\brave.exe")], 9)
        self.assertEqual(self.resolve(desktop)["window_id"], 4)
        self.assertEqual(desktop.front, 4)

    def test_only_chutku_open_is_refused(self):
        desktop = FakeDesktop([window(9, "Chutku - Microsoft Edge", r"C:\e\msedge.exe")], 9)
        with self.assertRaisesRegex(ValueError, "Only Chutku"):
            self.resolve(desktop)

    def test_vanished_exact_window_refused(self):
        desktop = FakeDesktop([window(1, "a", r"C:\a.exe")], 1)
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            self.resolve(desktop, {"window_id": 77, "process_id": 77, "executable": r"C:\a.exe"})


class ToolContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        for capability in ("desktop.input", "audio.modify", "settings.modify", "settings.observe", "process.observe"):
            self.runtime.capability_grants.grant(capability)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_risk_classes(self):
        risk = lambda name: self.runtime.registry.get(name).base_risk
        self.assertEqual(risk("keyboard.shortcut"), Risk.REVERSIBLE)
        self.assertEqual(risk("keyboard.edit"), Risk.DATA_MODIFICATION)
        self.assertEqual(risk("keyboard.type_text"), Risk.DATA_MODIFICATION)
        self.assertEqual(risk("keyboard.press_enter"), Risk.EXTERNAL_SIDE_EFFECT)

    def test_validation_boundaries(self):
        tool = lambda name: self.runtime.registry.get(name).validate_arguments
        for bad in ({"text": ""}, {"text": "a\nb"}, {"text": "x" * 1001}, {"text": "hi", "window_id": 3}):
            with self.assertRaises(ValueError, msg=bad):
                tool("keyboard.type_text")(bad)
        with self.assertRaises(ValueError):
            tool("keyboard.shortcut")({"action": "alt_f4"})
        with self.assertRaises(ValueError):
            tool("keyboard.shortcut")({"action": "paste"})  # editing keys live in keyboard.edit
        for bad in ({"action": "set"}, {"action": "set", "level": 101}, {"action": "loud"}):
            with self.assertRaises(ValueError):
                tool("audio.volume")(bad)

    def test_volume_up_reads_back(self):
        states = [{"level": 40, "muted": True}]

        def fake(request):
            if request["action"] == "set":
                states.append({"level": request["level"], "muted": request["muted"]})
            return states[-1]
        with patch("chutku.tools.system_controls._volume_call", side_effect=fake):
            result = self.runtime.run("audio.volume", {"action": "up", "step": 15})
        self.assertEqual(str(result["state"]), "COMPLETED")
        self.assertEqual(result["output"]["after"], {"level": 55, "muted": False})

    def test_volume_mismatch_fails(self):
        with patch("chutku.tools.system_controls._volume_call", return_value={"level": 40, "muted": False}):
            result = self.runtime.run("audio.volume", {"action": "set", "level": 70})
        self.assertEqual(str(result["state"]), "FAILED")

    def test_brightness_clamps_and_verifies(self):
        calls = []

        def fake(request):
            calls.append(request)
            return request.get("level", 95)
        with patch.object(dc, "_brightness_call", side_effect=fake):
            result = self.runtime.run("display.brightness", {"action": "up", "step": 20})
        self.assertEqual(result["output"], {"before": 95, "after": 100, "undo_hint": "display.brightness set 95"})

    def test_largest_files(self):
        root = self.runtime.granted_root
        (root / "big.bin").write_bytes(b"x" * 3_000_000)
        (root / "sub").mkdir()
        (root / "sub" / "mid.bin").write_bytes(b"x" * 1_000_000)
        (root / "small.txt").write_text("x")
        result = self.runtime.run("filesystem.largest", {"path": ".", "count": 2})
        names = [Path(f["full_path"]).name for f in result["output"]["files"]]
        self.assertEqual(names, ["big.bin", "mid.bin"])

    def test_wallpaper_refuses_non_images_and_outside_grant(self):
        (self.runtime.granted_root / "evil.exe").write_bytes(b"MZ")
        self.assertEqual(str(self.runtime.run("desktop.wallpaper_set", {"path": "evil.exe"})["state"]), "FAILED")
        self.assertEqual(str(self.runtime.run("desktop.wallpaper_set", {"path": r"C:\Windows\Web\x.jpg"})["state"]),
                         "FAILED")

    def test_intent_guard_for_typing_editing_and_lock(self):
        session = AgentSession("what is on my screen?", mode="auto_edits")
        for tool in ("keyboard.type_text", "keyboard.edit", "system.lock", "keyboard.press_enter"):
            proposal = {"next_steps": [{"tool": tool, "arguments": {}, "purpose": "p"}], "finish": False}
            with self.assertRaises(ValueError, msg=tool):
                session._reject_unrelated_effects(proposal)
        ok = AgentSession("type hello and press enter", mode="auto_edits")
        proposal = {"next_steps": [{"tool": "keyboard.type_text", "arguments": {}, "purpose": "p"},
                                   {"tool": "keyboard.press_enter", "arguments": {}, "purpose": "p"}], "finish": False}
        ok._reject_unrelated_effects(proposal)
        self.assertEqual(len(proposal["next_steps"]), 2)


if __name__ == "__main__":
    unittest.main()


class ExistingDocumentGuardTests(unittest.TestCase):
    def test_existing_documents_are_protected_unless_named(self):
        from chutku.tools.desktop_controls import guard_document
        for title in ("*CHAPTER 1.txt - Notepad", "report.docx - Word", "main.py - app - Visual Studio Code"):
            with self.assertRaisesRegex(ValueError, "existing document"):
                guard_document({"title": title}, {})
            with self.assertRaisesRegex(ValueError, "existing document"):
                guard_document({"title": title}, {"document": "other.txt"})
        guard_document({"title": "report.docx - Word"}, {"document": "report.docx"})
        for title in ("Untitled - Notepad", "Notepad", "Save as", "Calculator"):
            guard_document({"title": title}, {})

    def test_typing_into_a_restored_user_document_is_refused_before_any_key(self):
        from unittest.mock import patch
        from chutku.tools import desktop_controls
        with patch.object(desktop_controls, "target_window", return_value=(None, {"title": "*CHAPTER 1.txt - Notepad",
                                                                                  "executable": "Notepad.exe",
                                                                                  "window_id": 1})), \
                patch.object(desktop_controls, "type_unicode") as typed, \
                patch.object(desktop_controls, "press_combo") as pressed:
            self.assertEqual(desktop_controls._type_text({"text": "hello"}, None).verification.name, "FAIL")
            self.assertEqual(desktop_controls._press_enter({}, None).verification.name, "FAIL")
            _validate, run = desktop_controls._make_shortcut(desktop_controls.EDIT_SHORTCUTS)
            self.assertEqual(run({"action": "save"}, None).verification.name, "FAIL")
        typed.assert_not_called()
        pressed.assert_not_called()
