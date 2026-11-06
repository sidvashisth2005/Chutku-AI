"""H25: backup and restore of Chutku's memory. The restore verifies every file first and refuses while Chutku runs."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
import zipfile

from chutku import backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "install"
        self.data = self.base / "data"
        (self.data / "logs").mkdir(parents=True)
        (self.data / "wake").mkdir()
        (self.data / "mind.json").write_text('{"facts": {"name": "Asha"}}', encoding="utf-8")
        (self.data / "logs" / "chutku.log").write_text("log", encoding="utf-8")
        (self.data / "wake" / "clip.wav").write_bytes(b"RIFF")
        (self.data / "embeddings.sqlite").write_bytes(b"rebuildable")
        (self.data / "execution.lock").write_bytes(b"\0")
        with closing(sqlite3.connect(self.data / "memory.db")) as db:
            db.execute("CREATE TABLE notes (text TEXT)")
            db.execute("INSERT INTO notes VALUES ('buy milk')")
            db.commit()
        self.folder = Path(self.temp.name) / "backups"

    def test_round_trip_restores_exactly_and_keeps_a_safety_copy(self):
        started = time.perf_counter()
        made = backup.create(self.base, folder=self.folder)
        seconds = time.perf_counter() - started
        with zipfile.ZipFile(made["path"]) as archive:
            names = set(archive.namelist())
        self.assertEqual(names, {"manifest.json", "data/mind.json", "data/memory.db"})   # logs, voice, caches skipped
        original = (self.data / "mind.json").read_bytes()
        (self.data / "mind.json").write_text('{"facts": {"name": "changed"}}', encoding="utf-8")
        result = backup.restore(self.base, made["path"], folder=self.folder)
        self.assertEqual((self.data / "mind.json").read_bytes(), original)
        with closing(sqlite3.connect(self.data / "memory.db")) as db:
            self.assertEqual(db.execute("SELECT text FROM notes").fetchall(), [("buy milk",)])
        with zipfile.ZipFile(result["safety_backup"]) as archive:
            self.assertIn(b"changed", archive.read("data/mind.json"))   # the state before the restore is kept
        print(f"\n[H25] backup in {seconds:.3f}s, {made['files']} files, restore of {result['restored']}")

    def test_a_damaged_backup_or_a_running_chutku_changes_nothing(self):
        made = backup.create(self.base, folder=self.folder)
        tampered = self.folder / "tampered.zip"
        with zipfile.ZipFile(made["path"]) as source, zipfile.ZipFile(tampered, "w") as target:
            for name in source.namelist():
                content = source.read(name)
                target.writestr(name, content.replace(b"Asha", b"Evil") if name == "data/mind.json" else content)
        before = hashlib.sha256((self.data / "mind.json").read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            backup.restore(self.base, tampered, folder=self.folder)
        self.assertEqual(hashlib.sha256((self.data / "mind.json").read_bytes()).hexdigest(), before)
        (self.data / "guard.running").write_text("1", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            backup.restore(self.base, made["path"], folder=self.folder)
        unsafe = self.folder / "unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"files": {"../evil.txt": "0"}}))
        (self.data / "guard.running").unlink()
        with self.assertRaises(ValueError):
            backup.verify(unsafe)

    def test_a_database_being_written_is_copied_consistently(self):
        writer = sqlite3.connect(self.data / "memory.db")
        writer.execute("BEGIN")
        writer.execute("INSERT INTO notes VALUES ('not committed yet')")
        made = backup.create(self.base, folder=self.folder)
        writer.rollback()
        writer.close()
        copy = Path(self.temp.name) / "copy.db"
        with zipfile.ZipFile(made["path"]) as archive:
            copy.write_bytes(archive.read("data/memory.db"))
        with closing(sqlite3.connect(copy)) as db:
            self.assertEqual(db.execute("SELECT text FROM notes").fetchall(), [("buy milk",)])

    def test_only_the_newest_four_are_kept_and_old_ones_go_to_the_recycle_bin(self):
        sent = []
        def recycle(path):   # the Recycle Bin moves the file away
            sent.append(Path(path).name)
            Path(path).unlink()
        with patch("chutku.core.recycle_bin.send", recycle):
            for minute in range(6):
                backup.create(self.base, folder=self.folder,
                              now=__import__("datetime").datetime(2026, 11, 6, 10, minute))
        self.assertEqual(sent, ["chutku-20261106-100000.zip", "chutku-20261106-100100.zip"])


if __name__ == "__main__":
    unittest.main()
