"""Send the owner's real sentences to the running Chutku (/api/chat) and time each answer (20x plan P1 checks).

    python scripts/live_replay.py [--mode owner] "sentence one" "sentence two" ...

Marked synthetic, so the scoreboard leaves these turns out. Waiting approvals are reported, never approved here.
"""
from __future__ import annotations

import argparse
import sys
import time

from time_live_chat import ROOT, TERMINAL  # noqa: F401  (same folder; ROOT used for the session file)
import json
import urllib.request


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="owner")
    parser.add_argument("sentences", nargs="+")
    args = parser.parse_args(argv)
    link = json.loads((ROOT / "data" / "dashboard-session.json").read_text(encoding="utf-8"))["url"]
    origin, token = link.split("#", 1)[0].rstrip("/"), link.split("token=", 1)[1]

    def call(path, data=None):
        request = urllib.request.Request(origin + path, headers={
            "X-Chutku-Token": token, "X-Chutku-Synthetic": "1", "Content-Type": "application/json", "Origin": origin},
            data=None if data is None else json.dumps(data).encode("utf-8"))
        return json.loads(urllib.request.urlopen(request, timeout=30).read())

    for sentence in args.sentences:
        started = time.monotonic()
        payload = call("/api/chat", {"message": sentence, "mode": args.mode})
        if payload.get("kind") == "direct":
            snap = {"status": "done", "reply": payload.get("message", ""), "planners": [{"planner": "direct"}],
                    "steps": [{"tool": (payload.get("result") or {}).get("tool", "?")}]}
        else:
            session_id = payload["session"]["id"]
            while True:
                snap = call("/api/agent/session?id=" + session_id)["session"]
                if snap["status"] in TERMINAL or time.monotonic() - started > 180:
                    break
                time.sleep(0.3)
        tools = ",".join(s.get("tool", "?") for s in snap.get("steps", [])) or "-"
        planners = ",".join(p.get("planner") or "?" for p in snap.get("planners", [])) or "-"
        print(f"{time.monotonic() - started:6.1f}s {snap['status']:<20} {planners:<12} {sentence!r} [{tools}] -> "
              f"{(snap.get('reply') or '')[:140]!r}", flush=True)
        if snap["status"] == "waiting_confirmation":
            call("/api/agent/confirm", {"id": snap["id"], "approve": False})   # never approved by a script
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
