"""X5 (2026-11-05): the drive index holds names only, skips system/code folders, and answers by name words."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import drive_index
from chutku.app import create_runtime


class DriveIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.disk = Path(self.temp.name) / "disk"
        for relative in ("Work/Resume final.pdf", "Work/old/resume draft.docx", "Bills/Electricity March.pdf",
                         "proj/node_modules/resume.js", "proj/.git/resume.txt", "Windows/System32/resume.dll"):
            path = self.disk / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        old = time.time() - 86400
        os.utime(self.disk / "Work/old/resume draft.docx", (old, old))
        self.zones = [os.path.normcase(str(self.disk / "Windows"))]

    def tearDown(self):
        self.temp.cleanup()

    def build(self, **kwargs):
        with patch.object(drive_index, "protected_zones", return_value=self.zones):
            return drive_index.build(self.base, roots=[str(self.disk)], **kwargs)

    def test_names_only_and_system_and_code_folders_are_skipped(self):
        result = self.build()
        self.assertEqual((result["files"], result["complete"]), (3, True))
        names = [m["name"] for m in drive_index.search("resume", self.base)]
        self.assertEqual(names, ["Resume final.pdf", "resume draft.docx"])   # newest first; no .git/node_modules/Windows
        self.assertEqual(drive_index.search("electricity march", self.base)[0]["name"], "Electricity March.pdf")
        self.assertEqual(drive_index.search("resume march", self.base), [])   # every word must match
        self.assertEqual(drive_index.search("the file", self.base), [])      # filler only: no wild match

    def test_the_cap_marks_the_index_incomplete(self):
        result = self.build(max_entries=2)
        self.assertEqual((result["files"], result["complete"]), (2, False))
        self.assertFalse(drive_index.status(self.base)["complete"])

    def test_drive_filter(self):
        self.build()
        letter = str(self.disk)[0]
        self.assertTrue(drive_index.search("resume", self.base, drive=letter))
        other = "Q" if letter.upper() != "Q" else "R"
        self.assertEqual(drive_index.search("resume", self.base, drive=other), [])


class LocateToolTests(unittest.TestCase):
    def test_without_an_index_it_searches_the_personal_folders_and_says_so(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp) / "state") as runtime:
            home = Path(temp) / "home"
            (home / "Documents").mkdir(parents=True)
            (home / "Documents" / "My Resume.pdf").write_text("x", encoding="utf-8")
            with patch.object(drive_index, "PROJECT_ROOT", Path(temp) / "state"), \
                    patch.dict(os.environ, {"USERPROFILE": str(home)}):
                missing = runtime.run("files.locate", {"query": "resume"}, provenance="delegated", autonomy="owner")
                self.assertEqual(str(missing["state"]), "COMPLETED", missing)
                self.assertIn("not built yet", missing["output"]["searched"])
                self.assertEqual(missing["output"]["matches"][0]["name"], "My Resume.pdf")
                disk = Path(temp) / "disk"
                disk.mkdir()
                (disk / "Resume.pdf").write_text("x", encoding="utf-8")
                with patch.object(drive_index, "protected_zones", return_value=[]):
                    drive_index.build(roots=[str(disk)])
                found = runtime.run("files.locate", {"query": "resume"}, provenance="delegated", autonomy="owner")
                self.assertEqual(str(found["state"]), "COMPLETED", found)
                bad = runtime.run("files.locate", {"query": "resume", "drive": "DD"}, provenance="delegated",
                                  autonomy="owner")
                self.assertNotEqual(str(bad["state"]), "COMPLETED")


if __name__ == "__main__":
    unittest.main()
