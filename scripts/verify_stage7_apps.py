"""Real Windows checker for controlled application open and graceful close."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest


def main():
    checks = []
    cleanup = {"needed": False, "completed": True}
    with tempfile.TemporaryDirectory(prefix="chutku-stage7-apps-") as temp:
        with create_runtime(Path(temp)) as runtime:
            before = runtime.run("apps.status", {"app": "notepad"})
            existing = before.get("output", {}).get("app_windows", [])
            checks.append({"check": "no_preexisting_notepad_targeted", "passed": not existing})
            if existing:
                report = {"timestamp_utc": datetime.now(UTC).isoformat(),
                          "source_sha256": source_digest(PROJECT_ROOT), "passed": False,
                          "checks": checks,
                          "scope": "Stage 7B controlled Notepad lifecycle; refused because a user window already existed."}
            else:
                opened = runtime.run("apps.open", {"app": "notepad"})
                opened_ok = str(opened.get("state")) == "COMPLETED"
                checks.append({"check": "controlled_notepad_open_verified", "passed": opened_ok})
                pid = opened.get("output", {}).get("process_id") if opened_ok else None
                cleanup["needed"] = opened_ok
                runtime.capability_grants.grant("desktop.input")
                denied_without_review = runtime.run("apps.close", {"app": "notepad"})
                checks.append({"check": "graceful_close_requires_review", "passed":
                               str(denied_without_review.get("state")) == "WAITING_CONFIRMATION"})
                closed = (runtime.approve(denied_without_review["approval"]["token"])
                          if str(denied_without_review.get("state")) == "WAITING_CONFIRMATION"
                          else denied_without_review)
                final = runtime.run("apps.status", {"app": "notepad"})
                closed_ok = (str(closed.get("state")) == "COMPLETED"
                             and final.get("output", {}).get("running") is False)
                checks.append({"check": "graceful_close_reobserved", "passed": closed_ok})
                cleanup["needed"] = opened_ok and not closed_ok
                if cleanup["needed"] and isinstance(pid, int):
                    runtime.capability_grants.grant("process.observe")
                    process = runtime.run("process.status", {"pid": pid})
                    executable = process.get("output", {}).get("process", {}).get("executable")
                    if executable:
                        runtime.capability_grants.grant("process.terminate")
                        pending = runtime.run("process.terminate", {"pid": pid, "expected_executable": executable})
                        terminated = (runtime.approve(pending["approval"]["token"])
                                      if str(pending.get("state")) == "WAITING_CONFIRMATION" else pending)
                        cleanup["completed"] = str(terminated.get("state")) == "COMPLETED"
                    else:
                        cleanup["completed"] = False
                checks.append({"check": "controlled_app_cleanup", "passed": cleanup["completed"]})
                report = {"timestamp_utc": datetime.now(UTC).isoformat(),
                          "source_sha256": source_digest(PROJECT_ROOT),
                          "passed": all(item["passed"] for item in checks), "checks": checks,
                          "scope": "Stage 7B controlled real Notepad open, reviewed graceful close, re-observation and cleanup."}
    target = PROJECT_ROOT / "verification/stage7-apps.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
