"""Real end-to-end check of "build me a calculator app" through the chat API.

Path: /api/chat -> quick router -> code.build_project (R3, confirmed like the on-screen click)
-> coder (Gemini if enabled, else the local model) writes files into D:\\ChutkuProjects\\...
-> VS Code opens the project -> compile + the project's own tests + the app window appears
-> repairs from real errors. The progress heartbeat is sampled to prove long builds keep the
guard's 120 s action deadline fresh.

Negatives: declining the confirmation writes nothing; a protected folder (C:\\Windows) is refused.
The built app and its VS Code window are left open for the owner to look at.
"""
from __future__ import annotations

import http.client
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.app import create_runtime  # noqa: E402
from chutku.dashboard import DashboardServer  # noqa: E402
from chutku.evidence import source_digest  # noqa: E402

TERMINAL = {"done", "clarify", "failed", "stopped", "cancelled"}
GOAL = sys.argv[1] if len(sys.argv) > 1 else "build me a calculator app"


def main():
    server = DashboardServer(ROOT, port=0)
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True).start()

    def call(path, data=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=120)
        headers = {"X-Chutku-Token": server.token, "Origin": server.origin, "Content-Type": "application/json"}
        connection.request("POST" if data is not None else "GET", path,
                           json.dumps(data) if data is not None else None, headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return body

    def run(goal, approve):
        body = call("/api/chat", {"message": goal, "mode": "auto_edits"})
        session_id = body["session"]["id"]
        started, max_stale, confirmed = time.monotonic(), 0.0, None
        while True:
            time.sleep(1.0)
            if server.action_started is not None:
                max_stale = max(max_stale, time.monotonic() - server.action_started)
            snap = call("/api/agent/session?id=" + session_id)["session"]
            if snap["status"] == "waiting_confirmation" and confirmed is None:
                confirmed = snap["pending"]["approval"]
                call("/api/agent/confirm", {"id": session_id, "approve": approve})
                continue
            if snap["status"] == "waiting_confirmation":  # a second request (e.g. a retry) is not auto-approved
                call("/api/agent/stop", {"id": session_id})
                continue
            if snap["status"] in TERMINAL:
                break
            if time.monotonic() - started > 2400:
                call("/api/agent/stop", {"id": session_id})
        session = server.agent_sessions.get(session_id)
        output = None
        for step in session.steps:
            if step["tool"] == "code.build_project":
                try:
                    output = json.loads(step["observation"])
                except (TypeError, ValueError):
                    output = {"raw": str(step["observation"])[:500]}
        return snap, confirmed, output, round(time.monotonic() - started, 1), round(max_stale, 1)

    checks = []
    try:
        before = {p.name for p in Path(r"D:\ChutkuProjects").glob("*")} if Path(r"D:\ChutkuProjects").exists() else set()
        snap, confirmed, output, seconds, stale = run(GOAL, False)
        after = {p.name for p in Path(r"D:\ChutkuProjects").glob("*")} if Path(r"D:\ChutkuProjects").exists() else set()
        checks.append({"case": "declined confirmation writes nothing", "status": snap["status"],
                       "asked_tool": (confirmed or {}).get("tool"), "passed": confirmed is not None
                       and confirmed.get("tool") == "code.build_project" and after == before})
        print(json.dumps(checks[-1]), flush=True)

        with create_runtime(ROOT) as runtime:
            refused = runtime.run("code.build_project", {"request": "a calculator", "path": r"C:\Windows\ChutkuCalc"})
        checks.append({"case": "protected folder refused", "state": str(refused["state"]),
                       "passed": str(refused["state"]) in {"FAILED", "DENIED"} and not Path(r"C:\Windows\ChutkuCalc").exists()})
        print(json.dumps(checks[-1]), flush=True)

        snap, confirmed, output, seconds, stale = run(GOAL, True)
        folder = Path(output["folder"]) if output and output.get("folder") else None
        passed = (snap["status"] == "done" and output is not None and not output.get("error")
                  and folder is not None and folder.is_dir() and output.get("vscode", {}).get("opened") is True
                  and (output.get("app_running") or output.get("kind") in {"web", "cli"}) and stale < 120)
        checks.append({"case": GOAL, "status": snap["status"], "seconds": seconds,
                       "max_heartbeat_gap_seconds": stale, "reply": snap["reply"][:400],
                       "folder": str(folder) if folder else None,
                       "build": {k: output.get(k) for k in ("kind", "entry_file", "design", "files", "coder", "model",
                                                           "attempts", "checks", "vscode", "app_running", "seconds",
                                                           "error", "note")} if output else None,
                       "passed": bool(passed)})
        print(json.dumps(checks[-1], ensure_ascii=False)[:3000], flush=True)
    finally:
        if server.action_lock.acquire(timeout=120):
            server.action_lock.release()
        server.shutdown()
        server.server_close()
        from chutku.brain_service import shared_service
        shared_service(ROOT).close()
    report = {"generated_at": datetime.now(UTC).isoformat(), "source_digest": source_digest(ROOT),
              "passed": all(c["passed"] for c in checks), "checks": checks,
              "scope": "Real chat API on the owner's profile: project build with the configured coder, VS Code, "
                       "compile/tests/window checks, repair loop, heartbeat; decline and protected-folder negatives."}
    (ROOT / "verification/builder.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} passed")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
