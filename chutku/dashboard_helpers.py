"""Small dashboard helpers shared by the server and its mixins: the action log, pause explanations, the last task."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

from chutku.core.action_control import ActionControl


def _log():
    from chutku.core.log import get_logger
    return get_logger("dashboard")


_STOP_REASONS = {
    "heartbeat_timeout": "Chutku's core stopped responding (this also happens when the PC wakes from sleep)",
    "action_deadline": "an action ran longer than 2 minutes",
    "emergency_stop": "the emergency stop was used (Ctrl+Alt+F12, Stop Chutku or the tray menu)",
    "core_exited": "Chutku's core closed unexpectedly",
    "core_disconnected": "Chutku's core closed unexpectedly",
    "startup_timeout": "Chutku's core did not start in time",
}


def paused_spoken(base):
    """One short spoken sentence (her own Hinglish, feminine) for why actions are paused."""
    info = ActionControl(base).info()
    source, reason = info.get("source"), info.get("reason")
    if source == "owner":
        return ("Emergency stop dabaya gaya tha, isliye main paused hoon." if reason == "emergency_stop"
                else "Aapne mujhe pause kiya hua hai.")
    if source in {"guard", "startup"}:
        return "Main atak gayi thi, isliye paused hoon; thodi der mein khud chalu ho jaungi."
    return "Main abhi paused hoon."


def _when(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%I:%M %p on %d %b").lstrip("0")


def paused_explanation(base, *, short=False):
    """Plain words for 'why can't you do anything': who paused (the owner, or the guard and why) and how to
    resume. short=True gives only the reason, for the dashboard banner that carries its own Resume button."""
    info = ActionControl(base).info()
    why = ""
    if info.get("source") == "owner":
        when = f" at {_when(info['at'])}" if info.get("at") else ""
        why = (" The emergency stop was used" if info.get("reason") == "emergency_stop" else " You paused me") + when + "."
    elif info.get("source") == "startup":
        why = " I closed unexpectedly last time, so I paused to be safe; I resume by myself once I'm running fine."
    else:
        try:
            report = json.loads((Path(base) / "data" / "guard-last-stop.json").read_text(encoding="utf-8"))
            when = datetime.fromisoformat(report["timestamp_utc"]).astimezone().strftime("%I:%M %p on %d %b").lstrip("0")
            why = f" Chutku paused itself at {when} because {_STOP_REASONS.get(report.get('reason'), 'it was stopped')}."
            if info.get("source") == "guard":
                why += " I resume by myself once the restarted core is running fine."
        except (OSError, ValueError, KeyError):
            why = ""
    if short:
        return (why.strip() or "Actions are paused.") + " Nothing runs until you resume."
    return ("I'm paused, so I didn't do that." + why + " Nothing runs while paused, for safety. "
            "Click “Resume actions” at the top of this page (or in the tray menu), then ask again.")


def _last_task_file(base):
    return Path(base) / "data" / "last-task.json"


def interrupted_task(base):
    try:
        record = json.loads(_last_task_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if record.get("status") == "interrupted" else None


def open_app_window(url):
    """Open the dashboard. An installed Chutku opens it as its own app window (Edge's app mode: no tabs or address
    bar, a separate profile in Chutku's data folder), not as a tab in the user's browser (PC check 2026-11-07: the
    Start-menu launch opened an Edge tab). A git checkout keeps the browser tab the owner is used to."""
    import os
    import subprocess
    import webbrowser
    from chutku.core.paths import data_dir, is_checkout
    edges = [Path(os.environ.get(var, "")) / "Microsoft/Edge/Application/msedge.exe"
             for var in ("ProgramFiles(x86)", "ProgramFiles")]
    edge = next((e for e in edges if e.is_file()), None)
    if is_checkout() or edge is None:
        webbrowser.open(url)
        return
    subprocess.Popen([str(edge), f"--app={url}", "--window-size=1280,860", "--no-first-run",
                      f"--user-data-dir={data_dir() / 'app-window'}"], close_fds=True)
