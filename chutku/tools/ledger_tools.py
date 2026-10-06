"""Earned-autonomy tools (master plan S16): "reliability batao" and the owner-only relax switch."""
from __future__ import annotations

from pathlib import Path

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
_SWITCH = {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"], "additionalProperties": False}


def _root():
    from chutku import mind
    return Path(mind.PROJECT_ROOT)


def _summary(_arguments, _context):
    from chutku.core.ledger import Ledger, unreliable, Reliability, wilson_lower, MIN_TRIALS
    rows = Ledger(_root() / "data" / "ledger.db").table(50)
    weak = [r for r in rows if unreliable(Reliability(r["trials"], r["passes"],
                                                      wilson_lower(r["passes"], r["trials"]) if r["trials"] >= MIN_TRIALS
                                                      else None, r["target"]))]
    total = sum(r["trials"] for r in rows)
    passed = sum(r["passes"] for r in rows)
    return ToolResult({"actions_measured": total, "worked": passed, "rate": round(passed / total, 3) if total else None,
                       "by_action": rows[:15], "keeps_failing": weak[:10]}, Verification.PASS)


def _relax(arguments, _context):
    from chutku.core.preferences import Preferences
    prefs = Preferences(_root())
    prefs.update({"earned_autonomy_relax": bool(arguments["on"])})
    now = prefs.load()["earned_autonomy_relax"]
    return ToolResult({"earned_autonomy_relax": now}, Verification.PASS if now == bool(arguments["on"])
                      else Verification.FAIL)


def _validate_none(arguments):
    if arguments:
        raise ValueError("This takes no arguments.")


def _validate_switch(arguments):
    if set(arguments) != {"on"} or type(arguments["on"]) is not bool:
        raise ValueError("Give on: true or false.")


def register_ledger_tools(registry):
    registry.register(Tool("ledger.summary", "How reliable Chutku has been: per action, how often it really worked "
        "(checked after each step), and which kinds of steps keep failing.", Risk.OBSERVATION, _summary,
        _validate_none, argument_schema=_NONE, reversibility="not_applicable", success_predicate="ledger_read"))
    registry.register(Tool("settings.earned_autonomy", "Owner only: let file changes that worked 20+ times in a row "
        "on the same place run without asking (on), or always ask again (off).", Risk.REVERSIBLE, _relax,
        _validate_switch, argument_schema=_SWITCH, reversibility="compensatable",
        success_predicate="preference_written", user_only=True))
