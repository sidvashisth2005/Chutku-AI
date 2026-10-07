"""The owner's "never" rules (Phase 3b H1): "D:\\Exams ko kabhi mat chhoona" / "never touch D:\\Exams".

Adding a rule only restricts Chutku, so it runs at once (the owner's own words only). Removing one widens what she
may do, so it always asks first, in every mode. The rules themselves live in data/never_rules.json and are checked by
chutku/policy/never_rules.py before any other policy rule.
"""
from __future__ import annotations

from pathlib import Path

from chutku.policy import never_rules
from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
_ADD = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": list(never_rules.RULE_KINDS)},
    "pattern": {"type": "string", "minLength": 1, "maxLength": 300}},
    "required": ["kind", "pattern"], "additionalProperties": False}
_REMOVE = {"type": "object", "properties": {"id": {"type": "string", "pattern": "^[0-9a-f]{6}$"}},
           "required": ["id"], "additionalProperties": False}


def _root():
    from chutku import mind
    return Path(mind.PROJECT_ROOT)


def _describe(rule):
    what = {"path": "kabhi nahi chhoona", "tool": "kabhi use nahi karna", "command": "kabhi nahi chalana"}[rule["kind"]]
    return f"[{rule['id']}] {rule['pattern']} — {what}"


def _add(arguments, _context):
    try:
        rule = never_rules.add_rule(_root(), arguments["kind"], arguments["pattern"], said=arguments["pattern"])
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    saved = any(r["id"] == rule["id"] for r in never_rules.load_rules(_root()))
    return ToolResult({"rule": _describe(rule), "already_there": bool(rule.get("existing"))},
                      Verification.PASS if saved else Verification.FAIL)


def _list(_arguments, _context):
    try:
        rules = never_rules.load_rules(_root())
    except (OSError, ValueError) as error:
        return ToolResult({"error": f"never_rules.json could not be read: {error}"}, Verification.FAIL)
    return ToolResult({"rules": [_describe(r) for r in rules], "count": len(rules)},
                      Verification.PASS)


def _remove(arguments, _context):
    try:
        removed = never_rules.remove_rule(_root(), arguments["id"])
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    if removed is None:
        return ToolResult({"error": f"No never-rule with id {arguments['id']}."}, Verification.FAIL)
    gone = all(r["id"] != arguments["id"] for r in never_rules.load_rules(_root()))
    return ToolResult({"removed": _describe(removed)}, Verification.PASS if gone else Verification.FAIL)


def _validate_none(arguments):
    if arguments:
        raise ValueError("This takes no arguments.")


def _validate_add(arguments):
    if set(arguments) != {"kind", "pattern"} or arguments["kind"] not in never_rules.RULE_KINDS \
            or not isinstance(arguments["pattern"], str) or not 0 < len(arguments["pattern"].strip()) <= 300:
        raise ValueError("Give kind (path, tool or command) and a pattern.")


def _validate_remove(arguments):
    if set(arguments) != {"id"} or not isinstance(arguments["id"], str) or len(arguments["id"]) != 6:
        raise ValueError("Give the 6-character rule id (see 'never rules').")


def register_never_tools(registry):
    registry.register(Tool("never.list", "List the owner's never-rules (paths, tools, commands Chutku must never "
        "touch) and the always-blocked command classes.", Risk.OBSERVATION, _list, _validate_none,
        argument_schema=_NONE, reversibility="not_applicable", success_predicate="never_rules_read"))
    registry.register(Tool("never.add", "Owner only: add a never-rule. kind=path (a folder or file, e.g. D:\\Exams), "
        "tool (a tool name or pattern) or command (text a script or command must never contain).", Risk.REVERSIBLE,
        _add, _validate_add, argument_schema=_ADD, reversibility="compensatable",
        success_predicate="never_rule_saved", user_only=True))
    registry.register(Tool("never.remove", "Owner only: remove a never-rule by id. Always asks first.",
        Risk.DATA_MODIFICATION, _remove, _validate_remove, argument_schema=_REMOVE, reversibility="none",
        success_predicate="never_rule_removed", user_only=True, deletes=True))
