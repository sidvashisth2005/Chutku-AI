"""Time real questions through the running Chutku (its own /api/chat), read-only questions only.

Usage: .venv\\Scripts\\python.exe scripts\\time_live_chat.py
Reports, per question: seconds to the final answer, status, which planner answered (quick = instant rules).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "What time is it?", "Which graphics card do I have and how much VRAM?", "Which Windows version is this PC running?",
    "What is the current volume level?", "Is Windows using dark mode or light mode right now?",
    "How much free space is left on my C drive?", "D drive mein kitni jagah khali hai?", "How much RAM am I using right now?",
    "Is my internet working?", "Am I connected to the network? Which adapter is up?", "How many displays are connected?",
    "Is VLC or Spotify installed on this PC?", "What is my screen brightness?", "Which games do I have installed?",
    "What is the capital of France?", "Hi Chutku, how are you?",
]
TERMINAL = {"done", "clarify", "failed", "stopped", "cancelled", "waiting_confirmation"}


def main():
    link = json.loads((ROOT / "data" / "dashboard-session.json").read_text(encoding="utf-8"))["url"]
    origin, token = link.split("#", 1)[0].rstrip("/"), link.split("token=", 1)[1]

    def call(path, data=None):
        request = urllib.request.Request(origin + path, headers={"X-Chutku-Token": token, "Content-Type": "application/json",
                                                                 "Origin": origin},
                                         data=None if data is None else json.dumps(data).encode("utf-8"))
        return json.loads(urllib.request.urlopen(request, timeout=30).read())

    rows = []
    for question in QUESTIONS:
        started = time.monotonic()
        payload = call("/api/chat", {"message": question, "mode": "auto_safe"})
        if payload.get("kind") == "direct":
            snapshot = {"status": "done", "reply": payload.get("message", ""), "planners": [{"planner": "direct"}]}
        else:
            session_id = payload["session"]["id"]
            while True:
                snapshot = call("/api/agent/session?id=" + session_id)["session"]
                if snapshot["status"] in TERMINAL or time.monotonic() - started > 180:
                    break
                time.sleep(0.3)
        seconds = round(time.monotonic() - started, 1)
        planners = ",".join(p.get("planner") or "?" for p in snapshot.get("planners", [])) or "-"
        rows.append(seconds)
        print(f"{seconds:6.1f}s  {snapshot['status']:<10} {planners:<14} {question}  ->  "
              f"{snapshot.get('reply', '')[:110]!r}", flush=True)
    ordered = sorted(rows)
    print(f"\nmedian {ordered[len(ordered) // 2]} s, max {ordered[-1]} s over {len(rows)} questions")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
