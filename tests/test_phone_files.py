"""Owner 2026-11-07: browse the laptop's files from the phone (no paths to remember), with kind filters."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from chutku.remote import files_browse


class FilesBrowseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        zones = mock.patch("chutku.core.paths.protected_zones", return_value=[])   # the temp folder is under AppData
        zones.start()
        self.addCleanup(zones.stop)
        for name in ("trip.JPG", "notes.pdf", "budget.xlsx", "song.mp3", "setup.exe", ".hidden.pdf"):
            (self.root / name).write_bytes(b"x" * 10)
        (self.root / "Album").mkdir()
        (self.root / "Album" / "beach.png").write_bytes(b"x")

    def names(self, listing):
        return sorted(f["name"] for f in listing["files"])

    def test_kinds(self):
        self.assertEqual(files_browse.kind_of("a.JPG"), "photo")
        self.assertEqual(files_browse.kind_of("a.tar.gz"), "archive")
        self.assertEqual(files_browse.kind_of("README"), "other")

    def test_a_folder_lists_folders_first_and_filters_files(self):
        everything = files_browse.listing(str(self.root))
        self.assertEqual([f["name"] for f in everything["folders"]], ["Album"])
        self.assertEqual(self.names(everything), ["budget.xlsx", "notes.pdf", "setup.exe", "song.mp3", "trip.JPG"])
        self.assertNotIn(".hidden.pdf", self.names(everything))                    # hidden and dot files are skipped
        self.assertEqual(self.names(files_browse.listing(str(self.root), "photo")), ["trip.JPG"])
        self.assertEqual(self.names(files_browse.listing(str(self.root), "pdf")), ["notes.pdf"])
        self.assertEqual(files_browse.listing(str(self.root / "Album"))["parent"], str(self.root.resolve()))

    def test_refusals(self):
        with self.assertRaises(ValueError):
            files_browse.listing(str(self.root / "missing"))
        with self.assertRaises(ValueError):
            files_browse.listing(str(self.root / "notes.pdf"))
        with self.assertRaises(ValueError):
            files_browse.listing(str(self.root), "exe")
        with mock.patch("chutku.core.paths.protected_zones", return_value=[str(self.root.resolve()).casefold()]):
            with self.assertRaises(PermissionError):
                files_browse.listing(str(self.root))
        with mock.patch("chutku.references.secret_reason", lambda p: "secret" if p.endswith(".pdf") else None):
            self.assertNotIn("notes.pdf", self.names(files_browse.listing(str(self.root))))

    def test_search_and_recent_filter_by_kind_and_drop_gone_files(self):
        rows = [{"path": str(self.root / n)} for n in ("notes.pdf", "trip.JPG", "deleted.pdf")]
        with mock.patch("chutku.drive_index.search", return_value=rows):
            self.assertEqual([f["name"] for f in files_browse.search("notes", "pdf")["files"]], ["notes.pdf"])
            self.assertEqual(len(files_browse.search("x")["files"]), 2)               # deleted.pdf is gone
        with self.assertRaises(ValueError):
            files_browse.search("")


class FilesEndpointTests(unittest.TestCase):
    def test_the_endpoints_are_read_only_and_inside_the_pin_session(self):
        from chutku.remote import server
        handler = server.PhoneHandler.__new__(server.PhoneHandler)
        handler.server = mock.Mock(pin_ok={})
        record = {"device": "d"}
        from chutku.remote.auth import RemoteDenied
        with self.assertRaisesRegex(RemoteDenied, "PIN needed"):   # no PIN session: asks first
            handler._post_files_list(record, {"path": str(Path.home())})
        handler.server.pin_ok["d"] = 10 ** 12
        with tempfile.TemporaryDirectory() as folder, mock.patch("chutku.core.paths.protected_zones", return_value=[]):
            Path(folder, "a.pdf").write_bytes(b"x")
            self.assertEqual([f["name"] for f in handler._post_files_list(record, {"path": folder, "kind": "pdf"})["files"]],
                             ["a.pdf"])
        for path in ("/api/files/list", "/api/files/search", "/api/files/recent", "/api/files/places"):
            self.assertEqual(server.KINDS[path], "poll")


if __name__ == "__main__":
    unittest.main()
