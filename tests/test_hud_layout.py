"""HUD layout logic: remembered size/position, and a click on another app sends it behind."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import hud


class FakeRoot:
    def __init__(self):
        self.topmost = True
        self.pointer = (10, 10)

    def attributes(self, name, value):
        if name == "-topmost":
            self.topmost = value

    def winfo_pointerxy(self):
        return self.pointer

    def winfo_rootx(self):
        return 100

    def winfo_rooty(self):
        return 100


class FakeUser32:
    def __init__(self):
        self.pressed = False

    def GetAsyncKeyState(self, key):
        return 0x8000 if self.pressed and key == 0x01 else 0


class HudLayoutTests(unittest.TestCase):
    def make(self, saved=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        layout = Path(temp.name) / "hud.json"
        if saved is not None:
            layout.write_text(json.dumps(saved), encoding="utf-8")
        with patch.object(hud, "LAYOUT_FILE", layout):
            panel = hud.Hud(lambda: {}, None)
        panel.root, panel.w, panel.h = FakeRoot(), 400, 500
        panel._release_focus = lambda: None
        return panel

    def click(self, panel, user32, where):
        panel.root.pointer = where
        user32.pressed = True
        with patch.object(hud.ctypes, "windll", type("W", (), {"user32": user32})()):
            panel._watch_outside_click()
            user32.pressed = False
            panel._watch_outside_click()

    def test_click_on_another_app_sends_it_behind_and_inside_clicks_do_not(self):
        panel, user32 = self.make(), FakeUser32()
        self.click(panel, user32, (150, 150))            # inside the panel
        self.assertTrue(panel.root.topmost)
        self.click(panel, user32, (900, 400))            # on another app
        self.assertFalse(panel.root.topmost)
        self.assertFalse(panel.on_top)
        panel._raise()                                   # Ctrl+Alt+Space
        self.assertTrue(panel.root.topmost)

    def test_holding_the_mouse_counts_once_and_dragging_never_hides(self):
        panel, user32 = self.make(), FakeUser32()
        panel._drag = ("move", 0, 0)
        self.click(panel, user32, (900, 400))
        self.assertTrue(panel.root.topmost)

    def test_a_quick_click_between_two_checks_still_counts(self):
        panel = self.make()
        quick = type("Quick", (), {"GetAsyncKeyState": lambda self, key: 0x1 if key == 0x01 else 0})()
        panel.root.pointer = (900, 400)                  # real 2026-10-04 run: a fast click was missed
        with patch.object(hud.ctypes, "windll", type("W", (), {"user32": quick})()):
            panel._watch_outside_click()
        self.assertFalse(panel.root.topmost)

    def test_saved_size_and_position_are_loaded_and_clamped(self):
        panel = self.make({"zoom": 0.7, "position": [40, 60]})
        self.assertEqual((panel.zoom, panel.position), (0.7, [40, 60]))
        self.assertEqual(self.make({"zoom": 9}).zoom, hud.ZOOM_MAX)
        self.assertEqual(self.make({"zoom": 0.01}).zoom, hud.ZOOM_MIN)
        broken = self.make()
        self.assertEqual((broken.zoom, broken.position), (1.0, None))


if __name__ == "__main__":
    unittest.main()
