import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.policy.kernel import Decision, PolicyKernel
from chutku.tools import everyday
from chutku.tools.registry import Risk

APPS = [{"name": "Spotify", "app_id": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},
        {"name": "Visual Studio Code", "app_id": "Microsoft.VisualStudioCode"},
        {"name": "Visual Studio Installer", "app_id": "Microsoft.VisualStudio.Installer"},
        {"name": "Uninstall Foo", "app_id": r"C:\Foo\unins000.exe"},
        {"name": "Foo Website", "app_id": "https://foo.example"}]


class EverydayValidationTests(unittest.TestCase):
    def test_url_validation_refuses_non_http_and_credentials(self):
        for bad in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "https://user:pw@example.com",
                    "https://exa mple.com", "ftp://example.com", "https://", "http://exa\nmple.com",
                    "https://example.com/\"onload"):
            with self.assertRaises(ValueError, msg=bad):
                everyday.validate_url(bad)
        self.assertEqual(everyday.validate_url("https://www.youtube.com/watch?v=x"), "https://www.youtube.com/watch?v=x")

    def test_app_resolution_is_exact_and_refuses_uninstallers_and_links(self):
        self.assertEqual(everyday.resolve_app({"name": "spotify"}, APPS)["app_id"], APPS[0]["app_id"])
        self.assertEqual(everyday.resolve_app({"name": "Visual Studio Code"}, APPS)["name"], "Visual Studio Code")
        with self.assertRaisesRegex(ValueError, "Several"):
            everyday.resolve_app({"name": "Visual Studio"}, APPS)
        with self.assertRaisesRegex(ValueError, "No installed app"):
            everyday.resolve_app({"name": "cmd /c del"}, APPS)
        with self.assertRaisesRegex(ValueError, "Uninstallers"):
            everyday.resolve_app({"name": "Uninstall Foo"}, APPS)
        with self.assertRaisesRegex(ValueError, "web link"):
            everyday.resolve_app({"name": "Foo Website"}, APPS)
        with self.assertRaises(ValueError):
            everyday.resolve_app({"app_id": "Microsoft.VisualStudioCode && calc"}, APPS)

    def test_search_urls_are_built_deterministically(self):
        opened = []
        with patch.object(everyday, "_open_url", side_effect=lambda url, browser=None, tab="auto": opened.append(url)):
            everyday._web_search({"query": "lo-fi & chill", "site": "youtube"}, None)
        self.assertEqual(opened, ["https://www.youtube.com/results?search_query=lo-fi+%26+chill"])


class EverydayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.runtime.capability_grants.grant("apps.launch")
        self.runtime.capability_grants.grant("browser.navigate")

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_files_open_refuses_programs_and_scripts_without_launching(self):
        for name in ("setup.exe", "run.bat", "x.ps1", "link.lnk", "a.vbs", "i.msi", "z.url"):
            (self.runtime.granted_root / name).write_text("x", encoding="utf-8")
            with patch("os.startfile") as start:
                result = self.runtime.run("files.open", {"path": name})
            self.assertEqual(str(result["state"]), "FAILED", name)
            start.assert_not_called()

    def test_files_open_outside_grant_refused(self):
        with patch("os.startfile") as start:
            result = self.runtime.run("files.open", {"path": r"C:\Windows\win.ini"})
        self.assertEqual(str(result["state"]), "FAILED")
        start.assert_not_called()

    def test_capability_required(self):
        self.runtime.capability_grants.revoke("apps.launch")
        with patch.object(everyday, "start_apps", return_value=APPS), patch("subprocess.Popen") as popen:
            result = self.runtime.run("apps.launch", {"name": "Spotify"})
        self.assertEqual(str(result["state"]), "DENIED")
        popen.assert_not_called()

    def test_launch_without_window_is_not_success(self):
        with patch.object(everyday, "start_apps", return_value=APPS), patch("subprocess.Popen"), \
                patch.object(everyday, "_await_new_window", return_value=(None, None)), \
                patch.object(everyday, "Desktop"):
            result = self.runtime.run("apps.launch", {"name": "Spotify"})
        self.assertEqual(str(result["state"]), "FAILED")

    def test_tainted_network_egress_requires_confirmation(self):
        tool = self.runtime.registry.get("web.open")
        self.assertTrue(tool.network_egress)
        kernel = PolicyKernel()
        clean = kernel.authorize(tool, {}, provenance="delegated", autonomy="auto_safe", capability_allowed=True)
        tainted = kernel.authorize(tool, {}, provenance="delegated", autonomy="auto_edits", tainted=True,
                                   capability_allowed=True)
        self.assertEqual(clean.decision, Decision.ALLOW)
        self.assertEqual(tainted.decision, Decision.CONFIRM)

    def test_window_close_is_r3(self):
        self.assertEqual(self.runtime.registry.get("windows.close").base_risk, Risk.EXTERNAL_SIDE_EFFECT)


class StartAppsCacheTests(unittest.TestCase):
    def setUp(self):
        from chutku.tools import everyday
        self.everyday = everyday
        self.saved = dict(everyday._APPS_CACHE)
        everyday._APPS_CACHE.update(apps=None, at=0.0, refreshing=False)

    def tearDown(self):
        self.everyday._APPS_CACHE.update(self.saved)

    def test_one_read_then_cached_and_a_miss_reads_fresh(self):
        everyday = self.everyday
        old = [{"name": "Spotify", "app_id": "S"}]
        new = old + [{"name": "VLC media player", "app_id": "V"}]
        with patch.object(everyday, "_read_start_apps", side_effect=[old, new]) as read:
            self.assertEqual(everyday.start_apps(), old)
            self.assertEqual(everyday.start_apps(), old)
            self.assertEqual(read.call_count, 1)
            out = everyday._installed({"query": "vlc"}, None).output  # not in the copy: looks again
            self.assertEqual([a["name"] for a in out["apps"]], ["VLC media player"])
            self.assertEqual(read.call_count, 2)

    def test_not_installed_is_said_only_after_a_fresh_look(self):
        everyday = self.everyday
        apps = [{"name": "Spotify", "app_id": "S"}]
        with patch.object(everyday, "_read_start_apps", return_value=apps) as read:
            everyday.start_apps()
            out = everyday._installed({"query": "zzqx"}, None).output
            self.assertEqual(out["count"], 0)
            self.assertEqual(read.call_count, 2)

    def test_stale_copy_is_returned_at_once_and_refreshed_in_background(self):
        import threading
        everyday = self.everyday
        old, new = [{"name": "A", "app_id": "A"}], [{"name": "B", "app_id": "B"}]
        everyday._APPS_CACHE.update(apps=old, at=-10_000.0)
        done = threading.Event()

        def slow_read():
            done.set()
            return new
        with patch.object(everyday, "_read_start_apps", side_effect=slow_read):
            self.assertEqual(everyday.start_apps(), old)  # no waiting for the slow read
            self.assertTrue(done.wait(5))
            for _ in range(50):
                if everyday._APPS_CACHE["apps"] == new:
                    break
                time.sleep(0.02)
        self.assertEqual(everyday._APPS_CACHE["apps"], new)
        self.assertFalse(everyday._APPS_CACHE["refreshing"])



# Lines read from the real Windows 11 search window for "calculator" (2026-10-04), window rect (460, 82, 1460, 1020).
SEARCH_RECT = (460, 82, 1460, 1020)
SEARCH_LINES = [{"text": t, "rect": r} for t, r in (
    ("calculatorl", (572, 125, 647, 149)), ("Apps", (629, 194, 669, 210)), ("Best match", (518, 257, 605, 270)),
    ("Calculator", (562, 309, 640, 322)), ("Folders 2", (521, 389, 596, 402)), ("Web", (825, 193, 860, 206)),
    ("Open", (1001, 500, 1037, 514)), ("Calculator", (1119, 384, 1219, 401)), ("calculator - in alex", (562, 439, 703, 453)),
    ("Search the web 10+", (521, 543, 675, 556)), ("Q calculator app", (530, 644, 672, 662)),
    ("Documents 27+", (521, 851, 646, 864)), ("calculator", (562, 901, 637, 915)), ("Uninstall", (1001, 733, 1058, 745)))]


class WindowsSearchTests(unittest.TestCase):
    def test_reads_only_best_match_and_app_results_in_order(self):
        self.assertEqual(everyday.search_results(SEARCH_LINES, SEARCH_RECT), ["Calculator"])

    def test_picks_first_result_that_is_an_installed_app_even_if_not_on_top(self):
        apps = [{"name": "Visual Studio Code", "app_id": "Code"}, {"name": "Calculator", "app_id": "Calc"}]
        self.assertEqual(everyday.pick_search_result(["VS Code tips", "Visual Studio Code"], apps)["app_id"], "Code")
        self.assertEqual(everyday.pick_search_result(["Calculator"], apps)["app_id"], "Calc")
        self.assertEqual(everyday.pick_search_result(["I Calculator"], apps)["app_id"], "Calc")   # icon read as "I"

    def test_never_picks_web_folders_documents_uninstallers_or_unknown_names(self):
        apps = [{"name": "Calculator", "app_id": "Calc"}, {"name": "Uninstall Foo", "app_id": "UnFoo"}]
        self.assertIsNone(everyday.pick_search_result(["calculator - in alex", "Uninstall Foo", "Q calculator app"],
                                                      apps))
        lines = [{"text": "Search the web", "rect": (521, 300, 600, 310)},
                 {"text": "Calculator", "rect": (562, 330, 640, 340)}]
        self.assertEqual(everyday.search_results(lines, SEARCH_RECT), [])   # a web result, not an app

    def test_only_related_results_open_and_uninstall_never_searches(self):
        apps = [{"name": "Control Panel", "app_id": "CP"}, {"name": "Visual Studio Code", "app_id": "Code"},
                {"name": "Calculator", "app_id": "Calc"}]
        # Real 2026-10-04: Windows search answered "Uninstall" with Control Panel, and it was opened.
        self.assertIsNone(everyday.pick_search_result(["Control Panel"], apps, "Uninstall"))
        self.assertEqual(everyday.pick_search_result(["Visual Studio Code"], apps, "vs code")["app_id"], "Code")
        self.assertEqual(everyday.pick_search_result(["Calculator"], apps, "calc app")["app_id"], "Calc")
        self.assertTrue(everyday.related("word", "Word"))
        self.assertFalse(everyday.related("photoshop", "Photos"))
        pressed = []
        with patch("chutku.tools.desktop_controls.press_combo", side_effect=pressed.append):
            with self.assertRaises(ValueError):
                everyday.search_start_menu("Uninstall", apps)
        self.assertEqual(pressed, [])                                       # Windows search was never opened

    def test_types_nothing_when_windows_search_does_not_open(self):
        class FakeDesktop:
            def foreground(self):
                return 1

            def describe(self, _hwnd):
                return {"executable": r"C:\Windows\notepad.exe", "title": "notes.txt - Notepad"}
        typed = []
        with patch.object(everyday, "Desktop", FakeDesktop), \
                patch("chutku.tools.desktop_controls.press_combo"), \
                patch("chutku.tools.desktop_controls.type_unicode", side_effect=typed.append):
            with self.assertRaises(ValueError):
                everyday.search_start_menu("word", [])
        self.assertEqual(typed, [])                                          # the user's document stays untouched



class BrowserChoiceTests(unittest.TestCase):
    """Owner's choice 2026-10-04: websites, YouTube and searches open in Brave unless another browser is named."""

    def run_open(self, browser=None, exe=r"C:\B\brave.exe", preferred="brave"):
        launched, started = [], []

        class FakeDesktop:
            def windows(self):
                return []

            def foreground(self):
                return 0

            def describe(self, hwnd):
                return {"window_id": hwnd, "title": "t", "executable": exe}
        with patch.object(everyday, "Desktop", FakeDesktop), patch.object(everyday, "_titles", return_value={}), \
                patch.object(everyday, "preferred_browser", return_value=preferred), \
                patch.object(everyday, "browser_exe", side_effect=lambda name: exe if name in ("brave", "edge") else None), \
                patch.object(everyday, "default_browser", return_value=r"C:\E\msedge.exe"), \
                patch.object(everyday.subprocess, "Popen", side_effect=lambda args, **kw: launched.append((args, kw))), \
                patch.object(everyday.os, "startfile", side_effect=started.append), \
                patch.object(everyday, "_await_new_window", return_value=({"window_id": 1, "title": "t",
                                                                          "executable": exe}, "new_window")), \
                patch.object(everyday, "_launched", side_effect=lambda output, info, how: output):
            output = everyday._open_url("https://youtube.com", browser)
        return output, launched, started

    def test_preferred_brave_is_launched_directly_with_the_url_and_no_shell(self):
        output, launched, started = self.run_open()
        self.assertEqual(launched[0][0], [r"C:\B\brave.exe", "https://youtube.com"])
        self.assertFalse(launched[0][1].get("shell"))
        self.assertEqual(started, [])

    def test_missing_browser_falls_back_to_windows_default_and_says_so(self):
        output, launched, started = self.run_open(browser="firefox")
        self.assertEqual((launched, started), ([], ["https://youtube.com"]))
        self.assertIn("Firefox was not found", output["note"])

    def test_open_brave_reuses_the_open_window_instead_of_a_new_one(self):
        class FakeDesktop:
            def windows(self):
                return [1, 2]

            def describe(self, hwnd):
                return {1: {"window_id": 1, "process_id": 9, "title": "YouTube - Brave", "minimized": True,
                            "executable": r"C:\\B\\brave.exe"},
                        2: {"window_id": 2, "process_id": 9, "title": "Latent - Brave", "minimized": False,
                            "executable": r"C:\\B\\brave.exe"}}[hwnd]
        launched = []
        with patch.object(everyday, "Desktop", FakeDesktop), \
                patch.object(everyday, "start_apps", return_value=[{"name": "Brave", "app_id": "Brave"}]), \
                patch.object(everyday.subprocess, "Popen", side_effect=lambda *a, **k: launched.append(a)), \
                patch("chutku.tools.windows_apps.WindowsDesktop") as focus:
            result = everyday._launch({"name": "Brave"}, None)
        self.assertEqual(launched, [])                                   # no second Brave window
        self.assertEqual(result.output["window"]["window_id"], 2)        # the visible one, brought to the front
        focus.return_value.focus.assert_called_once_with(2)

    def test_browser_argument_is_validated(self):
        everyday._validate_url({"url": "https://youtube.com", "browser": "brave"})
        everyday._validate_search({"query": "lofi", "site": "youtube", "browser": "edge"})
        with self.assertRaises(ValueError):
            everyday._validate_url({"url": "https://youtube.com", "browser": "netscape"})


if __name__ == "__main__":
    unittest.main()
