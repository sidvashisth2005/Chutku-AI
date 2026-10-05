"""Real read-only Windows clipboard boundary checker; never prints clipboard content."""
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
    with tempfile.TemporaryDirectory(prefix="chutku-clipboard-") as temp:
        with create_runtime(Path(temp)) as runtime:
            denied = runtime.run("clipboard.read_text", {})
            checks.append({"check": "clipboard_read_denied_without_grant",
                           "passed": str(denied.get("state")) == "DENIED"})
            runtime.capability_grants.grant("clipboard.read")
            result = runtime.run("clipboard.read_text", {})
            output = result.get("output", {})
            checks.append({"check": "real_bounded_text_clipboard_read",
                           "passed": str(result.get("state")) == "COMPLETED"
                           and isinstance(output.get("text"), str)
                           and output.get("characters") == len(output.get("text", ""))})
            events = runtime.event_log.events_for(result["task_id"])
            tool_result = next((payload for name, payload in events if name == "tool_result"), {})
            checks.append({"check": "clipboard_content_redacted_from_audit",
                           "passed": tool_result.get("output", {}).get("text") == "[REDACTED]"})
    report = {"timestamp_utc": datetime.now(UTC).isoformat(),
              "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(item["passed"] for item in checks), "checks": checks,
              "scope": "Stage 8B real read-only text clipboard boundary. Clipboard write remains unit-verified only."}
    target = PROJECT_ROOT / "verification/clipboard-read.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
