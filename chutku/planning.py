"""The deterministic brain boundary, independent of any language model.

Understanding produces a typed proposal. Only Runtime can authorize and execute.
Unmatched requests ask for clarification; they never silently invoke an LLM.
"""
from dataclasses import asdict, dataclass, field
from typing import Any

from chutku.core.task import Task, TaskState
from chutku.router.catalog import CommandCatalog


@dataclass(frozen=True)
class RequestPlan:
    state: str
    reason: str
    intent: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    router: str = "deterministic_catalog"

    def to_dict(self):
        return asdict(self)


def plan_request(message: str) -> RequestPlan:
    if not isinstance(message, str) or not message.strip() or len(message) > 70000:
        return RequestPlan("CLARIFYING", "Please enter a request of 1 to 70000 characters.")
    try:
        command = CommandCatalog().route(message)
    except ValueError as error:
        return RequestPlan("CLARIFYING", str(error))
    return RequestPlan(
        "READY",
        "Matched a supported command. Runtime authorization and verification are still required.",
        intent=command.intent,
        tool=command.tool_name,
        arguments=command.arguments,
    )


def execute_request(message, runtime, *, provenance="user_stated"):
    plan = plan_request(message)
    if plan.state == "READY":
        return runtime.run(plan.tool, plan.arguments, provenance=provenance)
    task = Task(command="brain.clarify")
    runtime.event_log.append(task.task_id, "task_received", {"tool": task.command, "arguments": {}})
    runtime._transition(task, TaskState.UNDERSTANDING)
    runtime._transition(task, TaskState.CLARIFYING)
    return {"task_id": task.task_id, "state": task.state, "reason": plan.reason}
