"""Real multi-step tasks (5-10+ steps) through the chat API on the owner's PC, with Gemini leading
(free models) and screen vision. Each task has an end-state check that inspects the real result.

Confirmations: the script approves steps that stay inside D:\\ChutkuLong or are the app actions a task
asks for (like closing the Notepad window it opened). It denies everything else, and records every
decision. Outputs go to D:\\ChutkuLong, which is cleaned before each run.
"""
from __future__ import annotations

import http.client
import json
from datetime import UTC, datetime
from pathlib import Path
import re
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from chutku.dashboard import DashboardServer  # noqa: E402
from chutku.evidence import source_digest  # noqa: E402

OUT = Path(r"D:\ChutkuLong")
TERMINAL = {"done", "clarify", "failed", "stopped", "cancelled"}


def text_of(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


TASKS = [
    dict(id="research-report", goal=r"Research the 3 best budget laptops under 70000 rupees in India right now, compare "
         r"their price, processor and RAM, and save a short comparison report to D:\ChutkuLong\laptops.txt",
         check=lambda s: len(text_of(OUT / "laptops.txt")) > 200),
    dict(id="project-scaffold", goal=r"Create the folder D:\ChutkuLong\todo-app with subfolders docs, src and tests, "
         r"write a README.md in it that explains what a to-do app does, then list the folder to confirm",
         check=lambda s: all((OUT / "todo-app" / d).is_dir() for d in ("docs", "src", "tests"))
         and len(text_of(OUT / "todo-app" / "README.md")) > 40),
    dict(id="largest-files", goal=r"Find the 5 largest files in my Downloads folder and write their names and sizes "
         r"into D:\ChutkuLong\big.txt, one per line",
         check=lambda s: len([l for l in text_of(OUT / "big.txt").splitlines() if l.strip()]) >= 5),
    dict(id="weather-news-brief", goal=r"Get the weather in Delhi and the top 3 cricket headlines, and save both into "
         r"D:\ChutkuLong\brief.txt",
         check=lambda s: re.search(r"°|celsius|temperature", text_of(OUT / "brief.txt"), re.I) is not None
         and len(text_of(OUT / "brief.txt")) > 120),
    dict(id="notepad-type-save", goal=r"Open Notepad, type 'Chutku long task test', save the file as "
         r"D:\ChutkuLong\note.txt and then close Notepad",
         check=lambda s: "Chutku long task test" in text_of(OUT / "note.txt") and s["status"] == "done"),
    dict(id="calculator-by-vision", goal="Open Calculator and use the screen to click the buttons to calculate 125 x 48, "
         "then tell me the result and close Calculator",
         check=lambda s: "6000" in s["reply"].replace(",", "")),
    dict(id="screen-what", goal="Look at my screen and tell me which app is in front and what it is showing",
         check=lambda s: s["status"] == "done" and any(st["tool"] == "screen.understand" and st["state"] == "COMPLETED"
                                                       for st in s["steps"])),
    dict(id="youtube-play-first", goal="Open YouTube in the browser, search for lofi hip hop, and click the first "
         "video to play it",
         check=lambda s: any(st["tool"] in {"screen.click", "youtube.play"} and st["state"] == "COMPLETED"
                             for st in s["steps"])),
]

SAFE_TOOLS = {"filesystem.write_text", "filesystem.create_directory", "filesystem.copy", "filesystem.move",
              "keyboard.type_text", "keyboard.edit", "keyboard.press_enter", "apps.quit", "apps.close", "windows.close",
              "screen.click_risky", "uia.set_value", "uia.invoke", "input.type_text", "input.click"}


def _windows():
    from chutku.tools.everyday import Desktop
    desktop = Desktop()
    return {hwnd: desktop.describe(hwnd) for hwnd in desktop.windows(300)}


_DISCARD = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]; $S = [System.Windows.Automation.TreeScope]
$w = $A::FromHandle([IntPtr]%d)
$w.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close(); Start-Sleep -Milliseconds 1500
$b = $w.FindFirst($S::Descendants, (New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, "Don't save")))
if ($b) { $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
"""


def _dialogs(pids):
    import ctypes
    from ctypes import wintypes as w
    user32, found = ctypes.windll.user32, []
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def collect(hwnd, _):
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        pid = w.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if name.value == "#32770" and user32.IsWindowVisible(hwnd) and pid.value in pids:
            found.append(hwnd)
        return True
    user32.EnumWindows(callback(collect), 0)
    return found


def close_new_windows(before):
    """Close what a task opened (never the owner's existing windows): its dialogs first (= Cancel), then
    its windows; an unsaved test editor window is closed with "Don't save"."""
    import ctypes
    import subprocess
    user32 = ctypes.windll.user32
    new = {hwnd: info for hwnd, info in _windows().items()
           if hwnd not in before and "Visual Studio Code" not in info["title"]}
    for dialog in _dialogs({info["process_id"] for info in new.values()}):
        user32.PostMessageW(dialog, 0x10, 0, 0)
    time.sleep(1.0)
    for hwnd, info in new.items():
        if info["title"].startswith("*"):
            subprocess.run(["powershell", "-NoProfile", "-Command", _DISCARD % hwnd], capture_output=True, timeout=30)
        else:
            user32.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE
    time.sleep(1.0)


BEFORE = set()  # windows that existed before the current task
BEFORE_TITLES = []


def decide(approval):
    """Approve only what the task asked for and what stays inside D:\\ChutkuLong or the task's own apps."""
    tool, args = approval.get("tool"), approval.get("arguments") or {}
    paths = [str(v) for k, v in args.items() if k in ("path", "source", "destination")]
    if tool not in SAFE_TOOLS:
        return False
    if paths and not all(p.lower().startswith(str(OUT).lower()) for p in paths):
        return False
    if tool in {"apps.quit", "apps.close"}:
        # closes every window of the app: only when the task opened it and the owner had none open before
        name = str(args.get("name", args.get("app", ""))).casefold()
        return bool(name) and not any(name in str(title).casefold() for title in BEFORE_TITLES)
    if tool == "windows.close":
        return int(args.get("window_id", 0)) not in BEFORE  # only windows this task opened
    return True


def main():
    only = set(sys.argv[1:])
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
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

    rows = []
    try:
        for task in TASKS:
            if only and task["id"] not in only:
                continue
            started = time.monotonic()
            before = _windows()
            BEFORE.clear()
            BEFORE.update(before)
            BEFORE_TITLES[:] = [info["title"] for info in before.values()]
            body = call("/api/chat", {"message": task["goal"], "mode": "auto_edits"})
            if body.get("kind") != "agent":
                rows.append({"id": task["id"], "passed": False, "detail": body})
                continue
            session_id, decisions = body["session"]["id"], []
            while True:
                time.sleep(1.0)
                snap = call("/api/agent/session?id=" + session_id)["session"]
                if snap["status"] == "waiting_confirmation":
                    approval = snap["pending"]["approval"]
                    verdict = decide(approval)
                    decisions.append({"tool": approval["tool"], "approved": verdict,
                                      "arguments": {k: str(v)[:60] for k, v in (approval.get("arguments") or {}).items()}})
                    call("/api/agent/confirm", {"id": session_id, "approve": verdict})
                    continue
                if snap["status"] in TERMINAL:
                    break
                if time.monotonic() - started > 900:
                    call("/api/agent/stop", {"id": session_id})
            try:
                passed = bool(task["check"](snap))
            except Exception as error:
                passed = False
            row = {"id": task["id"], "passed": passed, "status": snap["status"],
                   "seconds": round(time.monotonic() - started, 1), "rounds": snap["rounds"],
                   "planners": [p["planner"] for p in snap["planners"]],
                   "steps": [f"{s['tool']}:{s['state']}" for s in snap["steps"]],
                   "confirmations": decisions, "reply": snap["reply"][:500]}
            rows.append(row)
            close_new_windows(before)
            print(("PASS " if passed else "FAIL ") + json.dumps(row, ensure_ascii=False)[:1500], flush=True)
    finally:
        if server.action_lock.acquire(timeout=300):
            server.action_lock.release()
        server.shutdown()
        server.server_close()
        from chutku.brain_service import shared_service
        shared_service(ROOT).close()
    report = {"generated_at": datetime.now(UTC).isoformat(), "source_digest": source_digest(ROOT),
              "passed": sum(r["passed"] for r in rows), "total": len(rows), "rows": rows,
              "scope": "Real multi-step tasks on the owner's PC via the chat API: Gemini-led planning (free models), "
                       "screen vision and clicks, web research, files, apps. End states checked on disk/screen."}
    name = "long-tasks.json" if not only else "long-tasks-subset.json"
    (ROOT / "verification" / name).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{report['passed']}/{report['total']} passed")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
