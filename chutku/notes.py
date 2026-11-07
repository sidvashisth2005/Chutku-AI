"""A small to-do / notes list: "note: buy milk", "show my list", "mark 2 done".

Stored in data/notes.json (Chutku's own data, not the user's documents). Items are numbered;
marking one done is reversible ("mark 2 not done"); finished items are hidden after 7 days.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import threading

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
MAX_ITEMS = 200
_lock = threading.Lock()


def store_path() -> Path:
    return PROJECT_ROOT / "data" / "notes.json"


def load() -> list[dict]:
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict) and {"id", "text"} <= set(item)] \
        if isinstance(data, list) else []


def _write(items):
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def visible(items=None, now=None):
    """Open items first, then items finished in the last 7 days."""
    now = now or datetime.now()
    items = load() if items is None else items
    recent = (now - timedelta(days=7)).isoformat(timespec="minutes")
    open_items = [i for i in items if not i.get("done")]
    finished = [i for i in items if i.get("done") and i.get("done") >= recent]
    return open_items + finished


def _add(arguments, context):
    text = " ".join(arguments["text"].split())
    from chutku import scan
    try:
        scan.check(text, instructions=False)   # hidden characters only: a note is the owner's own words (H3)
    except ValueError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    with _lock:
        items = load()
        if any(" ".join(i["text"].split()).casefold() == text.casefold() and not i.get("done") for i in items):
            return ToolResult({"error": "Ye pehle se list mein hai.", "duplicate": True}, Verification.FAIL)
        if sum(not i.get("done") for i in items) >= MAX_ITEMS:
            return ToolResult({"error": f"The list already has {MAX_ITEMS} open items."}, Verification.FAIL)
        number = max((i["id"] for i in items), default=0) + 1
        items.append({"id": number, "text": text, "created": datetime.now().isoformat(timespec="minutes"),
                      "done": None})
        _write(items)
    return ToolResult({"id": number, "text": text, "open": sum(not i.get("done") for i in items)}, Verification.PASS)


def _list(arguments, context):
    shown = visible()
    return ToolResult({"items": [{"id": i["id"], "text": i["text"], "done": bool(i.get("done"))} for i in shown]},
                      Verification.PASS, {"count": len(shown), "items": "[REDACTED]"})


def _mark(arguments, context):
    with _lock:
        items = load()
        item = next((i for i in items if i["id"] == arguments["id"]), None)
        if item is None:
            return ToolResult({"error": f"There is no item number {arguments['id']}."}, Verification.FAIL)
        item["done"] = datetime.now().isoformat(timespec="minutes") if arguments.get("done", True) else None
        _write(items)
    return ToolResult({"id": item["id"], "text": item["text"], "done": bool(item["done"])}, Verification.PASS)


def _validate_add(arguments):
    if set(arguments) != {"text"} or not isinstance(arguments["text"], str) or not 1 <= len(arguments["text"].strip()) <= 300:
        raise ValueError("Give the note text (up to 300 characters).")


def _validate_mark(arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"id", "done"} or type(arguments.get("id")) is not int \
            or arguments["id"] < 1 or type(arguments.get("done", True)) is not bool:
        raise ValueError("Give the item number, and done true/false.")


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This takes no arguments.")


def register_note_tools(registry):
    registry.register(Tool("note.add", "Add an item to the user's to-do / notes list (e.g. 'buy milk').",
        Risk.REVERSIBLE, _add, _validate_add, argument_schema={"type": "object", "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 300}}, "required": ["text"],
            "additionalProperties": False},
        reversibility="compensatable", success_predicate="note_stored"))
    registry.register(Tool("note.list", "Show the to-do / notes list with item numbers.", Risk.OBSERVATION, _list,
        _no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="notes_read"))
    registry.register(Tool("note.done", "Mark a to-do item done by number (done=false to reopen it).",
        Risk.REVERSIBLE, _mark, _validate_mark, argument_schema={"type": "object", "properties": {
            "id": {"type": "integer", "minimum": 1}, "done": {"type": "boolean"}}, "required": ["id"],
            "additionalProperties": False},
        reversibility="compensatable", success_predicate="note_state_written"))
