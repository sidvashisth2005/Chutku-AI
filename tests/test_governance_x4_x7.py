"""Phase 6 X4 (windows.snap), X6 (CPU temperature + network in system.performance) and X7 (system.powershell).

No test touches a real window, WMI or PowerShell: ctypes helpers, the PowerShell query and subprocess are faked.
"""
import base64
import contextlib
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.tools import desktop_controls, documents, everyday
from chutku.tools.registry import Verification
from tests.test_agent_loop import ScriptedPlanner, proposal, step

WORK = (0, 0, 1920, 1040)
BORDER = 7   # Windows 11 invisible resize border (left, right, bottom; none on top)


class _FakeUser32:
    def __init__(self, zoomed=False, iconic=False, obeys=True):
        self.zoomed, self.iconic, self.obeys = zoomed, iconic, obeys
        self.calls = []
        self.rect = (100 - BORDER, 100, 900 + BORDER, 700 + BORDER)

    def IsZoomed(self, _hwnd):
        return self.zoomed

    def IsIconic(self, _hwnd):
        return self.iconic

    def ShowWindowAsync(self, _hwnd, command):
        self.calls.append(("show", command))
        if command == 9:
            self.zoomed = self.iconic = False
        elif command == 3:
            self.zoomed = True
        return True

    def SetWindowPos(self, _hwnd, _after, x, y, cx, cy, flags):
        self.calls.append(("pos", (x, y, x + cx, y + cy), flags))
        if self.obeys:
            self.rect = (x, y, x + cx, y + cy)
        return True


class _FakeDesktop:
    def __init__(self, u, exists=True):
        self.u, self.exists = u, exists

    def exact(self, window_id, process_id, executable):
        return {"window_id": window_id} if self.exists else None


def _visible(_hwnd, outer):
    return outer[0] + BORDER, outer[1], outer[2] - BORDER, outer[3] - BORDER


class SnapTests(unittest.TestCase):
    ARGS = {"window_id": 42, "process_id": 7, "executable": r"C:\Windows\notepad.exe"}

    def snap(self, position, u, exists=True):
        desktop = _FakeDesktop(u, exists)
        with patch.object(everyday, "Desktop", lambda: desktop), \
                patch.object(everyday, "_work_area", lambda _d, _h: WORK), \
                patch.object(everyday, "_window_rect", lambda _d, _h: u.rect), \
                patch.object(everyday, "_visible_rect", _visible), \
                patch.object(everyday, "_wait", lambda check, seconds=2.0: bool(check())), \
                patch("chutku.vision.dpi_aware", contextlib.nullcontext):
            return everyday._snap(dict(self.ARGS, position=position), None)

    def test_rectangles_for_every_position(self):
        expected = {"left": (0, 0, 960, 1040), "right": (960, 0, 1920, 1040), "top": (0, 0, 1920, 520),
                    "bottom": (0, 520, 1920, 1040), "top_left": (0, 0, 960, 520), "top_right": (960, 0, 1920, 520),
                    "bottom_left": (0, 520, 960, 1040), "bottom_right": (960, 520, 1920, 1040)}
        for position, rect in expected.items():
            self.assertEqual(everyday.snap_rect(position, WORK, (800, 600)), rect, position)
        self.assertEqual(everyday.snap_rect("center", WORK, (800, 600)), (560, 220, 1360, 820))
        self.assertEqual(everyday.snap_rect("center", WORK, (3000, 2000)), WORK)   # never bigger than the screen
        # A second monitor left of the main one, with its taskbar on top.
        self.assertEqual(everyday.snap_rect("right", (-1920, 40, 0, 1080), (1, 1)), (-960, 40, 0, 1080))

    def test_snaps_left_with_the_invisible_border_and_reads_it_back(self):
        u = _FakeUser32()
        result = self.snap("left", u)
        self.assertEqual(result.verification, Verification.PASS)
        _, rect, flags = u.calls[-1]
        self.assertEqual(rect, (-BORDER, 0, 960 + BORDER, 1040 + BORDER))   # the visible frame lands on 0..960
        self.assertEqual(flags & 0x0010, 0x0010)   # SWP_NOACTIVATE: snapping never steals focus
        self.assertEqual(result.output["observed_rect"], list(rect))

    def test_a_maximized_window_is_restored_before_moving(self):
        u = _FakeUser32(zoomed=True)
        result = self.snap("bottom_right", u)
        self.assertEqual(result.verification, Verification.PASS)
        self.assertEqual(u.calls[0], ("show", 9))
        self.assertEqual(u.calls[1][0], "pos")

    def test_maximize_uses_windows_own_maximize(self):
        u = _FakeUser32()
        result = self.snap("maximize", u)
        self.assertEqual(result.verification, Verification.PASS)
        self.assertEqual(u.calls, [("show", 3)])

    def test_a_window_that_does_not_move_is_not_reported_as_snapped(self):
        u = _FakeUser32(obeys=False)
        result = self.snap("right", u)
        self.assertEqual(result.verification, Verification.UNKNOWN)
        self.assertFalse(result.output["state_observed"])
        self.assertIn("error", result.output)

    def test_a_gone_window_moves_nothing(self):
        u = _FakeUser32()
        result = self.snap("left", u, exists=False)
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertEqual(u.calls, [])

    def test_arguments_are_exact(self):
        for bad in ({"position": "left"}, dict(self.ARGS, position="diagonal"),
                    dict(self.ARGS, position="left", extra=1), dict(self.ARGS, window_id="42", position="left")):
            with self.assertRaises(ValueError):
                everyday._validate_snap(bad)
        everyday._validate_snap(dict(self.ARGS, position="top_left"))


class TelemetryTests(unittest.TestCase):
    def test_missing_cpu_temperature_is_said_honestly(self):
        with patch.object(everyday, "_powershell", return_value={"cpu_c": None, "network": None}):
            out = desktop_controls._telemetry()
        self.assertIsNone(out["cpu_temperature_c"])
        self.assertEqual(out["cpu_temperature_note"], "CPU temperature isn't exposed on this PC without admin.")
        for error in (OSError("no"), subprocess.TimeoutExpired("powershell", 10)):
            with patch.object(everyday, "_powershell", side_effect=error):
                self.assertIn("cpu_temperature_note", desktop_controls._telemetry())

    def test_reported_temperature_and_network(self):
        found = {"cpu_c": 51.4, "network": {"down_mbps": 12.5, "up_mbps": 0.8}}
        with patch.object(everyday, "_powershell", return_value=found):
            out = desktop_controls._telemetry()
        self.assertEqual(out, {"cpu_temperature_c": 51.4, "network_mbps": {"down_mbps": 12.5, "up_mbps": 0.8}})

    def test_performance_output_gains_the_fields(self):
        def query(script, _request, timeout=12):
            if script is desktop_controls._TELEMETRY:
                return {"cpu_c": None, "network": {"down_mbps": 1.0, "up_mbps": 0.1}}
            return [{"name": "Code", "memory_mib": 900}]
        with patch.object(everyday, "_powershell", query), patch.object(desktop_controls, "_cpu_percent", lambda: 5.0), \
                patch.object(desktop_controls.subprocess, "run", side_effect=OSError("no nvidia-smi")):
            out = desktop_controls._performance({}, None).output
        self.assertEqual(out["cpu_percent"], 5.0)
        self.assertIsNone(out["cpu_temperature_c"])
        self.assertIn("without admin", out["cpu_temperature_note"])
        self.assertEqual(out["network_mbps"]["down_mbps"], 1.0)
        self.assertEqual(out["top_memory_processes"], [{"name": "Code", "memory_mib": 900}])

    def test_spoken_answer(self):
        from chutku.quick_intents import QUICK_ANSWERS
        base = {"cpu_percent": 9, "memory": {"used_percent": 50, "used_gib": 8, "total_gib": 16}}
        hot = QUICK_ANSWERS["system.performance"](dict(base, cpu_temperature_c=93.2,
                                                      network_mbps={"down_mbps": 12.5, "up_mbps": 0.8}))
        self.assertIn("CPU 9% at 93°C", hot)
        self.assertIn("network 12.5 Mbps down, 0.8 up", hot)
        self.assertIn("CPU is hot", hot)
        missing = QUICK_ANSWERS["system.performance"](dict(base, cpu_temperature_c=None,
                                                          cpu_temperature_note=desktop_controls.CPU_TEMP_MISSING))
        self.assertIn("isn't exposed on this PC without admin", missing)
        self.assertNotIn("°C", missing)


class _FakeSubprocess:
    TimeoutExpired, DEVNULL, CREATE_NO_WINDOW = subprocess.TimeoutExpired, subprocess.DEVNULL, 0x08000000

    def __init__(self, stdout="hello\n", returncode=0, timeout=False):
        self.calls, self.stdout, self.returncode, self.timeout = [], stdout, returncode, timeout

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, 60)
        return types.SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


class PowerShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "mind")
        self.mind_root.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")
        self.runtime.capability_grants.grant("process.launch")
        self.fake = _FakeSubprocess()
        self.sub = patch.object(documents, "subprocess", self.fake)
        self.sub.start()

    def tearDown(self):
        import chutku.agent_loop as loop
        loop._RECENT_APPROVALS.clear()
        self.sub.stop()
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def test_declared_r4_runs_code_and_untrusted(self):
        from chutku.agent_loop import PRIVATE_TOOLS, TAINTING_TOOLS
        from chutku.reflex import _eligible_tool
        tool = self.runtime.registry.get("system.powershell")
        self.assertEqual(int(tool.base_risk), 4)
        self.assertTrue(tool.runs_code)
        self.assertEqual(tool.required_capability, "process.launch")
        self.assertIn("system.powershell", TAINTING_TOOLS)
        self.assertIn("system.powershell", PRIVATE_TOOLS)
        self.assertFalse(_eligible_tool(tool))   # never compiled into a reflex

    def test_stops_for_a_click_in_every_mode(self):
        for mode in ("owner", "auto_edits", "auto_safe", "review"):
            result = self.runtime.run("system.powershell", {"command": "Get-Date"}, provenance="delegated",
                                      autonomy=mode, tainted=False, exposed=False)
            self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION", mode)
            self.runtime.approve(result["approval"]["token"], cancel=True)   # deny it: nothing runs
        direct = self.runtime.run("system.powershell", {"command": "Get-Date"})
        self.assertEqual(str(direct["state"]), "WAITING_CONFIRMATION")
        self.assertEqual(str(self.runtime.approve(direct["approval"]["token"], cancel=True)["state"]), "DENIED")
        self.assertEqual(self.fake.calls, [])

    def test_bad_commands_are_refused_before_anything_runs(self):
        for command in ("Get-Date\nRemove-Item x", "a\rb", "a\tb", "a\u2028b", "a\x00b", "x" * 501, "", "   "):
            result = self.runtime.run("system.powershell", {"command": command}, provenance="delegated",
                                      autonomy="owner", tainted=False, exposed=False)
            self.assertNotIn(str(result["state"]), {"WAITING_CONFIRMATION", "COMPLETED"}, repr(command[:20]))
        result = self.runtime.run("system.powershell", {"command": "Get-Date", "cwd": "C:\\"})
        self.assertNotIn(str(result["state"]), {"WAITING_CONFIRMATION", "COMPLETED"})
        self.assertEqual(self.fake.calls, [])

    def test_after_the_click_it_runs_exactly_that_command(self):
        command = "Get-ChildItem 'C:\\x y' | Select-Object -First 1 \"Name\""
        pending = self.runtime.run("system.powershell", {"command": command}, provenance="delegated",
                                   autonomy="owner", tainted=False, exposed=False)
        result = self.runtime.approve(pending["approval"]["token"])
        self.assertEqual(str(result["state"]), "COMPLETED")
        self.assertEqual(result["output"]["stdout"], "hello\n")
        self.assertEqual(result["output"]["provenance"], "external_untrusted")
        (argv, kwargs), = self.fake.calls
        self.assertTrue(argv[0].casefold().endswith("powershell.exe"))
        self.assertEqual(argv[1:4], ["-NoProfile", "-NonInteractive", "-EncodedCommand"])
        script = base64.b64decode(argv[4]).decode("utf-16-le")
        self.assertTrue(script.endswith("\n" + command))
        self.assertEqual(kwargs["timeout"], 60)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_output_is_truncated_and_failures_are_failures(self):
        self.fake.stdout, self.fake.returncode = "x" * 20000, 1
        result = documents._powershell_command({"command": "Get-Date"}, None)
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertEqual(len(result.output["stdout"]), documents.OUTPUT_CHARS)
        self.assertTrue(result.output["truncated"])
        self.assertEqual(result.audit_output["stdout"], "[REDACTED]")
        self.fake.timeout = True
        self.assertEqual(documents._powershell_command({"command": "Start-Sleep 90"}, None).verification,
                         Verification.FAIL)

    def test_an_approval_is_not_reused_by_a_later_request(self):
        from chutku.agent_loop import AgentSession
        first = AgentSession("run Get-Date in powershell", mode="owner")
        snap = first.advance(self.runtime, ScriptedPlanner(proposal(steps=[step("system.powershell",
                                                                                command="Get-Date")])))
        self.assertEqual(snap["status"], "waiting_confirmation")
        first.decide(self.runtime, approve=True)
        self.assertEqual(len(self.fake.calls), 1)
        again = AgentSession("run Get-Date in powershell", mode="owner")   # e.g. a scheduled task, same command
        snap = again.advance(self.runtime, ScriptedPlanner(proposal(steps=[step("system.powershell",
                                                                                command="Get-Date")])))
        self.assertEqual(snap["status"], "waiting_confirmation")
        self.assertEqual(len(self.fake.calls), 1)   # still only the first, clicked run

    def test_the_planner_cannot_pick_it_unless_a_command_was_asked_for(self):
        from chutku.agent_loop import AgentSession
        session = AgentSession("what is my ip address", mode="owner")
        snap = session.advance(self.runtime, ScriptedPlanner(
            proposal(steps=[step("system.powershell", command="ipconfig")]),
            proposal(steps=[step("system.powershell", command="ipconfig")]),
            proposal("clarify", reply="No.")))
        self.assertNotEqual(snap["status"], "waiting_confirmation")
        self.assertEqual(self.fake.calls, [])


class ContractTests(unittest.TestCase):
    def test_new_tools_and_unchanged_performance_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = create_runtime(Path(temp) / "state")
            try:
                snap, manage = runtime.registry.get("windows.snap"), runtime.registry.get("windows.manage")
                self.assertEqual(snap.base_risk, manage.base_risk)
                self.assertEqual(snap.required_capability, manage.required_capability)
                for key in ("window_id", "process_id", "executable"):
                    self.assertEqual(snap.argument_schema["properties"][key], manage.argument_schema["properties"][key])
                self.assertEqual(runtime.registry.get("system.performance").description,
                                 "Show CPU %, RAM, GPU load/memory/temperature, battery and the programs using the "
                                 "most memory.")
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
