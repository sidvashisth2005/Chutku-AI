from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_hex
from time import time_ns


class TaskState(StrEnum):
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    AUTHORIZING = "AUTHORIZING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CLARIFYING = "CLARIFYING"


_TRANSITIONS = {
    TaskState.RECEIVED: {TaskState.UNDERSTANDING, TaskState.FAILED},
    TaskState.UNDERSTANDING: {TaskState.PLANNING, TaskState.CLARIFYING, TaskState.FAILED},
    TaskState.PLANNING: {TaskState.AUTHORIZING, TaskState.FAILED},
    TaskState.AUTHORIZING: {TaskState.EXECUTING, TaskState.DENIED, TaskState.WAITING_CONFIRMATION, TaskState.FAILED},
    TaskState.EXECUTING: {TaskState.VERIFYING, TaskState.FAILED},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.WAITING_CONFIRMATION: {TaskState.AUTHORIZING, TaskState.DENIED, TaskState.FAILED},
}


def new_task_id() -> str:
    """Sortable, collision-resistant identifier; replace with a standards ULID library when dependencies are introduced."""
    return f"CHUTKU-{time_ns():x}-{token_hex(4)}"


@dataclass
class Task:
    command: str
    task_id: str = field(default_factory=new_task_id)
    state: TaskState = TaskState.RECEIVED

    def transition(self, target: TaskState) -> None:
        if target not in _TRANSITIONS.get(self.state, set()):
            raise ValueError(f"Invalid task transition: {self.state} -> {target}")
        self.state = target
