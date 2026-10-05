"""Exercise the real authenticated HTTP voice-review boundary without recording."""
from __future__ import annotations

from datetime import UTC, datetime
import http.client
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from chutku.dashboard import DashboardServer
from chutku.app import create_runtime
from chutku.brain import validate_tool_plan
from chutku.evidence import source_digest


def main():
    output = BASE / "verification/voice-review-path.json"
    checks = []
    with TemporaryDirectory(prefix="chutku-voice-review-") as temporary:
        server = DashboardServer(Path(temporary), port=0)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()

        def request(path, data=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"X-Chutku-Token": server.token, "Origin": server.origin}
            body = None
            method = "GET"
            if data is not None:
                method = "POST"
                headers["Content-Type"] = "application/json"
                body = json.dumps(data)
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            payload = json.loads(response.read())
            connection.close()
            return response.status, payload

        try:
            source_task = "voice-capture-fixture"
            with create_runtime(Path(temporary)) as runtime:
                plan = validate_tool_plan({"reply": "Prepared.", "steps": [{
                    "tool": "system.get_time", "arguments": {}, "purpose": "Read the current time"}],
                    "needs_clarification": False}, runtime)
            token = server.voice_previews.add({"plan": plan, "source_task_id": source_task})
            status, _ = request("/api/voice/execute", {"review_token": token, "message": "open calculator"})
            checks.append({"check": "tampered_review_refused", "passed": status == 400})
            status, payload = request("/api/voice/execute", {"review_token": token})
            result = payload.get("result", {})
            checks.append({"check": "reviewed_command_completed", "passed": status == 200 and result.get("state") == "COMPLETED"})
            checks.append({"check": "source_task_bound", "passed": payload.get("voice_source_task_id") == source_task})
            task_id = result.get("plan_steps", [{}])[0].get("task_id", "")
            status, trace = request("/api/trace?id=" + task_id)
            authorization = next((row for row in trace.get("events", []) if row.get("event_type") == "authorization"), {})
            checks.append({"check": "microphone_provenance_preserved", "passed": status == 200 and authorization.get("details", {}).get("provenance") == "reviewed_microphone"})
            checks.append({"check": "replay_refused", "passed": request("/api/voice/execute", {"review_token": token})[0] == 400})
            cancelled = server.voice_previews.add({"plan": plan, "source_task_id": source_task})
            checks.append({"check": "cancel_accepted", "passed": request("/api/voice/review/cancel", {"review_token": cancelled})[0] == 200})
            checks.append({"check": "cancelled_review_cannot_execute", "passed": request("/api/voice/execute", {"review_token": cancelled})[0] == 400})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "source_sha256": source_digest(BASE),
        "passed": all(row["passed"] for row in checks),
        "checks": checks,
        "scope": "Authenticated loopback voice-review token boundary; no microphone or raw audio used by this checker.",
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
