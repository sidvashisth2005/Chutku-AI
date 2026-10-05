"""Reviewed cross-tool plans with manifest binding and declared reverse recovery."""
from __future__ import annotations

from copy import deepcopy
import secrets


MAX_STEPS = 8


def build_orchestration(steps, runtime):
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("An orchestration requires 1-8 exact steps.")
    result = []
    for index, raw in enumerate(steps, 1):
        if not isinstance(raw, dict) or set(raw) != {"tool", "arguments", "compensation"}:
            raise ValueError(f"Step {index} must declare tool, arguments and compensation.")
        tool = runtime.registry.get(raw["tool"]); tool.validate_arguments(raw["arguments"])
        compensation = raw["compensation"]
        if compensation is not None:
            if not isinstance(compensation, dict) or set(compensation) != {"tool", "arguments"}:
                raise ValueError(f"Step {index} has an invalid compensation.")
            undo = runtime.registry.get(compensation["tool"]); undo.validate_arguments(compensation["arguments"])
            compensation = {"tool": undo.name, "arguments": deepcopy(compensation["arguments"]),
                            "manifest_version": undo.manifest_version()}
        elif tool.reversibility not in {"not_applicable", "browser_closes_after_observation"}:
            raise ValueError(f"Step {index} can have effects and requires an explicit compensation.")
        result.append({"index": index, "tool": tool.name, "arguments": deepcopy(raw["arguments"]),
                       "manifest_version": tool.manifest_version(), "compensation": compensation})
    return {"version": 1, "steps": result, "review_required": True,
            "notes": ["Review every forward and recovery action.",
                      "Execution stops on first failure; completed steps recover in reverse order."]}


def _still_bound(call, runtime):
    return runtime.registry.get(call["tool"]).manifest_version() == call["manifest_version"]


def _run(call, runtime, approve):
    if not _still_bound(call, runtime):
        return {"state": "FAILED", "error": "Tool contract changed after review."}
    result = runtime.run(call["tool"], call["arguments"])
    if str(result.get("state")) == "WAITING_CONFIRMATION":
        if approve is None or approve(result.get("approval")) is not True:
            return runtime.approve(result["approval"]["token"], cancel=True)
        return runtime.approve(result["approval"]["token"])
    return result


def run_orchestration(plan, runtime, *, approve=None):
    if not isinstance(plan, dict) or set(plan) != {"version", "steps", "review_required", "notes"} or plan.get("version") != 1:
        raise ValueError("Invalid reviewed orchestration.")
    completed = []; forward = []; recovery = []
    failure = None
    for step in plan["steps"]:
        result = _run(step, runtime, approve)
        summary = {"index": step["index"], "tool": step["tool"], "state": str(result.get("state")),
                   "task_id": result.get("task_id")}
        forward.append(summary)
        if str(result.get("state")) != "COMPLETED":
            failure = f"Step {step['index']} failed or was denied."
            break
        completed.append(step)
    if failure is not None:
        for step in reversed(completed):
            call = step["compensation"]
            if call is None:
                continue
            result = _run(call, runtime, approve)
            recovery.append({"for_index": step["index"], "tool": call["tool"],
                             "state": str(result.get("state")), "task_id": result.get("task_id")})
        recovered = all(item["state"] == "COMPLETED" for item in recovery)
        return {"state": "FAILED", "verification": "FAIL", "message": failure,
                "forward": forward, "recovery": recovery, "recovered": recovered}
    return {"state": "COMPLETED", "verification": "PASS", "message": f"Completed all {len(forward)} reviewed steps.",
            "forward": forward, "recovery": [], "recovered": False}


class OrchestrationCoordinator:
    """Keeps the exact reviewed plan server-side behind a random single-use token."""
    def __init__(self, runtime):
        self.runtime = runtime
        self._pending = {}

    def prepare(self, steps):
        if len(self._pending) >= 16:
            raise ValueError("Too many orchestrations await review.")
        plan = build_orchestration(steps, self.runtime)
        token = secrets.token_urlsafe(32)
        self._pending[token] = deepcopy(plan)
        return {"token": token, "plan": deepcopy(plan), "single_use": True}

    def execute(self, token, *, approve=None):
        if not isinstance(token, str) or token not in self._pending:
            raise ValueError("Orchestration token is invalid or already used.")
        plan = self._pending.pop(token)
        return run_orchestration(plan, self.runtime, approve=approve)

    def cancel(self, token):
        return self._pending.pop(token, None) is not None
