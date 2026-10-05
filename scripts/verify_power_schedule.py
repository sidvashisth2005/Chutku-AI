"""Consented real proof: schedule a delayed shutdown, immediately cancel, and prove none remains."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest
from chutku.tools.power_controls import _command


def _reviewed(runtime, tool, arguments):
    pending = runtime.run(tool, arguments)
    if str(pending.get("state")) != "WAITING_CONFIRMATION":
        return pending
    return runtime.approve(pending["approval"]["token"])


def main():
    checks = []; cleanup_code = None
    with tempfile.TemporaryDirectory(prefix="chutku-power-") as temp, create_runtime(Path(temp)) as runtime:
        args = {"mode": "shutdown", "delay_seconds": 600, "confirmation_phrase": "SHUT DOWN THIS PC"}
        denied = runtime.run("power.schedule", args)
        checks.append({"check": "power_denied_without_capability", "passed": str(denied.get("state")) == "DENIED"})
        runtime.capability_grants.grant("power.control")
        try:
            scheduled = _reviewed(runtime, "power.schedule", args)
            checks.append({"check": "real_delayed_shutdown_command_accepted", "passed": str(scheduled.get("state")) == "COMPLETED"})
            cancelled = _reviewed(runtime, "power.cancel", {})
            checks.append({"check": "real_shutdown_cancelled_and_absence_verified", "passed": str(cancelled.get("state")) == "COMPLETED"})
        finally:
            cleanup_code = _command({"action": "cancel"})
            checks.append({"check": "final_cleanup_confirms_no_shutdown_pending", "passed": cleanup_code != 0})
    report = {"timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(x["passed"] for x in checks), "checks": checks,
              "scope": "Consented real delayed shutdown scheduling with immediate verified cancellation and final cleanup."}
    (PROJECT_ROOT / "verification/power-schedule.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
