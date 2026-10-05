from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime


DISPLAY = {"index": 0, "device": r"\\.\DISPLAY1", "primary": True,
           "x": 0, "y": 0, "width": 640, "height": 480}


def fake_png(path: Path, width=640, height=480):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                     + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00")


class ScreenTests(unittest.TestCase):
    def test_inventory_requires_exact_capability_and_validates_shape(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("screen.displays", {})["state"], "DENIED")
            runtime.capability_grants.grant("screen.observe")
            with patch("chutku.tools.screen._invoke", return_value={"displays": [DISPLAY]}):
                result = runtime.run("screen.displays", {})
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["output"], {"displays": [DISPLAY], "count": 1})
            with patch("chutku.tools.screen._invoke", return_value={"displays": [{**DISPLAY, "width": 0}]}):
                self.assertEqual(runtime.run("screen.displays", {})["state"], "FAILED")

    def test_capture_is_new_verified_journaled_and_undoable(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("screen.observe")
            target = runtime.granted_root / "capture.png"

            def invoke(request):
                if request["action"] == "inventory":
                    return {"displays": [DISPLAY]}
                fake_png(Path(request["path"]))
                return {"display_index": 0, "width": 640, "height": 480,
                        "device": DISPLAY["device"]}

            with patch("chutku.tools.screen._invoke", side_effect=invoke):
                result = runtime.run("screen.capture", {"display_index": 0, "path": "capture.png"})
            self.assertEqual(result["state"], "COMPLETED")
            self.assertTrue(target.is_file())
            self.assertFalse(result["output"]["pixels_sent_to_model"])

            undone = runtime.run("screen.undo_last_capture", {})
            self.assertEqual(undone["state"], "COMPLETED")
            self.assertFalse(target.exists())

    def test_layout_change_fails_and_removes_its_capture(self):
        changed = {**DISPLAY, "width": 800}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("screen.observe")
            target = runtime.granted_root / "capture.png"
            replies = [{"displays": [DISPLAY]},
                       {"display_index": 0, "width": 640, "height": 480,
                        "device": DISPLAY["device"]},
                       {"displays": [changed]}]

            def invoke(request):
                reply = replies.pop(0)
                if request["action"] == "capture":
                    fake_png(Path(request["path"]))
                return reply

            with patch("chutku.tools.screen._invoke", side_effect=invoke):
                result = runtime.run("screen.capture", {"display_index": 0, "path": "capture.png"})
            self.assertEqual(result["state"], "FAILED")
            self.assertFalse(target.exists())

    def test_existing_or_outside_path_fails_before_capture(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("screen.observe")
            (runtime.granted_root / "exists.png").write_bytes(b"keep")
            for path in ("exists.png", "../outside.png", "wrong.jpg"):
                with patch("chutku.tools.screen._invoke") as invoke:
                    result = runtime.run("screen.capture", {"display_index": 0, "path": path})
                    invoke.assert_not_called()
                self.assertIn(result["state"], {"FAILED", "DENIED"})
            self.assertEqual((runtime.granted_root / "exists.png").read_bytes(), b"keep")

    def test_undo_refuses_modified_capture(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("screen.observe")
            target = runtime.granted_root / "capture.png"

            def invoke(request):
                if request["action"] == "inventory":
                    return {"displays": [DISPLAY]}
                fake_png(Path(request["path"]))
                return {"display_index": 0, "width": 640, "height": 480,
                        "device": DISPLAY["device"]}

            with patch("chutku.tools.screen._invoke", side_effect=invoke):
                self.assertEqual(runtime.run("screen.capture", {
                    "display_index": 0, "path": "capture.png"})["state"], "COMPLETED")
            target.write_bytes(target.read_bytes() + b"changed")
            result = runtime.run("screen.undo_last_capture", {})
            self.assertEqual(result["state"], "FAILED")
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
