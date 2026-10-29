r"""Live check of the running Chutku: how long each answer takes AND whether it is correct.

Owner (2026-10-05): "when testing look for the time it is taking for the answer and then recheck that the answer must
be correct too". Every case asks the running Chutku (its own /api/chat) a read-only question and checks the reply
against an independent measurement (clock, disk, files, RAM, GPU, monitors, arithmetic). Nothing is changed on the PC.

Usage: .venv\Scripts\python.exe scripts\live_check.py [--only time disk-c ...]
Prints per case: PASS/WRONG/SLOW, seconds, which planner answered, the reply, and what was expected.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"done", "clarify", "failed", "stopped", "cancelled", "waiting_confirmation"}
SLOW_SECONDS = 30


def numbers(text):
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]


def check_time(reply):
    now = datetime.now()
    for hour, minute, half in re.findall(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", reply):
        hour = int(hour) % 12 + (12 if half and half.lower() == "pm" else 0) if half else int(hour)
        said = now.replace(hour=hour, minute=int(minute), second=0, microsecond=0)
        if abs(said - now) <= timedelta(minutes=2):
            return True, now.strftime("%H:%M")
    return False, now.strftime("%H:%M (±2 min)")


def free_check(drive):
    usage = shutil.disk_usage(f"{drive}:\\")
    gib, gb = usage.free / 1024 ** 3, usage.free / 1e9

    def check(reply):
        # The number right after "<drive>:" if present, else any number in the reply.
        near = re.search(rf"\b{drive}:?\s*(?:drive)?[^0-9]{{0,30}}(\d+(?:\.\d+)?)", reply, re.I)
        candidates = [float(near.group(1))] if near else numbers(reply)
        ok = any(abs(n - gib) <= 0.6 or abs(n - gb) <= 0.6 for n in candidates)
        return ok, f"{gib:.1f} GiB / {gb:.1f} GB free"
    return check


def biggest_download(reply):
    folder = Path(os.environ["USERPROFILE"]) / "Downloads"
    best = max(((p.stat().st_size, p.name) for p in folder.rglob("*") if p.is_file()), default=(0, ""))
    return best[1].casefold() in reply.casefold(), best[1]


def desktop_count(reply):
    folders = [Path(os.environ["USERPROFILE"]) / "Desktop", Path(os.environ.get("PUBLIC", "C:\\Users\\Public")) / "Desktop"]
    files = sum(1 for d in folders[:1] if d.is_dir() for p in d.iterdir() if p.is_file())
    entries = sum(1 for d in folders[:1] if d.is_dir() for _ in d.iterdir())
    return any(n in (files, entries) for n in numbers(reply)), f"{files} files ({entries} items)"


def ram_check(reply):
    class Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                   [(n, ctypes.c_ulonglong) for n in ("t", "a", "tp", "ap", "tv", "av", "e")]
    status = Status()
    status.dwLength = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    load = status.dwMemoryLoad
    used_gb = (status.t - status.a) / 1024 ** 3
    ok = any(abs(n - load) <= 8 for n in numbers(reply)) or any(abs(n - used_gb) <= 1.5 for n in numbers(reply))
    return ok, f"{load}% used ({used_gb:.1f} GiB)"


def monitors(reply):
    count = ctypes.windll.user32.GetSystemMetrics(80)   # SM_CMONITORS
    words = {1: "one", 2: "two", 3: "three"}
    return (str(count) in re.findall(r"\d+", reply) or words.get(count, "#") in reply.casefold()), f"{count} display(s)"


def check_night(reply):
    """The night report must quote the newest saved report: its date and how many requests it re-checked."""
    reports = sorted((ROOT / "data" / "nightshift").glob("report-*.json"))
    if not reports:
        return "not run yet" in reply, "no report saved -> 'not run yet'"
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    rechecked = str((report.get("jobs", {}).get("regression_replay") or {}).get("distinct_goals", ""))
    return report["date"] in reply and rechecked in reply, f"date {report['date']}, {rechecked} re-checked"


CASES = [
    ("time", "what time is it", check_time),
    ("night-report", "Have you prepared the night report?", check_night),
    ("night-report-hi", "नाइट शिफ्ट रिपोर्ट बताओ", check_night),
    ("time-hinglish", "kitne baje hain", check_time),
    ("disk-c", "how much free space is left on my C drive", free_check("C")),
    ("disk-d", "D drive mein kitni jagah khali hai", free_check("D")),
    ("math-power", "which is bigger, 2 to the power 10 or 10 cubed? one line",
     lambda r: (("1024" in r and "1000" in r and not re.search(r"10 cubed[^.]*\bis (?:bigger|larger|greater)", r, re.I)),
                "2^10 = 1024 is bigger than 1000")),
    ("math-percent", "what is 15 percent of 240? just the number",
     lambda r: (36.0 in numbers(r), "36")),
    ("biggest-download", "what is the biggest file in my Downloads folder", biggest_download),
    ("desktop-count", "mere desktop pe kitni files hain", desktop_count),
    ("ram", "how much RAM am I using right now", ram_check),
    ("slow-pc", "Ita lag kar rahe.", ram_check),   # night report 2026-10-07: must check what is using the PC
    ("slow-pc-hi", "इतना लैग कर रहा है", ram_check),
    ("gpu", "which graphics card do I have", lambda r: ("3050" in r, "NVIDIA GeForce RTX 3050")),
    ("displays", "how many displays are connected", monitors),
    ("knowledge", "what is the capital of France? one word", lambda r: ("paris" in r.casefold(), "Paris")),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    link = json.loads((ROOT / "data" / "dashboard-session.json").read_text(encoding="utf-8"))["url"]
    origin, token = link.split("#", 1)[0].rstrip("/"), link.split("token=", 1)[1]

    def call(path, data=None):
        request = urllib.request.Request(origin + path, data=None if data is None else json.dumps(data).encode(),
                                         headers={"X-Chutku-Token": token, "X-Chutku-Synthetic": "1", "Content-Type": "application/json",
                                                  "Origin": origin})
        return json.loads(urllib.request.urlopen(request, timeout=60).read())

    results = []
    for name, question, check in CASES:
        if args.only and name not in args.only:
            continue
        started = time.monotonic()
        out = call("/api/chat", {"message": question, "mode": "owner"})
        if out.get("kind") == "agent":
            sid = out["session"]["id"]
            while True:
                snap = call("/api/agent/session?id=" + sid)["session"]
                if snap["status"] in TERMINAL or time.monotonic() - started > 300:
                    break
                time.sleep(0.3)
            reply = re.sub(r"\s*\[Verified:.*\]\s*$", "", snap["reply"])
            planners = ",".join(p.get("planner") or "?" for p in snap.get("planners", []))
        else:
            reply, planners = out.get("message", ""), "direct"
        seconds = time.monotonic() - started
        try:
            ok, expected = check(reply)
        except Exception as error:   # a checker crash is a failure, shown
            ok, expected = False, f"checker error: {error}"
        verdict = "WRONG" if not ok else ("SLOW" if seconds > SLOW_SECONDS else "PASS")
        results.append((verdict, seconds))
        print(f"{verdict:5s} {name:16s} {seconds:5.1f}s [{planners}] {reply[:110]!r}  expected: {expected}", flush=True)
    right = sum(1 for v, _ in results if v != "WRONG")
    times = sorted(s for _, s in results)
    print(f"{right}/{len(results)} correct, {sum(1 for v, _ in results if v == 'PASS')} correct and under "
          f"{SLOW_SECONDS}s; median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")


if __name__ == "__main__":
    main()
