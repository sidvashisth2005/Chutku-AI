"""Reminders that survive restarts: Windows Task Scheduler runs chutku/remind.py at the
set time, which shows a Windows notification and speaks the message.

The message is stored in data/reminders.json and passed to the task only as a random
id, never as command-line text. Tasks live under the \\Chutku\\ Task Scheduler folder.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import threading

from chutku.app import PROJECT_ROOT
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

_lock = threading.Lock()

_REGISTER = r'''
$ErrorActionPreference = 'Stop'
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($r.action -eq 'register') {
  $action = New-ScheduledTaskAction -Execute $r.python -Argument ('"' + $r.script + '" ' + $r.id) -WorkingDirectory $r.root
  $trigger = New-ScheduledTaskTrigger -Once -At ([datetime]::Parse($r.at))
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
  Register-ScheduledTask -TaskPath '\Chutku\' -TaskName ('Reminder-' + $r.id) -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}
if ($r.action -eq 'unregister') {
  Unregister-ScheduledTask -TaskPath '\Chutku\' -TaskName ('Reminder-' + $r.id) -Confirm:$false -ErrorAction SilentlyContinue
}
$tasks = @(Get-ScheduledTask -TaskPath '\Chutku\' -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ name = $_.TaskName; at = ($_.Triggers | Select-Object -First 1).StartBoundary } })
@{ tasks = $tasks } | ConvertTo-Json -Compress -Depth 4
'''


def store_path(base=PROJECT_ROOT):
    return Path(base) / "data" / "reminders.json"


def load(base=PROJECT_ROOT):
    try:
        data = json.loads(store_path(base).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data, base=PROJECT_ROOT):
    from chutku.core.jsonstore import write_json
    write_json(store_path(base), data)   # an unreadable file is copied aside, never silently replaced


def scheduler(request):
    from chutku.tools.everyday import _powershell
    result = _powershell(_REGISTER, request, timeout=20)
    tasks = (result or {}).get("tasks") or []
    tasks = tasks if isinstance(tasks, list) else [tasks]
    return {t["name"].removeprefix("Reminder-"): t.get("at") for t in tasks if isinstance(t, dict) and t.get("name")}


def _parse_when(arguments, now=None):
    now = now or datetime.now()
    if "in_minutes" in arguments:
        # Task Scheduler works in whole minutes: round up so "in 1 minute" is never early.
        when = now + timedelta(minutes=arguments["in_minutes"])
        return when.replace(second=0, microsecond=0) + timedelta(minutes=1 if when.second or when.microsecond else 0)
    return datetime.strptime(arguments["at"], "%Y-%m-%dT%H:%M")


def _validate_set(arguments):
    if set(arguments) - {"message", "at", "in_minutes"} or "message" not in arguments \
            or len({"at", "in_minutes"} & set(arguments)) != 1:
        raise ValueError("Give message and exactly one of at (YYYY-MM-DDTHH:MM, local time) or in_minutes.")
    if not isinstance(arguments["message"], str) or not 1 <= len(arguments["message"].strip()) <= 200:
        raise ValueError("message must be 1-200 characters.")
    if "in_minutes" in arguments and not (type(arguments["in_minutes"]) is int and 1 <= arguments["in_minutes"] <= 525600):
        raise ValueError("in_minutes must be 1 to 525600.")
    if "at" in arguments:
        try:
            when = datetime.strptime(arguments["at"], "%Y-%m-%dT%H:%M")
        except (TypeError, ValueError) as error:
            raise ValueError("at must look like 2026-10-01T17:30 (local time).") from error
        if when <= datetime.now() or when > datetime.now() + timedelta(days=366):
            raise ValueError("The reminder time must be in the future and within a year.")


def _set(arguments, _context):
    when = _parse_when(arguments)
    reminder_id = secrets.token_hex(4)
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.is_file():
        python = Path(sys.executable)
    with _lock:
        data = load()
        data[reminder_id] = {"message": arguments["message"].strip(), "at": when.strftime("%Y-%m-%dT%H:%M"),
                             "created": datetime.now().isoformat(timespec="seconds"), "fired": False}
        save(data)
    try:
        tasks = scheduler({"action": "register", "id": reminder_id, "at": when.strftime("%Y-%m-%dT%H:%M:00"),
                           "python": str(python), "script": str(PROJECT_ROOT / "chutku" / "remind.py"),
                           "root": str(PROJECT_ROOT)})
    except OSError as error:
        with _lock:
            data = load()
            data.pop(reminder_id, None)
            save(data)
        return ToolResult({"error": f"Task Scheduler refused the reminder: {error}"}, Verification.FAIL)
    ok = reminder_id in tasks and (tasks[reminder_id] or "").startswith(when.strftime("%Y-%m-%dT%H:%M"))
    output = {"id": reminder_id, "at": when.strftime("%A %d %B %Y, %I:%M %p"), "message": arguments["message"].strip(),
              "undo_hint": f"reminder.cancel id={reminder_id}"}
    return ToolResult(output, Verification.PASS if ok else Verification.FAIL, output | {"message": "[REDACTED]"})


def _list(_arguments, _context):
    try:
        tasks = scheduler({"action": "list"})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    data = load()
    upcoming = sorted(({"id": k, "at": v["at"], "message": v["message"]} for k, v in data.items()
                       if not v.get("fired") and k in tasks), key=lambda r: r["at"])
    return ToolResult({"upcoming": upcoming, "count": len(upcoming)}, Verification.PASS,
                      {"count": len(upcoming)})


def _validate_cancel(arguments):
    if set(arguments) != {"id"} or not isinstance(arguments["id"], str) or not arguments["id"].isalnum() \
            or len(arguments["id"]) != 8:
        raise ValueError("Give the 8-character reminder id from reminder.list.")


def _cancel(arguments, _context):
    data = load()
    if arguments["id"] not in data:
        return ToolResult({"error": "No reminder has that id."}, Verification.FAIL)
    try:
        tasks = scheduler({"action": "unregister", "id": arguments["id"]})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    gone = arguments["id"] not in tasks
    if gone:
        with _lock:
            data = load()
            removed = data.pop(arguments["id"], None)
            save(data)
    return ToolResult({"cancelled": gone, "message": (removed or {}).get("message") if gone else None},
                      Verification.PASS if gone else Verification.FAIL)


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This tool takes no arguments.")


def register_reminder_tools(registry):
    registry.register(Tool("reminder.set", "Set a reminder: message plus either in_minutes or at "
        "(local time YYYY-MM-DDTHH:MM; use CONTEXT.now to compute). Shows a notification and speaks it, even "
        "after a restart.",
        Risk.REVERSIBLE, _set, _validate_set, frozenset({"message"}), required_capability="reminders.manage",
        argument_schema={"type": "object", "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 200},
            "at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"},
            "in_minutes": {"type": "integer", "minimum": 1, "maximum": 525600}},
            "required": ["message"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="scheduled_task_exists_at_requested_time"))
    registry.register(Tool("reminder.list", "List upcoming reminders (id, time, message).",
        Risk.OBSERVATION, _list, _no_arguments,
        required_capability="reminders.manage", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="scheduled_reminders_listed"))
    registry.register(Tool("reminder.cancel", "Cancel one reminder by id (from reminder.list).",
        Risk.REVERSIBLE, _cancel, _validate_cancel, required_capability="reminders.manage",
        argument_schema={"type": "object", "properties": {"id": {"type": "string", "minLength": 8, "maxLength": 8}},
                         "required": ["id"], "additionalProperties": False},
        reversibility="none", success_predicate="scheduled_task_removed"))
