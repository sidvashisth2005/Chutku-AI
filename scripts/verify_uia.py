"""Real read-only UI Automation checker using a controlled Notepad window."""
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
    observed_count = 0
    with tempfile.TemporaryDirectory(prefix="chutku-uia-") as temp:
        with create_runtime(Path(temp)) as runtime:
            existing = runtime.run("apps.status", {"app": "notepad"}).get("output", {}).get("app_windows", [])
            checks.append({"check": "zero_or_one_unambiguous_notepad_window", "passed": len(existing) <= 1})
            opened_by_checker = not existing
            if len(existing) <= 1:
                opened = (runtime.run("apps.open", {"app": "notepad"})
                          if opened_by_checker else {"state": "COMPLETED"})
                checks.append({"check": "controlled_notepad_open_verified",
                               "passed": str(opened.get("state")) == "COMPLETED"})
                denied = runtime.run("uia.inspect", {"app": "notepad", "max_depth": 3,
                                                      "max_elements": 100})
                checks.append({"check": "uia_denied_without_screen_capability",
                               "passed": str(denied.get("state")) == "DENIED"})
                runtime.capability_grants.grant("screen.observe")
                inspected = runtime.run("uia.inspect", {"app": "notepad", "max_depth": 3,
                                                         "max_elements": 100})
                output = inspected.get("output", {})
                observed_count = output.get("count", 0)
                checks.append({"check": "real_bounded_uia_tree_for_exact_window",
                               "passed": str(inspected.get("state")) == "COMPLETED"
                               and 1 <= observed_count <= 100
                               and output.get("read_only") is True})
                events = runtime.event_log.events_for(inspected["task_id"])
                audited = next((payload for name, payload in events if name == "tool_result"), {})
                checks.append({"check": "uia_text_redacted_from_audit",
                               "passed": audited.get("output", {}).get("elements") == "[REDACTED_UI_TEXT]"})

                if opened_by_checker:
                    runtime.capability_grants.grant("desktop.input")
                    pending = runtime.run("apps.close", {"app": "notepad"})
                    closed = (runtime.approve(pending["approval"]["token"])
                              if str(pending.get("state")) == "WAITING_CONFIRMATION" else pending)
                    final = runtime.run("apps.status", {"app": "notepad"})
                    cleaned = (str(closed.get("state")) == "COMPLETED"
                               and final.get("output", {}).get("running") is False)
                else:
                    cleaned = True
                checks.append({"check": "checker_did_not_leave_a_new_app_window",
                               "passed": cleaned})

    report = {"timestamp_utc": datetime.now(UTC).isoformat(),
              "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(item["passed"] for item in checks), "checks": checks,
              "observed_element_count": observed_count,
              "privacy": "UI element names were used only in memory and redacted from the audit/report.",
              "scope": "Stage 8A-2 real read-only bounded UI Automation inspection of one exact app window."}
    target = PROJECT_ROOT / "verification/uia.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
