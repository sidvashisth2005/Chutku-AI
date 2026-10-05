"""Real exact-target UIA invoke check against a newly owned Calculator window."""
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
    with tempfile.TemporaryDirectory(prefix="chutku-uia-action-") as temp:
        with create_runtime(Path(temp)) as runtime:
            existing = runtime.run("apps.status", {"app": "calculator"}).get("output", {}).get("app_windows", [])
            checks.append({"check": "no_preexisting_calculator_targeted", "passed": not existing})
            if not existing:
                opened = runtime.run("apps.open", {"app": "calculator"})
                arguments = {
                    "app": "calculator",
                    "selector": {"automation_id": "num1Button", "control_type": "ControlType.Button"},
                    "expect": {"selector": {"automation_id": "CalculatorResults",
                                              "control_type": "ControlType.Text"},
                               "property": "name", "expected": "Display is 1"},
                }
                denied = runtime.run("uia.invoke", arguments)
                checks.append({"check": "invoke_denied_without_desktop_input_capability",
                               "passed": str(denied.get("state")) == "DENIED"})
                runtime.capability_grants.grant("desktop.input")
                focused = runtime.run("apps.focus", {"app": "calculator"})
                checks.append({"check": "controlled_calculator_open_and_focus_verified",
                               "passed": str(opened.get("state")) == "COMPLETED"
                               and str(focused.get("state")) == "COMPLETED"})
                pending = runtime.run("uia.invoke", arguments)
                checks.append({"check": "exact_action_requires_onscreen_review",
                               "passed": str(pending.get("state")) == "WAITING_CONFIRMATION"})
                invoked = (runtime.approve(pending["approval"]["token"])
                           if str(pending.get("state")) == "WAITING_CONFIRMATION" else pending)
                checks.append({"check": "real_button_invoke_exact_postcondition_verified",
                               "passed": str(invoked.get("state")) == "COMPLETED"
                               and invoked.get("output", {}).get("verified") is True})
                closing = runtime.run("apps.close", {"app": "calculator"})
                closed = (runtime.approve(closing["approval"]["token"])
                          if str(closing.get("state")) == "WAITING_CONFIRMATION" else closing)
                final = runtime.run("apps.status", {"app": "calculator"})
                checks.append({"check": "controlled_calculator_cleanup",
                               "passed": str(closed.get("state")) == "COMPLETED"
                               and final.get("output", {}).get("running") is False})

    report = {"timestamp_utc": datetime.now(UTC).isoformat(),
              "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(item["passed"] for item in checks), "checks": checks,
              "scope": "Stage 8A-3 real button invoke with exact Calculator UIA postcondition; complementary menu/value/selection/scroll evidence is in uia-fixture.json."}
    target = PROJECT_ROOT / "verification/uia-actions.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
