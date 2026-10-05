import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.tools.clipboard import MAX_CLIPBOARD_BYTES


class ClipboardTests(unittest.TestCase):
    @staticmethod
    def completed(payload, returncode=0):
        class Completed:
            pass
        result = Completed()
        result.returncode = returncode
        result.stdout = json.dumps(payload)
        return result

    def test_read_requires_grant_and_redacts_clipboard_content_from_audit(self):
        secret = "private clipboard content"
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("clipboard.read_text", {})["state"], "DENIED")
            runtime.capability_grants.grant("clipboard.read")
            with patch("chutku.tools.clipboard.sys.platform", "win32"), patch(
                    "chutku.tools.clipboard.subprocess.run",
                    return_value=self.completed({"text": secret, "characters": len(secret)})):
                result = runtime.run("clipboard.read_text", {})
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["output"]["text"], secret)
            rows = runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall()
            self.assertNotIn(secret, str(rows))

    def test_write_uses_fixed_script_stdin_and_exact_verification(self):
        text = "literal $() ` text — not PowerShell"
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("clipboard.write_text", {"text": text})["state"], "DENIED")
            runtime.capability_grants.grant("clipboard.write")
            with patch("chutku.tools.clipboard.sys.platform", "win32"), patch(
                    "chutku.tools.clipboard.subprocess.run",
                    return_value=self.completed({"written": True, "characters": len(text)})) as run:
                result = runtime.run("clipboard.write_text", {"text": text})
            self.assertEqual(result["state"], "COMPLETED")
            self.assertNotIn(text, " ".join(run.call_args.args[0]))
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["text"], text)
            rows = runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall()
            self.assertNotIn(text, str(rows))

    def test_invalid_oversized_and_failed_operations_fail_closed(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("clipboard.write")
            for arguments in ({}, {"text": 1}, {"text": "x", "extra": True},
                              {"text": "x" * (MAX_CLIPBOARD_BYTES + 1)}):
                self.assertEqual(runtime.run("clipboard.write_text", arguments)["state"], "FAILED")
            with patch("chutku.tools.clipboard.sys.platform", "win32"), patch(
                    "chutku.tools.clipboard.subprocess.run",
                    return_value=self.completed({}, returncode=1)):
                self.assertEqual(runtime.run("clipboard.write_text", {"text": "safe"})["state"], "FAILED")


if __name__ == "__main__":
    unittest.main()
