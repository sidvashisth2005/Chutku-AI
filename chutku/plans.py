"""Bounded, reviewed deterministic plans over a deliberately small tool set."""
from copy import deepcopy
import hashlib

from chutku.core.paths import sandbox_target, read_bounded_text
from chutku.core.task import Task, TaskState
from chutku.planning import plan_request
from chutku.policy.kernel import Decision

PLAN_TOOLS = frozenset({"system.get_time", "system.environment", "system.gpu_status",
    "assistant.capabilities", "windows.list", "apps.open", "apps.status",
    "filesystem.list", "filesystem.read_text", "filesystem.create_directory", "filesystem.write_text"})


def _snapshot(root, raw):
    target = sandbox_target(root, raw)
    if not target.exists():
        return {"kind": "missing"}
    if target.is_dir():
        return {"kind": "directory", "identity": target.stat().st_ino}
    text = read_bounded_text(target)
    return {"kind": "file", "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def build_plan(commands, runtime):
    if (not isinstance(commands, list) or not 1 <= len(commands) <= 6
            or any(not isinstance(c, str) or not c.strip() for c in commands)
            or sum(len(c) for c in commands) > 70000):
        raise ValueError("Provide one to six non-empty commands, totaling at most 70000 characters.")
    steps, snapshots = [], {}
    virtual = {}
    root = runtime.granted_root
    for index, command in enumerate(commands, 1):
        understood = plan_request(command)
        if understood.state != "READY" or understood.tool not in PLAN_TOOLS:
            raise ValueError(f"Step {index} is unsupported in a bounded plan. No steps ran.")
        tool = runtime.registry.get(understood.tool)
        arguments = understood.arguments
        tool.validate_arguments(arguments)
        if runtime.authorize(tool, arguments).decision != Decision.ALLOW:
            raise ValueError(f"Step {index} is not authorized for this plan.")
        step = {"index": index, "tool": tool.name, "arguments": arguments,
                "manifest_version": tool.manifest_version()}
        if tool.name.startswith("filesystem."):
            target = sandbox_target(root, arguments["path"])
            raw = target.relative_to(root).as_posix()
            parent = target.parent.relative_to(root).as_posix() if target != root else "."
            for key in (raw, parent):
                if key not in snapshots:
                    snapshots[key] = _snapshot(root, key)
                    virtual[key] = snapshots[key]["kind"]
            kind = virtual[raw]
            if tool.name == "filesystem.create_directory":
                if kind != "missing" or virtual[parent] != "directory":
                    raise ValueError(f"Step {index} needs a new directory with an existing or earlier-created parent.")
                virtual[raw] = "directory"
                step["effect"] = "Create a new folder"
            elif tool.name == "filesystem.write_text":
                if kind == "directory" or virtual[parent] != "directory":
                    raise ValueError(f"Step {index} needs a file target and an existing or earlier-created parent.")
                step["effect"] = "Replace existing text" if kind == "file" else "Create a text file"
                virtual[raw] = "file"
            elif tool.name == "filesystem.read_text" and kind != "file":
                raise ValueError(f"Step {index} needs an existing or earlier-written text file.")
            elif tool.name == "filesystem.list" and kind != "directory":
                raise ValueError(f"Step {index} needs an existing or earlier-created directory.")
        steps.append(step)
    return {"commands": deepcopy(commands), "root": str(root), "steps": steps,
            "snapshots": snapshots, "review_required": True,
            "notes": ["Review every step and exact write content before running.",
                      "Changed targets invalidate this preview. It does not reserve files.",
                      "Stops on failure. Completed steps remain; there is no automatic whole-plan rollback."]}


def _check(root, snapshots):
    for raw, expected in snapshots.items():
        if _snapshot(root, raw) != expected:
            raise ValueError("A plan target changed after review. Preview again; no conflicting change was overwritten.")


def run_plan(plan, runtime):
    task = Task(command="brain.reviewed_plan")
    log = runtime.event_log
    log.append(task.task_id, "task_received", {"tool": task.command, "arguments": {}})
    steps = []
    try:
        with runtime.execution_lock:
            runtime.action_control.check()
            runtime._transition(task, TaskState.UNDERSTANDING)
            runtime._transition(task, TaskState.PLANNING)
            # Rebuild from the stored requests, never accept substituted tool calls.
            if not isinstance(plan, dict) or plan != build_plan(plan.get("commands"), runtime):
                raise ValueError("Plan changed or a target changed since review. Preview again.")
            runtime._transition(task, TaskState.AUTHORIZING)
            observed = deepcopy(plan["snapshots"])
            writes, directories = {}, []
            runtime._transition(task, TaskState.EXECUTING)
            for step in plan["steps"]:
                runtime.action_control.check()
                _check(runtime.granted_root, observed)
                result = runtime.run(step["tool"], step["arguments"])
                summary = {"index": step["index"], "label": step["tool"],
                           "task_id": result["task_id"], "state": str(result["state"])}
                steps.append(summary)
                log.append(task.task_id, "workflow_step", summary)
                if result["state"] != "COMPLETED":
                    raise ValueError(f"Step {step['index']} did not complete. Inspect its trace; earlier effects may remain.")
                if step["tool"] in {"filesystem.write_text", "filesystem.create_directory"}:
                    raw = sandbox_target(runtime.granted_root, step["arguments"]["path"]).relative_to(runtime.granted_root).as_posix()
                    observed[raw] = _snapshot(runtime.granted_root, raw)
                    if step["tool"] == "filesystem.write_text":
                        writes[raw] = step["arguments"]["content"]
                        observed[raw] = {"kind": "file", "sha256": hashlib.sha256(writes[raw].encode("utf-8")).hexdigest()}
                    else:
                        directories.append(raw)
            runtime._transition(task, TaskState.VERIFYING)
            runtime.action_control.check()
            _check(runtime.granted_root, observed)
            for raw, expected in writes.items():
                if read_bounded_text(sandbox_target(runtime.granted_root, raw)) != expected:
                    raise ValueError("Final text verification failed.")
            if any(not sandbox_target(runtime.granted_root, raw).is_dir() for raw in directories):
                raise ValueError("Final directory verification failed.")
            runtime._transition(task, TaskState.COMPLETED)
            message = f"Completed and verified all {len(steps)} reviewed steps."
    except Exception as error:
        runtime._transition(task, TaskState.FAILED)
        # Fixed error messages above contain no command body or file content.
        message = str(error)
        log.append(task.task_id, "runtime_error", {"type": type(error).__name__, "message": message})
    return {"task_id": task.task_id, "state": str(task.state), "steps": steps,
            "verification": "PASS" if task.state == TaskState.COMPLETED else "FAIL", "message": message}
