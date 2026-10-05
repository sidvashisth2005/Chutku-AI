"""Compile a disposable WinForms fixture and real-verify UIA menu/value/select/scroll."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest
from chutku.tools.windows_apps import WindowsDesktop


def _compile(source, output):
    compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not compiler.is_file():
        compiler = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
    references = Path(r"C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.7.2")
    return compiler.is_file() and references.is_dir() and subprocess.run([
        str(compiler), "/nologo", "/target:winexe", f"/out:{output}",
        f"/reference:{references / 'PresentationFramework.dll'}",
        f"/reference:{references / 'PresentationCore.dll'}",
        f"/reference:{references / 'WindowsBase.dll'}",
        f"/reference:{references / 'System.Xaml.dll'}", str(source)],
        capture_output=True, timeout=30).returncode == 0


def _window_for_pid(pid):
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback, w.LPARAM]; user.EnumWindows.restype = w.BOOL
    user.IsWindowVisible.argtypes = [w.HWND]; user.IsWindowVisible.restype = w.BOOL
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    found = []
    @callback
    def collect(hwnd, _):
        current = w.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(current))
        if current.value == pid and user.IsWindowVisible(hwnd): found.append(int(hwnd))
        return True
    user.EnumWindows(collect, 0)
    return found[0] if len(found) == 1 else None


def _reviewed(runtime, tool, arguments):
    pending = runtime.run(tool, arguments)
    if str(pending.get("state")) != "WAITING_CONFIRMATION": return pending
    return runtime.approve(pending["approval"]["token"])


def main():
    checks = []; process = None; hwnd = None
    with tempfile.TemporaryDirectory(prefix="chutku-uia-fixture-") as temp:
        exe = Path(temp) / "ChutkuUiaFixture.exe"
        checks.append({"check": "fixture_compiled", "passed": _compile(
            PROJECT_ROOT / "tests/fixtures/UiaFixture.cs", exe) and exe.is_file()})
        try:
            if checks[-1]["passed"]:
                process = subprocess.Popen([str(exe)], cwd=temp)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and hwnd is None:
                    hwnd = _window_for_pid(process.pid); time.sleep(0.05)
                desktop = WindowsDesktop()
                if hwnd: desktop.focus(hwnd)
                identity = {"window_id": hwnd or 0, "process_id": process.pid, "executable": str(exe)}
                checks.append({"check": "exact_fixture_foreground", "passed": bool(hwnd)
                               and desktop.foreground() == hwnd and desktop.exact_window(**identity) is not None})
                with create_runtime(Path(temp) / "runtime") as runtime:
                    runtime.capability_grants.grant("desktop.input")
                    expanded = _reviewed(runtime, "uia.expand", {"window": identity,
                        "selector": {"automation_id": "ActionsMenu", "control_type": "ControlType.MenuItem"},
                        "expect": {"selector": {"automation_id": "RunMenuItem", "control_type": "ControlType.MenuItem"},
                                   "property": "exists", "expected": True}})
                    value = _reviewed(runtime, "uia.set_value", {"window": identity,
                        "selector": {"automation_id": "InputField", "control_type": "ControlType.Edit"},
                        "value": "exact fixture value"})
                    selected = _reviewed(runtime, "uia.select", {"window": identity,
                        "selector": {"name": "Beta", "control_type": "ControlType.ListItem"}})
                    scrolled = _reviewed(runtime, "uia.scroll", {"window": identity,
                        "selector": {"automation_id": "ChoiceList", "control_type": "ControlType.List"},
                        "axis": "vertical", "direction": "increment"})
                    typed = _reviewed(runtime, "input.type_text", {"window": identity,
                        "selector": {"automation_id": "InputField", "control_type": "ControlType.Edit"},
                        "text": "keyboard verified"})
                    clicked = _reviewed(runtime, "input.click", {"window": identity,
                        "selector": {"automation_id": "ClickButton", "control_type": "ControlType.Button"},
                        "expect": {"selector": {"automation_id": "StatusLabel", "control_type": "ControlType.Text"},
                                   "property": "name", "expected": "Mouse clicked"}})
                    for name, result in (("menu_expand", expanded), ("value", value),
                                         ("selection", selected), ("scroll", scrolled),
                                         ("keyboard_type", typed), ("mouse_click", clicked)):
                        reason = result.get("error") or result.get("output", {}).get("error")
                        checks.append({"check": f"real_{name}_postcondition",
                                       "passed": str(result.get("state")) == "COMPLETED",
                                       "failure": reason if isinstance(reason, str) else None})
                    wrong = {**identity, "process_id": identity["process_id"] + 1}
                    refused = _reviewed(runtime, "uia.select", {"window": wrong,
                        "selector": {"name": "Beta", "control_type": "ControlType.ListItem"}})
                    checks.append({"check": "changed_identity_refused", "passed": str(refused.get("state")) == "FAILED"})
        finally:
            if process is not None and process.poll() is None:
                if hwnd: WindowsDesktop().close(hwnd)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate(); process.wait(timeout=5)
            checks.append({"check": "fixture_cleanup", "passed": process is None or process.poll() is not None})
    report = {"timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(x["passed"] for x in checks), "checks": checks,
              "scope": "Stage 8A-3 structured UIA and Stage 8A-4 exact foreground keyboard/mouse fixture."}
    (PROJECT_ROOT / "verification/uia-fixture.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__": main()
