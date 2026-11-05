"""O1 (2026-11-05): the original owner's folders are settings or found on disk, never hardcoded for everyone."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import know_me
from chutku.core.paths import user_folder
from chutku.core.preferences import Preferences


class UserFolderTests(unittest.TestCase):
    def test_existing_second_drive_folder_wins_else_the_profile(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"USERPROFILE": home}):
            with patch.object(Path, "is_dir", return_value=False):
                self.assertEqual(user_folder("ChutkuProjects"), str(Path(home) / "ChutkuProjects"))
            with patch.object(Path, "is_dir", return_value=True):
                self.assertEqual(user_folder("ChutkuProjects"), "D:\\ChutkuProjects")


class MediaFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.prefs = Preferences(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_is_empty_and_only_full_paths_are_accepted(self):
        self.assertEqual(self.prefs.load()["media_folders"], [])
        for bad in (["relative\\folder"], "D:\\Videos", [1], ["D:\\x"] * 21):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.prefs.update({"media_folders": bad})
        self.assertEqual(self.prefs.update({"media_folders": ["D:\\Shows"]})["media_folders"], ["D:\\Shows"])

    def test_a_hand_edited_bad_value_falls_back_to_the_default(self):
        (self.base / "data").mkdir()
        (self.base / "data" / "preferences.json").write_text('{"media_folders": ["no-drive"]}', encoding="utf-8")
        self.assertEqual(self.prefs.load()["media_folders"], [])

    def test_media_roots_use_the_owners_folders(self):
        shows = self.base / "Shows"
        shows.mkdir()
        self.prefs.update({"media_folders": [str(shows)]})
        with patch.object(know_me, "vlc_recent_paths", return_value=[]):
            self.assertIn(shows, know_me.media_roots(self.base))


if __name__ == "__main__":
    unittest.main()
