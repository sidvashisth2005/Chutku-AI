"""Run one real local-model proposal through reviewed Runtime execution."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from chutku.app import create_runtime
from chutku.brain import execute_plan, preview_plan
from chutku.evidence import source_digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed", action="store_true",
                        help="Confirm this checker may execute its exact read-only proposal after inspection.")
    args = parser.parse_args()
    if not args.reviewed:
        parser.error("reviewed execution requires --reviewed")
    checks = []
    with create_runtime(BASE) as runtime:
        history_before = len(runtime.event_log.recent_tasks(100))
        plan = preview_plan("Show me basic information about this computer.", runtime)
        history_after_preview = len(runtime.event_log.recent_tasks(100))
        exact = plan.get("commands") == ["system status"] and plan.get("needs_clarification") is False
        checks.append({"check": "exact_bounded_proposal", "passed": exact})
        checks.append({"check": "preview_has_no_runtime_effect", "passed": history_after_preview == history_before})
        result = execute_plan(plan, runtime) if exact else {"state": "FAILED", "plan_steps": []}
        checks.append({"check": "reviewed_execution_verified", "passed": result.get("state") == "COMPLETED"})
        task_id = result.get("plan_steps", [{}])[0].get("task_id") if result.get("plan_steps") else None
        authorization = next((payload for event, payload in runtime.event_log.events_for(task_id)
                              if event == "authorization"), {}) if task_id else {}
        checks.append({"check": "model_provenance_preserved", "passed": authorization.get("provenance") == "inferred"})
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": source_digest(BASE),
        "passed": all(row["passed"] for row in checks), "checks": checks,
        "plan": {"commands": plan.get("commands"), "router": plan.get("router"),
                 "model": plan.get("model"), "needs_clarification": plan.get("needs_clarification")},
        "scope": "One reviewed read-only model proposal; no general reliability claim.",
    }
    output = BASE / "verification/model-review-path.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
