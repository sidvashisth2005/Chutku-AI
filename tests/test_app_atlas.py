"""App atlases, runner and tools (App Mastery A1). A fake Driver stands in for Windows, so no test touches the screen."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku.apps import atlas as atlas_module
from chutku.apps import runner, tools as app_tools
from chutku.tools.registry import Risk, ToolRegistry

ATLAS = {
    "app": "demo", "name": "Demo", "window": {"exe": "Demo.exe"}, "launch": {"start_menu": "Demo"},
    "uri_schemes": ["demo"], "cli": {"demo": "demo.exe"},
    "actions": [
        {"id": "open", "title": "Open", "risk": "safe", "steps": [{"focus": True}], "check": {"window_open": True}},
        {"id": "search", "title": "Search", "risk": "safe", "params": {"query": {"type": "text"}},
         "phrases": ["search {query} on demo"], "steps": [{"uri": "demo:search:{query}"}]},
        {"id": "like", "title": "Like", "risk": "changes", "steps": [{"focus": True}, {"keys": "alt+shift+b"}],
         "check": {"ocr_contains": "Liked"}},
        {"id": "type_note", "title": "Type", "risk": "safe", "params": {"text": {"type": "text"}},
         "steps": [{"focus": True}, {"type": "{text}"}]},
        {"id": "play_list", "title": "Play list", "risk": "safe", "params": {"name": {"type": "text"}},
         "steps": [{"focus": True}, {"click_text": "{name}", "kind": "playlist"}, {"play_page": True}],
         "check": {"media_playing": True, "title_in_page": True}},
        {"id": "wipe", "title": "Delete everything", "risk": "destructive", "steps": [{"keys": "ctrl+shift+d"}],
         "check": {"window_open": True}},
    ]}


class FakeDriver:
    def __init__(self, window=7, foreground=7, lines=(), playing=True, page=None):
        self.window, self.fg, self.lines, self.calls = window, foreground, list(lines), []
        self.playing, self.page = playing, page or {"playing": True}

    def find_window(self, window):
        return self.window

    def focus(self, hwnd):
        self.calls.append(("focus", hwnd))

    def foreground(self):
        return self.fg

    def title(self, hwnd):
        return "Demo window"

    def launch(self, name):
        self.calls.append(("launch", name))
        self.window = 7

    def open_uri(self, uri):
        self.calls.append(("uri", uri))

    def run_program(self, program, args):
        self.calls.append(("cli", program, args))

    def keys(self, text):
        self.calls.append(("keys", text))

    def type(self, text):
        self.calls.append(("type", text))

    def window_rect(self, hwnd):
        return (0, 0, 100, 100)

    def ocr(self, rect):
        return [{"text": t, "rect": (0, 0, 1, 1)} for t in self.lines]

    def click_text(self, rect, name, kind, double=False):
        self.calls.append(("click_text", name, kind) + (("double",) if double else ()))
        return name

    def play_page(self, rect):
        self.calls.append(("play_page",))
        return self.page

    def media(self, action, match=None):
        if action == "status":
            return {"status": "Playing" if self.playing else "Paused", "title": "x"}
        self.calls.append(("media", action))
        return {"accepted": True}

    def process_running(self, exe):
        return True


def action(atlas, action_id):
    return next(a for a in atlas["actions"] if a["id"] == action_id)


class ValidatorTests(unittest.TestCase):
    def broken(self, change):
        atlas = copy.deepcopy(ATLAS)
        change(atlas)
        with self.assertRaises(atlas_module.AtlasError):
            atlas_module.validate(atlas)

    def test_the_demo_and_every_shipped_atlas_are_valid(self):
        atlas_module.validate(copy.deepcopy(ATLAS))
        atlases, errors = atlas_module.load_all()
        self.assertEqual(errors, {})
        self.assertIn("spotify", atlases)

    def test_unsafe_or_malformed_atlases_are_refused(self):
        self.broken(lambda a: a["actions"][1]["steps"].__setitem__(0, {"uri": "file:C:/x"}))   # not its scheme
        self.broken(lambda a: a["actions"].append({"id": "run", "title": "x", "risk": "safe",
                                                   "steps": [{"cli": ["cmd", "/c", "x"]}]}))   # not its program
        self.broken(lambda a: a["actions"][0]["steps"].append({"shell": "x"}))                  # unknown verb
        self.broken(lambda a: a["actions"][1].__setitem__("params", {}))                         # undeclared {query}
        self.broken(lambda a: a["actions"][2].__setitem__("check", {}))                          # changes needs a check
        self.broken(lambda a: a["actions"][0].__setitem__("risk", "harmless"))
        self.broken(lambda a: a["actions"][2]["steps"].__setitem__(1, {"keys": "ctrl+notakey"}))
        self.broken(lambda a: a["actions"].append(copy.deepcopy(a["actions"][0])))               # duplicate id

    def test_a_refused_atlas_is_not_loaded_and_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "demo.json").write_text(json.dumps(ATLAS), encoding="utf-8")
            bad = copy.deepcopy(ATLAS)
            bad["app"], bad["actions"][0]["risk"] = "bad", "??"
            Path(temp, "bad.json").write_text(json.dumps(bad), encoding="utf-8")
            Path(temp, "broken.json").write_text("{not json", encoding="utf-8")
            atlases, errors = atlas_module.load_all(Path(temp))
        self.assertEqual(set(atlases), {"demo"})
        self.assertEqual(set(errors), {"bad.json", "broken.json"})


class SongDriver(FakeDriver):
    """Media status changes once something is double-clicked: 'title' plays."""
    def __init__(self, title, lines, playing_before=False):
        super().__init__(lines=lines, playing=playing_before)
        self.song = "Old Song"
        self.next_title = title

    def click_text(self, rect, name, kind, double=False):
        self.playing, self.song = True, self.next_title
        return super().click_text(rect, name, kind, double)

    def media(self, action, match=None):
        if action == "status":
            return {"status": "Playing" if self.playing else "Paused", "title": self.song}
        if action == "pause":
            self.playing = False
        self.calls.append(("media", action))
        return {"accepted": True}


PLAY_LIST = {"id": "play_list2", "title": "Play list", "risk": "safe", "params": {"name": {"type": "text"}},
             "steps": [{"focus": True}, {"click_text": "{name}", "kind": "playlist", "double": True}],
             "check": {"playing_on_page": True}}


class RunnerTests(unittest.TestCase):
    def test_double_click_play_passes_only_when_the_song_is_on_the_page(self):
        page = ["After Party", "Kar Gayi Chull", 'Lehnga (From "Jatt']
        driver = SongDriver('Lehnga (From "Jatt & Juliet 3")', page)
        result = runner.run(ATLAS, PLAY_LIST, {"name": "After Party"}, driver)
        self.assertTrue(result["ok"], result)
        self.assertIn(("click_text", "After Party", "playlist", "double"), driver.calls)
        # Negative: a song that is not on the opened page started -> fail and pause it again.
        driver = SongDriver("Some Other Song", page)
        result = runner.run(ATLAS, PLAY_LIST, {"name": "After Party"}, driver)
        self.assertFalse(result["ok"])
        self.assertIn(("media", "pause"), driver.calls)
        self.assertEqual(result["paused_wrong"], "Some Other Song")

    def test_owner_music_is_not_paused_when_nothing_new_started(self):
        driver = SongDriver("Old Song", ["After Party"], playing_before=True)
        result = runner.run(ATLAS, PLAY_LIST, {"name": "After Party"}, driver)
        self.assertFalse(result["ok"])
        self.assertNotIn(("media", "pause"), driver.calls)

    def test_on_page_accepts_cut_titles_but_not_short_fragments(self):
        lines = [{"text": 'Lehnga (From "Jatt'}, {"text": "Hey"}]
        self.assertTrue(runner.on_page('Lehnga (From "Jatt & Juliet 3")', lines))
        self.assertFalse(runner.on_page("Hey Jude", lines))
        self.assertFalse(runner.on_page("", lines))

    def test_heading_needs_big_text_not_a_list_row(self):
        row = lambda text, height, y: {"text": text, "rect": (0, y, 100, y + height)}
        page = [row("After Party", 31, 190), row("Kar Gayi Chull", 14, 480), row("Song two", 14, 520),
                row("196 songs", 14, 270)]
        self.assertTrue(runner.is_heading("after party", page))
        self.assertFalse(runner.is_heading("Kar Gayi Chull", page))        # a track row, not the page title
        self.assertFalse(runner.is_heading("Afterparty", page))             # look-alike name
        self.assertFalse(runner.is_heading("After Party", [row("After Party", 14, 300), row("x", 14, 340)]))

    def test_area_and_page_area_leave_out_the_player_bar(self):
        self.assertEqual(runner._area((900, 0, 1900, 1000), [0, 0.08, 0.42, 0.88]), (900, 80, 1320, 880))
        self.assertEqual(runner._area((0, 0, 100, 100), None), (0, 0, 100, 100))
        seen = []

        class AreaDriver(SongDriver):
            def ocr(self, rect):
                seen.append(rect)
                return super().ocr(rect)
        driver = AreaDriver("Song", ["After Party"])
        runner.run(ATLAS, PLAY_LIST, {"name": "After Party"}, driver)
        self.assertEqual(seen[-1], (0, 0, 100, 86))   # the bottom bar always shows the song: not proof

    def test_singles_and_eps_count_as_albums(self):
        from chutku.tools.visible import kind_of
        lines = [{"text": "Gal Sun", "rect": (1007, 287, 1074, 301)},
                 {"text": "Single • Sabaat Batin", "rect": (1007, 315, 1150, 330)}]
        self.assertEqual(kind_of(lines[0], lines), "album")

    def test_bad_area_is_refused(self):
        bad = copy.deepcopy(ATLAS)
        bad["actions"][4]["steps"][1]["area"] = [0.5, 0, 0.2, 1]
        with self.assertRaises(atlas_module.AtlasError):
            atlas_module.validate(bad)

    def test_title_guards(self):
        cleanup = {"id": "close_history", "title": "x", "risk": "safe",
                   "steps": [{"focus": True}, {"keys": "ctrl+w", "if_title": "History - Brave"}],
                   "check": {"title_lacks": "History - Brave"}}
        driver = FakeDriver()                      # its window title is "Demo window"
        result = runner.run(ATLAS, cleanup, {}, driver)
        self.assertTrue(result["ok"])
        self.assertNotIn(("keys", "ctrl+w"), driver.calls)   # never closes a tab it did not open
        youtube = {"id": "yt", "title": "x", "risk": "safe",
                   "steps": [{"focus": True}, {"keys": "l", "require_title": "YouTube"}]}
        result = runner.run(ATLAS, youtube, {}, FakeDriver())
        self.assertFalse(result["ok"])
        self.assertIn("no keys were sent", result["error"])

        class TitledDriver(FakeDriver):
            def title(self, hwnd):
                return "Lofi - YouTube - Brave"
        driver = TitledDriver()
        self.assertTrue(runner.run(ATLAS, youtube, {}, driver)["ok"])
        self.assertIn(("keys", "l"), driver.calls)

    def test_unless_step_skips_a_toggle_that_is_already_showing(self):
        toggle = {"id": "queue", "title": "Queue", "risk": "safe",
                  "steps": [{"focus": True}, {"keys": "alt+shift+q", "unless": "Queue"}], "check": {"ocr_contains": "Queue"}}
        driver = FakeDriver(lines=["Queue", "Now playing"])
        result = runner.run(ATLAS, toggle, {}, driver)
        self.assertTrue(result["ok"])
        self.assertNotIn(("keys", "alt+shift+q"), driver.calls)
        driver = FakeDriver(lines=["Home"])
        runner.run(ATLAS, toggle, {}, driver)
        self.assertIn(("keys", "alt+shift+q"), driver.calls)

    def test_uri_values_are_encoded(self):
        driver = FakeDriver()
        result = runner.run(ATLAS, action(ATLAS, "search"), {"query": "after party & more"}, driver)
        self.assertTrue(result["ok"])
        self.assertEqual(driver.calls, [("uri", "demo:search:after%20party%20%26%20more")])

    def test_keys_are_never_sent_when_another_window_is_in_front(self):
        driver = FakeDriver(window=7, foreground=99)
        result = runner.run(ATLAS, action(ATLAS, "like"), {}, driver)
        self.assertFalse(result["ok"])
        self.assertIn("no keys were sent", result["error"])
        self.assertNotIn(("keys", "alt+shift+b"), driver.calls)

    def test_the_check_decides_success(self):
        result = runner.run(ATLAS, action(ATLAS, "like"), {}, FakeDriver(lines=["Song"]))
        self.assertFalse(result["ok"])
        self.assertIn("check failed: ocr_contains", result["error"])
        self.assertTrue(runner.run(ATLAS, action(ATLAS, "like"), {}, FakeDriver(lines=["Liked"]))["ok"])

    def test_the_app_is_opened_when_closed(self):
        driver = FakeDriver(window=None)
        self.assertTrue(runner.run(ATLAS, action(ATLAS, "open"), {}, driver)["ok"])
        self.assertIn(("launch", "Demo"), driver.calls)

    def test_play_steps_and_checks(self):
        driver = FakeDriver()
        result = runner.run(ATLAS, action(ATLAS, "play_list"), {"name": "After Party"}, driver)
        self.assertTrue(result["ok"], result)
        self.assertIn(("click_text", "After Party", "playlist"), driver.calls)
        failed = runner.run(ATLAS, action(ATLAS, "play_list"), {"name": "After Party"},
                            FakeDriver(page={"playing": False, "error": "wrong song, paused it"}))
        self.assertFalse(failed["ok"])
        self.assertIn("paused it", failed["error"])

    def test_typed_text_goes_in_unchanged(self):
        driver = FakeDriver()
        runner.run(ATLAS, action(ATLAS, "type_note"), {"text": "नमस्ते & {x}"}, driver)
        self.assertIn(("type", "नमस्ते & {x}"), driver.calls)


class ToolTests(unittest.TestCase):
    def test_actions_become_tools_with_risk_from_their_class(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "demo.json").write_text(json.dumps(ATLAS), encoding="utf-8")
            registry = ToolRegistry()
            summary = app_tools.register_app_tools(registry, Path(temp))
        self.assertEqual(summary, {"apps": 1, "actions": 6, "refused": {}})
        self.assertEqual(registry.get("app.demo.open").base_risk, Risk.REVERSIBLE)
        self.assertEqual(registry.get("app.demo.like").base_risk, Risk.DATA_MODIFICATION)
        wipe = registry.get("app.demo.wipe")
        self.assertEqual((wipe.base_risk, wipe.deletes), (Risk.DESTRUCTIVE_OR_PRIVILEGED, True))
        with self.assertRaises(ValueError):
            registry.get("app.demo.search").validate_arguments({})
        with patch.object(app_tools, "DRIVER", FakeDriver()):
            result = registry.get("app.demo.search").execute({"query": "x"}, None)
        self.assertEqual(result.verification, "PASS")

    def test_builtin_registry_has_the_spotify_actions(self):
        from chutku.tools.builtin import register_builtin_tools
        registry = ToolRegistry()
        register_builtin_tools(registry)
        names = {t.name for t in registry.list()}
        self.assertIn("app.spotify.play_playlist", names)
        self.assertIn("app.spotify.next", names)


class SearchDriver(SongDriver):
    """Spotify's search page: its green play button starts the top result."""
    def play_page(self, rect):
        self.playing, self.song = True, "Lofi Beats"
        return super().play_page(rect)


class FallbackTests(unittest.TestCase):
    """20x plan P1, owner's convos: "play Loki/lofi/Afterparty Hits playlist" failed when that exact name was not
    in Your Library (11 failures). Nothing was clicked, so Spotify's own search runs instead."""

    def spotify(self):
        atlases, _errors = atlas_module.load_all()
        atlas = copy.deepcopy(atlases["spotify"])
        for step in action(atlas, "play_playlist")["steps"]:
            if "wait_text" in step:
                step["timeout"] = 0.01
        return atlas

    def test_a_name_missing_from_the_library_is_searched_and_played(self):
        atlas, driver = self.spotify(), SearchDriver("x", lines=["Your Library", "After Party"])
        with patch.object(runner.time, "sleep"):
            out = runner.run(atlas, action(atlas, "play_playlist"), {"name": "Loki"}, driver)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["action"], out["instead_of"]), ("play_public_playlist", "play_playlist"))
        self.assertIn(("uri", "spotify:search:Loki playlist"), driver.calls)
        self.assertFalse(any(c[0] == "click_text" for c in driver.calls))      # the library was never clicked

    def test_checks_read_the_apps_own_session_not_a_movie_in_the_browser(self):
        """Live 2026-11-10: a Brave movie was Windows' current session, so Spotify's check read the movie."""
        class TwoPlayers(SearchDriver):
            def media(self, action, match=None):
                if match != ["spotify"]:
                    return {"status": "Playing", "title": "Movie in Brave", "app": "Brave"}
                return super().media(action, match)
        atlas, driver = self.spotify(), TwoPlayers("x", lines=["Your Library"])
        with patch.object(runner.time, "sleep"):
            out = runner.run(atlas, action(atlas, "play_public_playlist"), {"name": "lofi"}, driver)
        self.assertTrue(out["ok"], out)          # Spotify itself went from paused to playing
        driver = TwoPlayers("x", lines=["Your Library"])
        driver.play_page = lambda rect: {"playing": True}  # the green button did nothing in Spotify
        with patch.object(runner.time, "sleep"):
            out = runner.run(atlas, action(atlas, "play_public_playlist"), {"name": "lofi"}, driver)
        self.assertFalse(out["ok"], out)         # the movie no longer counts as Spotify playing

    def test_no_fallback_once_something_was_clicked(self):
        atlas, driver = self.spotify(), FakeDriver(lines=["Loki"], playing=False)
        with patch.object(runner.time, "sleep"):
            out = runner.run(atlas, action(atlas, "play_playlist"), {"name": "Loki"}, driver)
        self.assertFalse(out["ok"])
        self.assertNotIn("instead_of", out)
        self.assertNotIn(("uri", "spotify:search:Loki playlist"), driver.calls)

    def test_fallback_must_be_a_safe_action_of_the_same_atlas(self):
        for target in ("no_such_action", "play_playlist"):
            atlas = self.spotify()
            action(atlas, "play_playlist")["fallback"] = target
            with self.assertRaises(atlas_module.AtlasError, msg=target):
                atlas_module.validate(atlas)

    def test_a_searched_name_is_not_remembered_as_a_library_playlist(self):
        from chutku.apps import known
        with tempfile.TemporaryDirectory() as temp, patch.object(known, "PROJECT_ROOT", Path(temp)), \
                patch.object(runner, "run", return_value={"ok": True, "action": "play_public_playlist"}):
            registry = ToolRegistry()
            app_tools.register_app_tools(registry)
            registry.get("app.spotify.play_playlist").execute(
                {"name": "Loki"}, type("C", (), {"granted_root": Path(temp) / "sandbox"})())
            self.assertEqual(known.known("spotify", "playlist", Path(temp)), [])


if __name__ == "__main__":
    unittest.main()
