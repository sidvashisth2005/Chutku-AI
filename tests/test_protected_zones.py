import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from chutku.app import PROJECT_ROOT, create_runtime
from chutku.core.paths import protection_reason, sandbox_target
from chutku.core.resource_grants import ResourceGrantStore

WINDOWS = Path(os.environ.get("SystemRoot", r"C:\Windows"))
DRIVE = Path(WINDOWS.anchor)


class ProtectedZoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        store = ResourceGrantStore(self.base / "data/resource_grants.db")
        self.grant = store.grant(DRIVE, ["modify"])
        store.close()
        self.runtime = create_runtime(self.base, self.grant.grant_id)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def assert_denied_without_effect(self, tool, arguments, created):
        result = self.runtime.run(tool, arguments)
        self.assertIn(str(result["state"]), {"DENIED", "FAILED"}, result)
        self.assertFalse(Path(created).exists(), created)
        return result

    def test_system_areas_cannot_be_written(self):
        for target in (WINDOWS / "chutku-test.txt", Path(str(WINDOWS).upper()) / "chutku-test2.txt"):
            result = self.assert_denied_without_effect("filesystem.write_text",
                                                       {"path": str(target), "content": "x"}, target)
            self.assertEqual(str(result["state"]), "DENIED", target)

    def test_app_folders_ask_first_and_nothing_is_written_before_the_ok(self):
        # WA1 (owner 2026-11-08): Program Files, ProgramData and AppData are an app's own files: no longer refused,
        # they ask the first time (and nothing happens until the owner says yes)
        for target in (Path(r"C:\PROGRA~1\chutku-test.txt"), Path(os.environ["ProgramData"]) / "chutku-test.txt",
                       Path(os.environ["USERPROFILE"]) / "AppData" / "chutku-test.txt"):
            result = self.runtime.run("filesystem.write_text", {"path": str(target), "content": "x"})
            self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION", target)
            self.assertFalse(target.exists(), target)

    def test_chutku_runtime_cannot_be_modified(self):
        store = ResourceGrantStore(self.base / "data/resource_grants.db")
        grant = store.grant(Path(Path(PROJECT_ROOT).anchor), ["modify"])
        store.close()
        with create_runtime(self.base, grant.grant_id) as runtime:
            for relative in ("data/chutku-test.txt", "chutku/chutku-test.py", "models/x.gguf"):
                target = Path(PROJECT_ROOT) / relative
                result = runtime.run("filesystem.write_text", {"path": str(target), "content": "x"})
                self.assertEqual(str(result["state"]), "DENIED", relative)
                self.assertFalse(target.exists())
            allowed = Path(PROJECT_ROOT) / "sandbox" / f"chutku-self-test-{os.getpid()}.txt"
            made = not allowed.parent.exists()   # a fresh clone has no sandbox/ until Chutku first starts
            allowed.parent.mkdir(exist_ok=True)
            try:
                result = runtime.run("filesystem.write_text", {"path": str(allowed), "content": "ok"})
                self.assertEqual(str(result["state"]), "COMPLETED", result)
            finally:
                allowed.unlink(missing_ok=True)
                if made:
                    allowed.parent.rmdir()

    def test_move_or_recycle_out_of_system_area_denied(self):
        source = WINDOWS / "win.ini"
        self.assertTrue(source.exists())
        before = source.stat().st_mtime
        destination = Path(tempfile.gettempdir()) / "chutku-stolen.ini"
        self.assert_denied_without_effect("filesystem.move", {"source": str(source), "destination": str(destination)},
                                          destination)
        self.assertEqual(str(self.runtime.run("filesystem.recycle", {"path": str(source)})["state"]), "DENIED")
        self.assertEqual(source.stat().st_mtime, before)

    def test_junction_into_windows_refused(self):
        link = Path(tempfile.gettempdir()) / f"chutku-junction-{os.getpid()}"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(WINDOWS)], capture_output=True)
        if made.returncode != 0:
            self.skipTest("cannot create junction here")
        try:
            target = link / "chutku-test.txt"
            self.assert_denied_without_effect("filesystem.write_text", {"path": str(target), "content": "x"},
                                              WINDOWS / "chutku-test.txt")
        finally:
            os.rmdir(link)

    def test_observe_of_system_area_allowed(self):
        result = self.runtime.run("filesystem.inspect", {"path": str(WINDOWS / "win.ini")})
        self.assertEqual(str(result["state"]), "COMPLETED")

    def test_ordinary_user_location_writable_and_undoable(self):
        target = Path(tempfile.gettempdir()) / f"chutku-drive-grant-{os.getpid()}.txt"
        try:
            result = self.runtime.run("filesystem.write_text", {"path": str(target), "content": "hello"})
            self.assertEqual(str(result["state"]), "COMPLETED", result)
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")
            undone = self.runtime.run("filesystem.undo_last_write", {"path": str(target)})
            self.assertEqual(str(undone["state"]), "COMPLETED", undone)
            self.assertFalse(target.exists())
        finally:
            target.unlink(missing_ok=True)

    def test_modify_grant_inside_system_area_refused(self):
        store = ResourceGrantStore(self.base / "data/resource_grants.db")
        try:
            with self.assertRaises(ValueError):
                store.grant(WINDOWS, ["modify"])
            self.assertEqual(store.grant(WINDOWS, ["observe"]).access, frozenset({"observe"}))
        finally:
            store.close()

    def test_unparseable_path_argument_denied(self):
        """A modify tool's path that cannot be resolved safely is DENIED, not left to the tool."""
        for bad in (r"\\server\share\x.txt", "C:relative.txt", r"C:\Users\..\Windows\x.txt", "a\\file.txt:stream",
                    "CON", 42):
            result = self.runtime.run("filesystem.write_text", {"path": bad, "content": "x"})
            self.assertNotEqual(str(result["state"]), "COMPLETED", bad)
            tool = self.runtime.registry.get("filesystem.write_text")
            self.assertIsNotNone(self.runtime.protected_target(tool, {"path": bad, "content": "x"}), bad)

    def test_path_arguments_found_by_schema(self):
        from chutku.core.paths import path_argument_names
        from chutku.tools.registry import Risk, Tool
        tool = Tool("x.save", "test", Risk.DATA_MODIFICATION, lambda a, c: None, resource_access="modify",
                    argument_schema={"type": "object", "properties": {
                        "output_folder": {"type": "string"}, "target_file": {"type": "string"},
                        "where": {"type": "string", "format": "path"}, "note": {"type": "string"}}})
        self.assertEqual(path_argument_names(tool), {"output_folder", "target_file", "where"})
        for key in ("output_folder", "target_file", "where"):
            self.assertIsNotNone(self.runtime.protected_target(tool, {key: str(WINDOWS / "x")}), key)
        self.assertIsNone(self.runtime.protected_target(tool, {"note": str(WINDOWS / "x")}))

    def test_copy_into_program_files_asks(self):
        source = Path(tempfile.gettempdir()) / f"chutku-copy-src-{os.getpid()}.txt"
        source.write_text("x", encoding="utf-8")
        destination = Path(os.environ["ProgramFiles"]) / f"chutku-copy-{os.getpid()}.txt"
        try:
            result = self.runtime.run("filesystem.copy", {"source": str(source), "destination": str(destination)})
            self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION")   # WA1: asks, never silently
            self.assertFalse(destination.exists())
        finally:
            source.unlink(missing_ok=True)

    def test_drive_root_windows_on_other_drive_denied(self):
        self.assertIsNotNone(protection_reason(Path(r"D:\Windows\x.txt")))
        self.assertIsNotNone(protection_reason(Path(r"D:\Program Files\x"), "delete"))   # uninstall instead

    def test_path_forms(self):
        self.assertIsNotNone(protection_reason(DRIVE / "pagefile.sys"))
        self.assertIsNotNone(protection_reason(DRIVE))
        for bad in (r"\\server\share\x", "C:relative", r"\rooted", r"C:\..\Windows"):
            with self.assertRaises(ValueError):
                sandbox_target(DRIVE, bad)


if __name__ == "__main__":
    unittest.main()
