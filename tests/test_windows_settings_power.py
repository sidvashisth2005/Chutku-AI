from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime


class WindowsSettingsPowerTests(unittest.TestCase):
    def test_theme_change_is_reviewed_verified_and_restorable(self):
        light = {"apps": "light", "system": "light"}; dark = {"apps": "dark", "system": "dark"}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("settings.theme_status", {})["state"], "DENIED")
            runtime.capability_grants.grant("settings.observe")
            with patch("chutku.tools.windows_settings._invoke", return_value=light):
                self.assertEqual(runtime.run("settings.theme_status", {})["state"], "COMPLETED")
            runtime.capability_grants.grant("settings.modify")
            pending = runtime.run("settings.theme_set", {"mode": "dark"})
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.windows_settings._invoke", side_effect=[light, dark]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")
            pending = runtime.run("settings.theme_restore", {})
            with patch("chutku.tools.windows_settings._invoke", side_effect=[dark, light]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")

    def test_theme_restore_refuses_newer_state(self):
        light = {"apps": "light", "system": "light"}; dark = {"apps": "dark", "system": "dark"}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("settings.modify")
            pending = runtime.run("settings.theme_set", {"mode": "dark"})
            with patch("chutku.tools.windows_settings._invoke", side_effect=[light, dark]):
                runtime.approve(pending["approval"]["token"])
            pending = runtime.run("settings.theme_restore", {})
            mixed = {"apps": "light", "system": "dark"}
            with patch("chutku.tools.windows_settings._invoke", return_value=mixed):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "FAILED")

    def test_power_requires_capability_review_delay_and_exact_phrase(self):
        valid = {"mode": "shutdown", "delay_seconds": 300, "confirmation_phrase": "SHUT DOWN THIS PC"}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("power.schedule", valid)["state"], "DENIED")
            runtime.capability_grants.grant("power.control")
            for bad in ({**valid, "delay_seconds": 10}, {**valid, "confirmation_phrase": "yes"},
                        {**valid, "mode": "restart"}):
                self.assertEqual(runtime.run("power.schedule", bad)["state"], "FAILED")
            pending = runtime.run("power.schedule", valid)
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.power_controls._command", return_value=0):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")

    def test_power_cancel_requires_record_and_proves_no_schedule(self):
        valid = {"mode": "restart", "delay_seconds": 600, "confirmation_phrase": "RESTART THIS PC"}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("power.control")
            pending = runtime.run("power.cancel", {})
            with patch("chutku.tools.power_controls._command") as command:
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "FAILED")
                command.assert_not_called()
            pending = runtime.run("power.schedule", valid)
            with patch("chutku.tools.power_controls._command", return_value=0):
                runtime.approve(pending["approval"]["token"])
            pending = runtime.run("power.cancel", {})
            with patch("chutku.tools.power_controls._command", side_effect=[0, 1190]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
