"""Acting on what is already on the screen (owner, 2026-10-08): the exact item the owner named is clicked (never a
look-alike, never a search); two equal matches ask; "play" presses play and checks that music plays."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.quick_intents import QUICK_ANSWERS, quick_proposal
from chutku.tools import visible
from tests.test_agent_loop import ScriptedPlanner, proposal, step

# What Windows OCR read in the owner's Spotify window on 2026-10-08 (search results for "Afterparty").
SPOTIFY = [("After party songs", (1173, 203, 1372, 226)), ("Party With The Bhoothnath", (1124, 331, 1365, 349)),
           ("Afterparty", (1123, 411, 1217, 429)), ("Afterparty", (1123, 491, 1217, 509)),
           ("After Party", (1123, 571, 1220, 589)), ("AFTERPARTY", (1123, 651, 1244, 665)),
           ("bollywood sangeet afterparty", (1124, 730, 1394, 748)), ("afterparty 26'", (1123, 836, 1246, 854))]
LINES = [{"text": text, "rect": rect} for text, rect in SPOTIFY]


class MatchTests(unittest.TestCase):
    def test_the_exact_name_wins_over_look_alikes(self):
        tier, found = visible.matches(LINES, "after party")
        self.assertEqual((tier, [l["text"] for l in found]), ("exact", ["After Party"]))

    def test_several_equal_matches_are_all_returned(self):
        tier, found = visible.matches(LINES, "afterparty")
        self.assertEqual(tier, "exact")
        self.assertEqual(len(found), 3)                 # "Afterparty" ×2 and "AFTERPARTY"

    def test_no_look_alike_when_absent(self):
        self.assertEqual(visible.matches(LINES, "chill vibes"), (None, []))


class FakeShot:
    window = {}


class ActTests(unittest.TestCase):
    def run_act(self, arguments, lines=LINES, see=None, statuses=None, window=True, ocr=None, paused=None):
        clicks = []
        statuses = list(statuses or [{"status": "Paused", "title": "Old"}])
        reads = list(ocr) if ocr else None

        def media(action):
            if action == "pause":
                (paused if paused is not None else []).append(True)
                return {"accepted": True}
            return statuses.pop(0) if len(statuses) > 1 else statuses[0]
        with patch.object(visible, "_window_for", return_value=(type("D", (), {"focus": lambda s, h: None})(),
                                                                  42 if window else None)), \
                patch.object(visible, "_rect", return_value=(0, 0, 1920, 1080)), \
                patch.object(visible, "_ocr", side_effect=(lambda _r: reads.pop(0) if len(reads) > 1 else reads[0])
                             if reads else (lambda _r: lines)), \
                patch("chutku.vision.capture", return_value=FakeShot()), \
                patch("chutku.vision.changed", return_value=True), \
                patch("chutku.vision.click_at", side_effect=lambda x, y, *a, **k: clicks.append((x, y))), \
                patch("chutku.vision.see", return_value=see or {"elements": []}), \
                patch("chutku.vision.remember_seen"), \
                patch("chutku.tools.everyday.media", side_effect=media), \
                patch("time.sleep"):
            result = visible._act(arguments, None)
        return result, clicks

    def test_clicks_the_exact_item(self):
        result, clicks = self.run_act({"name": "after party", "app": "spotify", "action": "open"})
        self.assertEqual(clicks, [((1123 + 1220) // 2, (571 + 589) // 2)])
        self.assertEqual(result.output["clicked"], "After Party")

    def test_ambiguous_asks_and_clicks_nothing(self):
        result, clicks = self.run_act({"name": "afterparty", "app": "spotify"})
        self.assertEqual(clicks, [])
        self.assertEqual(result.verification, "FAIL")
        self.assertIn("say which one", result.output["error"])

    def test_not_visible_never_searches_or_clicks(self):
        result, clicks = self.run_act({"name": "chill vibes", "app": "spotify", "action": "play"})
        self.assertEqual(clicks, [])
        self.assertIn("did not search", result.output["error"])

    def test_app_not_open(self):
        result, clicks = self.run_act({"name": "after party", "app": "spotify"}, window=False)
        self.assertEqual(clicks, [])
        self.assertIn("is not open", result.output["error"])

    def test_play_presses_play_and_checks_music(self):
        see = {"elements": [{"id": "e1", "label": "Play", "kind": "button", "rect": (950, 300, 1010, 360)},
                            {"id": "e2", "label": "Playlist title", "kind": "text", "rect": (0, 0, 10, 10)}]}
        page = LINES + [{"text": "Song A", "rect": (1050, 500, 1200, 520)}]   # the opened page lists the track
        result, clicks = self.run_act({"name": "after party", "app": "spotify", "action": "play"}, see=see,
                                      ocr=[LINES, page],
                                      statuses=[{"status": "Paused", "title": "Old"},
                                                {"status": "Playing", "title": "Song A"}])
        self.assertEqual(clicks[1], (980, 330))          # the play button, after the playlist
        self.assertTrue(result.output["playing"])
        self.assertEqual(result.verification, "PASS")
        self.assertIn("Played “After Party”", QUICK_ANSWERS["screen.act_on_visible"](result.output))

    # 2026-10-08 live: the exact text "After Party" was the SONG by Don Toliver, not the owner's playlist.
    SONG = [{"text": "Playlists", "rect": (1200, 120, 1270, 140)},
            {"text": "After Party", "rect": (1123, 571, 1220, 589)},
            {"text": "Song • Don Toliver", "rect": (1124, 593, 1300, 607)}]
    PLAYLIST = [{"text": "After Party", "rect": (1123, 300, 1220, 318)},
                {"text": "Playlist • Siddhant", "rect": (1124, 322, 1300, 336)}]
    PAGE = [{"text": "After Party", "rect": (1000, 200, 1300, 260)},
            {"text": "Kesariya", "rect": (1050, 500, 1200, 520)}, {"text": "Raataan Lambiyan", "rect": (1050, 560, 1250, 580)}]
    PLAY = {"elements": [{"id": "e1", "label": "Play", "kind": "button", "rect": (1000, 280, 1060, 340)}]}

    def test_a_song_with_the_same_name_is_not_the_playlist(self):
        result, clicks = self.run_act({"name": "after party", "app": "spotify", "action": "play", "kind": "playlist"},
                                      ocr=[[l for l in self.SONG if l["text"] != "Playlists"]])
        self.assertEqual(clicks, [])
        self.assertIn("as a song, not as a playlist", result.output["error"])

    def test_the_playlists_filter_is_used_to_find_the_playlist(self):
        result, clicks = self.run_act({"name": "after party", "app": "spotify", "action": "play", "kind": "playlist"},
                                      ocr=[self.SONG, self.PLAYLIST, self.PAGE], see=self.PLAY,
                                      statuses=[{"status": "Paused", "title": "Old"},
                                                {"status": "Playing", "title": "Kesariya"}])
        self.assertEqual(clicks[0], (1235, 130))                      # the "Playlists" filter
        self.assertEqual(clicks[1], ((1123 + 1220) // 2, (300 + 318) // 2))   # the playlist, not the song row
        self.assertEqual(result.output["kind"], "playlist")
        self.assertTrue(result.output["playing"])

    def test_a_wrong_song_starting_is_paused_and_reported(self):
        paused = []
        result, _ = self.run_act({"name": "after party", "app": "spotify", "action": "play", "kind": "playlist"},
                                 ocr=[self.PLAYLIST, self.PAGE], see=self.PLAY, paused=paused,
                                 statuses=[{"status": "Paused", "title": "Old"},
                                           {"status": "Playing", "title": "After Party (Don Toliver)"}])
        self.assertEqual(paused, [True])
        self.assertFalse(result.output["playing"])
        self.assertIn("so I paused it", result.output["error"])

    def test_the_player_bar_play_button_is_never_used(self):
        bar = {"elements": [{"id": "e1", "label": "Play", "kind": "button", "rect": (1400, 1000, 1440, 1040)}]}
        result, clicks = self.run_act({"name": "after party", "app": "spotify", "action": "play", "kind": "playlist"},
                                      ocr=[self.PLAYLIST, self.PAGE], see=bar)
        self.assertEqual(len(clicks), 1)                              # only the playlist itself
        self.assertIn("could not find its own play button", result.output["error"])

    def test_play_that_does_not_start_is_not_claimed(self):
        see = {"elements": [{"id": "e1", "label": "Play", "kind": "button", "rect": (950, 300, 1010, 360)}]}
        result, _ = self.run_act({"name": "after party", "app": "spotify", "action": "play"}, see=see,
                                 statuses=[{"status": "Paused", "title": "Old"}])
        self.assertFalse(result.output["playing"])
        self.assertEqual(result.verification, "FAIL")


class PhraseAndGuardTests(unittest.TestCase):
    def test_owner_phrasings(self):
        playlist = {"name": "after party", "action": "play", "kind": "playlist", "app": "spotify"}
        cases = {"playlist screen pr hi h after party ki play it": playlist,
                 "after party playlist screen pr hi h play kr do": playlist,
                 "screen pe jo after party playlist hai usko play karo": playlist,
                 "play After Party from the screen": {"name": "After Party", "action": "play",
                                                      "app_if_open": "spotify"},
                 "screen pe Settings dikh raha hai usko kholo": {"name": "Settings", "action": "open"}}
        with patch("chutku.apps.lab.verified", return_value=False):   # before the Action Lab verified play_playlist
            for text, arguments in cases.items():
                got = quick_proposal(text)["next_steps"][0]
                self.assertEqual((got["tool"], got["arguments"]), ("screen.act_on_visible", arguments), text)
        with patch("chutku.apps.lab.verified", return_value=True):    # verified: the library route (2026-10-11)
            got = quick_proposal("playlist screen pr hi h after party ki play it")["next_steps"][0]
            self.assertEqual((got["tool"], got["arguments"]), ("app.spotify.play_playlist", {"name": "after party"}))
        self.assertEqual(quick_proposal("screen pe kya hai")["next_steps"][0]["tool"], "screen.ask")

    def test_a_failed_on_screen_action_is_final(self):
        # 2026-10-08 live: after "not as a playlist", the planner clicked a play button and started the song.
        from chutku.tools.registry import ToolResult, Verification
        refusal = ToolResult({"error": "I can see 'after party', but only as song, not as a playlist; I clicked "
                                       "nothing and did not search."}, Verification.FAIL)
        with tempfile.TemporaryDirectory() as temp:
            runtime = create_runtime(Path(temp))
            try:
                runtime.capability_grants.grant("desktop.input")
                planner = ScriptedPlanner(
                    proposal(steps=[step("screen.act_on_visible", name="after party", action="play",
                                         kind="playlist", app="spotify")]),
                    proposal(steps=[step("screen.click", element="e2", label="Play button")]))
                with patch.object(visible, "_act", return_value=refusal):
                    snap = AgentSession("playlist screen pr hi h after party ki play it",
                                        mode="owner").advance(runtime, planner)
            finally:
                runtime.close()
        self.assertEqual([s["tool"] for s in snap["steps"]], ["screen.act_on_visible"])   # no improvised click
        self.assertEqual(snap["status"], "failed")
        self.assertIn("not as a playlist", snap["reply"])
        self.assertEqual(len(planner.proposals), 1)     # the planner was never asked again

    def test_search_is_refused_when_the_owner_said_it_is_on_screen(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = create_runtime(Path(temp))
            try:
                planner = ScriptedPlanner(proposal(steps=[step("spotify.search", query="Afterparty")]),
                                          proposal(steps=[step("spotify.search", query="Afterparty")]))
                snap = AgentSession("after party playlist screen pe hai, search mat karna, play it",
                                    mode="owner").advance(runtime, planner)
            finally:
                runtime.close()
        self.assertEqual(snap["steps"], [])                      # the search never ran
        self.assertEqual(snap["status"], "failed")
        self.assertIn("Do not search", planner.inputs[1])


if __name__ == "__main__":
    unittest.main()
