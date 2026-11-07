"""H14 (Hermes execute_code, without running code): one planned step that repeats a tool for every item of a list.

The planner proposes `steps.for_each` with the list's source (an earlier step and a small JSONPath), the tool and its
arguments with `{item}` (or `{item_name}`, the last part of a path) where each item goes. The agent session expands
it into ordinary steps. Every item still runs through Runtime.run, so grants, policy, taint and verification apply to
each one. The first item that needs a click shows one card for the whole list. Approving it covers only these exact
items (agent_loop.AgentSession.decide); a DENY stops the run.

Not allowed: tools above risk 2, deleting tools, code runners, owner-only tools, messages and emails (no bulk sends),
and for_each inside for_each.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
import re

from chutku.tools.registry import Risk, Tool, ToolResult, Verification, check_schema

TOOL = "steps.for_each"
MAX_ITEMS = 50
BLOCKED_PREFIXES = ("message.", "email.", "steps.", "task.delegate", "telegram.", "skill.")

SCHEMA = {"type": "object", "properties": {
    "from_step": {"type": "integer", "minimum": 1, "maximum": 120},
    "path": {"type": "string", "minLength": 1, "maxLength": 120},
    "tool": {"type": "string", "minLength": 3, "maxLength": 80},
    "arguments": {"type": "object"},
    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS},
}, "required": ["from_step", "path", "tool", "arguments"], "additionalProperties": False}

_TOKEN = re.compile(r"\.?([A-Za-z_]\w*)|\[\*\]|\[\?\(@\.(\w+)\s*==\s*'([^']{0,40})'\)\]")


def select(data, path):
    """The values at `path` in `data`. A small JSONPath subset: `a.b`, `[*]` and `[?(@.key=='value')]` (case-folded
    match). Any other syntax raises ValueError."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("The list path is empty.")
    path, position, current = path.strip().removeprefix("$"), 0, [data]
    while position < len(path):
        match = _TOKEN.match(path, position)
        if match is None or match.end() == position:
            raise ValueError(f"Unsupported list path near {path[position:position + 20]!r}.")
        position = match.end()
        name, key, wanted = match.groups()
        if name is not None:
            current = [item[name] for item in current if isinstance(item, dict) and name in item]
            continue
        flat = [element for item in current if isinstance(item, list) for element in item]
        if key is not None:
            flat = [element for element in flat if isinstance(element, dict)
                    and str(element.get(key, "")).casefold() == wanted.casefold()]
        current = flat
    return current


def _fill(value, item):
    """Put the item where the planner wrote {item} / {item_name}."""
    if isinstance(value, str):
        if value == "{item}":
            return item
        name = PureWindowsPath(str(item)).name if isinstance(item, str) else str(item)
        return value.replace("{item_name}", name).replace("{item}", str(item))
    if isinstance(value, dict):
        return {key: _fill(element, item) for key, element in value.items()}
    if isinstance(value, list):
        return [_fill(element, item) for element in value]
    return value


def _uses_item(value):
    if isinstance(value, str):
        return "{item}" in value or "{item_name}" in value
    if isinstance(value, dict):
        return any(_uses_item(element) for element in value.values())
    if isinstance(value, list):
        return any(_uses_item(element) for element in value)
    return False


def allowed(tool):
    """Tools for-each may repeat (fail closed)."""
    return (not tool.name.startswith(BLOCKED_PREFIXES) and int(tool.base_risk) <= int(Risk.DATA_MODIFICATION)
            and not tool.deletes and not tool.runs_code and not tool.user_only)


def expand(arguments, outputs, registry, done=frozenset()):
    """The expanded steps for one steps.for_each call, plus a summary. `outputs` maps a step number (1-based) to that
    COMPLETED step's raw output. `done` holds (tool, arguments-json) signatures already completed in this session:
    those items are skipped, so a re-planned for_each never runs an item twice. Raises ValueError (nothing runs)."""
    import json
    check_schema(arguments, SCHEMA, "steps.for_each arguments")
    try:
        tool = registry.get(arguments["tool"])
    except KeyError:
        raise ValueError(f"{arguments['tool']} is not a tool.") from None
    if not allowed(tool):
        raise ValueError(f"{tool.name} cannot run for many items at once (only reversible, low-risk tools; "
                         "never messages, deletions or code).")
    if not _uses_item(arguments["arguments"]):
        raise ValueError("The arguments must say where each item goes ({item} or {item_name}).")
    source = outputs.get(arguments["from_step"])
    if source is None:
        raise ValueError(f"Step {arguments['from_step']} has no completed result to take the list from.")
    items = select(source, arguments["path"])
    if any(not isinstance(item, (str, int, float)) or isinstance(item, bool) for item in items):
        raise ValueError("The list path must point at plain values (e.g. files[*].path), not objects.")
    unique = list(dict.fromkeys(items))
    if not unique:
        raise ValueError("That list is empty: nothing to repeat.")
    limit = min(arguments.get("limit", MAX_ITEMS), MAX_ITEMS)
    steps, skipped = [], 0
    for item in unique[:limit]:
        filled = _fill(arguments["arguments"], item)
        check_schema(filled, tool.argument_schema, f"{tool.name} for {str(item)[:60]}")
        tool.validate_arguments(filled)
        if (tool.name, json.dumps(filled, sort_keys=True, default=str)) in done:
            skipped += 1
            continue
        steps.append({"tool": tool.name, "arguments": filled,
                      "purpose": f"{tool.name} for {PureWindowsPath(str(item)).name or item}"[:160]})
    summary = {"tool": tool.name, "items": len(steps), "found": len(unique), "skipped_done": skipped,
               "capped": max(0, len(unique) - limit)}
    return steps, summary


def _refuse_direct(_arguments, _context):
    return ToolResult({"error": "steps.for_each runs only inside a planned task."}, Verification.FAIL)


def register_for_each_tool(registry):
    registry.register(Tool(
        TOOL, "Repeat ONE tool for all / every / each item (saari, sabhi, har) of a list that an earlier step "
        "returned, in one step instead of one round per item: from_step = that step's number in STEPS, path = where "
        "the list is in its result (e.g. matches[*].path, files[?(@.ext=='.pdf')].path), tool + arguments with {item} "
        "(or {item_name}, the file name) where each item goes, limit <= 50. Only reversible low-risk tools (move, "
        "copy, open, rename...): never deletes, messages or code. All items share one approval.",
        Risk.OBSERVATION, _refuse_direct, argument_schema=SCHEMA))
