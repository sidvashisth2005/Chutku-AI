import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile

from chutku.app import create_runtime


class FilesPlusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.root = self.runtime.granted_root

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def run_confirmed(self, tool, arguments):
        result = self.runtime.run(tool, arguments)
        if result["state"] == "WAITING_CONFIRMATION":
            result = self.runtime.approve(result["approval"]["token"])
        return result

    def test_zip_folder_then_unzip_round_trip(self):
        (self.root / "proj" / "src").mkdir(parents=True)
        (self.root / "proj" / "src" / "a.py").write_text("print(1)", encoding="utf-8")
        (self.root / "proj" / "readme.md").write_text("hi", encoding="utf-8")
        zipped = self.run_confirmed("files.zip", {"path": "proj"})
        self.assertEqual(zipped["state"], "COMPLETED", zipped)
        self.assertEqual(zipped["output"]["files"], 2)
        self.assertTrue((self.root / "proj.zip").is_file())
        unzipped = self.run_confirmed("files.unzip", {"path": "proj.zip", "destination": "restored"})
        self.assertEqual(unzipped["state"], "COMPLETED", unzipped)
        self.assertEqual((self.root / "restored" / "proj" / "src" / "a.py").read_text(encoding="utf-8"), "print(1)")

    def test_zip_never_overwrites(self):
        (self.root / "a.txt").write_text("x", encoding="utf-8")
        (self.root / "a.zip").write_bytes(b"keep")
        result = self.run_confirmed("files.zip", {"path": "a.txt"})
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual((self.root / "a.zip").read_bytes(), b"keep")

    def test_unzip_refuses_path_escape_and_existing_destination(self):
        with zipfile.ZipFile(self.root / "evil.zip", "w") as archive:
            archive.writestr("../escape.txt", "x")
        result = self.run_confirmed("files.unzip", {"path": "evil.zip"})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("unsafe", result["output"]["error"])
        self.assertFalse((self.root.parent / "escape.txt").exists())
        self.assertFalse((self.root / "evil").exists())
        with zipfile.ZipFile(self.root / "ok.zip", "w") as archive:
            archive.writestr("x.txt", "x")
        (self.root / "ok").mkdir()
        self.assertEqual(self.run_confirmed("files.unzip", {"path": "ok.zip"})["state"], "FAILED")

    def test_unzip_refuses_zip_bombs(self):
        with zipfile.ZipFile(self.root / "bomb.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("zeros.bin", b"\0" * (50 * 1024 * 1024))
        result = self.run_confirmed("files.unzip", {"path": "bomb.zip"})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("compression", result["output"]["error"])

    def test_recent_files_newest_first(self):
        for index, name in enumerate(("old.txt", "new.txt")):
            path = self.root / name
            path.write_text(name, encoding="utf-8")
            os.utime(path, (time.time() - (10 - index) * 3600,) * 2)
        result = self.runtime.run("files.recent", {"path": ".", "days": 2})
        self.assertEqual(result["state"], "COMPLETED", result)
        self.assertEqual([item["name"] for item in result["output"]["files"]][:2], ["new.txt", "old.txt"])

    def test_cleanup_report_is_read_only_and_finds_big_files(self):
        from chutku.tools.files_plus import cleanup_report
        home = self.root / "home"
        (home / "Downloads").mkdir(parents=True)
        (home / "Videos").mkdir()
        big = home / "Videos" / "movie.mp4"
        with big.open("wb") as stream:
            stream.truncate(250 * 1024 ** 2)  # sparse: no real disk use
        before = sorted(str(p) for p in home.rglob("*"))
        report = cleanup_report(home)
        self.assertFalse(report["deleted_anything"])
        self.assertEqual(report["biggest_files"][0]["name"], "movie.mp4")
        self.assertTrue(any("Move big files" in s for s in report["suggestions"]))
        self.assertEqual(sorted(str(p) for p in home.rglob("*")), before)

    def test_find_personal_files_skips_code_folders(self):
        from chutku.tools.files_plus import find_personal
        docs = self.root / "Documents"
        (docs / "project" / "node_modules" / "pkg").mkdir(parents=True)
        (docs / "Resume_Final.pdf").write_text("x", encoding="utf-8")
        (docs / "old-resume-2024.docx").write_text("x", encoding="utf-8")
        (docs / "project" / "node_modules" / "pkg" / "resume.js").write_text("x", encoding="utf-8")
        names = sorted(m["name"] for m in find_personal([docs], "my resume file"))
        self.assertEqual(names, ["Resume_Final.pdf", "old-resume-2024.docx"])
        self.assertEqual(find_personal([docs], "the files"), [])
        result = self.runtime.run("files.find", {"path": "Documents", "query": "resume final"})
        self.assertEqual([m["name"] for m in result["output"]["matches"]], ["Resume_Final.pdf"])

    def test_folder_and_search_phrases(self):
        from chutku.quick_intents import quick_proposal
        home = os.environ["USERPROFILE"]
        step = lambda t: (lambda p: p and (p["next_steps"][0]["tool"], p["next_steps"][0]["arguments"]))(quick_proposal(t, apps=[]))
        self.assertEqual(step("open my downloads"), ("files.open", {"path": os.path.join(home, "Downloads")}))
        self.assertEqual(step("d drive kholo"), ("files.open", {"path": "D:\\"}))
        self.assertEqual(step("find my resume"), ("files.find", {"path": home, "query": "resume"}))
        self.assertEqual(step("meri resume file dhundo"), ("files.find", {"path": home, "query": "resume"}))
        for text in ("find my newest pdf", "where is my latest invoice", "find my keys"):
            self.assertIsNone(quick_proposal(text, apps=[]), text)

    def test_cleanup_phrases(self):
        from chutku.quick_intents import quick_proposal
        for text in ("free up space on my C drive", "what's taking up space", "clean up my pc", "c drive khali karo"):
            self.assertEqual(quick_proposal(text, apps=[])["next_steps"][0]["tool"], "storage.cleanup_report", text)

    def test_disk_space_lists_fixed_drives(self):
        result = self.runtime.run("system.disk_space", {})
        self.assertEqual(result["state"], "COMPLETED", result)
        drives = {item["drive"] for item in result["output"]["drives"]}
        self.assertIn(Path(os.environ["SystemRoot"]).anchor, drives)
        for item in result["output"]["drives"]:
            self.assertEqual(item["low"], item["free_percent"] < 10)


if __name__ == "__main__":
    unittest.main()
