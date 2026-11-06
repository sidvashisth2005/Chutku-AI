"""Z3 (owner, 2026-11-06: "other app actions too, all in a single step without thinking"): browser, YouTube, window
and Windows shortcuts are one instant step. Shortcut-only actions route without a lab run unless a lab run failed;
actions that change something still need the lab."""
import unittest
from unittest.mock import patch

from chutku.apps import phrases
from chutku.apps.atlas import load_all
from chutku.daily_intent import parse_daily
from chutku.tools import everyday

ATLASES = load_all()[0]
NOTHING_VERIFIED, NOTHING_FAILED = {}, {}


class ShortcutRoutingTests(unittest.TestCase):
    def test_plain_shortcuts_route_without_a_lab_run(self):
        for said, tool in {"new tab kholo": "app.brave.new_tab", "go back": "app.brave.back",
                           "full screen karo": "app.brave.yt_fullscreen", "scroll down": "app.brave.scroll_down",
                           "page reload karo": "app.brave.reload", "mute the video": "app.brave.yt_mute",
                           "agla tab": "app.brave.next_tab", "vlc full screen karo": "app.vlc.fullscreen"}.items():
            found = phrases.match(said, ATLASES, NOTHING_VERIFIED, NOTHING_FAILED)
            self.assertEqual(found and found[0], tool, said)

    def test_a_failed_lab_run_or_a_changing_action_needs_verification(self):
        self.assertIsNone(phrases.match("go back", ATLASES, NOTHING_VERIFIED, {"brave": {"back"}}))   # lab saw it fail
        self.assertIsNone(phrases.match("close this tab", ATLASES, NOTHING_VERIFIED, NOTHING_FAILED))  # "changes"
        self.assertEqual(phrases.match("close this tab", ATLASES, {"brave": {"close_tab"}}, NOTHING_FAILED)[0],
                         "app.brave.close_tab")
        self.assertFalse(phrases.shortcut({"risk": "safe", "steps": [{"focus": True}]}))           # no shortcut
        self.assertFalse(phrases.shortcut({"risk": "safe", "steps": [{"focus": True}, {"type": "{x}"}],
                                           "params": {"x": {"type": "text"}}}))

    def test_new_tab_is_an_action_not_a_tab_choice(self):
        from chutku.quick_intents import quick_proposal
        with patch.object(phrases, "match", lambda text: ("app.brave.new_tab", {}, {"title": "Open a new tab"})
                          if text == "new tab kholo" else None):
            proposal = quick_proposal("new tab kholo")
        self.assertEqual([s["tool"] for s in proposal["next_steps"]], ["app.brave.new_tab"])


class WindowPhraseTests(unittest.TestCase):
    def test_the_window_in_front_and_windows_shortcuts(self):
        cases = {"minimize this window": ("windows.this", {"action": "minimize"}),
                 "window chhota karo": ("windows.this", {"action": "minimize"}),
                 "window bada karo": ("windows.this", {"action": "maximize"}),
                 "snap this window left": ("windows.this", {"action": "snap_left"}),
                 "ye window right mein karo": ("windows.this", {"action": "snap_right"}),
                 "close this window": ("windows.close_this", {}),
                 "show desktop": ("keyboard.keys", {"keys": "win+d"}),
                 "switch window": ("keyboard.keys", {"keys": "alt+tab"}),
                 "task view kholo": ("keyboard.keys", {"keys": "win+tab"})}
        for said, (tool, arguments) in cases.items():
            self.assertEqual(parse_daily(said)[:2], (tool, arguments), said)
        self.assertIsNone(parse_daily("window"))                                          # nothing to do

    def test_chutkus_own_window_is_never_the_target(self):
        class Desk:
            foreground = staticmethod(lambda: 42)
            describe = staticmethod(lambda hwnd: {"window_id": 42, "process_id": 7, "executable": "pythonw.exe",
                                                  "title": "Chutku Bar"})
        with patch.object(everyday, "Desktop", Desk), patch.object(everyday, "_manage") as manage:
            result = everyday._this_window({"action": "minimize"}, None)
        self.assertEqual(result.verification, everyday.Verification.FAIL)
        manage.assert_not_called()
        for bad in ({"action": "close"}, {}, {"action": "minimize", "extra": 1}):
            with self.assertRaises(ValueError):
                everyday._validate_this(bad)

    def test_the_window_in_front_goes_through_the_checked_window_code(self):
        class Desk:
            foreground = staticmethod(lambda: 42)
            describe = staticmethod(lambda hwnd: {"window_id": 42, "process_id": 7, "executable": r"C:\x\brave.exe",
                                                  "title": "YouTube - Brave"})
        with patch.object(everyday, "Desktop", Desk), patch.object(everyday, "_manage", lambda a, c: a), \
                patch.object(everyday, "_snap", lambda a, c: a):
            self.assertEqual(everyday._this_window({"action": "maximize"}, None),
                             {"window_id": 42, "process_id": 7, "executable": r"C:\x\brave.exe", "action": "maximize"})
            self.assertEqual(everyday._this_window({"action": "snap_left"}, None)["position"], "left")


if __name__ == "__main__":
    unittest.main()
