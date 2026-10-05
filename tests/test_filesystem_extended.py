from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.app import create_runtime
from chutku.planning import execute_request


class ExtendedFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)
        self.root = self.runtime.granted_root

    def tearDown(self):
        self._purge_recycled()
        self.runtime.close()
        self.temp.cleanup()

    def test_inspect_and_bounded_name_search(self):
        (self.root / "docs").mkdir()
        target = self.root / "docs/report-final.txt"
        target.write_text("verified content", encoding="utf-8")
        inspected = self.runtime.run("filesystem.inspect", {"path": "docs/report-final.txt"})
        self.assertEqual(inspected["state"], "COMPLETED")
        self.assertEqual(inspected["output"]["kind"], "file")
        self.assertEqual(inspected["output"]["size"], len(b"verified content"))
        self.assertEqual(len(inspected["output"]["sha256"]), 64)
        searched = self.runtime.run("filesystem.search", {"path": ".", "query": "REPORT", "recursive": True})
        self.assertEqual(searched["state"], "COMPLETED")
        matches = searched["output"]["matches"]
        self.assertEqual([(m["path"], m["kind"], m["size"]) for m in matches],
                         [("docs/report-final.txt", "file", len(b"verified content"))])
        self.assertEqual(matches[0]["full_path"], str(target.resolve()))
        self.assertTrue(searched["output"]["complete"])

    def test_inspect_missing_target_is_a_verified_answer(self):
        result = self.runtime.run("filesystem.inspect", {"path": "not-there.txt"})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertIs(result["output"]["exists"], False)

    def test_copy_is_no_overwrite_verified_and_undoable(self):
        source = self.root / "source.bin"
        source.write_bytes(b"copy me\x00exactly")
        copied = self.runtime.run("filesystem.copy", {"source": "source.bin", "destination": "copied.bin"})
        self.assertEqual(copied["state"], "COMPLETED")
        self.assertEqual((self.root / "copied.bin").read_bytes(), source.read_bytes())
        collision = self.runtime.run("filesystem.copy", {"source": "source.bin", "destination": "copied.bin"})
        self.assertEqual(collision["state"], "FAILED")
        self.assertEqual((self.root / "copied.bin").read_bytes(), b"copy me\x00exactly")
        undone = self.runtime.run("filesystem.undo_last_copy", {})
        self.assertEqual(undone["state"], "COMPLETED")
        self.assertFalse((self.root / "copied.bin").exists())
        self.assertTrue(source.exists())

    def test_copy_undo_refuses_conflicting_edit(self):
        (self.root / "source.txt").write_text("before", encoding="utf-8")
        self.assertEqual(self.runtime.run("filesystem.copy", {
            "source": "source.txt", "destination": "copy.txt"})["state"], "COMPLETED")
        (self.root / "copy.txt").write_text("external edit", encoding="utf-8")
        refused = self.runtime.run("filesystem.undo_last_copy", {})
        self.assertEqual(refused["state"], "FAILED")
        self.assertEqual((self.root / "copy.txt").read_text(encoding="utf-8"), "external edit")

    def test_move_and_rename_are_verified_and_undoable(self):
        source = self.root / "old-name.txt"
        source.write_text("move me", encoding="utf-8")
        moved = self.runtime.run("filesystem.move", {
            "source": "old-name.txt", "destination": "new-name.txt"})
        self.assertEqual(moved["state"], "COMPLETED")
        self.assertFalse(source.exists())
        self.assertEqual((self.root / "new-name.txt").read_text(encoding="utf-8"), "move me")
        undone = self.runtime.run("filesystem.undo_last_move", {})
        self.assertEqual(undone["state"], "COMPLETED")
        self.assertEqual(source.read_text(encoding="utf-8"), "move me")
        self.assertFalse((self.root / "new-name.txt").exists())

    def test_move_refuses_collision_traversal_and_non_file_source(self):
        (self.root / "source.txt").write_text("source", encoding="utf-8")
        (self.root / "existing.txt").write_text("preserve", encoding="utf-8")
        (self.root / "folder").mkdir()
        for arguments in (
            {"source": "source.txt", "destination": "existing.txt"},
            {"source": "../outside.txt", "destination": "new.txt"},
            {"source": "folder", "destination": "renamed-folder"},
        ):
            self.assertIn(self.runtime.run("filesystem.move", arguments)["state"], {"FAILED", "DENIED"})
        self.assertEqual((self.root / "existing.txt").read_text(encoding="utf-8"), "preserve")
        self.assertTrue((self.root / "source.txt").exists())
        self.assertTrue((self.root / "folder").is_dir())

    def test_observe_only_grant_cannot_copy_or_move(self):
        external = self.base / "external"
        external.mkdir()
        (external / "source.txt").write_text("data", encoding="utf-8")
        grant_id = self.runtime.resource_grants.grant(external, {"observe"}).grant_id
        self.runtime.close()
        self.runtime = create_runtime(self.base, grant_id)
        self.root = external
        self.assertEqual(self.runtime.run("filesystem.inspect", {"path": "source.txt"})["state"], "COMPLETED")
        self.assertEqual(self.runtime.run("filesystem.copy", {
            "source": "source.txt", "destination": "copy.txt"})["state"], "DENIED")
        self.assertFalse((external / "copy.txt").exists())

    def test_plain_language_uses_same_runtime_and_verification_path(self):
        (self.root / "spoken.txt").write_text("same safe path", encoding="utf-8")
        result = execute_request("copy spoken.txt to copied-by-text.txt", self.runtime)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual((self.root / "copied-by-text.txt").read_text(encoding="utf-8"),
                         "same safe path")

    def _recycle(self, path):
        """Recycling always asks first; approve it as the user would on screen."""
        waiting = self.runtime.run("filesystem.recycle", {"path": path})
        self.assertEqual(waiting["state"], "WAITING_CONFIRMATION", waiting)
        return self.runtime.approve(waiting["approval"]["token"])

    def _purge_recycled(self):
        """Remove only the Recycle Bin items this test created (their journal records name them)."""
        from chutku.core import recycle_bin
        for record in self.runtime.journal.records("filesystem.recycle"):
            after = record.get("after") or {}
            if after.get("info") and Path(after["info"]).exists():
                recycle_bin.purge(after["info"], after["data"])

    def test_recycle_and_restore_file_through_windows_recycle_bin(self):
        target = self.root / "recover-me.txt"
        target.write_text("recoverable", encoding="utf-8")
        recycled = self._recycle("recover-me.txt")
        self.assertEqual(recycled["state"], "COMPLETED", recycled)
        self.assertFalse(target.exists())
        record = self.runtime.journal.records("filesystem.recycle")[-1]
        self.assertIn("$recycle.bin", record["after"]["info"].casefold())
        self.assertTrue(Path(record["after"]["data"]).is_file())
        restored = self.runtime.run("filesystem.restore_last_recycled", {})
        self.assertEqual(restored["state"], "COMPLETED", restored)
        self.assertEqual(target.read_text(encoding="utf-8"), "recoverable")
        self.assertFalse(Path(record["after"]["info"]).exists())
        self.assertFalse((self.root / ".chutku-trash").exists())

    def test_recycle_and_restore_folder(self):
        folder = self.root / "old project"
        (folder / "src").mkdir(parents=True)
        (folder / "src" / "main.py").write_text("print(1)", encoding="utf-8")
        recycled = self._recycle("old project")
        self.assertEqual(recycled["state"], "COMPLETED", recycled)
        self.assertFalse(folder.exists())
        restored = self.runtime.run("filesystem.restore_last_recycled", {})
        self.assertEqual(restored["state"], "COMPLETED", restored)
        self.assertEqual((folder / "src" / "main.py").read_text(encoding="utf-8"), "print(1)")

    def test_restore_refuses_existing_original_and_preserves_both_files(self):
        target = self.root / "conflict.txt"
        target.write_text("original", encoding="utf-8")
        self.assertEqual(self._recycle("conflict.txt")["state"],
                         "COMPLETED")
        target.write_text("new external file", encoding="utf-8")
        refused = self.runtime.run("filesystem.restore_last_recycled", {})
        self.assertEqual(refused["state"], "FAILED")
        self.assertEqual(target.read_text(encoding="utf-8"), "new external file")
        record = self.runtime.journal.records("filesystem.recycle")[-1]
        self.assertEqual(Path(record["after"]["data"]).read_text(encoding="utf-8"), "original")

    def test_recycle_refuses_drives_without_a_recycle_bin(self):
        from unittest.mock import patch
        target = self.root / "keep.txt"
        target.write_text("keep", encoding="utf-8")
        with patch("chutku.core.recycle_bin._drive_type", return_value=2):  # DRIVE_REMOVABLE
            result = self._recycle("keep.txt")
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("Recycle Bin", result["output"]["error"])
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_recycle_and_forget_always_ask_even_when_typed(self):
        from chutku.core.memory import MemoryStore  # noqa: F401  (memory.forget is registered)
        (self.root / "ask.txt").write_text("x", encoding="utf-8")
        for tool in ("filesystem.recycle", "memory.forget"):
            self.assertTrue(self.runtime.registry.get(tool).deletes, tool)
        waiting = self.runtime.run("filesystem.recycle", {"path": "ask.txt"})
        self.assertEqual(waiting["state"], "WAITING_CONFIRMATION", waiting)
        self.assertTrue((self.root / "ask.txt").exists())

    def test_permanent_delete_asks_and_removes_folder_without_following_junctions(self):
        import os, subprocess
        folder = self.root / "gone"
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "a.txt").write_text("x", encoding="utf-8")
        windows = Path(os.environ["SystemRoot"])
        before = sorted(item.name for item in windows.iterdir())[:50]
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(folder / "link"), str(windows)], capture_output=True)
        waiting = self.runtime.run("filesystem.delete_permanent", {"path": "gone"})
        self.assertEqual(waiting["state"], "WAITING_CONFIRMATION", waiting)
        self.assertEqual(waiting["approval"]["risk"], 4)
        self.assertTrue(folder.exists())
        done = self.runtime.approve(waiting["approval"]["token"])
        self.assertEqual(done["state"], "COMPLETED", done)
        self.assertFalse(folder.exists())
        if made.returncode == 0:
            self.assertEqual(sorted(item.name for item in windows.iterdir())[:50], before)

    def test_permanent_delete_never_chosen_by_the_agent(self):
        (self.root / "keep.txt").write_text("x", encoding="utf-8")
        for provenance in ("delegated", "inferred"):
            extra = {"autonomy": "auto_edits", "tainted": False, "exposed": False} if provenance == "delegated" else {}
            result = self.runtime.run("filesystem.delete_permanent", {"path": "keep.txt"}, provenance=provenance, **extra)
            self.assertEqual(result["state"], "DENIED", result)
        self.assertTrue((self.root / "keep.txt").exists())


if __name__ == "__main__":
    unittest.main()
