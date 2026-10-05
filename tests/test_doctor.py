from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.doctor import inspect_foundation


class DoctorTests(unittest.TestCase):
    def base(self, directory):
        base = Path(directory)
        (base / "chutku/web").mkdir(parents=True)
        for name in ("index.html", "app.js", "style.css"):
            (base / "chutku/web" / name).touch()
        (base / "pyproject.toml").write_text('[project]\ndependencies=["numpy==2.5.3","sounddevice==0.5.6"]\n')
        (base / "requirements.lock").write_text("numpy==2.5.3\nsounddevice==0.5.6\n")
        (base / "THIRD_PARTY_LICENSES.md").write_text("numpy sounddevice llama.cpp qwen")
        (base / "models").mkdir()
        (base / "models/manifest.json").write_text(
            '{"runtime":{"license":"MIT"},"model":{"license":"Apache-2.0","revision":"test"}}')
        return base

    def test_missing_license_ledger_fails_foundation_read_only(self):
        with TemporaryDirectory() as temp, patch("chutku.doctor.sys.platform", "win32"):
            base = self.base(temp)
            (base / "THIRD_PARTY_LICENSES.md").unlink()
            report = inspect_foundation(base)
            self.assertFalse(report["ready"])
            self.assertFalse(next(c["ready"] for c in report["checks"]
                                  if c["name"] == "Project THIRD_PARTY_LICENSES.md"))

    def test_dependency_lock_mismatch_fails_foundation(self):
        with TemporaryDirectory() as temp, patch("chutku.doctor.sys.platform", "win32"):
            base = self.base(temp)
            (base / "requirements.lock").write_text("numpy==0.0.0\nsounddevice==0.5.6\n")
            report = inspect_foundation(base)
            self.assertFalse(report["ready"])
            self.assertFalse(next(c["ready"] for c in report["checks"]
                                  if c["name"] == "Dependency lock alignment"))

    def test_missing_optional_model_does_not_disable_core_or_create_data(self):
        with TemporaryDirectory() as temp, patch("chutku.doctor.sys.platform", "win32"):
            base = self.base(temp)
            report = inspect_foundation(base)
            self.assertTrue(report["ready"])
            self.assertFalse(next(c["ready"] for c in report["checks"] if c["name"] == "Local model artifacts"))
            self.assertFalse((base / "data").exists())
            self.assertFalse((base / "sandbox").exists())

    def test_corrupt_storage_fails_without_modifying_it(self):
        with TemporaryDirectory() as temp:
            base = self.base(temp)
            (base / "data").mkdir()
            path = base / "data/chutku.db"
            path.write_bytes(b"not a database")
            self.assertFalse(inspect_foundation(base)["ready"])
            self.assertEqual(path.read_bytes(), b"not a database")

    def test_file_cannot_be_used_as_sandbox_root(self):
        with TemporaryDirectory() as temp:
            base = self.base(temp)
            (base / "sandbox").write_text("preserve")
            self.assertFalse(inspect_foundation(base)["ready"])
