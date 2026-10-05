"""Planner model / speculative-draft selection from the pinned manifest (2026-10-05)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import brain_service
from chutku.brain_service import BrainService

BASE_CANDIDATES = [{"backend": "Vulkan", "executable": "gpu.exe", "gpu_layers": 99, "model": "base.gguf"},
                   {"backend": "CPU", "executable": "cpu.exe", "gpu_layers": 0, "model": "base.gguf"}]


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "models").mkdir()
        self.manifest = {}

    def tearDown(self):
        self.temp.cleanup()

    def add(self, key, name, data=b"model", **extra):
        (self.base / "models" / name).write_bytes(data)
        self.manifest[key] = {"path": f"models\\{name}", "sha256": hashlib.sha256(b"model").hexdigest(), **extra}

    def candidates(self):
        (self.base / "models/manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with patch.object(brain_service, "runtime_candidates", return_value=[dict(c) for c in BASE_CANDIDATES]):
            return BrainService(self.base)._candidates()

    def test_default_is_unchanged(self):
        self.assertEqual(self.candidates(), BASE_CANDIDATES)

    def test_enabled_draft_is_tried_first_on_gpu_with_a_plain_fallback(self):
        self.add("draft", "small.gguf", enabled=True)
        found = self.candidates()
        self.assertEqual([(c["backend"], bool(c.get("draft"))) for c in found],
                         [("Vulkan", True), ("Vulkan", False), ("CPU", False)])

    def test_disabled_or_tampered_draft_is_not_used(self):
        self.add("draft", "small.gguf", enabled=False)
        self.assertFalse(any(c.get("draft") for c in self.candidates()))
        self.add("draft", "small.gguf", data=b"tampered", enabled=True)
        self.assertFalse(any(c.get("draft") for c in self.candidates()))

    def test_active_planner_switches_the_model(self):
        self.add("planner_2507", "new.gguf")
        self.manifest["active_planner"] = "planner_2507"
        self.assertTrue(all(c["model"].endswith("new.gguf") for c in self.candidates()))


if __name__ == "__main__":
    unittest.main()
