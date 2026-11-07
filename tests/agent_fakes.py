"""Small fakes for agent-session tests that must run without Windows grants (H14, H18, H15).

The registry is the real one (every built-in tool, plus steps.for_each), so arguments are checked against the real
tool contracts. Execution is faked: nothing touches the PC.
"""
from __future__ import annotations

import itertools

from chutku.for_each import register_for_each_tool
from chutku.tools.builtin import register_builtin_tools
from chutku.tools.registry import ToolRegistry


def real_registry():
    registry = ToolRegistry()
    register_builtin_tools(registry)
    register_for_each_tool(registry)
    return registry


class _Control:
    def check(self):
        return None


class _Grant:
    grant_id = "sandbox"


class FakeRuntime:
    """run() answers from `outputs` (tool -> output dict); tools in `ask` wait for a click first; tools in `deny`
    are DENIED. Every call is recorded in `calls` as (tool, arguments, tainted)."""

    def __init__(self, outputs=None, *, ask=(), deny=(), fail=()):
        self.registry = real_registry()
        self.outputs, self.ask, self.deny, self.fail = dict(outputs or {}), set(ask), set(deny), set(fail)
        self.calls, self.approved, self.cancelled = [], [], []
        self.action_control, self.resource_grant, self.resource_grants = _Control(), _Grant(), None
        self.approvals, self.control_root = None, None
        self._tokens, self._waiting = itertools.count(1), {}

    def run(self, tool, arguments, **kwargs):
        self.calls.append((tool, arguments, kwargs.get("tainted")))
        if tool in self.deny:
            return {"state": "DENIED", "reason": f"{tool} is not allowed here"}
        if tool in self.fail:
            return {"state": "FAILED", "error": f"{tool} failed"}
        if tool in self.ask:
            token = f"t{next(self._tokens)}"
            self._waiting[token] = (tool, arguments)
            return {"state": "WAITING_CONFIRMATION", "reason": "asks",
                    "approval": {"token": token, "tool": tool, "arguments": arguments, "risk": 2}}
        return {"state": "COMPLETED", "verification": "PASS", "output": self.outputs.get(tool, {"ok": True})}

    def approve(self, token, cancel=False):
        tool, arguments = self._waiting.pop(token)
        if cancel:
            self.cancelled.append((tool, arguments))
            return {"state": "CANCELLED"}
        self.approved.append((tool, arguments))
        return {"state": "COMPLETED", "verification": "PASS", "output": self.outputs.get(tool, {"ok": True})}

    def close(self):
        return None


class ScriptedPlanner:
    """Returns one prepared proposal per planning round; records each planner_input it saw."""
    name = "scripted"

    def __init__(self, *rounds):
        self.rounds, self.seen = list(rounds), []

    def propose(self, session, runtime, check=None):
        self.seen.append(session.planner_input())
        if not self.rounds:
            return {"status": "done", "reply": "Done.", "declared_plan": [], "next_steps": [], "finish": False}, \
                {"planner": self.name}
        return self.rounds.pop(0), {"planner": self.name}


def continue_with(*steps, finish=False, reply="Working on it."):
    return {"status": "continue", "reply": reply, "declared_plan": [s["tool"] for s in steps],
            "next_steps": [dict(s, purpose=s.get("purpose", "step")) for s in steps], "finish": finish}
