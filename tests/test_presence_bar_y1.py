"""Y1 (2026-11-06): Chutku starts as a small bar at the top centre; expand shows the full window and back."""
import sys
import time
import types
import unittest
from unittest.mock import patch

from chutku import presence
from chutku.dashboard import DashboardServer, PROJECT_ROOT
from tests import test_dashboard as _harness

LINK = "http://127.0.0.1:8765/#token=abc"


class Event(list):   # pywebview's window.events.closed: handlers are added with +=
    def __iadd__(self, handler):
        self.append(handler)
        return self


class FakeWindow:
    def __init__(self, log, name):
        self.log, self.name = log, name
        self.events = types.SimpleNamespace(closed=Event())

    def show(self):
        self.log.append(("show", self.name))

    def hide(self):
        self.log.append(("hide", self.name))


def settle(log, count):
    deadline = time.monotonic() + 2
    while len(log) < count and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    return log


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.bridge = presence.Bridge(FakeWindow(self.log, "bar"), FakeWindow(self.log, "full"))

    def test_expand_shows_the_full_window_and_hides_the_bar_and_back(self):
        self.assertEqual(self.bridge.expand(), {"view": "full"})
        self.assertEqual(settle(self.log, 2), [("show", "full"), ("hide", "bar")])
        self.log.clear()
        self.assertEqual(self.bridge.compact(), {"view": "bar"})
        self.assertEqual(settle(self.log, 2), [("show", "bar"), ("hide", "full")])

    def test_asking_for_the_view_already_shown_does_nothing(self):
        self.assertEqual(self.bridge.compact(), {"view": "bar"})
        self.assertEqual(settle(self.log, 1), [])

    def test_two_quick_clicks_never_leave_both_windows_shown(self):
        self.bridge.expand()
        self.bridge.compact()
        log = settle(self.log, 4)
        self.assertEqual(log[-2:], [("show", "bar"), ("hide", "full")])

    def test_without_windows_it_is_harmless(self):
        self.assertEqual(presence.Bridge().expand(), {"view": "bar"})


class WindowSetupTests(unittest.TestCase):
    def test_bar_url_keeps_the_token_and_other_hosts_are_refused(self):
        self.assertEqual(presence.presence_url(LINK, "bar"), "http://127.0.0.1:8765/presence?view=bar#token=abc")
        self.assertEqual(presence.presence_url(LINK), "http://127.0.0.1:8765/presence#token=abc")
        with self.assertRaises(ValueError):
            presence.presence_url("https://evil.example/#token=abc", "bar")

    def test_the_bar_sits_at_the_top_centre_of_the_work_area(self):
        with patch.object(presence, "work_area", return_value=(0, 0, 1920, 1040)):
            self.assertEqual(presence.top_centre(presence.BAR), ((1920 - presence.BAR[0]) // 2, 10))

    def test_start_up_shows_the_bar_on_top_and_keeps_the_full_window_hidden(self):
        created, started = [], []

        def create_window(title, url, **options):
            window = FakeWindow([], title)
            created.append((title, url, options, window))
            return window
        fake = types.SimpleNamespace(create_window=create_window, start=lambda *a, **k: started.append(a))
        with patch.dict(sys.modules, {"webview": fake}):
            presence.main([LINK])
        (full_title, full_url, full, full_window), (bar_title, bar_url, bar, bar_window) = created
        self.assertEqual((full_title, full_url), (presence.TITLE, "http://127.0.0.1:8765/presence#token=abc"))
        self.assertTrue(full["hidden"])
        self.assertFalse(full["frameless"])
        self.assertEqual((bar_title, bar_url), (presence.BAR_TITLE, "http://127.0.0.1:8765/presence?view=bar#token=abc"))
        self.assertEqual((bar["width"], bar["height"]), presence.BAR)
        self.assertTrue(bar["frameless"] and bar["on_top"] and not bar.get("hidden"))
        self.assertIs(full["js_api"], bar["js_api"])
        self.assertIs(full["js_api"].full, full_window)
        for window in (full_window, bar_window):   # closing either still quits Chutku (owner, 2026-11-01)
            self.assertEqual(window.events.closed, [presence.quit_chutku])
        self.assertEqual(len(started), 1)


class BarMoodTests(unittest.TestCase):
    def test_conversation_cues_pick_hearts_brows_and_spirals(self):
        mood = DashboardServer.presence_mood
        self.assertEqual(mood("speaking", [], "thank you Chutku"), "love")
        self.assertEqual(mood("done", [], "धन्यवाद"), "love")              # Hindi script is romanised first
        self.assertEqual(mood("thinking", [], "kya kar rahi ho, galat hai"), "annoyed")
        self.assertEqual(mood("clarify", [], "open it"), "confused")
        self.assertEqual(mood("thinking", [], "open notepad"), "thinking")

    def test_cues_never_hide_a_pause_an_error_or_an_approval(self):
        mood = DashboardServer.presence_mood
        self.assertEqual(mood("paused", [], "thanks"), "sleepy")
        self.assertEqual(mood("error", [], "thanks"), "sorry")
        self.assertEqual(mood("confirm", [], "stupid"), "listening")
        self.assertEqual(mood("done", [], "galat"), "calm")                 # annoyance is over once it is done


class BarPageTests(unittest.TestCase):
    setUp, tearDown, request = _harness.DashboardTests.setUp, _harness.DashboardTests.tearDown, \
        _harness.DashboardTests.request

    def test_bar_view_is_the_same_page_with_the_strict_policy(self):
        status, body, headers = self.request("/presence?view=bar")
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        html = body.decode("utf-8")
        for needle in ('id="strip"', 'id="eyes"', 'id="strip-text"', 'id="expand"', 'id="to-bar"'):
            self.assertIn(needle, html)
        self.assertNotRegex(html, r"https?://|<img")
        script = (PROJECT_ROOT / "chutku" / "web" / "presence.js").read_text(encoding="utf-8")
        for needle in ('get("view") === "bar"', "function renderBar(", 'windowApi("expand")', 'windowApi("compact")',
                       "location.pathname+location.search"):
            self.assertIn(needle, script)


if __name__ == "__main__":
    unittest.main()
