"""Chutku never acts while elevated (plan Phase 1, item 1)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.core import elevation


class ElevationTests(unittest.TestCase):
    def test_real_token_query_answers_a_bool(self):
        self.assertIs(type(elevation.is_elevated()), bool)
        # The test suite itself must not be elevated, or Windows ACLs stop protecting system folders.
        self.assertFalse(elevation.is_elevated())

    def test_query_failure_counts_as_elevated(self):
        with patch("chutku.core.elevation._query_token", side_effect=OSError("no token")):
            self.assertTrue(elevation.is_elevated())

    def test_elevated_runtime_refuses_every_tool(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            target = runtime.granted_root / "elevated.txt"
            with patch("chutku.core.elevation.is_elevated", return_value=True):
                for tool, arguments in (("filesystem.write_text", {"path": "elevated.txt", "content": "x"}),
                                        ("filesystem.list", {"path": "."})):
                    result = runtime.run(tool, arguments)
                    self.assertEqual(result["state"], "DENIED", result)
                    self.assertIn("administrator", result["reason"])
            self.assertFalse(target.exists())
            self.assertEqual(runtime.run("filesystem.write_text", {"path": "elevated.txt", "content": "x"})["state"],
                             "COMPLETED")

    def test_elevated_approval_is_refused_too(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            with patch("chutku.core.elevation.is_elevated", return_value=False):
                pending = runtime.run("filesystem.write_text", {"path": "a.txt", "content": "x"},
                                      provenance="delegated", autonomy="review", tainted=False, exposed=False)
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION", pending)
            with patch("chutku.core.elevation.is_elevated", return_value=True):
                result = runtime.approve(pending["approval"]["token"])
            self.assertEqual(result["state"], "DENIED", result)
            self.assertFalse((runtime.granted_root / "a.txt").exists())

    def test_doctor_reports_elevation(self):
        from chutku.doctor import inspect_foundation
        from chutku.app import PROJECT_ROOT
        with patch("chutku.core.elevation.is_elevated", return_value=True):
            report = inspect_foundation(PROJECT_ROOT)
        check = next(c for c in report["checks"] if c["name"] == "Not elevated")
        self.assertFalse(check["ready"])
        self.assertFalse(report["ready"])


if __name__ == "__main__":
    unittest.main()
