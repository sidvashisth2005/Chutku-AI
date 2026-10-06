"""Causal Rewind (master plan S18): one undo for everything Chutku did in a time window or a task.

The action log says what Chutku changed. Each completed change becomes an *effect* with the resources it wrote
(a file, a folder, a setting, a reminder) and its inverse. A file that Chutku moved keeps its identity at the new
place, so a later change to it depends on the move. Undoing some effects also undoes every *later* effect that
depends on them (even outside the window), newest first.

Before anything runs, every effect is checked against the present: when the owner changed a file or a setting after
Chutku did, it is a *conflict* and is left alone (with everything that depends on it). Messages, web pages, typing
and power actions cannot be undone and are listed honestly; apps Chutku opened are left open (closing could lose
the owner's work).

Each inverse is the same undo code ``log.undo`` uses, run on exactly the recorded operation, after the protected-zone
and capability checks. The whole rewind is one step (``rewind.run``, a file change), so it asks once, showing the
full list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path, PurePosixPath

JOURNALED = {"filesystem.write_text": "filesystem.undo_last_write", "filesystem.copy": "filesystem.undo_last_copy",
             "filesystem.move": "filesystem.undo_last_move", "filesystem.recycle": "filesystem.restore_last_recycled"}
SETTINGS = {"audio.volume": "volume", "system.volume_set": "volume", "display.brightness": "brightness",
            "settings.theme_set": "theme"}
REFS = {"reminder.set": ("reminder.cancel", "reminder"), "task.schedule": ("task.cancel", "scheduled task")}
UNDO_KINDS = {"filesystem.undo_last_write", "filesystem.undo_last_copy", "filesystem.undo_last_move",
              "filesystem.restore_last_recycled", "files.organize_undo", "system.volume_restore",
              "settings.theme_restore", "reminder.cancel", "task.cancel", "log.undo", "rewind.run",
              "filesystem.recover_incomplete_write", "screen.undo_last_capture"}
LEFT_OPEN = ("apps.launch", "files.open", "web.open", "youtube.play", "web.search", "message.open_chat")
CAPABILITY = {"volume": "audio.modify", "brightness": "settings.modify", "theme": "settings.modify"}
MAX_ENTRIES = 3000


@dataclass
class Effect:
    seq: int
    at: str
    tool: str
    task_id: str
    entry: dict
    kind: str                    # journaled | organize | setting | ref | folder | left_open | irreversible
    what: str
    writes: set = field(default_factory=set)
    status: str = ""
    why: str = ""


# -- reading the log ---------------------------------------------------------------------------------------------------

def _norm(path):
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def _root_of(record):
    """The grant root a journaled operation used (its records keep paths relative to that root)."""
    before = record["before"] or {}
    relative = before.get("source") if record["operation"] in {"filesystem.move", "filesystem.recycle"} else \
        before.get("destination") if record["operation"] == "filesystem.copy" else None
    target = Path(record["target"])
    if relative is None:
        return None   # a text write: any granted root that contains the file works
    parts = [p for p in PurePosixPath(relative).parts if p not in {".", ""}]
    return target if not parts else target.parents[len(parts) - 1]


def _paths(record):
    """(written, read) absolute paths of a journaled operation."""
    target, before = Path(record["target"]), record["before"] or {}
    root = _root_of(record)
    if record["operation"] == "filesystem.move":
        return [target, root / before["destination"]], []
    if record["operation"] == "filesystem.copy":
        return [target], [root / before["source"]]
    return [target], []


def effects(runtime, since=None):
    """Every completed change since ``since`` (aware datetime), oldest first, with what it wrote."""
    stamp = since.astimezone(timezone.utc).isoformat(timespec="seconds") if since else None
    entries = [e for e in reversed(runtime.action_log.recent(MAX_ENTRIES, stamp))
               if e.get("state") == "COMPLETED" and (e.get("risk") or 0) >= 1 and e.get("tool") not in UNDO_KINDS]
    ids, counter = {}, [0]

    def resource(path):
        key = _norm(path)
        if key not in ids:
            counter[0] += 1
            ids[key] = f"r{counter[0]}"
        return ids[key]

    out = []
    for entry in entries:
        tool, arguments = entry["tool"], entry.get("arguments") or {}
        effect = Effect(entry["seq"], entry.get("time", ""), tool, entry.get("task_id") or "", entry, "irreversible",
                        _describe(tool, arguments))
        if tool in JOURNALED and entry.get("operation_id"):
            record = runtime.journal.get(entry["operation_id"])
            if record is not None and record["after"] is not None:
                effect.kind = "journaled"
                effect.entry = dict(entry, _record=record)
                written, _read = _paths(record)
                if tool == "filesystem.move":
                    source, destination = written
                    identity = resource(source)
                    effect.writes = {identity, resource(destination)}
                    ids[_norm(destination)] = identity          # the moved file keeps its identity ...
                    counter[0] += 1
                    ids[_norm(source)] = f"r{counter[0]}"        # ... and its old place is a new, empty one
                else:
                    effect.writes = {resource(p) for p in written}
        elif tool == "files.organize" and entry.get("undo_id"):
            effect.kind, effect.writes = "organize", {resource(p) for p in entry.get("paths") or []}
        elif tool in SETTINGS and "state_before" in entry:
            effect.kind, effect.writes = "setting", {"setting:" + SETTINGS[tool]}
        elif tool in REFS and entry.get("ref"):
            effect.kind, effect.writes = "ref", {f"{tool}:{entry['ref']}"}
        elif tool == "filesystem.create_directory" and entry.get("paths"):
            effect.kind = "folder"
            effect.writes = {resource(entry["paths"][0])}
        elif tool.startswith(LEFT_OPEN):
            effect.kind = "left_open"
        out.append(effect)
    return out


def _describe(tool, arguments):
    shown = {k: v for k, v in arguments.items() if v != "[REDACTED]"}
    detail = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(shown.items())[:3])
    return f"{tool}({detail})"


# -- choosing ----------------------------------------------------------------------------------------------------------

def _scope_start(scope, now):
    if scope.get("since"):
        return datetime.fromisoformat(scope["since"]).astimezone()
    if scope.get("minutes"):
        return now - timedelta(minutes=scope["minutes"])
    if scope.get("today"):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=7)   # a task (or the last task) is looked for in the last week


def plan(runtime, scope, now=None):
    """The effects to undo for ``scope`` (since / minutes / today / task_id / last_task), newest first, each with a
    status: ok, conflict, blocked (depends on a conflict), done_before, irreversible or left_open."""
    now = (now or datetime.now()).astimezone()
    start = _scope_start(scope, now)
    every = effects(runtime, start - timedelta(seconds=1))
    if scope.get("task_id") or scope.get("last_task"):
        task = scope.get("task_id") or next((e.task_id for e in reversed(every)
                                             if e.kind not in {"irreversible", "left_open"}), None)
        chosen = [e for e in every if e.task_id == task]
    else:
        stamp = start.astimezone(timezone.utc).isoformat(timespec="seconds")
        chosen = [e for e in every if e.at >= stamp]
    if not chosen:
        return []
    # Later changes that build on a chosen one are undone too (first), even when outside the window.
    selected, touched = {e.seq for e in chosen}, set().union(*(e.writes for e in chosen))
    for effect in every:
        if effect.seq > min(selected) and effect.seq not in selected and effect.writes & touched:
            selected.add(effect.seq)
            touched |= effect.writes
    items = sorted((e for e in every if e.seq in selected), key=lambda e: -e.seq)
    _check(runtime, items)
    return items


def _check(runtime, items):
    rewound = _rewound(runtime)
    blocked, handled = set(), set()
    for item in items:
        if item.kind in {"irreversible", "left_open"}:
            item.status = item.kind
            item.why = ("Cannot be undone (it already happened outside this PC or on screen)."
                        if item.kind == "irreversible" else "Left open: closing it could lose your work.")
            continue
        if _already_undone(runtime, item, rewound):
            item.status, item.why = "done_before", "Already undone."
            continue
        if item.writes & blocked:
            item.status, item.why = "blocked", "Depends on a later change that you edited since; left alone."
            blocked |= item.writes
            continue
        if item.writes & handled:
            item.status, item.why = "ok", "Undone after the later change to the same thing."
        else:
            reason = _conflict(runtime, item)
            if reason:
                item.status, item.why = "conflict", reason
                blocked |= item.writes
            else:
                item.status = "ok"
        handled |= item.writes


def _rewound(runtime):
    path = Path(runtime.control_root) / "data" / "rewound.json"
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def _already_undone(runtime, item, rewound):
    if item.seq in rewound:
        return True
    if item.kind == "journaled":
        record = runtime.journal.get(item.entry["operation_id"])
        return record is None or record["status"] != "COMPLETED"
    if item.kind == "organize":
        from chutku.tools.documents import _records_dir
        return not (_records_dir() / f"organize-{item.entry['undo_id']}.json").is_file()
    if item.kind == "ref":
        return not _ref_alive(runtime, item)
    return False


def _ref_alive(runtime, item):
    if item.tool == "reminder.set":
        from chutku.tools.reminders import load
        return item.entry["ref"] in load()
    from chutku import scheduled
    return any(j["id"] == item.entry["ref"] for j in scheduled.active(runtime.control_root))


# -- what is there now -------------------------------------------------------------------------------------------------

def read_setting(name):
    if name == "volume":
        from chutku.tools.system_controls import _volume_call
        return _volume_call({"action": "get"})
    if name == "brightness":
        from chutku.tools.desktop_controls import _brightness_call
        return _brightness_call({"action": "get"})
    from chutku.tools.windows_settings import _invoke
    return _invoke({"action": "get"})


def write_setting(name, value):
    if name == "volume":
        from chutku.tools.system_controls import _volume_call
        return _volume_call({"action": "set", **value})
    if name == "brightness":
        from chutku.tools.desktop_controls import _brightness_call
        return _brightness_call({"action": "set", "level": value})
    from chutku.tools.windows_settings import _invoke
    return _invoke({"action": "set", "mode": value["apps"]})


def _same_setting(name, current, expected):
    if name == "brightness":
        return isinstance(current, int) and isinstance(expected, int) and abs(current - expected) <= 2
    return current == expected


def _conflict(runtime, item):
    """Why undoing this now would overwrite something newer, or None."""
    try:
        if item.kind == "journaled":
            return _file_conflict(item.entry["_record"])
        if item.kind == "setting":
            name = SETTINGS[item.tool]
            if not _same_setting(name, read_setting(name), item.entry["state_after"]):
                return f"The {name} was changed again after Chutku set it; left as it is now."
            return None
        if item.kind == "folder":
            folder = Path(item.entry["paths"][0])
            if not folder.is_dir():
                return "The folder is gone already."
            if any(folder.iterdir()):
                return "The folder is not empty (something else was put in it); left alone."
        return None
    except OSError as error:
        return f"Could not check it ({error}); left alone."


def _file_conflict(record):
    from chutku.core.paths import read_bounded_text
    from chutku.tools.filesystem_extended import _identity
    target, before, after = Path(record["target"]), record["before"] or {}, record["after"] or {}
    if record["operation"] == "filesystem.write_text":
        if not target.is_file() or read_bounded_text(target) != after.get("content"):
            return "The file was changed after Chutku wrote it; your version is kept."
    elif record["operation"] == "filesystem.copy":
        if not target.is_file() or _identity(target) != after.get("destination_identity"):
            return "The copy was changed or removed since; left alone."
    elif record["operation"] == "filesystem.move":
        destination = _root_of(record) / before["destination"]
        if target.exists():
            return "Something new is at the old place now; the moved file stays where it is."
        if not destination.is_file() or _identity(destination) != after.get("destination_identity"):
            return "The moved file was changed or moved again since; left alone."
    elif record["operation"] == "filesystem.recycle" and target.exists():
        return "Something new is at that place now; the recycled file stays in the Recycle Bin."
    return None


# -- doing it ----------------------------------------------------------------------------------------------------------

def preview_text(items):
    if not items or all(i.status == "done_before" for i in items):
        return "Nothing Chutku changed in that time is left to undo."
    counts = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    shown = [i for i in items if i.status != "done_before"]   # undone earlier: only counted, not listed
    lines = [f"{'✓' if i.status == 'ok' else '✗'} {i.what}" + (f" — {i.why}" if i.status != "ok" else "")
             for i in shown[:12]]
    if counts.get("done_before"):
        lines.append(f"({counts['done_before']} already undone earlier)")
    head = (f"Undo {counts.get('ok', 0)} change(s), newest first"
            + "".join(f"; {n} {label}" for label, n in (("conflict(s) kept as they are", counts.get("conflict", 0)),
                                                        ("blocked", counts.get("blocked", 0)),
                                                        ("cannot be undone", counts.get("irreversible", 0)),
                                                        ("left open", counts.get("left_open", 0))) if n) + ":")
    return head + "\n" + "\n".join(lines)


def _grant_root(runtime, record):
    """An active grant that may modify this exact root (fail closed: no grant, no undo)."""
    wanted = _root_of(record)
    target = Path(record["target"])
    grants = runtime.resource_grants.list(active_only=True) if runtime.resource_grants is not None else []
    for grant in sorted(grants, key=lambda g: -len(str(g.root))):
        root = Path(grant.root).resolve()
        if "modify" not in grant.access:
            continue
        if wanted is not None and _norm(root) == _norm(wanted):
            return root
        if wanted is None and (_norm(target).startswith(_norm(root) + "\\") or _norm(target) == _norm(root)):
            return root
    return None


def _run_tool(runtime, name, arguments, context):
    tool = runtime.registry.get(name)
    if tool.required_capability is not None:
        runtime.current_capability(tool.required_capability)   # ValueError when not granted
    result = tool.execute(arguments, context)
    if tool.verify is not None and result.verification.name != "FAIL":
        result = tool.verify(arguments, result, context)
    return result


def undo_one(runtime, item, context):
    """Undo one effect. Returns (ok, message)."""
    from chutku.core.paths import protection_reason
    from chutku.tools.registry import ExecutionContext, Verification
    if item.kind == "journaled":
        record = item.entry["_record"]
        written, _read = _paths(record)
        for path in written:
            reason = protection_reason(Path(path))
            if reason:
                return False, reason
        root = _grant_root(runtime, record)
        if root is None:
            return False, "No folder access grant covers it any more; left alone."
        undo_context = ExecutionContext(context.task_id, runtime.journal, root, runtime.memory,
                                        runtime.capability_grants, approved=context.approved,
                                        autonomy=context.autonomy, provenance=context.provenance)
        result = _run_tool(runtime, JOURNALED[item.tool], {"operation_id": record["operation_id"]}, undo_context)
        return result.verification == Verification.PASS, (result.output or {}).get("error") or "undone"
    if item.kind == "organize":
        result = _run_tool(runtime, "files.organize_undo", {"id": item.entry["undo_id"]}, context)
        return result.verification == Verification.PASS, "put back" if result.verification == Verification.PASS \
            else f"partly: {(result.output or {}).get('left_in_place_because_changed')}"
    if item.kind == "setting":
        name = SETTINGS[item.tool]
        runtime.current_capability(CAPABILITY[name])
        if not _same_setting(name, read_setting(name), item.entry["state_after"]):
            return False, f"The {name} was changed again; left as it is now."
        before = item.entry["state_before"]
        write_setting(name, before)
        now = read_setting(name)
        return _same_setting(name, now, before), f"{name} back to {before}"
    if item.kind == "ref":
        tool, _label = REFS[item.tool]
        result = _run_tool(runtime, tool, {"id": item.entry["ref"]}, context)
        return result.verification == Verification.PASS, "cancelled"
    if item.kind == "folder":
        folder = Path(item.entry["paths"][0])
        reason = protection_reason(folder)
        if reason:
            return False, reason
        if not folder.is_dir() or any(folder.iterdir()):
            return False, "The folder is not empty; left alone."
        folder.rmdir()
        return not folder.exists(), "empty folder removed"
    return False, "cannot be undone"


def execute(runtime, items, context):
    """Undo every ok item newest first. A failure blocks the older changes to the same thing."""
    report = {"undone": [], "skipped_conflict": [], "irreversible": [], "left_open": [], "failed": []}
    blocked = set()
    for item in items:
        if item.status in {"irreversible", "left_open"}:
            report[item.status].append(item.what)
            continue
        if item.status in {"conflict", "blocked"} or item.writes & blocked:
            report["skipped_conflict"].append(f"{item.what}: {item.why or 'depends on a change that was kept'}")
            blocked |= item.writes
            continue
        if item.status != "ok":
            continue
        try:
            ok, message = undo_one(runtime, item, context)
        except (ValueError, OSError, KeyError) as error:
            ok, message = False, str(error)
        if ok:
            report["undone"].append(item.what)
            _remember(runtime, item.seq)
        else:
            report["failed"].append(f"{item.what}: {message}")
            blocked |= item.writes
    return report


def _remember(runtime, seq):
    from chutku.core.jsonstore import lock_for, write_json
    path = Path(runtime.control_root) / "data" / "rewound.json"
    with lock_for(path):
        done = sorted(_rewound(runtime) | {seq})[-5000:]
        write_json(path, done)


# -- tools -------------------------------------------------------------------------------------------------------------

_SCOPE = {"type": "object", "properties": {
    "minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
    "since": {"type": "string", "minLength": 16, "maxLength": 32},
    "today": {"type": "boolean"}, "task_id": {"type": "string", "minLength": 4, "maxLength": 80},
    "last_task": {"type": "boolean"}}, "additionalProperties": False}


def _validate_scope(arguments):
    given = [k for k in ("minutes", "since", "task_id") if k in arguments] + \
            [k for k in ("today", "last_task") if arguments.get(k) is True]
    if len(given) != 1 or set(arguments) - set(_SCOPE["properties"]):
        raise ValueError("Give exactly one of minutes, since, today, task_id or last_task.")
    if "since" in arguments:
        try:
            datetime.fromisoformat(arguments["since"])
        except ValueError as error:
            raise ValueError("since must look like 2026-10-06T11:00:00.") from error


def question(runtime, arguments):
    """The approval card text: exactly what will be undone and what will not."""
    try:
        return "Rewind — " + preview_text(plan(runtime, arguments))[:900]
    except Exception as error:   # the card still asks; it just cannot list the changes
        return f"Rewind (the list could not be prepared: {error})."


def register_rewind_tools(registry, runtime):
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification

    def item_view(item):
        return {"seq": item.seq, "time": item.at, "what": item.what, "status": item.status, "why": item.why}

    def preview(arguments, _context):
        items = plan(runtime, arguments)
        return ToolResult({"items": [item_view(i) for i in items], "summary": preview_text(items),
                           "can_undo": sum(1 for i in items if i.status == "ok")}, Verification.PASS)

    def run(arguments, context):
        items = plan(runtime, arguments)
        report = execute(runtime, items, context)
        ok = not report["failed"]
        report["summary"] = (f"Undid {len(report['undone'])} change(s)"
                             + (f"; kept {len(report['skipped_conflict'])} you changed since" if report['skipped_conflict']
                                else "")
                             + (f"; {len(report['irreversible'])} cannot be undone" if report["irreversible"] else "")
                             + (f"; {len(report['failed'])} failed" if report["failed"] else "") + ".")
        return ToolResult(report, Verification.PASS if ok else Verification.UNKNOWN)

    registry.register(Tool("rewind.preview", "Show what 'undo everything' would do for a time window (minutes, since, "
        "today) or a task (task_id, last_task): each change Chutku made, newest first, and whether it can be undone, "
        "conflicts with a newer change by the owner, or cannot be undone (messages, web, typing).",
        Risk.OBSERVATION, preview, _validate_scope, argument_schema=_SCOPE, reversibility="not_applicable",
        success_predicate="rewind_plan_built"))
    registry.register(Tool("rewind.run", "Undo everything Chutku changed in a time window or task, newest first, "
        "including later changes that depend on it. Never overwrites a newer change by the owner. Asks once with the "
        "full list.", Risk.DATA_MODIFICATION, run, _validate_scope, resource_access="modify", argument_schema=_SCOPE,
        reversibility="journaled", success_predicate="every_ok_inverse_verified"))
