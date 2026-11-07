"""Named routines ("work mode", "focus mode"): up to four everyday commands run together.

Every command must be one that the deterministic router understands, checked when the routine
is saved, so a routine can never smuggle in an unparsed or model-planned step. Running a routine
goes through the normal agent loop, so each step still passes grants, policy and verification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

MAX_COMMANDS = 4
from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
NAME = re.compile(r"^[a-z][a-z0-9 -]{0,29}$")


def store_path() -> Path:
    return PROJECT_ROOT / "data" / "routines.json"


def load() -> dict[str, list[str]]:
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, list)} if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    from chutku.core.jsonstore import write_json
    write_json(store_path(), data)   # an unreadable file is copied aside, never silently replaced


def clean_name(name: str) -> str:
    return " ".join(str(name).casefold().split())


def steps_for(name: str):
    """The checked steps of a saved routine, or None if there is no such routine."""
    from chutku.quick_intents import _single
    commands = load().get(clean_name(name))
    if not commands:
        return None
    steps = []
    for command in commands:
        proposal = _single(command)
        if proposal is None or not proposal["next_steps"]:
            return None  # an app was uninstalled since saving: let the model handle it
        steps.extend(proposal["next_steps"])
    return steps[:MAX_COMMANDS]


def _validate_save(arguments):
    if set(arguments) != {"name", "commands"} or not isinstance(arguments["name"], str):
        raise ValueError("Provide a routine name and its commands.")
    if not NAME.match(clean_name(arguments["name"])):
        raise ValueError("Routine names use letters, numbers, spaces or dashes (up to 30).")
    commands = arguments["commands"]
    if (not isinstance(commands, list) or not 1 <= len(commands) <= MAX_COMMANDS
            or any(not isinstance(c, str) or not 1 <= len(c.strip()) <= 200 for c in commands)):
        raise ValueError(f"A routine has 1 to {MAX_COMMANDS} short commands.")


def _save(arguments, context):
    from chutku.quick_intents import _single
    name = clean_name(arguments["name"])
    commands = [" ".join(c.split()) for c in arguments["commands"]]
    unknown = [c for c in commands if _single(c) is None or not _single(c)["next_steps"]
               or _single(c)["next_steps"][0]["tool"].startswith("routine.")]
    if unknown:
        return ToolResult({"error": "I can't run these instantly, so they can't go in a routine: "
                                    + "; ".join(unknown)}, Verification.FAIL)
    if sum(len(_single(c)["next_steps"]) for c in commands) > MAX_COMMANDS:
        return ToolResult({"error": f"That routine needs more than {MAX_COMMANDS} steps."}, Verification.FAIL)
    data = load()
    previous = data.get(name)
    data[name] = commands
    _write(data)
    return ToolResult({"name": name, "commands": commands, "replaced": previous}, Verification.PASS)


def _list(arguments, context):
    return ToolResult({"routines": load()}, Verification.PASS)


def _forget(arguments, context):
    data = load()
    name = clean_name(arguments["name"])
    if name not in data:
        return ToolResult({"error": f"There is no routine called {name}."}, Verification.FAIL)
    removed = data.pop(name)
    _write(data)
    return ToolResult({"name": name, "removed_commands": removed}, Verification.PASS)


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This takes no arguments.")


def _validate_name(arguments):
    if set(arguments) != {"name"} or not isinstance(arguments["name"], str) or not NAME.match(clean_name(arguments["name"])):
        raise ValueError("Provide the routine name.")


def register_routine_tools(registry):
    registry.register(Tool("routine.save", f"Save a named routine of 1-{MAX_COMMANDS} everyday commands (e.g. "
        "work: open VS Code, play lofi on YouTube, set volume to 30). Start it later with 'start <name> mode'.",
        Risk.REVERSIBLE, _save, _validate_save, argument_schema={"type": "object", "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 30},
            "commands": {"type": "array", "minItems": 1, "maxItems": MAX_COMMANDS,
                         "items": {"type": "string", "minLength": 1, "maxLength": 200}}},
            "required": ["name", "commands"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="routine_written_previous_version_returned"))
    registry.register(Tool("routine.list", "List saved routines and their commands.", Risk.OBSERVATION, _list,
        _no_arguments,
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable", success_predicate="routines_read"))
    registry.register(Tool("routine.forget", "Delete one saved routine by name.", Risk.DATA_MODIFICATION, _forget,
        _validate_name, argument_schema={"type": "object", "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 30}}, "required": ["name"],
            "additionalProperties": False}, reversibility="irreversible", deletes=True,
        success_predicate="routine_removed"))
