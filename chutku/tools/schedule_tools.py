"""Scheduled tasks: "30 min baad X", "har 15 min X", "raat 12 baje X" (see chutku/scheduled.py).

Scheduling is reversible (task.cancel). The task itself runs later as an ordinary request in the same autonomy mode
the order was given in, so every later step meets the same policy, approvals and verification as if said then.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
_SCHEDULE = {"type": "object", "properties": {
    "goal": {"type": "string", "minLength": 1, "maxLength": 300},
    "in_minutes": {"type": "integer", "minimum": 1, "maximum": 527040},
    "at": {"type": "string", "minLength": 16, "maxLength": 19},
    "every_minutes": {"type": "integer", "minimum": 1, "maximum": 10080}},
    "required": ["goal"], "additionalProperties": False}
_CANCEL = {"type": "object", "properties": {"id": {"type": "string", "minLength": 1, "maxLength": 12},
                                            "all": {"type": "boolean"}}, "additionalProperties": False}


def _root():
    from chutku import mind
    return Path(mind.PROJECT_ROOT)


def _when(arguments):
    if "in_minutes" in arguments:
        return datetime.now().replace(microsecond=0) + timedelta(minutes=arguments["in_minutes"])
    text = arguments["at"]
    for form in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, form)
        except ValueError:
            continue
    raise ValueError("at must look like 2026-10-06T21:30 (local time).")


def _validate_schedule(arguments):
    if not isinstance(arguments.get("goal"), str) or not arguments["goal"].strip():
        raise ValueError("Say what to do.")
    if len({"in_minutes", "at"} & set(arguments)) != 1:
        raise ValueError("Give exactly one of in_minutes or at.")
    when = _when(arguments)
    if when <= datetime.now() - timedelta(minutes=1) or when > datetime.now() + timedelta(days=366):
        raise ValueError("The time must be in the future and within a year.")
    from chutku.scheduled import parse
    if parse(arguments["goal"]) is not None:
        raise ValueError("The task itself must not contain another time; schedule it once.")


def _schedule(arguments, context):
    from chutku import scheduled
    mode = context.autonomy or ("owner" if context.provenance in {None, "user_stated"} else "review")
    origin = "voice" if context.provenance in {"delegated_microphone", "reviewed_microphone"} else "text"
    try:
        job = scheduled.add(_root(), arguments["goal"], _when(arguments), every_minutes=arguments.get("every_minutes"),
                            mode=mode, origin=origin)
    except ValueError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    stored = next((j for j in scheduled.active(_root()) if j["id"] == job["id"]), None)
    output = {"id": job["id"], "goal": job["goal"], "next_at": job["next_at"], "every_minutes": job["every_minutes"],
              "mode": mode, "summary": scheduled.describe(job), "undo_hint": f"task.cancel id={job['id']}"}
    return ToolResult(output, Verification.PASS if stored == job else Verification.FAIL)


def _list(_arguments, _context):
    from chutku import scheduled
    jobs = scheduled.active(_root())
    return ToolResult({"tasks": [{"id": j["id"], "goal": j["goal"], "next_at": j["next_at"],
                                  "every_minutes": j.get("every_minutes"), "runs": j.get("runs", 0),
                                  "last": (j.get("history") or [{}])[-1].get("status"),
                                  "summary": scheduled.describe(j)} for j in jobs], "count": len(jobs)},
                      Verification.PASS)


def _validate_cancel(arguments):
    if set(arguments) - {"id", "all"} or (("id" in arguments) == bool(arguments.get("all"))):
        raise ValueError("Give id, or all: true.")


def _cancel(arguments, _context):
    from chutku import scheduled
    cancelled = scheduled.cancel(_root(), None if arguments.get("all") else arguments["id"])
    left = {j["id"] for j in scheduled.active(_root())}
    ok = bool(cancelled) and not any(j["id"] in left for j in cancelled)
    return ToolResult({"cancelled": [{"id": j["id"], "goal": j["goal"]} for j in cancelled],
                       "still_scheduled": len(left)},
                      Verification.PASS if ok else Verification.FAIL)


def _validate_none(arguments):
    if arguments:
        raise ValueError("This takes no arguments.")


def register_schedule_tools(registry):
    registry.register(Tool("task.schedule", "Do a task later by itself: once after in_minutes, once at a local time "
        "(at, e.g. 2026-10-06T21:30), and optionally again every_minutes until cancelled. goal is the request in the "
        "owner's words without the time (e.g. 'send hi to UB'). Chutku keeps working normally meanwhile; at the time "
        "the goal runs as a normal request with the same safety checks.", Risk.REVERSIBLE, _schedule,
        _validate_schedule, argument_schema=_SCHEDULE, reversibility="compensatable",
        success_predicate="task_stored"))
    registry.register(Tool("task.list", "List the scheduled tasks that are still waiting (id, what, next time, "
        "repeat).", Risk.OBSERVATION, _list, _validate_none, argument_schema=_NONE,
        reversibility="not_applicable", success_predicate="tasks_read"))
    registry.register(Tool("task.cancel", "Cancel one scheduled task by id (from task.list), or all of them "
        "(all: true).", Risk.REVERSIBLE, _cancel, _validate_cancel, argument_schema=_CANCEL,
        reversibility="compensatable", success_predicate="task_cancelled"))
