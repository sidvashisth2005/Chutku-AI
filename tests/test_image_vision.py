from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.tools import image_vision

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


class ImageVisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.root = self.runtime.granted_root
        (self.root / "dot.png").write_bytes(PNG)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_gemini_backup_needs_the_cloud_capability(self):
        sent = []
        with patch("chutku.local_vision.available", return_value=False), \
                patch("chutku.tools.screen_vision._key", return_value="k"), \
                patch("chutku.gemini.generate_best", side_effect=lambda *a, **k: sent.append(1) or ("x", "g")):
            result = self.runtime.run("image.describe", {"path": "dot.png"})
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertIn("cloud.gemini", result["output"]["error"])
        self.assertEqual(sent, [])          # nothing went to Google without the grant

    def test_describes_locally_first_without_any_cloud_grant(self):
        class Eyes:
            def look(self, images, system, prompt, **kw):
                return "A tiny dot.", {"model": "local:Qwen3-VL-4B", "backend": "test"}
        with patch("chutku.local_vision.available", return_value=True), \
                patch("chutku.local_vision.shared", return_value=Eyes()), \
                patch("chutku.gemini.generate_best", side_effect=AssertionError("Gemini must not be called")):
            result = self.runtime.run("image.describe", {"path": "dot.png"})
        self.assertEqual(str(result["state"]), "COMPLETED", result)
        self.assertEqual(result["output"]["model"], "local:Qwen3-VL-4B")

    def test_describes_with_gemini_and_marks_output_untrusted(self):
        self.runtime.capability_grants.grant("cloud.gemini")
        sent = {}

        def fake(key, purpose, system, user, **kw):
            sent.update(kw)
            return "A single red pixel.", "gemini-test"
        with patch("chutku.tools.screen_vision._key", return_value="k"), \
                patch("chutku.local_vision.available", return_value=False), \
                patch("chutku.gemini.generate_best", side_effect=fake):
            result = self.runtime.run("image.describe", {"path": "dot.png", "question": "what colour?"})
        self.assertEqual(result["state"], "COMPLETED", result)
        self.assertEqual(result["output"]["description"], "A single red pixel.")
        self.assertEqual(result["output"]["provenance"], "external_untrusted")
        self.assertEqual(sent["images"][0][0], "image/png")

    def test_refuses_wrong_files(self):
        self.runtime.capability_grants.grant("cloud.gemini")
        (self.root / "notes.txt").write_text("x", encoding="utf-8")
        with patch("chutku.tools.screen_vision._key", return_value="k"):
            for path in ("notes.txt", "missing.png"):
                self.assertEqual(self.runtime.run("image.describe", {"path": path})["state"], "FAILED", path)
            with patch("chutku.tools.image_vision.MAX_IMAGE_BYTES", 10):
                self.assertEqual(self.runtime.run("image.describe", {"path": "dot.png"})["state"], "FAILED")

    def test_marked_as_sending_data_off_the_machine(self):
        self.assertTrue(self.runtime.registry.get("image.describe").network_egress)


if __name__ == "__main__":
    unittest.main()
