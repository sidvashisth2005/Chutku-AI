"""Y1 (2026-11-06): Chutku starts as a small bar at the top centre; expand shows the full window and back."""
import sys
from pathlib import Path
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
        quiet = patch.object(presence, "_log")   # never write to the owner's data/logs from a test
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_expand_shows_the_full_window_and_hides_the_bar_and_back(self):
        self.assertEqual(self.bridge.expand(), {"view": "full"})
        self.assertEqual(settle(self.log, 2), [("show", "full"), ("hide", "bar")])
        self.log.clear()
        self.assertEqual(self.bridge.compact(), {"view": "bar"})
        self.assertEqual(settle(self.log, 2), [("show", "bar"), ("hide", "full")])

    def test_asking_for_the_view_already_shown_does_nothing(self):
        self.bridge.compact()
        settle(self.log, 2)
        self.log.clear()
        self.assertEqual(self.bridge.compact(), {"view": "bar"})
        self.assertEqual(settle(self.log, 1), [])

    def test_nothing_shows_until_wanted_and_ctrl_alt_c_toggles(self):
        """Owner 2026-11-06: "it must not always be there; it appears when I press its hotkey, vanishes if pressed again"."""
        self.assertEqual(self.bridge.view, "none")
        self.assertEqual(self.bridge.toggle(), {"view": "bar"})
        self.assertEqual(settle(self.log, 2), [("show", "bar"), ("hide", "full")])
        self.log.clear()
        self.assertEqual(self.bridge.toggle(), {"view": "none"})
        self.assertEqual(sorted(settle(self.log, 2)), [("hide", "bar"), ("hide", "full")])
        self.bridge.expand()
        self.assertEqual(self.bridge.toggle(), {"view": "none"})   # the full window goes away too

    def test_the_bar_peeks_while_she_works_and_leaves_unless_pinned(self):
        self.assertEqual(self.bridge.peek(), {"view": "bar"})
        self.assertEqual(self.bridge.unpeek(), {"view": "none"})
        self.bridge.toggle()                                       # pinned with Ctrl+Alt+C
        self.assertEqual(self.bridge.unpeek(), {"view": "bar"})    # stays
        self.bridge.expand()
        self.assertEqual(self.bridge.unpeek(), {"view": "full"})   # the full window is never hidden by itself

    def test_two_quick_clicks_never_leave_both_windows_shown(self):
        self.bridge.expand()
        self.bridge.compact()
        log = settle(self.log, 4)
        self.assertEqual(log[-2:], [("show", "bar"), ("hide", "full")])

    def test_without_windows_it_is_harmless(self):
        self.assertEqual(presence.Bridge().expand(), {"view": "none"})


class WindowSetupTests(unittest.TestCase):
    def test_bar_url_keeps_the_token_and_other_hosts_are_refused(self):
        self.assertEqual(presence.presence_url(LINK, "bar"), "http://127.0.0.1:8765/presence?view=bar#token=abc")
        self.assertEqual(presence.presence_url(LINK), "http://127.0.0.1:8765/presence#token=abc")
        with self.assertRaises(ValueError):
            presence.presence_url("https://evil.example/#token=abc", "bar")

    def test_the_bar_returns_where_it_was_dragged_if_that_is_still_on_screen(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp, patch.object(presence, "PROJECT_ROOT", Path(temp)),                 patch.object(presence, "work_area", return_value=(0, 0, 1920, 1040)):
            (Path(temp) / "data").mkdir()
            self.assertEqual(presence.bar_place(), presence.top_centre(presence.BAR))   # nothing saved yet
            presence.remember_place(100, 600)
            self.assertEqual(presence.bar_place(), (100, 600))
            presence.remember_place(5000, 600)                                          # off screen: back to top centre
            self.assertEqual(presence.bar_place(), presence.top_centre(presence.BAR))

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
        self.assertTrue(bar["frameless"] and bar["on_top"] and bar["easy_drag"] and bar["hidden"])   # hidden until wanted
        self.assertIs(full["js_api"], bar["js_api"])
        bridge = full["js_api"]   # it switches windows through Windows itself, never pywebview (2026-11-06 deadlock)
        self.assertEqual((type(bridge.full), bridge.full.title, bridge.bar.title),
                         (presence.NativeWindow, presence.TITLE, presence.BAR_TITLE))
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


class StateWatcherTests(unittest.TestCase):
    """2026-11-06: the bar appears while she works, leaves when she is quiet, and an approval opens the full window."""

    def run_states(self, states, *, pinned=False):
        log = []
        bridge = presence.Bridge(FakeWindow(log, "bar"), FakeWindow(log, "full"))
        if pinned:
            bridge.toggle()
        feed = iter(states)
        watcher = presence.StateWatcher(bridge, LINK, fetch=lambda: next(feed))
        views = []
        with patch.object(presence, "_log"):
            for now, _state in enumerate(states):
                watcher.step(float(now))
                views.append(bridge.view)
        return views

    def test_peeks_while_busy_and_leaves_after_the_quiet_time(self):
        idle, busy = {"phase": "idle"}, {"phase": "thinking"}
        states = [idle, busy, busy, idle] + [idle] * 8
        views = self.run_states(states)
        self.assertEqual(views[:4], ["none", "bar", "bar", "bar"])
        self.assertEqual(views[-1], "none")                      # gone QUIET_SECONDS after she was done
        self.assertEqual(views[3 + int(presence.QUIET_SECONDS) - 1], "bar")   # not before

    def test_a_pinned_bar_stays_and_an_approval_opens_the_full_window_once(self):
        self.assertEqual(self.run_states([{"phase": "idle"}] * 10, pinned=True)[-1], "bar")
        pending = {"phase": "confirm", "session_id": "s1", "pending": {"tool": "filesystem.recycle"}}
        views = self.run_states([pending, pending, {"phase": "done"}])
        self.assertEqual(views, ["full", "full", "full"])   # the full window is never hidden by itself
