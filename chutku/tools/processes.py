"""Bounded Windows process observation with no shell-derived user input."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


_LIST_QUERY = (
    "$ErrorActionPreference='Stop';"
    "Get-CimInstance Win32_Process | Sort-Object ProcessId | Select-Object -First 200 "
    "ProcessId,Name,ExecutablePath | ConvertTo-Json -Compress"
)

_PID_ARGUMENTS = {
    "type": "object",
    "properties": {"pid": {"type": "integer", "minimum": 1, "maximum": 0xFFFFFFFF}},
    "required": ["pid"],
    "additionalProperties": False,
}
_LAUNCH_ARGUMENTS = {
    "type": "object",
    "properties": {
        "executable": {"type": "string", "maxLength": 1000, "description": "Absolute existing .exe path."},
        "arguments": {"type": "array", "maxItems": 20,
                      "items": {"type": "string", "maxLength": 512}},
    },
    "required": ["executable"],
    "additionalProperties": False,
}
_TERMINATE_ARGUMENTS = {
    "type": "object",
    "properties": {
        "pid": {"type": "integer", "minimum": 1, "maximum": 0xFFFFFFFF},
        "expected_executable": {"type": "string", "maxLength": 1000,
                                "description": "Absolute executable path rebound immediately before termination."},
    },
    "required": ["pid", "expected_executable"],
    "additionalProperties": False,
}


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("This process observation takes no arguments.")


def _validate_pid(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"pid"}:
        raise ValueError("Provide only an integer pid.")
    if type(arguments["pid"]) is not int or not 1 <= arguments["pid"] <= 0xFFFFFFFF:
        raise ValueError("pid must be an integer between 1 and 4294967295.")


def _validated_executable(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 1000:
        raise ValueError("executable must be an absolute existing .exe path.")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("executable must be an absolute existing .exe path.")
    path = path.resolve(strict=True)
    if (not path.is_file() or path.suffix.casefold() != ".exe" or path.is_symlink()
            or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValueError("executable must be a regular non-reparse .exe file.")
    return path


def _validate_launch(arguments):
    if not isinstance(arguments, dict) or not set(arguments) <= {"executable", "arguments"} or "executable" not in arguments:
        raise ValueError("Provide executable and optional arguments only.")
    _validated_executable(arguments["executable"])
    values = arguments.get("arguments", [])
    if (not isinstance(values, list) or len(values) > 20 or
            any(not isinstance(value, str) or len(value) > 512 or "\x00" in value for value in values)):
        raise ValueError("arguments must be a list of at most 20 bounded strings.")


def _validate_terminate(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"pid", "expected_executable"}:
        raise ValueError("Provide only pid and expected_executable.")
    _validate_pid({"pid": arguments["pid"]})
    _validated_executable(arguments["expected_executable"])


def _snapshot(pid=None):
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    query = (_LIST_QUERY if pid is None else
        "$ErrorActionPreference='Stop';Get-CimInstance Win32_Process -Filter \"ProcessId = "
        + str(pid) + "\" | Select-Object ProcessId,Name,ExecutablePath | ConvertTo-Json -Compress")
    completed = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or len(completed.stdout) > 512000:
        raise OSError("Windows process inventory failed or returned oversized output.")
    decoded = json.loads(completed.stdout or "[]")
    rows = decoded if isinstance(decoded, list) else [decoded]
    processes = []
    for row in rows[:200]:
        if not isinstance(row, dict) or type(row.get("ProcessId")) is not int:
            continue
        if pid is not None and row["ProcessId"] != pid:
            continue
        processes.append({"pid": row["ProcessId"], "name": str(row.get("Name") or "")[:260],
                          "executable": str(row.get("ExecutablePath") or "")[:1000] or None})
    return processes


def _list_processes(arguments, context):
    processes = _snapshot()
    return ToolResult({"processes": processes, "count": len(processes), "limit": 200}, Verification.PASS,
                      {"count": len(processes), "processes": "[REDACTED]"})


def _process_status(arguments, context):
    pid = arguments["pid"]
    process = next((item for item in _snapshot(pid) if item["pid"] == pid), None)
    return ToolResult({"pid": pid, "running": process is not None, "process": process}, Verification.PASS,
                      {"pid": pid, "running": process is not None, "process": "[REDACTED]"})


def _same_path(first, second):
    return os.path.normcase(os.path.normpath(str(first))) == os.path.normcase(os.path.normpath(str(second)))


def _launch_process(arguments, context):
    executable = _validated_executable(arguments["executable"])
    from chutku.core.launch import popen_user_app
    process = popen_user_app([str(executable), *arguments.get("arguments", [])], shell=False,
        cwd=str(executable.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    time.sleep(0.25)
    observed = next(iter(_snapshot(process.pid)), None)
    if observed is None or not observed["executable"] or not _same_path(observed["executable"], executable):
        if process.poll() is None:
            process.terminate()
        return ToolResult({"pid": process.pid, "error": "The launched process identity could not be verified."}, Verification.FAIL)
    return ToolResult({"pid": process.pid, "executable": str(executable), "running": True}, Verification.PASS,
                      {"pid": process.pid, "executable": "[REDACTED]", "running": True})


def _terminate_process(arguments, context):
    pid = arguments["pid"]
    expected = _validated_executable(arguments["expected_executable"])
    observed = next(iter(_snapshot(pid)), None)
    protected = {"system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe"}
    if (pid <= 4 or observed is None or not observed["executable"]
            or observed["name"].casefold() in protected
            or not _same_path(observed["executable"], expected)):
        return ToolResult({"pid": pid, "error": "Process identity was missing, protected, or different from the reviewed executable."}, Verification.FAIL)
    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
    completed = subprocess.run([str(taskkill), "/PID", str(pid), "/T", "/F"], capture_output=True,
        timeout=8, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0:
        return ToolResult({"pid": pid, "error": "Windows refused process termination."}, Verification.FAIL)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not _snapshot(pid):
            return ToolResult({"pid": pid, "running": False, "terminated": True}, Verification.PASS)
        time.sleep(0.1)
    return ToolResult({"pid": pid, "error": "Process remained observable after termination."}, Verification.FAIL)


def register_process_tools(registry):
    registry.register(Tool("process.list", "List up to 200 Windows processes with PID, name and observable image path.",
        Risk.OBSERVATION, _list_processes, _validate_none, required_capability="process.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("Windows CIM",), reversibility="not_applicable",
        success_predicate="bounded_process_inventory_parsed"))
    registry.register(Tool("process.status", "Check whether one exact Windows process ID exists and report its observed identity.",
        Risk.OBSERVATION, _process_status, _validate_pid, required_capability="process.observe",
        argument_schema=_PID_ARGUMENTS, prerequisites=("Windows CIM",), reversibility="not_applicable",
        success_predicate="exact_pid_observation_completed"))
    registry.register(Tool("process.launch", "Launch one exact absolute executable without a shell and verify its process image.",
        Risk.EXTERNAL_SIDE_EFFECT, _launch_process, _validate_launch, frozenset({"arguments"}),
        required_capability="process.launch", argument_schema=_LAUNCH_ARGUMENTS,
        prerequisites=("absolute existing non-reparse executable",), reversibility="compensatable", runs_code=True,
        success_predicate="spawned_pid_image_matches_reviewed_executable"))
    registry.register(Tool("process.terminate", "Force-terminate one exact PID only if its image still matches the reviewed executable.",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _terminate_process, _validate_terminate,
        required_capability="process.terminate", argument_schema=_TERMINATE_ARGUMENTS,
        prerequisites=("exact PID and executable identity match",), reversibility="irreversible",
        success_predicate="exact_pid_no_longer_observable"))
