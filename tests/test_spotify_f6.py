"""F6 (2026-10-29): the owner's own Spotify sentences. A song word means pause, never quit; a playlist that once
played is played again by name from loose sentences, never searched."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.apps import known
from chutku.quick_intents import quick_proposal

APPS = [{"name": "Spotify", "app_id": "S"}]


def steps(goal):
    proposal = quick_proposal(goal, apps=APPS)
    return [(s["tool"], s["arguments"]) for s in proposal["next_steps"]] if proposal else None


class SongWordsPauseTests(unittest.TestCase):
    def test_closing_the_song_pauses_and_keeps_spotify_open(self):
        for said in ("spotify ka gaana band karo", "Spotify open karke gana band karo", "gaana band karo",
                     "close the music", "spotify ke gaane band karo"):
            self.assertEqual(steps(said), [("media.control", {"action": "pause"})], said)

    def test_closing_spotify_itself_still_quits(self):
        self.assertEqual(steps("spotify band karo"), [("apps.quit", {"name": "spotify"})])


class KnownPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        patcher = patch.object(known, "PROJECT_ROOT", self.base)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_only_a_played_playlist_is_remembered(self):
        self.assertFalse(known.remember("spotify", "pause", "x"))
        self.assertTrue(known.remember("spotify", "play_playlist", "After Party"))
        known.remember("spotify", "play_playlist", "after  party")          # the same name once
        self.assertEqual(known.known("spotify", "playlist"), ["After Party"])

    def test_owner_sentences_play_the_known_playlist(self):
        known.remember("spotify", "play_playlist", "After Party")
        for said in ("Spotify pe After Party chalao", "after party bajao", "play after party",
                     "Mera Spotify open kar aur after party playlist chala", "After Party playlist chalao"):
            self.assertEqual(steps(said), [("app.spotify.play_playlist", {"name": "After Party"})], said)

    def test_unknown_names_and_non_play_sentences_are_left_alone(self):
        known.remember("spotify", "play_playlist", "After Party")
        self.assertIsNone(known.spoken_playlist("after party kab hai"))      # no play word
        self.assertIsNone(known.spoken_playlist("play night drive"))          # never played: not guessed
        self.assertEqual(known.spoken_playlist("AFTER PARTY chalao"), "After Party")

    def test_a_successful_app_action_remembers_its_name(self):
        from chutku.app import create_runtime
        from chutku.apps import runner
        with create_runtime(self.base) as runtime, \
                patch.object(runner, "run", return_value={"ok": True}):
            runtime.registry.get("app.spotify.play_playlist").execute({"name": "Chill Vibes"},
                                                                       type("C", (), {"granted_root": self.base / "sandbox"})())
        self.assertEqual(known.known("spotify", "playlist", self.base), ["Chill Vibes"])


if __name__ == "__main__":
    unittest.main()
