"""WA1 (owner 2026-11-08): never refuse except system damage; app folders ask the first time; ask-once memory with
its limits. Runs on Linux by pointing the Windows folders at a temporary tree."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from chutku import approval_memory
from chutku.core import paths
from chutku.policy.kernel import Decision, PolicyKernel
from chutku.runtime import Runtime
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


def tool(name, risk=Risk.DATA_MODIFICATION, **extra):
    return Tool(name, name, risk, lambda a, c: ToolResult({}, Verification.PASS), **extra)


class Tree(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for d in ("Windows/System32", "Program Files/App", "ProgramData/App", "Users/me/AppData/Local/App",
                  "Users/me/Documents", "Users/me/AppData/Local/Chutku/sandbox"):
            (self.root / d).mkdir(parents=True)
        env = {"SystemRoot": str(self.root / "Windows"), "windir": str(self.root / "Windows"),
               "ProgramFiles": str(self.root / "Program Files"), "ProgramData": str(self.root / "ProgramData"),
               "USERPROFILE": str(self.root / "Users/me"), "CHUTKU_HOME": str(self.root / "Users/me/AppData/Local/Chutku")}
        temp_folder = self.root / "Users/me/AppData/Local/Temp"
        temp_folder.mkdir()
        for p in (patch.dict(os.environ, env), patch.object(paths, "appdata_root",
                                                            return_value=str(self.root / "Users/me/AppData")),
                  patch.object(paths.tempfile, "gettempdir", return_value=str(temp_folder))):
            p.start()
            self.addCleanup(p.stop)

    def at(self, rel):
        return self.root / rel


class DamageListTests(Tree):
    def test_system_damage_is_refused_in_every_form(self):
        for rel, op in (("Windows/System32/drivers/x.sys", "write"), ("Windows/notepad.exe", "delete"),
                        ("Program Files/App", "delete"), ("Program Files/App/app.exe", "move"),
                        ("ProgramData/App", "delete"), ("Users/me/AppData/Local/Chutku/data/capability_grants.db", "write")):
            self.assertTrue(paths.system_damage(self.at(rel), op), (rel, op))
        self.assertTrue(paths.system_damage(paths.CODE_ROOT / "chutku" / "policy" / "kernel.py", "write"))

    def test_app_folders_are_not_damage_but_ask_and_the_users_own_files_do_neither(self):
        for rel in ("Program Files/App/settings.ini", "ProgramData/App/config.json", "Users/me/AppData/Local/App/x.cfg"):
            self.assertIsNone(paths.system_damage(self.at(rel), "write"), rel)
            self.assertTrue(paths.sensitive_reason(self.at(rel)), rel)
        for rel in ("Users/me/Documents/notes.txt", "Users/me/AppData/Local/Chutku/sandbox/a.txt",
                    "Users/me/AppData/Local/Temp/scratch.txt"):
            self.assertIsNone(paths.system_damage(self.at(rel), "delete"), rel)
            self.assertIsNone(paths.sensitive_reason(self.at(rel)), rel)

    def test_damaging_commands_are_refused_and_ordinary_ones_pass(self):
        for bad in ("format C: /q", "bcdedit /set {current} safeboot minimal", "diskpart",
                    r"Remove-Item C:\Windows\System32\drivers -Recurse -Force", r"del /f /q %SystemRoot%\x.dll",
                    r"reg delete HKLM\SYSTEM\CurrentControlSet\Services\x /f", "Set-MpPreference -DisableRealtimeMonitoring $true",
                    "netsh advfirewall set allprofiles state off", r"takeown /f C:\Windows\System32\x.dll",
                    r"Remove-ItemProperty -Path HKLM:\SOFTWARE\x -Name y", "Format-Volume -DriveLetter D"):
            self.assertTrue(paths.damage_in_text(bad), bad)
        for fine in (r"Get-ChildItem C:\Windows", r"Set-ItemProperty HKCU:\Software\x -Name y -Value 1",
                     r"Remove-Item C:\Users\me\Downloads\old.txt", "Get-Service", "winget list"):
            self.assertIsNone(paths.damage_in_text(fine), fine)

    def test_the_runtime_refuses_damage_by_text_and_asks_for_app_folders(self):
        fake = SimpleNamespace(granted_root=self.root, MOVE_TOOLS=Runtime.MOVE_TOOLS)
        powershell = tool("system.powershell", Risk.DESTRUCTIVE_OR_PRIVILEGED, runs_code=True)
        self.assertTrue(Runtime.protected_target(fake, powershell, {"command": "bcdedit /deletevalue x"}))
        self.assertIsNone(Runtime.protected_target(fake, powershell, {"command": "Get-Date"}))

    @unittest.skipUnless(os.name == "nt", "sandbox_target takes Windows paths")
    def test_the_runtime_asks_for_app_folders_and_refuses_windows(self):
        fake = SimpleNamespace(granted_root=self.root, MOVE_TOOLS=Runtime.MOVE_TOOLS)
        write = tool("filesystem.write_text", resource_access="modify")
        target = str(self.at("Program Files/App/settings.ini"))
        self.assertIsNone(Runtime.protected_target(fake, write, {"path": target}))
        self.assertTrue(Runtime.sensitive_question(fake, write, {"path": target}))
        self.assertTrue(Runtime.protected_target(fake, write, {"path": str(self.at("Windows/win.ini"))}))


class KernelTests(unittest.TestCase):
    def test_a_first_time_question_asks_even_for_a_typed_command(self):
        kernel, step = PolicyKernel(), tool("filesystem.write_text")
        asked = kernel.authorize(step, {}, owner_question="This changes an installed app's own files")
        self.assertEqual(asked.decision, Decision.CONFIRM)
        self.assertEqual(kernel.authorize(step, {}, True, owner_question="x").decision, Decision.ALLOW)
        self.assertEqual(kernel.authorize(step, {}, protected_reason="Windows' own folder").decision, Decision.DENY)


class AskOnceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = temp.name
        self.step = {"tool": "settings.change", "arguments": {"path": "C:/X/a.ini"}, "purpose": "Change a setting"}
        self.tool = tool("settings.change")

    def test_remembered_after_yes_always_then_allowed_for_the_same_step_only(self):
        self.assertFalse(approval_memory.allows(self.base, self.step, self.tool, tainted=False, origin="text"))
        self.assertTrue(approval_memory.remember(self.base, self.step, self.tool, tainted=False, origin="text"))
        same = {**self.step, "arguments": {"path": r"c:\x\A.INI "}}             # the same target, written differently
        self.assertTrue(approval_memory.allows(self.base, same, self.tool, tainted=False, origin="text"))
        other = {**self.step, "arguments": {"path": "C:/X/b.ini"}}              # a different target asks again
        self.assertFalse(approval_memory.allows(self.base, other, self.tool, tainted=False, origin="text"))

    def test_the_limits(self):
        approval_memory.remember(self.base, self.step, self.tool, tainted=False, origin="text")
        self.assertFalse(approval_memory.allows(self.base, self.step, self.tool, tainted=True, origin="text"))   # taint
        deleting = tool("filesystem.recycle", deletes=True)
        self.assertFalse(approval_memory.remember(self.base, {"tool": "filesystem.recycle", "arguments": {}}, deleting,
                                                  tainted=False, origin="text"))                                  # deletes
        power = tool("power.schedule", Risk.DESTRUCTIVE_OR_PRIVILEGED)
        self.assertFalse(approval_memory.eligible(power, tainted=False, origin="text"))                          # R4
        powershell = tool("system.powershell", Risk.DESTRUCTIVE_OR_PRIVILEGED, runs_code=True)
        self.assertTrue(approval_memory.eligible(powershell, tainted=False, origin="text"))   # the owner's exact text
        command = {"tool": "system.powershell", "arguments": {"command": "Get-Date"}}
        approval_memory.remember(self.base, command, powershell, tainted=False, origin="text")
        for origin in ("phone", "telegram"):                     # laptop-only: still waits for the laptop
            self.assertFalse(approval_memory.allows(self.base, command, powershell, tainted=False, origin=origin))
        self.assertFalse(approval_memory.remember(self.base, self.step, self.tool, tainted=False, origin="phone"))

    def test_unused_entries_expire_and_settings_can_forget(self):
        approval_memory.remember(self.base, self.step, self.tool, tainted=False, origin="text", now=1000.0)
        late = 1000.0 + approval_memory.EXPIRE_SECONDS + 1
        self.assertFalse(approval_memory.allows(self.base, self.step, self.tool, tainted=False, origin="text", now=late))
        approval_memory.remember(self.base, self.step, self.tool, tainted=False, origin="text")
        [entry] = approval_memory.entries(self.base)
        self.assertEqual(approval_memory.forget(self.base, entry["id"]), [])
        with self.assertRaises(ValueError):
            approval_memory.forget(self.base, entry["id"])


if __name__ == "__main__":
    unittest.main()
