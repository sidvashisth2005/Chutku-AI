"""General keyboard/mouse tools: key parsing, finding text on screen, phrases, and owner-mode file safety."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.input_intent import parse_input
from chutku.policy.kernel import Decision
from chutku.tools import free_input
from chutku.tools.free_input import CTRL, SHIFT, file_risk, find_text, parse_keys


def lines(*items):
    return [{"text": text, "rect": rect} for text, rect in items]


class KeyParsingTests(unittest.TestCase):
    def test_combos_sequences_and_names(self):
        self.assertEqual(parse_keys("ctrl+shift+t"), [[CTRL, SHIFT, 0x54]])
        self.assertEqual(parse_keys("Ctrl K, ctrl c"), [[CTRL, 0x4B], [CTRL, 0x43]])
        self.assertEqual(parse_keys("f5"), [[0x74]])
        self.assertEqual(parse_keys("win+d"), [[0x5B, 0x44]])
        self.assertEqual(parse_keys("alt + tab"), [[0x12, 0x09]])

    def test_refuses_unknown_too_many_and_ctrl_alt_del(self):
        for bad in ("ctrl+banana", "", "a, b, c, d, e, f, g", "ctrl+alt+del"):
            with self.assertRaises(ValueError, msg=bad):
                parse_keys(bad)


class FindTextTests(unittest.TestCase):
    SCREEN = lines(("Downloads", (10, 100, 90, 116)), ("Open Downloads folder", (300, 400, 500, 416)),
                   ("Settings", (10, 140, 70, 156)), ("Settings", (10, 600, 70, 616)))

    def test_exact_line_wins_then_words_inside_a_line(self):
        self.assertEqual(find_text(self.SCREEN, "downloads")[:2], (50, 108))
        x, y, seen = find_text(self.SCREEN, "Downloads folder")
        self.assertEqual((y, seen), (408, "Open Downloads folder"))
        self.assertGreater(x, 400)                                    # points at the words, not the line centre

    def test_repeats_need_nth_and_missing_text_is_an_error(self):
        with self.assertRaises(ValueError):
            find_text(self.SCREEN, "Settings")
        self.assertEqual(find_text(self.SCREEN, "Settings", 2)[1], 608)
        with self.assertRaises(ValueError):
            find_text(self.SCREEN, "Submit")
        with self.assertRaises(ValueError):
            find_text(self.SCREEN, "Settings", 3)


class PhraseTests(unittest.TestCase):
    def test_keys_and_clicks(self):
        self.assertEqual(parse_input("ctrl shift t dabao")[:2], ("keyboard.keys", {"keys": "ctrl shift t"}))
        self.assertEqual(parse_input("press down 5 times")[:2], ("keyboard.keys", {"keys": "down", "repeat": 5}))
        self.assertEqual(parse_input("Downloads pe click karo")[:2], ("mouse.click", {"text": "Downloads"}))
        self.assertEqual(parse_input("right click on Recycle Bin")[:2],
                         ("mouse.click", {"text": "Recycle Bin", "button": "right"}))
        self.assertEqual(parse_input("double click on the Chrome icon")[:2],
                         ("mouse.click", {"text": "Chrome", "double": True}))

    def test_vague_targets_are_left_to_screen_understanding(self):
        for text in ("click the first video", "click on it", "press the button", "click that button",
                     "press ctrl+alt+del", "spotify band karo"):
            self.assertIsNone(parse_input(text), text)


class FileSafetyTests(unittest.TestCase):
    def fg(self, exe):
        return patch.object(free_input, "_foreground", return_value=(None, {"title": "x"}, exe))

    def test_saving_always_asks(self):
        with self.fg("notepad.exe"):
            self.assertIsNotNone(file_risk("keyboard.keys", {"keys": "ctrl+s"}))
            self.assertIsNotNone(file_risk("keyboard.keys", {"keys": "ctrl+shift+s"}))
            self.assertIsNotNone(file_risk("keyboard.edit", {"action": "save"}))
            self.assertIsNone(file_risk("keyboard.keys", {"keys": "delete"}))       # deleting text, not files
            self.assertIsNone(file_risk("keyboard.keys", {"keys": "ctrl+shift+t"}))

    def test_file_explorer_delete_rename_move_keys_ask(self):
        with self.fg("explorer.exe"):
            for keys in ("delete", "shift+delete", "f2", "ctrl+x", "ctrl+v", "ctrl+z", "ctrl+d"):
                self.assertIsNotNone(file_risk("keyboard.keys", {"keys": keys}), keys)
            self.assertIsNotNone(file_risk("keyboard.edit", {"action": "delete"}))
            self.assertIsNotNone(file_risk("mouse.drag", {"from_x": 1, "from_y": 1, "to_x": 9, "to_y": 9}))
            self.assertIsNone(file_risk("keyboard.keys", {"keys": "ctrl+shift+n"}))  # new folder: creates only

    def test_clicking_delete_like_buttons_asks_even_by_coordinates(self):
        for text in ("Delete", "Uninstall", "Move to Recycle Bin", "Save", "Replace the file"):
            self.assertIsNotNone(file_risk("mouse.click", {"text": text}), text)
        self.assertIsNone(file_risk("mouse.click", {"text": "Downloads"}))
        with patch.object(free_input, "_text_at", return_value="Delete"):
            self.assertIsNotNone(file_risk("mouse.click", {"x": 10, "y": 10}))
        with patch.object(free_input, "_text_at", side_effect=OSError("no screen")):
            self.assertIsNotNone(file_risk("mouse.click", {"x": 10, "y": 10}))  # cannot check: asks

    def test_owner_mode_runs_safe_input_and_asks_for_file_changes(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(mind, "PROJECT_ROOT", Path(temp.name)), create_runtime(Path(temp.name) / "s") as runtime, \
                self.fg("chrome.exe"):
            def decide(name, arguments, mode="owner"):
                tool = runtime.registry.get(name)
                return runtime.policy.authorize(tool, arguments, provenance="delegated", capability_allowed=True,
                                                autonomy=mode, owner_question=runtime.owner_question(tool, arguments)
                                                if mode == "owner" else None).decision
            self.assertEqual(decide("keyboard.keys", {"keys": "ctrl+shift+t"}), Decision.ALLOW)
            self.assertEqual(decide("mouse.click", {"text": "Downloads"}), Decision.ALLOW)
            self.assertEqual(decide("mouse.move", {"text": "Downloads"}), Decision.ALLOW)
            self.assertEqual(decide("keyboard.keys", {"keys": "ctrl+s"}), Decision.CONFIRM)
            self.assertEqual(decide("mouse.click", {"text": "Delete"}), Decision.CONFIRM)
            self.assertEqual(decide("keyboard.keys", {"keys": "ctrl+shift+t"}, "auto_safe"), Decision.CONFIRM)


if __name__ == "__main__":
    unittest.main()
