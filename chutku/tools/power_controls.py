"""Delayed Windows power scheduling with exact phrases and explicit cancellation."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


_PHRASES = {"shutdown": "SHUT DOWN THIS PC", "restart": "RESTART THIS PC"}
_SCHEDULE_SCHEMA = {"type": "object", "properties": {
    "mode": {"type": "string", "enum": ["shutdown", "restart"]},
    "delay_seconds": {"type": "integer", "minimum": 300, "maximum": 3600},
    "confirmation_phrase": {"type": "string", "maxLength": 20}},
    "required": ["mode", "delay_seconds", "confirmation_phrase"], "additionalProperties": False}


def _validate_schedule(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != {"mode", "delay_seconds", "confirmation_phrase"}
            or arguments.get("mode") not in _PHRASES or type(arguments.get("delay_seconds")) is not int
            or not 300 <= arguments["delay_seconds"] <= 3600
            or arguments.get("confirmation_phrase") != _PHRASES[arguments["mode"]]):
        raise ValueError("Power scheduling requires an exact mode, 300-3600 second delay and matching confirmation phrase.")


def _none(arguments):
    if arguments != {}:
        raise ValueError("This operation takes no arguments.")


def _command(arguments):
    if sys.platform != "win32":
        raise OSError("Power control requires Windows.")
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/shutdown.exe"
    if arguments["action"] == "schedule":
        flag = "/s" if arguments["mode"] == "shutdown" else "/r"
        command = [str(exe), flag, "/t", str(arguments["delay_seconds"]), "/d", "p:0:0", "/c", "Scheduled by Chutku; use power.cancel to abort."]
    else:
        command = [str(exe), "/a"]
    done = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return done.returncode


def _schedule(arguments, context):
    record = context.journal.begin(context.task_id, "power.schedule", context.granted_root / ".power-schedule",
                                   {"scheduled": False, "mode": arguments["mode"], "delay_seconds": arguments["delay_seconds"]})
    try:
        code = _command({"action": "schedule", **arguments})
    except (OSError, subprocess.SubprocessError) as error:
        context.journal.mark_recovered(record)
        return ToolResult({"error": f"Windows power scheduling failed: {type(error).__name__}."}, Verification.FAIL)
    if code != 0:
        context.journal.mark_recovered(record)
        return ToolResult({"error": "Windows refused the delayed power request."}, Verification.FAIL)
    after = {"scheduled": True, "mode": arguments["mode"], "delay_seconds": arguments["delay_seconds"]}
    try:
        context.journal.complete(record, after)
    except Exception:
        _command({"action": "cancel"})
        context.journal.mark_recovered(record)
        raise
    return ToolResult({**after, "operation_id": record, "cancel_command": "power.cancel"}, Verification.PASS)


def _cancel(_arguments, context):
    record = context.journal.latest_completed("power.schedule", context.granted_root)
    if record is None:
        return ToolResult({"error": "No Chutku power schedule is recorded."}, Verification.FAIL)
    try:
        first = _command({"action": "cancel"})
        second = _command({"action": "cancel"})
    except (OSError, subprocess.SubprocessError) as error:
        return ToolResult({"error": f"Windows power cancellation failed: {type(error).__name__}."}, Verification.FAIL)
    verified = first == 0 and second != 0
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"cancelled": verified, "operation_id": record["operation_id"]},
                      Verification.PASS if verified else Verification.FAIL)


def register_power_tools(registry):
    registry.register(Tool("power.schedule", "Schedule shutdown or restart 5-60 minutes later; unsaved work can be lost unless cancelled.",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _schedule, _validate_schedule, frozenset({"confirmation_phrase"}),
        required_capability="power.control", argument_schema=_SCHEDULE_SCHEMA,
        prerequisites=("exact typed phrase", "on-screen approval", "no unsaved work",), reversibility="cancel_before_deadline",
        success_predicate="Windows_shutdown_command_accepted_and_cancel_window_returned"))
    registry.register(Tool("power.cancel", "Cancel the last Chutku delayed shutdown/restart and verify no schedule remains.",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _cancel, _none, required_capability="power.control",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("active Chutku power schedule",), reversibility="not_applicable",
        success_predicate="first_abort_succeeds_and_second_abort_proves_no_schedule"))
