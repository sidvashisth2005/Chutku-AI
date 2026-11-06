"""O3 (2026-11-06): a PC without a working GPU runtime still gets the local brain and speech, on the CPU."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import brain_service
from chutku.voice import whisper_stt


class NoGpuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "models").mkdir()
        (self.base / "vendor").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def candidates(self, gpu_entry):
        (self.base / "models" / "manifest.json").write_text(json.dumps({"gpu_runtime": gpu_entry}), encoding="utf-8")
        with patch.object(brain_service, "verify_local_artifacts",
                          return_value={"runtime": "cpu-server.exe", "model": "planner.gguf"}):
            return brain_service.runtime_candidates(self.base)

    def test_no_gpu_runtime_folder_means_the_cpu_runtime_only(self):
        found = self.candidates({"directory": "vendor/llama-vulkan", "directory_sha256": "0" * 64})
        self.assertEqual([(c["backend"], c["gpu_layers"]) for c in found], [("CPU", 0)])

    def test_a_tampered_gpu_runtime_is_never_used(self):
        folder = self.base / "vendor" / "llama-vulkan"
        folder.mkdir()
        (folder / "llama-server.exe").write_bytes(b"changed")
        found = self.candidates({"directory": "vendor/llama-vulkan", "directory_sha256": "0" * 64})
        self.assertEqual([c["backend"] for c in found], ["CPU"])

    def test_speech_falls_back_to_the_cpu_model_when_the_gpu_one_fails(self):
        fast, cpu = {"path": "fast"}, {"path": "cpu", "device": "cpu"}
        calls = []

        def load(entry):
            calls.append(entry["path"])
            if entry is fast:
                raise RuntimeError("CUDA driver not found")
            return "model", entry
        with patch.object(whisper_stt, "configured_model", side_effect=lambda base, key="stt": fast if key == "stt_fast"
                          else cpu), patch.object(whisper_stt, "_load_entry", side_effect=load), \
                patch.dict(whisper_stt.FAST, {"failed": None}):
            self.assertEqual(whisper_stt._load(self.base), ("model", cpu))
            self.assertEqual(calls, ["fast", "cpu"])
            self.assertIn("CUDA", whisper_stt.FAST["failed"])   # the reason is kept, and the GPU model is not retried


if __name__ == "__main__":
    unittest.main()
