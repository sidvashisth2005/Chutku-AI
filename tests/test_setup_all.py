"""O4 (2026-11-05): setup_all fetches runtime zips safely; nothing unverified is kept."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup_all", ROOT / "scripts" / "setup_all.py")
setup_all = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_all)


class RuntimeFetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def zip_with(self, members):
        archive = self.root / "vendor" / "downloads" / "rt.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as package:
            for name, data in members.items():
                package.writestr(name, data)
        return archive

    def test_an_archive_entry_escaping_the_folder_is_refused_before_extraction(self):
        archive = self.zip_with({"llama-server.exe": b"x", "../../evil.txt": b"owned"})
        with self.assertRaisesRegex(OSError, "unsafe path"):
            setup_all._safe_extract(archive, self.root / "vendor" / "rt")
        self.assertFalse((self.root / "evil.txt").exists())

    def test_a_runtime_whose_executable_digest_differs_is_deleted(self):
        archive = self.zip_with({"llama-server.exe": b"tampered"})
        entry = {"source": "https://example.invalid/rt.zip", "sha256": setup_all.sha256(archive),
                 "directory": "vendor/rt", "executable_sha256": "0" * 64}
        with patch.object(setup_all, "ROOT", self.root):
            with self.assertRaisesRegex(OSError, "does not match"):
                setup_all.fetch_runtime("runtime", entry)
        self.assertFalse((self.root / "vendor" / "rt").exists())

    def test_a_matching_runtime_is_kept(self):
        archive = self.zip_with({"llama-server.exe": b"good"})
        good = setup_all.sha256(archive)
        with zipfile.ZipFile(archive) as package:
            executable = __import__("hashlib").sha256(package.read("llama-server.exe")).hexdigest()
        entry = {"source": "https://example.invalid/rt.zip", "sha256": good, "directory": "vendor/rt",
                 "executable_sha256": executable}
        with patch.object(setup_all, "ROOT", self.root), patch.object(setup_all, "download") as fetch:
            setup_all.fetch_runtime("runtime", entry)
        fetch.assert_not_called()   # the archive was already there and verified
        self.assertTrue((self.root / "vendor" / "rt" / "llama-server.exe").is_file())


if __name__ == "__main__":
    unittest.main()
