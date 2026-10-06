"""Episodic timeline tools (master plan S21): "wo PDF jo kal shaam khola tha", and the owner-only on/off switch."""
from __future__ import annotations

from pathlib import Path

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_SEARCH = {"type": "object", "properties": {
    "query": {"type": "string", "maxLength": 120},
    "when": {"type": "string", "maxLength": 60}}, "additionalProperties": False}
_SWITCH = {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"], "additionalProperties": False}


def _root():
    from chutku import mind
    return Path(mind.PROJECT_ROOT)


def _validate_search(arguments):
    if set(arguments) - {"query", "when"} or not all(isinstance(v, str) for v in arguments.values()):
        raise ValueError("Give query and/or when as text.")


def _validate_switch(arguments):
    if set(arguments) != {"on"} or type(arguments["on"]) is not bool:
        raise ValueError("Give on: true or false.")


def register_timeline_tools(registry, runtime=None):
    from chutku import timeline

    def search(arguments, _context):
        if not timeline.enabled(_root()) and not timeline.path(_root()).exists():
            return ToolResult({"matches": [], "recording": False,
                               "note": "The timeline is off. Type 'timeline on' to let Chutku remember which window "
                                       "was in front (titles only, 14 days)."}, Verification.PASS)
        return ToolResult(timeline.search(_root(), arguments.get("query", ""), arguments.get("when"),
                                          runtime=runtime), Verification.PASS)

    def switch(arguments, _context):
        from chutku.core.preferences import Preferences
        prefs = Preferences(_root())
        prefs.update({"timeline": bool(arguments["on"])})
        if not arguments["on"]:
            timeline.clear(_root())   # off keeps nothing
        now = prefs.load()["timeline"]
        ok = now == bool(arguments["on"]) and (arguments["on"] or not timeline.path(_root()).exists())
        return ToolResult({"timeline": now}, Verification.PASS if ok else Verification.FAIL)

    registry.register(Tool("timeline.search", "Which window, document or page was in front at a time the owner "
        "describes: query (e.g. 'pdf', 'invoice') and when ('kal shaam', 'yesterday evening', 'today', 'abhi', 'last "
        "week'). Uses the opt-in timeline (window titles only) and the files Chutku opened.", Risk.OBSERVATION,
        search, _validate_search, argument_schema=_SEARCH, reversibility="not_applicable",
        success_predicate="timeline_read"))
    registry.register(Tool("settings.timeline", "Owner only: start (on) or stop (off) remembering which window is in "
        "front, titles only, for 14 days. Off also deletes what was stored.", Risk.REVERSIBLE, switch,
        _validate_switch, argument_schema=_SWITCH, reversibility="compensatable", success_predicate="preference_written",
        user_only=True))
