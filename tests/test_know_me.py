"""2026-11-01: Chutku learns the owner's shows (folders + VLC history), apps and sites, and plays the right episode."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import know_me


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name) / "SID"
        baki = self.root / "Tele" / "Baki"
        baki.mkdir(parents=True)
        for name in ("24 Defeat.mkv", "25 God and the Devil.mkv", "26 The Centennial Tournament.mkv",
                     "OVA - Baki [Sub] [480p] @Anime_Wars.mkv", "notes.txt"):
            (baki / name).write_bytes(b"x")
        (self.root / "Tele" / "[@Anime_RTX] Ep 8 Bleach TYBW Part 4 [1080p] [Sub].mkv").write_bytes(b"x")
        self.baki = baki
        self.addCleanup(self.temp.cleanup)

    def library(self, history):
        library = know_me.scan_media([self.root])
        return {"media": library, "progress": know_me.progress(library, history)}

    def test_folders_become_series_with_episode_numbers(self):
        data = self.library([])
        self.assertEqual(sorted(data["media"]["Baki"]["episodes"]), ["24", "25", "26"])
        self.assertEqual(len(data["media"]["Baki"]["extras"]), 1)            # the OVA
        self.assertIn("Bleach TYBW Part 4", data["media"])
        self.assertEqual(know_me.find_series("baki", data), "Baki")
        self.assertEqual(know_me.find_series("bleach", data), "Bleach TYBW Part 4")

    def test_vlc_history_decides_continue_next_and_resume(self):
        data = self.library([(self.baki / "24 Defeat.mkv", 600_000)])           # stopped 10 min into 24
        path, number, start = know_me.choose_episode("Baki", data)
        self.assertEqual((number, start), (24, 600))                          # resume where they stopped
        path, number, start = know_me.choose_episode("Baki", data, which="next")
        self.assertEqual((number, start), (25, 0))
        data = self.library([(self.baki / "25 God and the Devil.mkv", 0)])      # finished 25
        self.assertEqual(know_me.choose_episode("Baki", data)[1], 26)
        self.assertEqual(know_me.choose_episode("Baki", data, episode=24)[1], 24)
        with self.assertRaises(LookupError):
            know_me.choose_episode("Baki", data, episode=3)                    # not on this PC: says so

    def test_all_watched_mentions_the_extra(self):
        data = self.library([(self.baki / "26 The Centennial Tournament.mkv", 0)])
        with self.assertRaises(LookupError) as caught:
            know_me.choose_episode("Baki", data)
        self.assertIn("OVA", str(caught.exception))

    def test_vlc_ini_is_read(self):
        ini = Path(self.temp.name) / "vlc-qt-interface.ini"
        ini.write_text("[RecentsMRL]\nlist=file:///D:/SID/Tele/Baki/26%20The%20Centennial%20Tournament.mkv, "
                       "file:///D:/SID/Tele/Baki/25%20God.mkv\ntimes=0, 1343077\n", encoding="utf-8")
        with patch.object(know_me, "vlc_ini", return_value=ini):
            history = know_me.vlc_history()
        self.assertEqual(history[0][0].name, "26 The Centennial Tournament.mkv")
        self.assertEqual(history[1][1], 1343077)


class SitesTests(unittest.TestCase):
    def test_brave_history_gives_top_domains(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "History"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE urls (url TEXT, title TEXT, visit_count INT, last_visit_time INT)")
            now = int((know_me.datetime.utcnow() - know_me.datetime(1601, 1, 1)).total_seconds() * 1_000_000)
            con.executemany("INSERT INTO urls VALUES (?,?,?,?)", [
                ("https://www.youtube.com/watch?v=1", "YT", 50, now), ("https://github.com/x", "GH", 20, now),
                ("https://old.example/", "old", 99, 0), ("chrome://settings", "", 5, now)])
            con.commit()
            con.close()
            sites = know_me.frequent_sites(db=db)
        self.assertEqual([s["site"] for s in sites], ["youtube.com", "github.com"])   # old visits and chrome:// left out


class PhraseTests(unittest.TestCase):
    def test_owner_sentences(self):
        from chutku import quick_intents
        data = {"media": {"Baki": {"folder": "D:/x", "episodes": {"25": "a", "26": "b"}, "extras": []}},
                "sites": [{"site": "github.com", "url": "https://github.com/", "visits": 9, "title": ""}]}
        with patch.object(know_me, "load", return_value=data), patch.object(quick_intents, "_installed_apps", return_value=[]):
            cases = {"play baki episode 25": ("media.play_series", {"series": "Baki", "episode": 25}),
                     "baki ka next episode chalao": ("media.play_series", {"series": "Baki", "which": "next"}),
                     "baki chalao": ("media.play_series", {"series": "Baki", "which": "continue"}),
                     "open github": ("web.open", {"url": "https://github.com/"})}
            for said, expected in cases.items():
                step = quick_intents.quick_proposal(said)["next_steps"][0]
                self.assertEqual((step["tool"], step["arguments"]), expected, said)
            self.assertIsNone(quick_intents._my_show("baki kab aayega"))              # no play word: not a request


if __name__ == "__main__":
    unittest.main()
