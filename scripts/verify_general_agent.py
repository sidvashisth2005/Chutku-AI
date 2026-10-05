"""Real local-LLM -> reviewed typed plan -> verified observation path."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from chutku.agent_execution import AgentExecutionStore
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.brain import preview_tool_plan
from chutku.evidence import source_digest


def main():
    checks = []
    request = "Tell me the current UTC time, then report this computer's system environment."
    with create_runtime(PROJECT_ROOT) as runtime:
        before_tasks = runtime.event_log.recent_tasks(100)
        plan = preview_tool_plan(request, runtime)
        tools = [step["tool"] for step in plan.get("steps", [])]
        checks.append({"check": "free_form_request_became_exact_ordered_tools",
                       "passed": tools == ["system.get_time", "system.environment"],
                       "observed_tools": tools})
        checks.append({"check": "preview_had_no_task_side_effect",
                       "passed": runtime.event_log.recent_tasks(100) == before_tasks})
        if checks[0]["passed"]:
            store = AgentExecutionStore()
            token = store.prepare(plan, runtime, provenance="reviewed_inferred")
            result = store.start(token, runtime)
        else:
            result = {"state": "NOT_RUN", "verification": "UNKNOWN", "plan_steps": []}
        checks.append({"check": "reviewed_plan_completed_and_verified",
                       "passed": result.get("state") == "COMPLETED"
                       and result.get("verification") == "PASS"
                       and len(result.get("plan_steps", [])) == 2})
        task_ids = [step.get("task_id") for step in result.get("plan_steps", [])]
        provenances = []
        for task_id in task_ids:
            authorization = next((payload for event, payload in runtime.event_log.events_for(task_id)
                                  if event == "authorization"), {})
            provenances.append(authorization.get("provenance"))
        checks.append({"check": "reviewed_provenance_preserved",
                       "passed": provenances == ["reviewed_inferred", "reviewed_inferred"]})
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "source_sha256": source_digest(PROJECT_ROOT),
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "model": plan.get("model"),
        "selected_domains": plan.get("selected_domains"),
        "inference_seconds": plan.get("inference_seconds"),
        "scope": "Real free-form local Qwen planning followed by exact reviewed observation-only Runtime execution.",
    }
    output = PROJECT_ROOT / "verification/general-agent.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
