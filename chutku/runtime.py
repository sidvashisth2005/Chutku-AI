from __future__ import annotations

from pathlib import Path
from typing import Any

from chutku.core import elevation
from chutku.core.action_log import ActionLog
from chutku.core.event_log import EventLog
from chutku.core.operation_journal import OperationJournal
from chutku.core.memory import MemoryStore
from chutku.core.execution_lock import ExecutionLock, ExecutionBusy
from chutku.core.action_control import ActionControl
from chutku.core.approvals import ApprovalStore
from chutku.core.resource_grants import ResourceGrant, ResourceGrantStore
from chutku.core.capability_grants import CapabilityGrantStore
from chutku.core.task import Task, TaskState
from chutku.core.paths import path_argument_names, protection_reason, sandbox_target
from chutku.policy.kernel import Decision, PolicyKernel
from chutku.tools.registry import ExecutionContext, ToolRegistry, Verification

# How to reverse a completed action (used by log.undo; each undo tool reverses only the latest of its kind).
UNDO_TOOLS = {
    "filesystem.write_text": "filesystem.undo_last_write",
    "filesystem.copy": "filesystem.undo_last_copy",
    "filesystem.move": "filesystem.undo_last_move",
    "filesystem.recycle": "filesystem.restore_last_recycled",
    "files.organize": "files.organize_undo",
    "screen.capture": "screen.undo_last_capture",
}


class Runtime:
    def __init__(self, registry: ToolRegistry, policy: PolicyKernel, event_log: EventLog, journal: OperationJournal,
                 granted_root: Path, memory: MemoryStore | None = None, *, resource_grants: ResourceGrantStore | None = None,
                 resource_grant: ResourceGrant | None = None, state_root: Path | None = None,
                 capability_grants: CapabilityGrantStore | None = None) -> None:
        self.registry = registry
        self.policy = policy
        self.event_log = event_log
        self.journal = journal
        self.granted_root = granted_root.resolve()
        self.memory = memory
        self.resource_grants = resource_grants
        self.capability_grants = capability_grants
        self.resource_grant = resource_grant or ResourceGrant(
            "direct", self.granted_root, frozenset({"observe", "modify"}), "runtime", False, True, "direct")
        control_root = (state_root or self.granted_root.parent).resolve()
        self.execution_lock = ExecutionLock(control_root / "data" / "execution.lock")
        self.action_control = ActionControl(control_root)
        self.approvals = ApprovalStore()
        self.action_log = ActionLog(control_root / "data" / "actions.log.jsonl")

    def close(self) -> None:
        self.event_log.close()
        self.journal.close()
        if self.memory is not None:
            self.memory.close()
        if self.resource_grants is not None:
            self.resource_grants.close()
        if self.capability_grants is not None:
            self.capability_grants.close()

    def current_grant(self) -> ResourceGrant:
        if self.resource_grants is None:
            return self.resource_grant
        current = self.resource_grants.get(self.resource_grant.grant_id)
        if current.snapshot() != self.resource_grant.snapshot():
            raise ValueError("The selected resource grant changed; start a new request.")
        return current

    def authorize(self, tool, arguments, confirmed=False, *, provenance="user_stated", autonomy=None, tainted=False,
                  exposed=None):
        access = self.current_grant().access if tool.resource_access is not None else None
        capability_allowed = None
        if tool.required_capability is not None:
            try:
                self.current_capability(tool.required_capability)
                capability_allowed = True
            except ValueError:
                capability_allowed = False
        return self.policy.authorize(tool, arguments, confirmed, provenance=provenance,
                                     resource_access=access, capability_allowed=capability_allowed,
                                     autonomy=autonomy, tainted=tainted, exposed=exposed,
                                     protected_reason=self.protected_target(tool, arguments),
                                     owner_question=self.owner_question(tool, arguments) if autonomy == "owner" else None)

    def owner_question(self, tool, arguments):
        """In owner mode a message to someone Chutku does not know yet still asks; once they are remembered,
        messages to them go straight out."""
        if tool.name in {"keyboard.keys", "keyboard.edit", "mouse.click", "mouse.drag"}:
            from chutku.tools.free_input import file_risk  # keys/clicks that would save, delete or move files
            return file_risk(tool.name, arguments)
        if tool.name != "message.send":
            return None
        from chutku.tools.apps_extra import known_recipient
        to = str(arguments.get("to", ""))
        if known_recipient(to, self.memory):
            return None
        return (f"{to} is not in your memory yet, so this message asks first. Say 'remember {to} is my ...' "
                "and later messages to them go straight out.")

    def protected_target(self, tool, arguments):
        """Deny modification of system/runtime areas regardless of grant, mode or approval."""
        if tool.resource_access != "modify":
            return None
        for key in sorted(path_argument_names(tool)):
            if key in arguments:
                try:
                    target = sandbox_target(self.granted_root, arguments[key])
                    reason = protection_reason(target)
                except (ValueError, OSError) as error:
                    # Fail closed: a location that cannot be resolved safely is never modified.
                    return f"The '{key}' location could not be resolved safely ({error}); Chutku will not modify it."
                if reason is not None:
                    return reason
        # Path-less modify tools only reverse Chutku's own journaled operations.
        return None

    def current_capability(self, capability):
        if self.capability_grants is None:
            raise ValueError("No PC capabilities are configured for this runtime.")
        return self.capability_grants.get(capability)

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _transition(self, task: Task, target: TaskState) -> None:
        previous = task.state
        task.transition(target)
        self.event_log.append(task.task_id, "task_state", {"from": previous, "to": target})

    @staticmethod
    def _redact(arguments: dict[str, Any], sensitive_names: frozenset[str]) -> dict[str, Any]:
        return {key: "[REDACTED]" if key in sensitive_names else value for key, value in arguments.items()}

    def run(self, tool_name: str, arguments: dict[str, Any], *, provenance: str = "user_stated",
            autonomy: str | None = None, tainted: bool = False, exposed: bool | None = None) -> dict[str, Any]:
        try:
            with self.execution_lock:
                result = self._run(tool_name, arguments, provenance=provenance, autonomy=autonomy, tainted=tainted,
                                   exposed=exposed)
                self._log_action(tool_name, arguments, result, provenance, autonomy)
                return result
        except ExecutionBusy as error:
            task = Task(command=tool_name)
            self.event_log.append(task.task_id, "task_received", {"tool": tool_name, "arguments": {}})
            self._transition(task, TaskState.FAILED)
            self.event_log.append(task.task_id, "runtime_error", {"type": "ExecutionBusy", "message": str(error)})
            return {"task_id": task.task_id, "state": TaskState.FAILED, "error": str(error)}

    def approve(self, token: str, *, cancel: bool = False) -> dict[str, Any]:
        with self.execution_lock:
            pending = self.approvals.take(token)
            if pending["root"] != str(self.granted_root):
                raise ValueError("Approval belongs to a different granted root.")
            if pending.get("grant") != self.current_grant().snapshot():
                raise ValueError("Resource grant changed after approval was requested.")
            capability = pending.get("capability")
            if capability is not None and self.current_capability(capability["capability"]).snapshot() != capability:
                raise ValueError("PC capability grant changed after approval was requested.")
            current_tool = self.registry.get(pending["tool"])
            if pending.get("manifest_version") != current_tool.manifest_version():
                raise ValueError("Tool manifest changed after approval was requested.")
            task = Task(command=pending["tool"], task_id=pending["task_id"], state=TaskState.WAITING_CONFIRMATION)
            if cancel:
                self._transition(task, TaskState.DENIED)
                result = {"task_id": task.task_id, "state": task.state, "reason": "Cancelled on screen."}
            else:
                result = self._run(pending["tool"], pending["arguments"],
                                   provenance=pending["provenance"], approved_task=task,
                                   autonomy=pending.get("autonomy"), tainted=pending.get("tainted", False),
                                   exposed=pending.get("exposed"))
            self._log_action(pending["tool"], pending["arguments"], result, pending["provenance"],
                             pending.get("autonomy"), approved=not cancel)
            return result

    def _log_action(self, tool_name, arguments, result, provenance, autonomy, approved=False):
        """Write one action-log entry for anything that changes something, asks first, or is refused."""
        try:
            tool = self.registry.get(tool_name)
        except (KeyError, ValueError):
            tool = None
        state = str(result.get("state"))
        risk = int(tool.base_risk) if tool is not None else None
        if (risk is not None and risk == 0) and state not in {"DENIED", "WAITING_CONFIRMATION"}:
            return  # plain observations are in the audit trace, not the action log
        safe = arguments if isinstance(arguments, dict) else {}
        sensitive = tool.sensitive_argument_names if tool is not None else frozenset()
        shown = {key: ("[REDACTED]" if key in sensitive else
                       (value[:200] if isinstance(value, str) else value)) for key, value in safe.items()}
        paths = [safe[key][:300] for key in sorted(path_argument_names(tool)) if isinstance(safe.get(key), str)] \
            if tool is not None else []
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        message = result.get("reason") or result.get("error") or output.get("error")
        entry = {"task_id": result.get("task_id"), "tool": tool_name, "risk": risk, "state": state,
                 "provenance": provenance, "autonomy": autonomy, "approved_on_screen": approved,
                 "arguments": shown, "paths": paths,
                 "message": str(message)[:200] if message else None,
                 "operation_id": output.get("operation_id"), "undo_id": output.get("undo_id"),
                 "undo": UNDO_TOOLS.get(tool_name) if state == "COMPLETED" else None}
        try:
            self.action_log.append(entry)
        except (OSError, ValueError) as error:
            self.event_log.append(str(result.get("task_id")), "runtime_error",
                                  {"type": "ActionLogUnavailable", "message": str(error)})

    def _run(self, tool_name: str, arguments: dict[str, Any], *, provenance="user_stated", approved_task=None,
             autonomy=None, tainted=False, exposed=None) -> dict[str, Any]:
        task = approved_task or Task(command=tool_name)
        if approved_task is None:
            self.event_log.append(task.task_id, "task_received", {"tool": tool_name, "arguments": {}})
        try:
            self.action_control.check()
            if approved_task is None:
                self._transition(task, TaskState.UNDERSTANDING)
                self._transition(task, TaskState.PLANNING)
            tool = self.registry.get(tool_name)
            tool.validate_arguments(arguments)
            self.event_log.append(task.task_id, "validated_command", {"tool": tool_name, "arguments": self._redact(arguments, tool.sensitive_argument_names)})
            self._transition(task, TaskState.AUTHORIZING)
            if elevation.is_elevated():
                # Never act with an administrator token: Windows ACLs are the second protection layer.
                self.event_log.append(task.task_id, "authorization", {
                    "decision": "DENY", "reason": elevation.ELEVATED_REASON, "elevated": True})
                self._transition(task, TaskState.DENIED)
                return {"task_id": task.task_id, "state": task.state, "reason": elevation.ELEVATED_REASON}
            authorization = self.authorize(tool, arguments, approved_task is not None, provenance=provenance,
                                           autonomy=autonomy, tainted=tainted, exposed=exposed)
            self.event_log.append(task.task_id, "authorization", authorization.__dict__ | {
                "risk": int(authorization.risk), "provenance": provenance,
                "autonomy": autonomy, "tainted": tainted, "exposed": exposed})
            if authorization.decision == Decision.DENY:
                self._transition(task, TaskState.DENIED)
                return {"task_id": task.task_id, "state": task.state, "reason": authorization.reason}
            if authorization.decision == Decision.CONFIRM:
                grant = self.current_grant()
                capability = (self.current_capability(tool.required_capability).snapshot()
                              if tool.required_capability is not None else None)
                token = self.approvals.add(task.task_id, tool_name, arguments, self.granted_root,
                                           grant=grant.snapshot(), capability=capability,
                                           manifest_version=tool.manifest_version(), provenance=provenance,
                                           autonomy=autonomy, tainted=tainted, exposed=exposed)
                self._transition(task, TaskState.WAITING_CONFIRMATION)
                return {"task_id": task.task_id, "state": task.state, "reason": authorization.reason,
                        "approval": {"token": token, "tool": tool_name, "arguments": arguments,
                                     "risk": int(authorization.risk), "risk_label": authorization.risk.name,
                                     "origin": provenance, "resource": grant.public(),
                                     "capability": capability,
                                     "manifest_version": tool.manifest_version(),
                                     "consequence": tool.description, "expires_in": self.approvals.ttl}}
            self.action_control.check()
            self._transition(task, TaskState.EXECUTING)
            context = ExecutionContext(task.task_id, self.journal, self.granted_root, self.memory,
                                       getattr(self, "capability_grants", None))
            result = tool.execute(arguments, context)
            self.event_log.append(
                task.task_id,
                "tool_result",
                {"output": result.audit_output if result.audit_output is not None else result.output, "verification": result.verification},
            )
            self._transition(task, TaskState.VERIFYING)
            self.action_control.check()
            if tool.verify is not None and result.verification != Verification.FAIL:
                result = tool.verify(arguments, result, context)
                self.event_log.append(task.task_id, "verification_result", {
                    "output": result.audit_output if result.audit_output is not None else result.output,
                    "verification": result.verification})
            if result.verification != Verification.PASS:
                self._transition(task, TaskState.FAILED)
                return {"task_id": task.task_id, "state": task.state, "output": result.output, "verification": result.verification}
            self._transition(task, TaskState.COMPLETED)
            return {"task_id": task.task_id, "state": task.state, "output": result.output, "verification": result.verification}
        except Exception as error:
            if task.state not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.DENIED}:
                self._transition(task, TaskState.FAILED)
            self.event_log.append(task.task_id, "runtime_error", {"type": type(error).__name__, "message": str(error)})
            return {"task_id": task.task_id, "state": TaskState.FAILED, "error": str(error)}
