"""Counting files is exact, never left to a model (live check 2026-10-05: "5 files" for 3 files + 3 folders)."""
import os
import tempfile
import unittest
from pathlib import Path

from chutku.app import create_runtime
from chutku.quick_intents import _say_listing, quick_proposal


class FolderCountTests(unittest.TestCase):
    def test_named_folder_questions_list_the_real_folder_instantly(self):
        home = os.environ.get("USERPROFILE", r"C:\Users\Public")
        for text, folder in (("mere desktop pe kitni files hain", "Desktop"),
                             ("how many files are in my downloads", "Downloads"),
                             ("what is on my desktop", "Desktop"), ("documents mein kya kya hai", "Documents")):
            step = quick_proposal(text)["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]["path"]), ("filesystem.list", os.path.join(home, folder)))
        self.assertIsNone(quick_proposal("mere desktop pe kitni files hain aur unhe delete karo"))

    def test_listing_counts_files_and_folders_apart(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = create_runtime(Path(temp))
            root = runtime.granted_root
            for name in ("a.txt", "b.png", "c.md"):
                (root / name).write_text("x", encoding="utf-8")
            for name in ("one", "two", "three"):
                (root / name).mkdir()
            out = runtime.run("filesystem.list", {"path": "."})["output"]
            runtime.close()
        self.assertEqual((out["file_count"], out["folder_count"]), (3, 3))
        said = _say_listing(out)
        self.assertIn("3 files", said)
        self.assertIn("3 folders", said)


if __name__ == "__main__":
    unittest.main()
