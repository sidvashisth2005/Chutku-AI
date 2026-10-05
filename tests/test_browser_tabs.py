"""Reuse the tab Chutku opened instead of a new tab each time (owner, 2026-10-05)."""
import types
import unittest
from unittest.mock import patch

from chutku.quick_intents import quick_proposal
from chutku.tools import everyday

BRAVE = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


class FakeDesktop:
    def __init__(self, title="lofi songs - YouTube - Brave", foreground=11):
        self.title, self.front = title, foreground

    def describe(self, hwnd):
        return {"window_id": hwnd, "process_id": 7, "title": self.title, "executable": BRAVE, "minimized": False}

    def windows(self):
        return [11]

    def foreground(self):
        return self.front


class TabTests(unittest.TestCase):
    def setUp(self):
        everyday.LAST_TAB.update(window_id=None, title=None, executable=None, at=0.0)
        self.addCleanup(lambda: everyday.LAST_TAB.update(window_id=None, title=None, executable=None, at=0.0))

    def open(self, desktop, tab="auto", navigated=True):
        launched = []
        def navigate(_desktop, info, _url):
            if not navigated:
                return None
            desktop.title = "Latent S2 - YouTube - Brave"   # the real tab renames itself after loading
            return dict(info, title=desktop.title)
        with patch.object(everyday, "preferred_browser", return_value="brave"), \
                patch.object(everyday, "browser_exe", return_value=BRAVE), \
                patch.object(everyday, "Desktop", return_value=desktop), \
                patch.object(everyday, "_titles", return_value={}), \
                patch.object(everyday, "_navigate_in_place", side_effect=navigate) as nav, \
                patch.object(everyday.subprocess, "Popen", side_effect=lambda *a, **k: launched.append(a[0])), \
                patch.object(everyday, "_await_new_window",
                             return_value=(desktop.describe(11), "window_title_changed")):
            result = everyday._open_url("https://www.youtube.com/results?search_query=latent", tab=tab)
        return result, nav.called, launched

    def remember_chutku_tab(self, title="lofi songs - YouTube - Brave"):
        everyday.LAST_TAB.update(window_id=11, title=title, executable=BRAVE, at=everyday.time.monotonic())

    def test_chutkus_own_tab_still_showing_is_reused(self):
        self.remember_chutku_tab()
        result, navigated, launched = self.open(FakeDesktop())
        self.assertTrue(navigated)
        self.assertEqual(launched, [])                       # no new tab
        self.assertEqual(result.output["tab"], "same")
        for _ in range(50):                                  # the final title is filled in the background
            if everyday.LAST_TAB["title"] == "Latent S2 - YouTube - Brave":
                break
            everyday.time.sleep(0.02)
        self.assertEqual(everyday.LAST_TAB["title"], "Latent S2 - YouTube - Brave")   # follows the tab

    def test_owner_switched_to_their_own_tab_so_a_new_tab_is_opened(self):
        self.remember_chutku_tab()
        result, navigated, launched = self.open(FakeDesktop(title="Gmail - Inbox - Brave"))
        self.assertFalse(navigated)                          # the owner's tab is never overwritten
        self.assertEqual(len(launched), 1)
        self.assertEqual(result.output["tab"], "new")

    def test_new_tab_when_asked_even_if_chutkus_tab_is_showing(self):
        self.remember_chutku_tab()
        _result, navigated, launched = self.open(FakeDesktop(), tab="new")
        self.assertFalse(navigated)
        self.assertEqual(len(launched), 1)

    def test_same_tab_when_asked_uses_the_current_tab(self):
        with patch.object(everyday, "existing_browser_window", return_value=FakeDesktop("Gmail - Brave").describe(11)):
            result, navigated, launched = self.open(FakeDesktop(title="Gmail - Brave"), tab="same")
        self.assertTrue(navigated)
        self.assertEqual(launched, [])

    def test_failed_in_place_navigation_falls_back_to_a_new_tab(self):
        self.remember_chutku_tab()
        _result, navigated, launched = self.open(FakeDesktop(), navigated=False)
        self.assertTrue(navigated)
        self.assertEqual(len(launched), 1)

    def test_nothing_is_typed_unless_the_browser_is_in_front(self):
        typed = []
        with patch("chutku.tools.windows_apps.WindowsDesktop"), \
                patch("chutku.tools.desktop_controls.press_combo", side_effect=typed.append), \
                patch("chutku.tools.desktop_controls.type_unicode", side_effect=typed.append), \
                patch.object(everyday.time, "sleep"):
            got = everyday._navigate_in_place(FakeDesktop(foreground=99), FakeDesktop().describe(11), "https://x.org")
        self.assertIsNone(got)
        self.assertEqual(typed, [])


class FollowRenameTests(unittest.TestCase):
    def setUp(self):
        everyday.LAST_TAB.update(window_id=None, title=None, executable=None, at=0.0)

    def run_titles(self, titles, url="https://www.youtube.com/results?search_query=lofi+songs"):
        desktop = FakeDesktop(title=titles[0])
        sequence = list(titles[1:])

        def describe(hwnd):
            if sequence:
                desktop.title = sequence.pop(0)
            return {"window_id": hwnd, "process_id": 7, "title": desktop.title, "executable": BRAVE}
        desktop.describe = describe
        with patch.object(everyday, "FOLLOW_SECONDS", 3), patch.object(everyday.time, "sleep", lambda s: None):
            everyday._remember_tab(desktop, {"window_id": 11, "title": titles[0], "executable": BRAVE}, url)
            for thread in __import__("threading").enumerate():
                if thread.name == "chutku-tab-title":
                    thread.join(5)
        return everyday.LAST_TAB["title"]

    def test_loading_renames_are_followed(self):
        self.assertEqual(self.run_titles(["youtube.com/results - Brave", "YouTube - Brave",
                                          "lofi songs - YouTube - Brave"]), "lofi songs - YouTube - Brave")

    def test_switch_to_an_unrelated_tab_is_not_followed(self):
        self.assertEqual(self.run_titles(["lofi songs - YouTube - Brave", "Gmail - Inbox - Brave",
                                          "Gmail - Inbox (1) - Brave"]), "lofi songs - YouTube - Brave")

    def test_page_tokens(self):
        self.assertEqual(everyday.page_tokens("https://www.youtube.com/results?search_query=lofi+songs"),
                         {"youtube", "lofi", "songs"})


class TabPhraseTests(unittest.TestCase):
    def steps(self, text):
        return [(s["tool"], s["arguments"]) for s in quick_proposal(text)["next_steps"]]

    def test_phrases(self):
        self.assertEqual(self.steps("search Latent season 2 on youtube in brave in a new tab"),
                         [("web.search", {"query": "Latent season 2", "site": "youtube", "browser": "brave",
                                          "tab": "new"})])
        self.assertEqual(self.steps("play arijit singh on youtube in brave isi tab mein")[0][1]["tab"], "same")
        self.assertNotIn("tab", self.steps("search lofi songs on youtube in brave")[0][1])   # automatic


if __name__ == "__main__":
    unittest.main()
