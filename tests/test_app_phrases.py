"""App phrases, app-scoped planner menu and apps.howto (App Mastery A3). No test touches the screen."""
import unittest
from unittest.mock import patch

from chutku import agent_loop
from chutku.agent_loop import AgentSession, relevant_rows
from chutku.apps import atlas as atlas_module, howto, phrases
from chutku.apps.tools import register_app_tools
from chutku.quick_intents import QUICK_ANSWERS, quick_proposal
from chutku.tools.registry import ToolRegistry

ATLASES = {
    "demo": {"app": "demo", "name": "Demo", "aliases": ["demo player"], "window": {"exe": "Demo.exe"}, "actions": [
        {"id": "play_list", "title": "Play a list", "risk": "safe", "params": {"name": {"type": "text"}},
         "phrases": ["play {name} list", "play my {name} list"], "steps": [{"focus": True}]},
        {"id": "play_any", "title": "Play anything", "risk": "safe", "params": {"name": {"type": "text"}},
         "phrases": ["play {name}"], "steps": [{"focus": True}]},
        {"id": "pause", "title": "Pause", "risk": "safe", "phrases": ["demo pause karo"], "steps": [{"focus": True}]},
        {"id": "pause2", "title": "Pause too", "risk": "safe", "phrases": ["demo pause karo"],
         "steps": [{"focus": True}]},
        {"id": "open", "title": "Open", "risk": "safe", "phrases": ["open demo"], "route": False,
         "steps": [{"focus": True}]},
    ]}}
ALL = {"demo": {"play_list", "play_any", "pause", "pause2", "open"}}
SPOTIFY_VERIFIED = {"spotify": {"open", "pause", "resume", "next", "previous", "shuffle", "repeat", "volume_up",
                                "volume_down", "search", "go_home", "go_playlists", "go_liked", "go_queue",
                                "play_playlist", "play_liked"}}


def steps(goal):
    proposal = quick_proposal(goal, apps=[{"name": "Spotify", "app_id": "S"}])
    return [(s["tool"], s["arguments"]) for s in proposal["next_steps"]] if proposal else None


class PhraseTests(unittest.TestCase):
    def test_slots_and_the_longest_fixed_phrase_win(self):
        self.assertEqual(phrases.match("play After Party list", ATLASES, ALL)[:2],
                         ("app.demo.play_list", {"name": "After Party"}))
        self.assertEqual(phrases.match("please play my After Party list", ATLASES, ALL)[:2],
                         ("app.demo.play_list", {"name": "After Party"}))
        self.assertEqual(phrases.match("play Lofi Beats", ATLASES, ALL)[:2], ("app.demo.play_any", {"name": "Lofi Beats"}))

    def test_only_verified_actions_are_routed(self):
        self.assertIsNone(phrases.match("play After Party list", ATLASES, {"demo": {"pause"}}))
        self.assertIsNone(phrases.match("play After Party list", ATLASES, {}))

    def test_two_actions_reading_the_same_are_left_to_the_planner(self):
        self.assertIsNone(phrases.match("demo pause karo", ATLASES, ALL))
        self.assertEqual(phrases.match("demo pause karo", ATLASES, {"demo": {"pause"}})[0], "app.demo.pause")

    def test_route_false_and_partial_matches_are_not_routed(self):
        self.assertIsNone(phrases.match("open demo", ATLASES, ALL))
        self.assertIsNone(phrases.match("can you demo pause karo and more", ATLASES, ALL))

    def test_shipped_spotify_phrases(self):
        with patch("chutku.apps.lab.verified_actions", return_value=SPOTIFY_VERIFIED):
            self.assertEqual(steps("After Party wali playlist chalao"),
                             [("app.spotify.play_playlist", {"name": "After Party"})])
            self.assertEqual(steps("spotify mein lofi beats dhoondo"), [("app.spotify.search", {"query": "lofi beats"})])
            self.assertEqual(steps("liked songs kholo"), [("app.spotify.go_liked", {})])
            # Generic phrases keep Chutku's own rules: any player, and launching stays apps.launch.
            self.assertEqual(steps("gaana roko"), [("media.control", {"action": "pause"})])
            self.assertEqual(steps("open spotify"), [("apps.launch", {"name": "Spotify"})])
            # Negative: an unverified action is not routed instantly.
            self.assertNotIn("app.spotify.new_playlist", str(steps("nayi playlist banao")))
        with patch("chutku.apps.lab.verified_actions", return_value={}):
            self.assertNotIn("app.spotify", str(steps("After Party wali playlist chalao")))


def row(name, description="x"):
    return {"name": name, "description": description, "arguments": {}, "risk": 1}


class ScopeTests(unittest.TestCase):
    ROWS = [row("apps.launch"), row("app.demo.play_list", "Demo: play a list"), row("app.spotify.pause", "Spotify: pause")]

    def test_app_tools_only_for_the_named_app(self):
        atlases = dict(ATLASES, spotify={"app": "spotify", "name": "Spotify", "aliases": ["gaane"]})
        names = lambda goal, used=(): [r["name"] for r in phrases.app_scope(self.ROWS, goal, used, atlases)]
        self.assertEqual(names("open the folder"), ["apps.launch"])
        self.assertEqual(names("spotify pe kuch chalao"), ["apps.launch", "app.spotify.pause"])
        self.assertEqual(names("use the demo player"), ["apps.launch", "app.demo.play_list"])
        self.assertEqual(names("hmm", {"app.demo.play_list"}), ["apps.launch", "app.demo.play_list"])

    def test_planner_menu_is_scoped(self):
        rows = self.ROWS + [row("web.search")]
        session = AgentSession("play some lofi music", mode="owner")
        self.assertNotIn("app.spotify.pause", [r["name"] for r in relevant_rows(rows, session)])
        session = AgentSession("spotify pause", mode="owner")
        self.assertIn("app.spotify.pause", [r["name"] for r in relevant_rows(rows, session)])
        session.full_catalog = True   # the retry with every tool offers every tool
        self.assertIn("app.demo.play_list", [r["name"] for r in relevant_rows(rows, session)])


class FinalFailureTests(unittest.TestCase):
    def test_an_app_action_that_found_nothing_ends_the_request(self):
        # 2026-10-09 live: after "'Afterparty Hits' (playlist) is not visible; nothing clicked" the planner spent
        # 142 s on screen.understand and then asked to click. The refusal is the answer.
        import tempfile
        from pathlib import Path
        from chutku.app import create_runtime
        from chutku.apps import runner, tools as app_tools
        from tests.test_agent_loop import ScriptedPlanner, proposal, step
        refusal = {"ok": False, "error": "'Afterparty Hits' (playlist) is not visible; nothing clicked", "steps": []}
        with tempfile.TemporaryDirectory() as temp:
            runtime = create_runtime(Path(temp))
            try:
                runtime.capability_grants.grant("desktop.input")
                planner = ScriptedPlanner(
                    proposal(steps=[step("app.spotify.play_playlist", name="Afterparty Hits")]),
                    proposal(steps=[step("screen.understand", question="where is it")]))
                with patch.object(runner, "run", return_value=refusal):
                    snap = AgentSession("Afterparty Hits playlist chalao", mode="owner").advance(runtime, planner)
            finally:
                runtime.close()
        self.assertEqual([s["tool"] for s in snap["steps"]], ["app.spotify.play_playlist"])
        self.assertEqual(snap["status"], "failed")
        self.assertIn("nothing clicked", snap["reply"])
        self.assertEqual(len(planner.proposals), 1)

    def test_other_app_failures_are_still_replanned(self):
        self.assertTrue(agent_loop._final_failure({"tool": "app.spotify.play_playlist",
                                                   "message": "2 items read 'X'; say which one"}))
        self.assertFalse(agent_loop._final_failure({"tool": "app.spotify.go_home",
                                                    "message": "the steps ran but the check failed: ocr_contains"}))
        self.assertFalse(agent_loop._final_failure({"tool": "web.search", "message": "nothing clicked"}))


class HowtoTests(unittest.TestCase):
    def test_resolve_names(self):
        self.assertEqual(howto.resolve("VS Code"), "vscode")
        self.assertEqual(howto.resolve("File Explorer"), "explorer")
        self.assertIsNone(howto.resolve("photoshop"))

    def test_answers_come_from_the_feature_map(self):
        atlases, _ = atlas_module.load_all()
        out = howto.answer("shuffle", "spotify", atlases["spotify"], {"shuffle"})
        self.assertIn("Ctrl+S", out["answers"][0]["text"])
        self.assertEqual(out["can_do"][0], {"tool": "app.spotify.shuffle", "title": "Turn shuffle on or off",
                                            "verified": True})
        self.assertIn("khud kar sakti", howto.say(out))
        self.assertIn("abhi test nahi hua", howto.say(howto.answer("shuffle", "spotify", atlases["spotify"])))
        self.assertIn("Alt+Shift+B", howto.answer("like a song", "spotify")["answers"][0]["text"])
        self.assertIn("nahi mila", howto.say(howto.answer("fly to the moon", "spotify")))

    def test_quick_phrases(self):
        self.assertEqual(steps("spotify mein shuffle kaise karte hain"),
                         [("apps.howto", {"app": "spotify", "question": "shuffle"})])
        self.assertEqual(steps("vs code mein terminal kaise kholte hain"),
                         [("apps.howto", {"app": "vscode", "question": "terminal kholte"})])
        self.assertEqual(steps("how do I mute a chat in whatsapp"),
                         [("apps.howto", {"app": "whatsapp", "question": "mute a chat"})])
        self.assertNotIn("apps.howto", str(steps("how do I mute a chat in photoshop")))
        self.assertIn("apps.howto", QUICK_ANSWERS)

    def test_tool_is_read_only_and_validates(self):
        registry = ToolRegistry()
        register_app_tools(registry)
        tool = registry.get("apps.howto")
        self.assertEqual(int(tool.base_risk), 0)
        tool.validate_arguments({"app": "spotify", "question": "shuffle"})
        for bad in ({"app": "photoshop", "question": "x"}, {"app": "spotify"}, {"app": "spotify", "question": ""}):
            with self.assertRaises(ValueError):
                tool.validate_arguments(bad)
        self.assertNotIn("apps.howto", agent_loop.TAINTING_TOOLS)   # our own maps, not web text


if __name__ == "__main__":
    unittest.main()
