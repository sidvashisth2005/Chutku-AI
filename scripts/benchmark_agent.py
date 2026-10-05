"""Golden-task benchmark for the chat agent on the owner's real PC.

Runs benchmarks/agent_tasks.py through the same session, router, planners, policy
and verified tools as the dashboard chat. File tasks use a fresh D:\\ChutkuBench.
Reports per-task and per-category pass rates with Wilson 95% intervals.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.agent_tasks import TASKS, cleanup, prepare  # noqa: E402
from chutku.agent_loop import AgentSession, LocalAgentPlanner, RuntimeRouter, default_context  # noqa: E402
from chutku.app import create_runtime  # noqa: E402
from chutku.brain_service import BrainService  # noqa: E402
from chutku.evidence import source_digest  # noqa: E402
from chutku.quick_intents import QuickPlanner  # noqa: E402


def wilson(passed, total, z=1.96):
    if not total:
        return [0.0, 0.0]
    p = passed / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [round(max(0, centre - margin), 3), round(min(1, centre + margin), 3)]


def facts():
    now = datetime.now().astimezone()
    return {"hour12": f"{int(now.strftime('%I'))}:", "c_free_gib": shutil.disk_usage("C:\\").free / 1024**3,
            "d_free_gib": shutil.disk_usage("D:\\").free / 1024**3}


def close_windows(kind):
    from chutku.tools.windows_apps import WindowsDesktop
    desktop = WindowsDesktop()
    for window in desktop.windows(kind):
        if kind == "calculator" or window["title"].startswith(("Untitled", "*Untitled")):
            desktop.close(window["window_id"])


def run_task(task, router, planner):
    prepare(task)
    session = AgentSession(task["goal"], mode=task["mode"], context=default_context(router))
    session.quick = QuickPlanner()
    started = time.monotonic()
    confirmations = []
    snapshot = session.advance(router, planner)
    while snapshot["status"] == "waiting_confirmation" and len(confirmations) < 4:
        approve = task.get("confirm") == "approve"
        confirmations.append({"tool": snapshot["pending"]["approval"]["tool"], "approved": approve})
        session.decide(router, approve=approve)
        snapshot = session.advance(router, planner)
    result = {"snapshot": snapshot, "facts": facts()}
    result["snapshot"] = {**snapshot, "steps": [{**s, "observation": o["observation"]}
                                                for s, o in zip(snapshot["steps"], session.steps)]}
    try:
        passed = bool(task["check"](result))
    except Exception as error:  # a checker crash is a failure, recorded
        passed = False
        snapshot = {**snapshot, "reply": snapshot["reply"] + f" [checker error: {error}]"}
    if task.get("after"):
        try:
            task["after"](result)
        except Exception:
            pass
    if task.get("cleanup"):
        time.sleep(0.5)
        close_windows(task["cleanup"])
    return {"id": task["id"], "category": task["cat"], "mode": task["mode"], "passed": passed,
            "status": snapshot["status"], "seconds": round(time.monotonic() - started, 1),
            "steps": [f"{s['tool']}:{s['state']}" for s in snapshot["steps"]],
            "planners": [p["planner"] for p in snapshot["planners"]], "confirmations": confirmations,
            "reply": snapshot["reply"][:400]}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # replies may contain Devanagari
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--output", type=Path, default=ROOT / "verification/agent-benchmark.json")
    args = parser.parse_args()
    tasks = [t for t in TASKS if not args.only or t["id"] in args.only]
    service = BrainService()
    planner = LocalAgentPlanner(service)
    rows = []
    with create_runtime(ROOT) as runtime:
        router = RuntimeRouter(runtime, opener=lambda g: create_runtime(ROOT, g))
        try:
            for round_index in range(args.repeat):
                for task in tasks:
                    row = run_task(task, router, planner) | {"round": round_index + 1}
                    rows.append(row)
                    print(("PASS " if row["passed"] else "FAIL ") + json.dumps(row, ensure_ascii=False)[:600],
                          flush=True)
        finally:
            router.close()
            service.close()
            cleanup()
    summary = {}
    for key in sorted({r["category"] for r in rows}) + ["all"]:
        subset = [r for r in rows if key == "all" or r["category"] == key]
        passed = sum(r["passed"] for r in subset)
        seconds = sorted(r["seconds"] for r in subset)
        summary[key] = {"passed": passed, "total": len(subset), "rate": round(passed / len(subset), 3),
                        "wilson95": wilson(passed, len(subset)), "median_seconds": seconds[len(seconds) // 2]}
    report = {"generated_at": datetime.now(UTC).isoformat(), "source_digest": source_digest(ROOT),
              "tasks": len(tasks), "repeat": args.repeat, "summary": summary, "rows": rows,
              "scope": "Owner's PC, real grants, local GPU planner + deterministic router. Checks inspect real final "
                       "state or independently measured facts. Small versioned set; not general task accuracy."}
    args.output.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
