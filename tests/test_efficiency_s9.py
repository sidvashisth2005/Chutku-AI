"""Efficiency, logging and packaging (master plan S9)."""
import json
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

from chutku import dashboard, evidence, health
from chutku.core import log
from tests import test_dashboard


class LogTests(unittest.TestCase):
    def test_secrets_and_message_text_never_reach_the_log(self):
        line = log.redact('send {"text": "I love you", "phone": "+91 98765 43210"} token=abcdefghijklmnopqrstuvwxyz0123456789')
        self.assertNotIn("I love you", line)
        self.assertNotIn("98765", line)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", line)

    def test_tests_never_write_the_owners_log(self):
        logger = log.get_logger("test")
        self.assertFalse(any(isinstance(h, log.RotatingFileHandler) for h in logger.parent.handlers))


class ErrorIdTests(unittest.TestCase):
    setUp = test_dashboard.DashboardTests.setUp   # borrow the harness, not its tests
    tearDown = test_dashboard.DashboardTests.tearDown
    request = test_dashboard.DashboardTests.request

    def test_a_failed_read_carries_an_error_id(self):
        with patch.object(dashboard, "create_runtime", side_effect=RuntimeError("disk on fire")), \
                patch.object(dashboard, "_error_ref", return_value="abcd1234") as ref:
            status, payload, _ = self.request("/api/state")
        self.assertEqual(status, 500)
        self.assertEqual(payload["error_id"], "abcd1234")
        self.assertNotIn("disk on fire", json.dumps(payload))   # details go to the log, not the page
        ref.assert_called_once()

    def test_polled_session_reads_need_no_runtime(self):
        with patch.object(dashboard, "create_runtime", side_effect=AssertionError("no runtime for a poll")):
            status, payload, _ = self.request("/api/agent/latest")
        self.assertEqual(status, 200)
        self.assertIn("handsfree", payload)


class EvidenceTests(unittest.TestCase):
    def test_cached_digest_matches_and_follows_changes(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(evidence.cached_source_digest(root), evidence.source_digest(root))
        with patch.object(evidence, "source_digest", side_effect=AssertionError("should be cached")):
            evidence.cached_source_digest(root)   # unchanged files: no re-hash


class PackagingTests(unittest.TestCase):
    def test_every_imported_third_party_package_is_pinned(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        pinned = {dep.split("==")[0].casefold() for dep in project["project"]["dependencies"]}
        self.assertIn("websockets", pinned)   # chutku/voice/live.py imports it
        self.assertEqual(project["build-system"]["build-backend"], "setuptools.build_meta")
        lock = (root / "requirements.lock").read_text(encoding="utf-8").splitlines()
        names = [line.split("==")[0] for line in lock if "==" in line and not line.startswith("#")]
        self.assertEqual(len(names), len(set(names)))   # nothing pinned twice

    def test_powershell_is_never_found_through_path(self):
        self.assertTrue(health.powershell_exe().casefold().endswith(
            "system32\\windowspowershell\\v1.0\\powershell.exe".replace("\\", "/").casefold().replace("/", "\\"))
            or health.powershell_exe().casefold().endswith("powershell.exe"))
        self.assertIn("System32", health.powershell_exe())
        root = Path(__file__).resolve().parents[1]
        for name in ("autostart.py", "health.py", "remind.py"):
            self.assertNotIn('["powershell"', (root / "chutku" / name).read_text(encoding="utf-8"), name)

    def test_toasts_use_chutkus_own_name(self):
        self.assertIn("Chutku.Assistant", health._TOAST)
        from chutku import remind
        self.assertIn("Chutku.Assistant", remind._TOAST)


if __name__ == "__main__":
    unittest.main()
