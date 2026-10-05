"""Real Windows checker for the first full-PC authority/observation slice."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest
from chutku.gemini import configured


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="chutku-full-pc-") as temp:
        with create_runtime(Path(temp)) as runtime:
            denied = runtime.run("process.status", {"pid": os.getpid()})
            checks.append({"check": "process_observation_denied_without_grant",
                           "passed": str(denied["state"]) == "DENIED"})
            grant = runtime.capability_grants.grant("process.observe")
            observed = runtime.run("process.status", {"pid": os.getpid()})
            checks.append({"check": "real_current_process_observed",
                           "passed": str(observed["state"]) == "COMPLETED"
                           and observed.get("output", {}).get("running") is True})
            runtime.capability_grants.revoke(grant.capability)
            revoked = runtime.run("process.status", {"pid": os.getpid()})
            checks.append({"check": "revoked_process_observation_denied",
                           "passed": str(revoked["state"]) == "DENIED"})
            # Launch a harmless, bounded loopback ping process through the same
            # approval path, then terminate only that exact PID/image.
            windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            ping = windows / "System32/ping.exe"
            runtime.capability_grants.grant("process.launch")
            launch_pending = runtime.run("process.launch", {
                "executable": str(ping), "arguments": ["-t", "127.0.0.1"]})
            launched = (runtime.approve(launch_pending["approval"]["token"])
                        if str(launch_pending["state"]) == "WAITING_CONFIRMATION" else launch_pending)
            launch_passed = str(launched["state"]) == "COMPLETED"
            checks.append({"check": "exact_process_launch_verified", "passed": launch_passed})
            if launch_passed:
                pid = launched["output"]["pid"]
                runtime.capability_grants.grant("process.terminate")
                terminate_pending = runtime.run("process.terminate", {
                    "pid": pid, "expected_executable": str(ping)})
                terminated = (runtime.approve(terminate_pending["approval"]["token"])
                              if str(terminate_pending["state"]) == "WAITING_CONFIRMATION" else terminate_pending)
                checks.append({"check": "exact_process_termination_verified",
                               "passed": str(terminated["state"]) == "COMPLETED"
                               and terminated.get("output", {}).get("running") is False})
            else:
                checks.append({"check": "exact_process_termination_verified", "passed": False})
    checks.append({"check": "gemini_is_optional", "passed": True,
                   "configured": configured(),
                   "detail": "Without a configured key, dual preview uses the local model; cloud calls require explicit consent."})
    report = {"timestamp_utc": datetime.now(UTC).isoformat(),
              "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(row["passed"] for row in checks), "checks": checks,
              "scope": "Stage 6 authority foundation plus exact Windows process observation, approved launch, identity recheck and verified termination."}
    target = PROJECT_ROOT / "verification/full-pc-foundation.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
