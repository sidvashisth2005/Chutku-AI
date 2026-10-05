import unittest
from types import SimpleNamespace
from unittest.mock import patch

from chutku import autostart


class AutostartTests(unittest.TestCase):
    def test_sign_in_task_runs_with_normal_rights_from_the_project_folder(self):
        scripts = []

        def fake(script):
            scripts.append(script)
            return SimpleNamespace(returncode=0, stdout="Ready", stderr="")
        with patch.object(autostart, "_ps", side_effect=fake), patch.object(autostart, "_LEGACY") as legacy:
            legacy.is_file.return_value = False
            result = autostart.enable()
        register = scripts[0]
        self.assertIn("-AtLogOn", register)
        self.assertIn("-RunLevel Limited", register)
        self.assertNotIn("Highest", register)
        self.assertIn("-WorkingDirectory", register)
        self.assertIn("chutku.guard", register)
        self.assertIn(r"-TaskPath '\Chutku\'", register)
        legacy.unlink.assert_called_once()  # the old Startup-folder entry is removed
        self.assertTrue(result["autostart"])

    def test_failure_is_reported_not_hidden(self):
        with patch.object(autostart, "_ps", return_value=SimpleNamespace(returncode=1, stdout="", stderr="Access is denied")):
            with self.assertRaisesRegex(OSError, "Access is denied"):
                autostart.enable()


if __name__ == "__main__":
    unittest.main()
