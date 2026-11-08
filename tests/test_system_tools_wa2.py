"""WA2: system tools on fakes (registry, winget/powercfg, the elevation broker). Nothing here touches Windows."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from chutku import elevate, system_journal
from chutku.tools import system_tools as st
from chutku.tools.registry import ToolRegistry, Verification


class FakeReg:
    def __init__(self):
        self.data = {}

    def get(self, path, name):
        return self.data.get((path, name))

    def set(self, path, name, value, kind):
        self.data[(path, name)] = {"value": value, "type": kind}

    def delete(self, path, name):
        self.data.pop((path, name), None)

    def names(self, path):
        return [(n, bytes.fromhex(v["value"]) if v["type"] == "binary" else v["value"])
                for (p, n), v in self.data.items() if p == path]


class Base(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        (self.base / "sandbox").mkdir()
        self.context = SimpleNamespace(granted_root=self.base / "sandbox")
        self.reg, self.runs, self.elevated = FakeReg(), [], []
        self.answers = {}
        for name, value in (("REG", self.reg), ("RUN", self.run_fake), ("ELEVATE", self.elevate_fake)):
            p = patch.object(st, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.registry = ToolRegistry()
        st.register_system_tools(self.registry)

    def run_fake(self, argv, timeout=600):
        self.runs.append(argv)
        for key, answer in self.answers.items():
            if key in " ".join(argv):
                return answer() if callable(answer) else answer
        return 0, ""

    def elevate_fake(self, argv):
        self.elevated.append(argv)
        return 0, ""

    def tool(self, name, arguments):
        tool = self.registry.get(name)
        tool.validate_arguments(arguments)
        return tool.execute(arguments, self.context)


class SettingsAndRegistryTests(Base):
    def test_a_setting_is_read_back_journaled_and_undone(self):
        self.reg.set(st.ADVANCED, "HideFileExt", 1, "dword")
        result = self.tool("settings.set", {"name": "file_extensions", "value": "show"})
        self.assertEqual(result.verification, Verification.PASS, result.output)
        self.assertEqual(self.reg.get(st.ADVANCED, "HideFileExt")["value"], 0)
        entry = system_journal.last(self.base)
        self.assertEqual((entry["kind"], entry["before"], entry["after"]), ("setting", 1, 0))
        self.assertEqual(self.tool("system.undo_last", {}).verification, Verification.PASS)
        self.assertEqual(self.reg.get(st.ADVANCED, "HideFileExt")["value"], 1)
        self.assertIsNone(system_journal.last(self.base))
        self.assertEqual(self.tool("system.undo_last", {}).verification, Verification.FAIL)   # nothing left
        with self.assertRaises(ValueError):
            self.tool("settings.set", {"name": "file_extensions", "value": "purple"})

    def test_power_plan_through_powercfg(self):
        plan = ["381b4222-f694-41f0-9685-ff5bb260df2e"]
        self.answers = {"/getactivescheme": lambda: (0, f"Power Scheme GUID: {plan[0]}  (Balanced)"),
                        "/setactive": lambda: (plan.__setitem__(0, self.runs[-1][-1]), (0, ""))[1]}
        result = self.tool("settings.set", {"name": "power_plan", "value": "high_performance"})
        self.assertEqual(result.verification, Verification.PASS, result.output)
        self.assertEqual(plan[0], st.POWER_PLANS["high_performance"])

    def test_registry_only_your_own_software_keys(self):
        good = {"key": r"HKCU\Software\Chutku\Test", "name": "Level", "type": "dword", "value": 3}
        self.assertEqual(self.tool("registry.set_user", good).verification, Verification.PASS)
        self.assertEqual(self.reg.get(r"Software\Chutku\Test", "Level")["value"], 3)
        for bad in ({**good, "key": r"HKLM\SOFTWARE\x"}, {**good, "key": r"HKCU\Software\Policies\Microsoft\x"},
                    {**good, "key": r"HKCU\Software\Microsoft\Windows Defender"}, {**good, "key": r"HKCU\Software\..\x"},
                    {**good, "value": -1}, {**good, "type": "binary"}):
            with self.assertRaises(ValueError, msg=bad):
                self.tool("registry.set_user", bad)
        self.tool("system.undo_last", {})
        self.assertIsNone(self.reg.get(r"Software\Chutku\Test", "Level"))   # it did not exist before: removed


class StartupTests(Base):
    def test_listing_and_switching_off_like_task_manager(self):
        self.reg.set(st.RUN_KEY, "Discord", r"C:\x\Discord.exe", "string")
        listed = self.tool("startup.list", {})
        self.assertEqual(listed.output["apps"][0]["enabled"], True)
        self.assertEqual(self.tool("startup.toggle", {"name": "discord", "enabled": False}).verification,
                         Verification.PASS)
        self.assertEqual(self.reg.get(st.APPROVED, "Discord")["value"][:2], "03")
        self.assertFalse(self.tool("startup.list", {}).output["apps"][0]["enabled"])
        self.assertEqual(self.reg.get(st.RUN_KEY, "Discord")["value"], r"C:\x\Discord.exe")   # never deleted
        self.assertEqual(self.tool("startup.toggle", {"name": "nope", "enabled": True}).verification, Verification.FAIL)


class ServiceAndAppTests(Base):
    def services(self, status="Running", start="Manual"):
        return lambda: (0, json.dumps({"Name": "Spooler", "DisplayName": "Print Spooler", "Status": status,
                                       "StartType": start}))

    def test_a_service_change_goes_through_the_broker_and_security_services_are_refused(self):
        self.answers = {"Get-Service": self.services()}
        self.assertEqual(self.tool("services.set", {"name": "spooler", "action": "disabled"}).verification,
                         Verification.PASS)
        self.assertEqual(self.elevated, [["sc.exe", "config", "Spooler", "start=", "disabled"]])
        for name in ("WinDefend", "mpssvc", "EventLog"):
            result = self.tool("services.set", {"name": name, "action": "stop"})
            self.assertEqual(result.verification, Verification.FAIL)
        self.assertEqual(len(self.elevated), 1)                           # nothing more reached the broker
        self.tool("system.undo_last", {})
        self.assertIn(["sc.exe", "config", "Spooler", "start=", "demand"], self.elevated)

    def test_install_tries_per_user_first_and_undo_uninstalls(self):
        self.answers = {"--scope user": (-1978335212, "No applicable installer")}
        result = self.tool("apps.install", {"app": "VideoLAN.VLC"})
        self.assertEqual(result.output["scope"], "machine")
        self.assertIn("--scope", self.runs[0])
        self.assertNotIn("--scope", self.runs[1])
        self.tool("system.undo_last", {})
        self.assertEqual(self.runs[-1][:2], ["winget", "uninstall"])
        for bad in ("vlc; rm -rf", "", "a" * 90, "--source x"):
            with self.assertRaises(ValueError, msg=bad):
                self.tool("apps.install", {"app": bad})


class ElevationBrokerTests(unittest.TestCase):
    def test_one_program_through_runas_damage_first_and_a_no_is_reported(self):
        seen = []

        def launch(argv, **_):
            seen.append(argv)
            return SimpleNamespace(returncode=0, stderr="")
        code, _out = elevate.run(["sc.exe", "start", "Spooler"], launch=launch)
        self.assertEqual(code, 0)
        self.assertIn("-Verb RunAs", seen[0][-1])
        for bad in (["bcdedit", "/set", "x"], ["cmd", "/c", r"del C:\Windows\System32\x.dll"],
                    ["sc.exe", "start\nother"]):
            with self.assertRaises((elevate.ElevationRefused, ValueError)):
                elevate.run(bad, launch=launch)
        self.assertEqual(len(seen), 1)
        with self.assertRaises(elevate.ElevationRefused):
            elevate.run(["sc.exe", "stop", "Spooler"],
                        launch=lambda argv, **_: SimpleNamespace(returncode=1, stderr="The operation was canceled by the user."))

    def test_the_output_file_is_closed_and_removed(self):   # CI on Windows: an open mkstemp handle blocked the delete
        made = []
        real = elevate.tempfile.mkstemp

        def mkstemp(**kw):
            made.append(real(**kw))
            return made[-1]
        with patch.object(elevate.tempfile, "mkstemp", mkstemp), \
                patch.object(elevate.os, "close", wraps=elevate.os.close) as closed:
            elevate.run(["sc.exe", "start", "Spooler"], launch=lambda *a, **k: SimpleNamespace(returncode=0, stderr=""))
        closed.assert_called_once_with(made[0][0])
        self.assertFalse(Path(made[0][1]).exists())

    def test_elevated_and_removing_steps_are_never_remembered(self):
        from chutku import approval_memory
        registry = ToolRegistry()
        st.register_system_tools(registry)
        for name in ("services.set", "apps.uninstall"):
            self.assertFalse(approval_memory.eligible(registry.get(name), tainted=False, origin="text"), name)
        self.assertTrue(approval_memory.eligible(registry.get("settings.set"), tainted=False, origin="text"))



class ListTypedSchemaTests(unittest.TestCase):
    def test_a_list_typed_argument_does_not_crash_the_action_log(self):
        # PC live check 2026-11-08: registry.set_user's value is ["integer", "string"]; the action log raised
        # TypeError (unhashable list) after every run
        from chutku.core.paths import path_argument_names
        from chutku.tools.registry import Tool, Risk
        tool = Tool("x.y", "d", Risk.OBSERVATION, lambda a, c: None, argument_schema={"type": "object", "properties": {
            "value": {"type": ["integer", "string"]}, "path": {"type": ["string", "null"]}}})
        self.assertEqual(path_argument_names(tool), {"path"})

if __name__ == "__main__":
    unittest.main()
