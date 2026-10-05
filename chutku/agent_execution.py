"""Server-held execution state for reviewed general language-model plans."""
from __future__ import annotations

from copy import deepcopy
import secrets
import time

from chutku.brain import validate_bound_tool_plan


class AgentExecutionStore:
    """Execute reviewed steps in order and pause at action-time approvals."""

    def __init__(self, ttl: float = 600, limit: int = 16):
        self.ttl = ttl
        self.limit = limit
        self.pending = {}

    def _prune(self):
        now = time.monotonic()
        self.pending = {key: value for key, value in self.pending.items()
                        if value["expires"] > now}

    def prepare(self, plan, runtime, *, provenance):
        if provenance not in {"reviewed_inferred", "reviewed_microphone"}:
            raise ValueError("Invalid reviewed plan provenance.")
        validate_bound_tool_plan(plan, runtime)
        self._prune()
        if len(self.pending) >= self.limit:
            raise ValueError("Too many reviewed plans are awaiting execution.")
        token = secrets.token_urlsafe(32)
        self.pending[token] = {"expires": time.monotonic() + self.ttl,
                               "plan": deepcopy(plan), "provenance": provenance,
                               "cursor": 0, "results": [], "approval_token": None}
        return token

    def cancel(self, token, runtime):
        self._prune()
        state = self.pending.pop(token, None)
        if state is None:
            return False
        if state["approval_token"] is not None:
            runtime.approve(state["approval_token"], cancel=True)
        return True

    def start(self, token, runtime):
        return self._continue(token, runtime)

    def decide(self, token, runtime, *, approve):
        self._prune()
        state = self.pending.get(token)
        if state is None or state["approval_token"] is None:
            raise ValueError("No action-time approval is pending for this plan.")
        result = runtime.approve(state["approval_token"], cancel=approve is not True)
        state["approval_token"] = None
        self._record(state, result)
        if str(result.get("state")) != "COMPLETED":
            return self._finish(token, state, completed=False)
        state["cursor"] += 1
        return self._continue(token, runtime)

    @staticmethod
    def _record(state, result):
        step = state["plan"]["steps"][state["cursor"]]
        state["results"].append({"index": step["index"], "tool": step["tool"],
                                 "purpose": step["purpose"], "state": str(result.get("state")),
                                 "task_id": result.get("task_id"),
                                 "verification": result.get("verification"),
                                 "message": result.get("error") or result.get("reason")})

    def _continue(self, token, runtime):
        self._prune()
        state = self.pending.get(token)
        if state is None:
            raise ValueError("Execution token expired, was cancelled or already completed.")
        validate_bound_tool_plan(state["plan"], runtime)
        if state["approval_token"] is not None:
            raise ValueError("Resolve the pending action-time approval before continuing.")
        while state["cursor"] < len(state["plan"]["steps"]):
            step = state["plan"]["steps"][state["cursor"]]
            result = runtime.run(step["tool"], step["arguments"], provenance=state["provenance"])
            if str(result.get("state")) == "WAITING_CONFIRMATION":
                state["approval_token"] = result["approval"]["token"]
                return {"state": "WAITING_CONFIRMATION", "verification": "UNKNOWN",
                        "execution_token": token, "approval": result["approval"],
                        "plan_steps": deepcopy(state["results"]),
                        "next_step": {key: step[key] for key in ("index", "tool", "arguments", "purpose", "risk", "required_capability")},
                        "message": "Confirm or cancel this exact high-risk step to continue the reviewed plan."}
            self._record(state, result)
            if str(result.get("state")) != "COMPLETED":
                return self._finish(token, state, completed=False)
            state["cursor"] += 1
        return self._finish(token, state, completed=True)

    def _finish(self, token, state, *, completed):
        self.pending.pop(token, None)
        return {"state": "COMPLETED" if completed else "FAILED",
                "verification": "PASS" if completed else "FAIL",
                "plan_steps": deepcopy(state["results"]),
                "message": (f"Completed and verified all {len(state['results'])} reviewed steps."
                            if completed else "Stopped at the first denied, cancelled, failed or unverified step.")}
