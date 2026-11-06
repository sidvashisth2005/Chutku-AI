"""Standing goals (H24, from Hermes `/goal`): a goal stays across conversations and is checked without a model.

"goal: is hafte DBMS ke 5 chapter ke notes, D:\\Study\\DBMS mein" -> a goal whose criterion is "5 files in that folder",
due at the end of this week. Criteria are checked from the PC itself:
    folder_count   at least N files directly in a folder   (a number and a folder path in the goal)
    file_exists    a file exists                            (a file path in the goal)
    said_done      the owner says it is done ("goal 2 ho gaya")
"mere goals" shows each goal with its progress ("3/5, 2 din bache"). Stored in data/goals.json.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re

MAX_GOALS = 20
_FILE_PATH = re.compile(r"[A-Za-z]:\\[^\n,;\"]*?\.[A-Za-z0-9]{1,5}\b")   # a file path ends at its extension
_PATH = re.compile(r"[A-Za-z]:\\[^\n,;\"]*?(?=\s+(?:mein|me|main|in|par|pe)\b|[,;\"]|\s*$)")
_COUNT = re.compile(r"\b(\d{1,3})\b")


def _file(base):
    return Path(base) / "data" / "goals.json"


def load(base):
    try:
        goals = json.loads(_file(base).read_text(encoding="utf-8"))
        return goals if isinstance(goals, list) else []
    except (OSError, ValueError):
        return []


def _save(base, goals):
    path = _file(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(goals, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)


def due_from(text, now=None):
    """End of the period the goal names, or None: "is hafte" (Sunday night), "aaj", "kal tak", "N din mein"."""
    now = now or datetime.now()
    end_of = lambda day: day.replace(hour=23, minute=59, second=0, microsecond=0)   # noqa: E731
    lowered = text.casefold()
    days = re.search(r"\b(\d{1,2})\s*(?:din|days?)\b", lowered)
    if days:
        return end_of(now + timedelta(days=int(days.group(1))))
    if re.search(r"\b(?:is|iss|this)\s+(?:hafte|week)\b", lowered):
        return end_of(now + timedelta(days=6 - now.weekday()))
    if re.search(r"\bkal\s+tak\b|\bby\s+tomorrow\b", lowered):
        return end_of(now + timedelta(days=1))
    if re.search(r"\baaj\b|\btoday\b", lowered):
        return end_of(now)
    return None


def criterion_from(text):
    path = _FILE_PATH.search(text) or _PATH.search(text)
    if path:
        folder = path.group(0).strip().rstrip("\\. ")
        count = [int(n) for n in _COUNT.findall(text[:path.start()] + text[path.end():]) if 0 < int(n) <= 500]
        if count:
            return {"kind": "folder_count", "path": folder, "count": count[0]}
        return {"kind": "file_exists", "path": folder}
    return {"kind": "said_done"}


def add(base, text, now=None):
    text = " ".join(str(text or "").split())
    if not 3 <= len(text) <= 300:
        raise ValueError("Say the goal in a few words (up to 300 characters).")
    goals = load(base)
    if len([g for g in goals if g["status"] == "open"]) >= MAX_GOALS:
        raise ValueError(f"{MAX_GOALS} goals are open already. Finish or remove one first.")
    now = now or datetime.now()
    due = due_from(text, now)
    goal = {"id": max([g["id"] for g in goals] or [0]) + 1, "text": text, "criterion": criterion_from(text),
            "due": due.isoformat(timespec="minutes") if due else None, "created": now.isoformat(timespec="minutes"),
            "status": "open"}
    goals.append(goal)
    _save(base, goals)
    return goal


def progress(goal):
    """(done, needed) for a goal's criterion, read from the PC."""
    criterion = goal["criterion"]
    if criterion["kind"] == "folder_count":
        folder = Path(criterion["path"])
        found = sum(1 for p in folder.iterdir() if p.is_file()) if folder.is_dir() else 0
        return min(found, criterion["count"]), criterion["count"]
    if criterion["kind"] == "file_exists":
        return int(Path(criterion["path"]).exists()), 1
    return int(bool(goal.get("said_done"))), 1


def check(base, now=None):
    """Every open goal with its progress; a goal whose criterion is met becomes done."""
    now = now or datetime.now()
    goals, rows, changed = load(base), [], False
    for goal in goals:
        if goal["status"] != "open":
            continue
        done, needed = progress(goal)
        if done >= needed:
            goal["status"], goal["finished"], changed = "done", now.isoformat(timespec="minutes"), True
        left = None
        if goal.get("due"):
            left = (datetime.fromisoformat(goal["due"]) - now).days
        rows.append({"id": goal["id"], "text": goal["text"], "done": done, "needed": needed, "status": goal["status"],
                     "days_left": left, "overdue": left is not None and left < 0 and goal["status"] == "open"})
    if changed:
        _save(base, goals)
    return rows


def describe(rows):
    if not rows:
        return "Koi goal nahi hai. Bolo: \"goal: <kya karna hai>\"."
    lines = []
    for row in rows:
        state = "pura! 🎉" if row["status"] == "done" else f"{row['done']}/{row['needed']}"
        if row["status"] == "open" and row["days_left"] is not None:
            state += ", time nikal gaya: aage badhaun ya hata dun?" if row["overdue"] else \
                f", {row['days_left']} din bache"
        lines.append(f"{row['id']}. {row['text']}: {state}")
    return "\n".join(lines)


def mark_done(base, goal_id):
    goals = load(base)
    goal = next((g for g in goals if g["id"] == goal_id and g["status"] == "open"), None)
    if goal is None:
        raise ValueError(f"No open goal {goal_id}.")
    goal["said_done"] = True
    _save(base, goals)
    return check(base)


def remove(base, goal_id):
    goals = load(base)
    if not any(g["id"] == goal_id for g in goals):
        raise ValueError(f"No goal {goal_id}.")
    _save(base, [g for g in goals if g["id"] != goal_id])
    return goal_id


def register_goal_tools(registry, base):
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification
    from chutku.tools.everyday import EMPTY_ARGUMENT_SCHEMA, _validate_none

    def safely(work):
        def run(arguments, _context):
            try:
                return work(arguments)
            except (ValueError, OSError) as error:
                return ToolResult({"error": str(error)[:300]}, Verification.FAIL)
        return run

    def schema(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def check_args(names):
        def validate(arguments):
            if set(arguments) != set(names):
                raise ValueError(f"Provide {', '.join(names)}.")
        return validate

    def adding(arguments):
        goal = add(base, arguments["text"])
        return ToolResult({"goal": goal, "progress": describe(check(base))}, Verification.PASS)

    def listing(_arguments):
        rows = check(base)
        return ToolResult({"goals": rows, "summary": describe(rows)}, Verification.PASS)

    def finishing(arguments):
        rows = mark_done(base, int(arguments["id"]))
        return ToolResult({"goals": rows, "summary": describe(rows)}, Verification.PASS)

    def removing(arguments):
        return ToolResult({"removed": remove(base, int(arguments["id"]))}, Verification.PASS)

    goal_id = {"id": {"type": "integer", "minimum": 1, "maximum": 100000}}
    registry.register(Tool("goals.add", "Set a standing goal that Chutku tracks across days (\"goal: 5 notes in "
        "D:\\Study this week\"); progress is checked from the PC.", Risk.REVERSIBLE, safely(adding),
        check_args(("text",)), argument_schema=schema({"text": {"type": "string", "minLength": 3, "maxLength": 300}}),
        reversibility="compensatable", success_predicate="goal_saved"))
    registry.register(Tool("goals.list", "Show the owner's standing goals with live progress and days left.",
        Risk.OBSERVATION, safely(listing), _validate_none, argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="goals_listed"))
    registry.register(Tool("goals.done", "The owner says a goal is done (\"goal 2 ho gaya\").", Risk.REVERSIBLE,
        safely(finishing), check_args(("id",)), argument_schema=schema(goal_id), reversibility="compensatable",
        success_predicate="goal_marked"))
    registry.register(Tool("goals.remove", "Remove a standing goal (asks first).", Risk.DATA_MODIFICATION,
        safely(removing), check_args(("id",)), argument_schema=schema(goal_id), reversibility="irreversible",
        success_predicate="goal_removed", deletes=True))
