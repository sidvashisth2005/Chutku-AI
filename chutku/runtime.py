from __future__ import annotations

import contextlib
from contextvars import ContextVar
import json
from pathlib import Path
import time
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

# The agent session a step belongs to (set by AgentSession while it works): the action log records it, so
# "undo the whole last task" (Causal Rewind) finds every step of that request, not only the last one.
SESSION = ContextVar("chutku_session", default=None)

# How to reverse a completed action (used by log.undo; each undo tool reverses only the latest of its kind).
UNDO_TOOLS = {
    "filesystem.write_text": "filesystem.undo_last_write",
    "filesystem.copy": "filesystem.undo_last_copy",
    "filesystem.move": "filesystem.undo_last_move",
    "filesystem.recycle": "filesystem.restore_last_recycled",
    "files.organize": "files.organize_undo",
    "screen.capture": "screen.undo_last_capture",
}


# Tools that send keystrokes or text to a window.
TYPING_TOOLS = frozenset({"keyboard.type_text", "keyboard.press_enter", "keyboard.keys", "input.type_text",
                          "uia.set_value"})


def command_window_question(tool, arguments):
    """Typing into a command window, opening the Run box, or launching a command-line app asks first."""
    from chutku.tools import desktop_controls
    if tool.name == "keyboard.shortcut" and arguments.get("action") == "run_dialog":
        return "Opening the Run box asks first."
    if tool.name == "apps.launch":
        return desktop_controls.command_app_reason(str(arguments.get("name") or arguments.get("app_id") or ""))
    if tool.name == "keyboard.keys":
        from chutku.tools.free_input import opens_run_box
        try:
            if opens_run_box(arguments.get("keys", "")):
                return "Opening the Run box asks first."
        except ValueError:
            return None  # unknown keys fail validation anyway
    if tool.name not in TYPING_TOOLS:
        return None
    try:
        if arguments.get("executable"):
            info = {"executable": str(arguments["executable"]), "title": ""}
        else:
            from chutku.tools.free_input import _foreground
            info = _foreground()[1]
        return desktop_controls.command_window_reason(info)
    except (OSError, ValueError, KeyError, TypeError):
        return "Chutku could not check which window is in front; this asks first."


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
        self.step_wait = 0.0   # seconds a step waits for another task's step (parallel tasks); 0: fail fast (CLI)
        self.action_control = ActionControl(control_root)
        self.approvals = ApprovalStore()
        self.action_log = ActionLog(control_root / "data" / "actions.log.jsonl")
        self.control_root = control_root
        self._ledger = None

    @property
    def ledger(self):
        """Earned-autonomy outcomes (data/ledger.db), opened on first use."""
        if self._ledger is None:
            from chutku.core.ledger import Ledger
            self._ledger = Ledger(self.control_root / "data" / "ledger.db")
        return self._ledger

    def reliability(self, tool, arguments):
        from chutku.core.ledger import target_key
        try:
            return self.ledger.stats(tool.name, target_key(tool.name, arguments))
        except Exception:   # the ledger informs; it never blocks
            from chutku.core.log import get_logger
            get_logger("ledger").exception("reading the ledger failed")
            return None

    def _relax(self):
        try:
            from chutku.core.preferences import Preferences
            return Preferences(self.control_root).load().get("earned_autonomy_relax", False) is True
        except (OSError, ValueError):
            return False

    def _record_outcome(self, tool_name, arguments, result, autonomy, seconds):
        """Expected (the tool's success predicate) vs observed, for every finished step that changes something."""
        try:
            tool = self.registry.get(tool_name)
            state = str(result.get("state"))
            if tool.base_risk < 1 or state not in {"COMPLETED", "FAILED"}:
                return
            from chutku.core.ledger import target_key
            verdict = "PASS" if state == "COMPLETED" else (
                "UNKNOWN" if str(result.get("verification")) == "UNKNOWN" else "FAIL")
            observed = state if verdict == "PASS" else (result.get("error") or result.get("reason") or
                                                       (result.get("output") or {}).get("error") or state)
            self.ledger.record(tool_name, target_key(tool_name, arguments), expected=tool.success_predicate,
                               observed=observed, verdict=verdict, seconds=round(seconds, 3), autonomy=autonomy,
                               session_id=result.get("task_id"))
        except Exception:
            from chutku.core.log import get_logger
            get_logger("ledger").exception("recording an outcome failed")

    def close(self) -> None:
        if self._ledger is not None:
            self._ledger.close()
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
                  exposed=None, suspicious=False):
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
                                     owner_question=self.step_question(tool, arguments) if autonomy is not None else None,
                                     suspicious=suspicious,
                                     reliability=self.reliability(tool, arguments)
                                     if autonomy is not None and tool.base_risk >= 1 else None,
                                     relax=self._relax() if autonomy == "owner" else False,
                                     floor_reason=self.floor_reason(tool, arguments))

    def floor_reason(self, tool, arguments):
        """The owner's never-rules (Phase 3b H1); False when the step passes them."""
        from chutku.policy import never_rules
        return never_rules.floor_reason(tool, arguments, granted_root=self.granted_root,
                                     base=getattr(self, "control_root", None)) or False

    def step_question(self, tool, arguments):
        """A reason this exact agent step must be confirmed on screen, in every autonomy mode, or None.

        A message to someone Chutku does not know yet asks (once they are remembered, messages go straight out);
        keys or clicks that would save, delete or move files ask; typing into a command window asks."""
        if tool.name == "rewind.run":   # the one approval card lists exactly what will be undone (S18)
            from chutku.rewind import question
            return question(self, arguments)
        command = command_window_question(tool, arguments)
        if command:
            return command
        contact = self._contact_change(tool, arguments)
        if contact:
            return contact
        if tool.name in {"browser.inspect", "browser.workflow"} and arguments.get("url"):   # no url: validation refuses
            from chutku.tools.internet import Blocked, check_public_url
            try:
                check_public_url(str(arguments.get("url", "")))
            except Blocked:
                return "This page is on this PC or the home network; opening it asks first."
            except (OSError, ValueError):
                return "Chutku could not check where this page is; opening it asks first."

        if tool.name in {"keyboard.keys", "keyboard.edit", "mouse.click", "mouse.drag"}:
            from chutku.tools.free_input import file_risk  # keys/clicks that would save, delete or move files
            return file_risk(tool.name, arguments)
        if tool.name == "email.send":   # every email asks, in every mode (X8)
            from chutku.tools.mail import send_question
            return send_question(arguments)
        if tool.name != "message.send":
            return None
        from chutku.tools.apps_extra import known_recipient
        to = str(arguments.get("to", ""))
        if known_recipient(to, self.memory):
            return None
        return (f"{to} is not in your memory yet, so this message asks first. Say 'remember {to} is my ...' "
                "and later messages to them go straight out.")

    owner_question = step_question  # older name, kept for callers and tests

    def _contact_change(self, tool, arguments):
        """Changing where a remembered person's messages go asks first (messages to them go out unasked)."""
        try:
            if tool.name == "mind.person":
                from chutku import mind
                what = mind.default().identity_change(arguments.get("name", ""), whatsapp=arguments.get("whatsapp", ""),
                                                      phone=arguments.get("phone", ""))
                if what:
                    return (f"This changes the saved {what} of {arguments.get('name')}; messages to them would go "
                            "somewhere new, so it asks first.")
            if tool.name == "memory.remember" and str(arguments.get("key", "")).casefold().startswith("contact_"):
                saved = self.memory.get(str(arguments["key"])) if self.memory is not None else None
                if saved and str(saved.get("value", "")) != str(arguments.get("value", "")):
                    return "This changes a saved contact; messages to them would go somewhere new, so it asks first."
        except (OSError, ValueError, KeyError, TypeError):
            return "Chutku could not check the saved contact; this asks first."
        return None

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
            autonomy: str | None = None, tainted: bool = False, exposed: bool | None = None,
            suspicious: bool = False) -> dict[str, Any]:
        try:
            return self._taking_turns(
                lambda: self._run_locked(tool_name, arguments, provenance, autonomy, tainted, exposed, suspicious))
        except ExecutionBusy:
            pass
        task = Task(command=tool_name)
        self.event_log.append(task.task_id, "task_received", {"tool": tool_name, "arguments": {}})
        self._transition(task, TaskState.FAILED)
        self.event_log.append(task.task_id, "runtime_error", {"type": "ExecutionBusy",
                                                               "message": "Another Chutku action is running."})
        return {"task_id": task.task_id, "state": TaskState.FAILED,
                "error": "Another Chutku action is running. Try again after it completes."}

    def _taking_turns(self, call):
        """Y3: tasks run side by side but their steps take turns. call raises ExecutionBusy before it does anything
        while another step holds the lock; it is retried for up to step_wait seconds (0: fail at once)."""
        deadline = None
        while True:
            try:
                return call()
            except ExecutionBusy:
                if not self.step_wait:
                    raise
                deadline = deadline or time.monotonic() + self.step_wait
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

    def _run_locked(self, tool_name, arguments, provenance, autonomy, tainted, exposed, suspicious):
        """One step; raises ExecutionBusy when another step holds the lock (run() waits and retries)."""
        # Y3 (2026-11-06): a plain observation changes nothing, so it does not take the exclusive lock and a
        # question can be answered while another task runs. Every other step still runs one at a time.
        with (contextlib.nullcontext() if self._observation(tool_name) else self.execution_lock):
            unlogged = self._log_not_ready(tool_name)
            if unlogged is not None:
                return unlogged
            started = time.perf_counter()
            result = self._run(tool_name, arguments, provenance=provenance, autonomy=autonomy, tainted=tainted,
                               exposed=exposed, suspicious=suspicious)
            self._log_action(tool_name, arguments, result, provenance, autonomy)
            self._record_outcome(tool_name, arguments, result, autonomy, time.perf_counter() - started)
            return result

    def _observation(self, tool_name):
        try:
            return self.registry.get(tool_name).base_risk == 0
        except KeyError:
            return False

    def _log_not_ready(self, tool_name):
        """Fail closed when a change could not be written to the action log: nothing runs unlogged."""
        try:
            if self.registry.get(tool_name).base_risk == 0:
                return None   # plain observations are not in the action log
            self.action_log.ready()
            return None
        except KeyError:
            return None       # unknown tools are refused by _run itself
        except (OSError, ValueError) as error:
            task = Task(command=tool_name)
            self.event_log.append(task.task_id, "task_received", {"tool": tool_name, "arguments": {}})
            self._transition(task, TaskState.FAILED)
            self.event_log.append(task.task_id, "runtime_error", {"type": "ActionLogUnavailable", "message": str(error)})
            return {"task_id": task.task_id, "state": TaskState.FAILED,
                    "error": f"The action log cannot be written ({error}); nothing ran. Run doctor."}

    def approve(self, token: str, *, cancel: bool = False) -> dict[str, Any]:
        return self._taking_turns(lambda: self._approve_locked(token, cancel))

    def _approve_locked(self, token, cancel):
        with self.execution_lock:   # the token is taken only once the lock is held, so a busy retry is safe
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
            unlogged = None if cancel else self._log_not_ready(pending["tool"])
            if unlogged is not None:
                return unlogged
            if cancel:
                self._transition(task, TaskState.DENIED)
                result = {"task_id": task.task_id, "state": task.state, "reason": "Cancelled on screen."}
            else:
                result = self._run(pending["tool"], pending["arguments"],
                                   provenance=pending["provenance"], approved_task=task,
                                   autonomy=pending.get("autonomy"), tainted=pending.get("tainted", False),
                                   exposed=pending.get("exposed"), suspicious=pending.get("suspicious", False))
            self._log_action(pending["tool"], pending["arguments"], result, pending["provenance"],
                             pending.get("autonomy"), approved=not cancel)
            if not cancel:
                self._record_outcome(pending["tool"], pending["arguments"], result, pending.get("autonomy"), 0.0)
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
        if SESSION.get():
            entry["session"] = SESSION.get()
        if state == "COMPLETED":   # what Causal Rewind (master plan S18) needs to put a setting back
            before, after = output.get("before"), output.get("after")
            if before is not None and after is not None and len(json.dumps([before, after], default=str)) <= 400:
                entry["state_before"], entry["state_after"] = before, after
            if tool_name in {"reminder.set", "task.schedule"} and isinstance(output.get("id"), str):
                entry["ref"] = output["id"]
        try:
            self.action_log.append(entry)
        except (OSError, ValueError) as error:
            self.event_log.append(str(result.get("task_id")), "runtime_error",
                                  {"type": "ActionLogUnavailable", "message": str(error)})

    def _run(self, tool_name: str, arguments: dict[str, Any], *, provenance="user_stated", approved_task=None,
             autonomy=None, tainted=False, exposed=None, suspicious=False) -> dict[str, Any]:
        task = approved_task or Task(command=tool_name)
        try:
            if approved_task is None:
                self.event_log.append(task.task_id, "task_received", {"tool": tool_name, "arguments": {}})
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
                                           autonomy=autonomy, tainted=tainted, exposed=exposed, suspicious=suspicious)
            self.event_log.append(task.task_id, "authorization", authorization.__dict__ | {
                "risk": int(authorization.risk), "provenance": provenance,
                "autonomy": autonomy, "tainted": tainted, "exposed": exposed, "suspicious": suspicious})
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
                                           autonomy=autonomy, tainted=tainted, exposed=exposed, suspicious=suspicious)
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
                                       getattr(self, "capability_grants", None), approved=approved_task is not None,
                                       autonomy=autonomy, provenance=provenance)
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
            try:   # recording the failure must never raise in its turn (e.g. a locked database)
                if task.state not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.DENIED}:
                    self._transition(task, TaskState.FAILED)
                self.event_log.append(task.task_id, "runtime_error", {"type": type(error).__name__,
                                                                      "message": str(error)})
            except Exception:
                task.state = TaskState.FAILED
            return {"task_id": task.task_id, "state": TaskState.FAILED, "error": str(error)}
