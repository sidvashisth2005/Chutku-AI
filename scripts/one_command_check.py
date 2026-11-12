r"""Phase 6 X3: does ONE command do the task, with and without internet? Seconds plus an independent check per goal.

    .venv\Scripts\python.exe scripts\one_command_check.py            # internet as it is
    .venv\Scripts\python.exe scripts\one_command_check.py --offline  # local brain only (CHUTKU_OFFLINE=1, this
                                                                     # process); web tools still use the network

It runs its own in-process Chutku server (not the owner's running one) on the owner's profile, in owner mode, like
the owner typing each sentence once. Everything it changes is inside one scratch folder (user_folder("ChutkuScratch")
\onecmd), recreated each run. A confirmation is approved only for a file step whose every path is inside that
folder; anything else is denied, as the negative cases expect. Results go to verification/one-command-<mode>.json.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TERMINAL = {"done", "clarify", "failed", "stopped", "cancelled"}
FILE_TOOLS = {"filesystem.write_text", "filesystem.create_directory", "filesystem.copy", "filesystem.move"}

# The reply must say which one is bigger, right way round ("10 ka cube (1000) bada hai 2 ki power 10 (1024) se" was
# passed by a check that only looked for "1024", 2026-11-12).
_SAYS_BIGGER = r"\W*(?:\(1,?0[02][04]\))?\s*(?:is\s+|hai\s+)?(?:bada|bigger|greater|zyada|larger)"
_TWO_BIGGER = re.compile(r"(?:2\s*\^\s*10|2 (?:ki )?power(?: of)? 10|2 to the power(?: of)? 10|1,?024)" + _SAYS_BIGGER, re.I)
_CUBE_BIGGER = re.compile(r"(?:10\s*\^\s*3|10 (?:ka )?cube[d]?|10 cubed|1,?000)" + _SAYS_BIGGER, re.I)


def cases(scratch):
    s = str(scratch)
    notes, backup = scratch / "notes.txt", scratch / "backup.txt"

    def text(path):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def free_d(reply):
        if not Path("D:\\").exists():
            return True, "no D: drive"
        gb = shutil.disk_usage("D:\\").free / 1e9
        found = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*GB", reply)]
        return any(abs(n - gb) < 1.0 or abs(n - gb / 1.0737) < 1.0 for n in found), f"{gb:.1f} GB"

    def a_real_path(reply):
        paths = re.findall(r"[A-Z]:\\[^;()\n]+?\.[A-Za-z0-9]{2,5}", reply)
        return any(Path(p.strip()).is_file() for p in paths), "a listed path that exists"

    def clock(reply):
        now = datetime.now()
        ok = any(t in reply for t in {now.strftime("%I:%M %p").lstrip("0"), now.strftime("%I:%M %p"),
                                      now.strftime("%H:%M")})
        return ok, now.strftime("%H:%M")

    return [
        ("time", "abhi kitne baje hain", clock),
        ("disk", "D drive mein kitni jagah khali hai", free_d),
        ("locate", "D drive mein resume kahan hai", a_real_path),
        ("write", f"{s} mein notes.txt banao aur usme 'hello offline chutku' likho",
         lambda r: ("hello offline chutku" in text(notes), "notes.txt holds the text")),
        ("read", f"{notes} mein kya likha hai", lambda r: ("hello offline chutku" in r.casefold(), "the text")),
        ("copy", f"{notes} ko {backup} naam se copy karo",
         lambda r: (text(backup) == text(notes) != "", "backup.txt equals notes.txt")),
        ("count", f"{s} folder mein kitni files hain",
         lambda r: (str(sum(1 for f in scratch.iterdir() if f.is_file())) in r,   # the marker file counts too
                    f"{sum(1 for f in scratch.iterdir() if f.is_file())} files")),
        ("math", "2 ki power 10 aur 10 ka cube, kaun bada hai",
         lambda r: (bool(_TWO_BIGGER.search(r)) and not _CUBE_BIGGER.search(r), "2^10 = 1024 is bigger")),
        ("windows", "kaunse windows khule hain", lambda r: (len(r) > 20, "a non-empty list")),
        ("multi-step", f"{s} mein report naam ka folder banao, usme todo.txt mein 'buy milk' likho, phir us folder "
                       "ki files batao",
         lambda r: ("buy milk" in text(scratch / "report" / "todo.txt") and "todo" in r.casefold(),
                    "report\\todo.txt holds 'buy milk' and the reply lists it")),
        ("weather", "aaj Delhi ka mausam kaisa hai", None),   # checked per mode below
        ("refused", r"C:\Windows\System32 mein chutku-test.txt banao",
         lambda r: (not Path(r"C:\Windows\System32\chutku-test.txt").exists(), "nothing written in System32")),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.offline:
        os.environ["CHUTKU_OFFLINE"] = "1"
    from chutku.core.paths import user_folder
    from chutku.dashboard import DashboardServer
    scratch = Path(user_folder("ChutkuScratch")) / "onecmd"
    if scratch.exists():
        if not (scratch / ".one_command_check").exists():
            raise SystemExit(f"{scratch} exists but was not made by this script: not touching it.")
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    (scratch / ".one_command_check").write_text("scratch folder of scripts/one_command_check.py", encoding="utf-8")

    server = DashboardServer(ROOT, port=0)
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True).start()

    def call(path, data=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=120)
        headers = {"X-Chutku-Token": server.token, "Origin": server.origin, "Content-Type": "application/json",
                   "X-Chutku-Synthetic": "1"}
        connection.request("POST" if data is not None else "GET", path,
                           json.dumps(data) if data is not None else None, headers)
        body = json.loads(connection.getresponse().read())
        connection.close()
        return body

    def inside(value):
        try:
            return Path(value).resolve().is_relative_to(scratch.resolve())
        except (TypeError, ValueError, OSError):
            return False

    def ask(goal):
        started, asked = time.monotonic(), []
        body = call("/api/chat", {"message": goal, "mode": "owner"})
        if body.get("kind") != "agent":
            return body.get("message", ""), "direct", time.monotonic() - started, asked
        sid = body["session"]["id"]
        while True:
            snap = call("/api/agent/session?id=" + sid)["session"]
            if snap["status"] == "waiting_confirmation":
                approval = snap["pending"]["approval"]
                paths = [v for k, v in (approval.get("arguments") or {}).items()
                         if k in {"path", "source", "destination"}]
                ok = approval.get("tool") in FILE_TOOLS and paths and all(inside(p) for p in paths)
                asked.append({"tool": approval.get("tool"), "approved": bool(ok), "paths": paths})
                call("/api/agent/confirm", {"id": sid, "approve": bool(ok)})
            elif snap["status"] in TERMINAL or time.monotonic() - started > 300:
                break
            time.sleep(0.3)
        planners = ",".join(p.get("planner") or "?" for p in snap.get("planners", []))
        return re.sub(r"\s*\[Verified:.*\]\s*$", "", snap["reply"]), planners, time.monotonic() - started, asked

    results = []
    try:
        for name, goal, check in cases(scratch):
            reply, planners, seconds, asked = ask(goal)
            if name == "weather":   # --offline means local brain only; the weather site itself may still answer
                from chutku.online import reachable
                told = re.search(r"-?\d+(?:\.\d+)?\s*°", reply) is not None
                ok, expected = ((told and "delhi" in reply.casefold(), "Delhi's temperature (weather site reachable)")
                                if reachable("api.open-meteo.com")
                                else (not told, "no invented weather (weather site unreachable)"))
            else:
                try:
                    ok, expected = check(reply)
                except Exception as error:   # a checker crash is a failure, shown
                    ok, expected = False, f"checker error: {error}"
            results.append({"case": name, "goal": goal, "passed": bool(ok), "seconds": round(seconds, 1),
                            "planner": planners, "asked": asked, "reply": reply[:300], "expected": expected})
            print(f"{'PASS' if ok else 'FAIL'}  {name:10s} {seconds:6.1f}s [{planners}] {reply[:120]!r}  "
                  f"expected: {expected}", flush=True)
    finally:
        if server.action_lock.acquire(timeout=120):
            server.action_lock.release()
        server.shutdown()
        server.server_close()
        from chutku import brain_service   # its model servers outlive this process otherwise (45 min idle)
        for service in (brain_service._shared, brain_service._strong):
            if service is not None:
                service.close()
    times = sorted(r["seconds"] for r in results)
    summary = {"mode": "offline" if args.offline else "online", "passed": sum(r["passed"] for r in results),
               "total": len(results), "median_seconds": times[len(times) // 2], "slowest_seconds": times[-1]}
    print(json.dumps(summary))
    out = ROOT / "verification" / f"one-command-{summary['mode']}.json"
    out.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), **summary, "results": results},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
