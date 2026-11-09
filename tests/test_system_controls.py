from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime


class SystemControlTests(unittest.TestCase):
    def test_volume_observe_has_separate_exact_capability(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("system.volume_status", {})["state"], "DENIED")
            runtime.capability_grants.grant("audio.observe")
            with patch("chutku.tools.system_controls._volume_call", return_value={"level": 42, "muted": False}):
                result = runtime.run("system.volume_status", {})
            self.assertEqual(result["state"], "COMPLETED")

    def test_volume_uses_direct_audio_call_then_powershell_fallback_and_fails_closed(self):
        from chutku.tools import system_controls
        with patch("chutku.tools.audio_output.master_volume", return_value={"level": 30, "muted": False}) as direct,                 patch.object(system_controls, "_powershell") as slow:
            self.assertEqual(system_controls._volume_call({"action": "set", "level": 30, "muted": False}),
                             {"level": 30, "muted": False})
            direct.assert_called_once_with(level=30, muted=False)
            slow.assert_not_called()
        with patch("chutku.tools.audio_output.master_volume", side_effect=OSError("no device")),                 patch.object(system_controls, "_powershell", return_value={"level": 30, "muted": False}) as slow:
            self.assertEqual(system_controls._volume_call({"action": "get"}), {"level": 30, "muted": False})
            slow.assert_called_once()
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("audio.observe")
            with patch("chutku.tools.audio_output.master_volume", side_effect=OSError("no device")),                     patch.object(system_controls, "_powershell", side_effect=OSError("query failed")):
                self.assertEqual(runtime.run("system.volume_status", {})["state"], "FAILED")

    def test_volume_change_requires_modify_review_and_conflict_aware_restore(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            args = {"level": 41, "muted": False}
            self.assertEqual(runtime.run("system.volume_set", args)["state"], "DENIED")
            runtime.capability_grants.grant("audio.modify")
            pending = runtime.run("system.volume_set", args)
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.system_controls._volume_call",
                       side_effect=[{"level": 42, "muted": False}, args]):
                changed = runtime.approve(pending["approval"]["token"])
            self.assertEqual(changed["state"], "COMPLETED")
            pending = runtime.run("system.volume_restore", {})
            with patch("chutku.tools.system_controls._volume_call",
                       side_effect=[args, {"level": 42, "muted": False}]):
                restored = runtime.approve(pending["approval"]["token"])
            self.assertEqual(restored["state"], "COMPLETED")

    def test_restore_refuses_newer_volume_and_network_is_bounded(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("audio.modify")
            pending = runtime.run("system.volume_set", {"level": 40, "muted": False})
            with patch("chutku.tools.system_controls._volume_call",
                       side_effect=[{"level": 42, "muted": False}, {"level": 40, "muted": False}]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")
            pending = runtime.run("system.volume_restore", {})
            with patch("chutku.tools.system_controls._volume_call", return_value={"level": 39, "muted": False}):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "FAILED")
            self.assertEqual(runtime.run("network.status", {})["state"], "DENIED")
            runtime.capability_grants.grant("network.observe")
            adapter = {"Name": "Wi-Fi", "InterfaceDescription": "Fixture", "InterfaceIndex": 1,
                       "Status": "Up", "MacAddress": "00-00-00-00-00-00", "LinkSpeed": "1 Gbps"}
            with patch("chutku.tools.system_controls._powershell", return_value=[adapter]):
                self.assertEqual(runtime.run("network.status", {})["state"], "COMPLETED")

    def test_invalid_volume_fails_before_windows_adapter(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("audio.modify")
            with patch("chutku.tools.system_controls._powershell") as invoke:
                for args in ({"level": 101, "muted": False}, {"level": True, "muted": False},
                             {"level": 50}, {"level": 50, "muted": 0}):
                    self.assertEqual(runtime.run("system.volume_set", args)["state"], "FAILED")
                invoke.assert_not_called()

    def test_network_change_requires_exact_identity_review_and_restore(self):
        identity = {"interface_index": 7, "name": "Wi-Fi", "interface_description": "Fixture adapter"}
        before = {**identity, "enabled": True, "status": "Up"}
        after = {**identity, "enabled": False, "status": "Disabled"}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            args = {**identity, "enabled": False}
            self.assertEqual(runtime.run("network.adapter_set", args)["state"], "DENIED")
            runtime.capability_grants.grant("network.modify")
            pending = runtime.run("network.adapter_set", args)
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.system_controls._powershell", side_effect=[before, after]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")
            pending = runtime.run("network.adapter_restore", {})
            with patch("chutku.tools.system_controls._powershell", side_effect=[after, before]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")

    def test_network_change_fails_closed_on_identity_or_newer_state(self):
        identity = {"interface_index": 7, "name": "Wi-Fi", "interface_description": "Fixture adapter"}
        before = {**identity, "enabled": True, "status": "Up"}
        after = {**identity, "enabled": False, "status": "Disabled"}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("network.modify")
            pending = runtime.run("network.adapter_set", {**identity, "enabled": False})
            changed_identity = {**before, "name": "Other"}
            with patch("chutku.tools.system_controls._powershell", return_value=changed_identity):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "FAILED")
            pending = runtime.run("network.adapter_set", {**identity, "enabled": False})
            with patch("chutku.tools.system_controls._powershell", side_effect=[before, after]):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")
            pending = runtime.run("network.adapter_restore", {})
            newer = {**identity, "enabled": True, "status": "Disconnected"}
            with patch("chutku.tools.system_controls._powershell", return_value=newer):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "FAILED")


    def test_bluetooth_status_and_switch_read_back_and_fail_closed(self):
        """Owner's convos 2026-11-10: Bluetooth had no tool; on/off/devices were asked about instead."""
        from chutku.tools import system_controls
        phone = {"name": "Redmi Note 12 Pro 5G", "connected": False}
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("system.bluetooth_status", {})["state"], "DENIED")
            runtime.capability_grants.grant("settings.observe")
            runtime.capability_grants.grant("settings.modify")
            twice = {"present": True, "on": False, "devices": [phone, phone | {"connected": True}]}
            with patch.object(system_controls, "_powershell", return_value=twice):
                out = runtime.run("system.bluetooth_status", {})
            self.assertEqual(out["output"], {"on": False, "devices": [{"name": phone["name"], "connected": True}]})
            pending = runtime.run("system.bluetooth_set", {"on": True})
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch.object(system_controls, "_powershell", return_value={"present": True, "on": True, "devices": []}):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")
            pending = runtime.run("system.bluetooth_set", {"on": True})
            with patch.object(system_controls, "_powershell",    # Windows refused: the read-back says off
                              return_value={"present": True, "on": False, "access": "DeniedByUser", "devices": []}):
                done = runtime.approve(pending["approval"]["token"])
            self.assertEqual(done["state"], "FAILED")
            self.assertIn("DeniedByUser", done["output"]["error"])
            with patch.object(system_controls, "_powershell", return_value={"present": False}):
                self.assertEqual(runtime.run("system.bluetooth_status", {})["state"], "FAILED")   # no radio
            with self.assertRaises(ValueError):
                runtime.registry.get("system.bluetooth_set").validate_arguments({"on": "yes"})


if __name__ == "__main__":
    unittest.main()
