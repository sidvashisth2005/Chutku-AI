from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chutku.core.paths import sandbox_target, read_bounded_text
from chutku.core.task import new_task_id
from chutku.policy.kernel import Decision
from chutku.runtime import Runtime


def project_plan(name: str, root: Path) -> dict[str, Any]:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,47}", name) or name != name.strip():
        raise ValueError("Use a project name of 1–48 letters, digits, spaces, underscores or hyphens, starting with a letter or digit.")
    target = sandbox_target(root, name)
    readme = f"# {name}\n\nCreated by Chutku's verified project workflow.\n\n## Goal\n\nDescribe your goal here.\n\n## Next steps\n\nSee tasks.md for your starter checklist.\n"
    tasks = f"# {name} — tasks\n\n- [ ] Define the first useful outcome\n- [ ] Implement one small step\n- [ ] Verify the result\n- [ ] Record what changed\n"
    return {
        "name": name, "recipe": "project_setup", "target": str(target),
        "steps": [
            {"label": "Create project folder", "tool": "filesystem.create_directory", "arguments": {"path": name}},
            {"label": "Write project README", "tool": "filesystem.write_text", "arguments": {"path": f"{name}/README.md", "content": readme}},
            {"label": "Write starter checklist", "tool": "filesystem.write_text", "arguments": {"path": f"{name}/tasks.md", "content": tasks}},
            {"label": "Read back README", "tool": "filesystem.read_text", "arguments": {"path": f"{name}/README.md"}},
            {"label": "Read back checklist", "tool": "filesystem.read_text", "arguments": {"path": f"{name}/tasks.md"}},
            {"label": "Inspect project folder", "tool": "filesystem.list", "arguments": {"path": name}},
        ],
        "notes": ["Creates two UTF-8 Markdown files in a new sandbox folder.",
                  "Stops on the first failed step. Completed steps remain visible in history.",
                  "Each text write can be undone separately; folder creation is not undone.",
                  "Existing project folders are refused; this does not overwrite an existing project."],
    }


def preflight(plan: dict, runtime: Runtime) -> None:
    if plan != project_plan(plan.get("name"), runtime.granted_root):
        raise ValueError("Workflow does not match the supported project recipe.")
    if Path(plan["target"]).exists():
        raise ValueError("Project folder already exists. Choose a new name; existing files were preserved.")
    for step in plan["steps"]:
        tool = runtime.registry.get(step["tool"])
        tool.validate_arguments(step["arguments"])
        sandbox_target(runtime.granted_root, step["arguments"]["path"])
        if runtime.authorize(tool, step["arguments"]).decision != Decision.ALLOW:
            raise ValueError("Workflow contains an operation that is not authorized.")


def run_project(plan: dict, runtime: Runtime) -> dict:
    from chutku.core.execution_lock import ExecutionBusy
    try:
        with runtime.execution_lock:
            return _run_project(plan, runtime)
    except ExecutionBusy as error:
        return {"state": "FAILED", "error": str(error), "message": str(error), "steps": [], "verification": "FAIL",
                "target": plan.get("target")}


def _run_project(plan: dict, runtime: Runtime) -> dict:
    task_id = new_task_id()
    log = runtime.event_log
    log.append(task_id, "task_received", {"tool": "workflow.project_setup", "arguments": {}})
    log.append(task_id, "task_state", {"from": "RECEIVED", "to": "PLANNING"})
    steps = []
    try:
        # Recheck immediately before execution; preview is not a reservation.
        preflight(plan, runtime)
        log.append(task_id, "task_state", {"from": "PLANNING", "to": "EXECUTING"})
        for index, step in enumerate(plan["steps"], 1):
            result = runtime.run(step["tool"], step["arguments"])
            summary = {"index": index, "label": step["label"], "tool": step["tool"],
                       "task_id": result["task_id"], "state": str(result["state"])}
            steps.append(summary)
            log.append(task_id, "workflow_step", summary)
            if result["state"] != "COMPLETED":
                raise ValueError(f"Step {index} failed: " + str(result.get("error") or result.get("output", {}).get("error") or result["state"]))
        # Check the complete final state, not only individual success strings.
        for step in plan["steps"]:
            if step["tool"] == "filesystem.write_text":
                target = sandbox_target(runtime.granted_root, step["arguments"]["path"])
                if read_bounded_text(target) != step["arguments"]["content"]:
                    raise ValueError("Final project verification found changed contents.")
        state, message = "COMPLETED", f"Created and verified {plan['name']}: README.md and tasks.md."
    except Exception as error:
        state, message = "FAILED", str(error)
    log.append(task_id, "workflow_result", {"state": state, "completed_steps": sum(s["state"] == "COMPLETED" for s in steps)})
    log.append(task_id, "task_state", {"from": "EXECUTING" if steps else "PLANNING", "to": state})
    return {"task_id": task_id, "state": state, "message": message, "steps": steps,
            "target": plan.get("target"), "verification": "PASS" if state == "COMPLETED" else "FAIL"}
