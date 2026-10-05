"""Start Chutku when the owner signs in to Windows, so Ctrl+Alt+Space works right away.

A per-user Task Scheduler logon task (normal rights, never elevated, no time limit, runs on
battery) starts the guarded server with the project folder as working directory. It starts at
sign-in, unlike the Startup folder, which Windows may delay by minutes, and opens no console.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from chutku.app import PROJECT_ROOT

TASK = "Chutku"
FOLDER = "\\Chutku\\"  # the same per-user folder reminders use (no admin rights needed)
_LEGACY = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/Chutku.cmd"


def _ps(script):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                          text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def status():
    done = _ps(f"$t = Get-ScheduledTask -TaskName {_quote(TASK)} -TaskPath {_quote(FOLDER)} -ErrorAction SilentlyContinue; "
               "if ($t) { $t.State } else { 'absent' }")
    state = (done.stdout or "").strip() or "absent"
    return {"autostart": state not in {"absent", "Disabled"}, "task": TASK, "state": state,
            "legacy_startup_file": _LEGACY.is_file(),
            "note": "Starts the guarded server at sign-in (no browser). Press Ctrl+Alt+Space or say "
                    "'Oye Chutku' / 'Chutku sun'. Open Start-Chutku.cmd for the chat page."}


def enable():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = (
        f"$a = New-ScheduledTaskAction -Execute {_quote(pythonw)} -Argument '-m chutku.guard' "
        f"-WorkingDirectory {_quote(PROJECT_ROOT)}; "
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew; "
        "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited; "
        f"Register-ScheduledTask -TaskName {_quote(TASK)} -TaskPath {_quote(FOLDER)} -Action $a -Trigger $t -Settings $s -Principal $p "
        "-Description 'Chutku voice/PC assistant (Ctrl+Alt+Space)' -Force | Out-Null")
    done = _ps(script)
    if done.returncode != 0:
        raise OSError("Could not create the sign-in task: " + (done.stderr or "").strip()[:300])
    _LEGACY.unlink(missing_ok=True)  # the old Startup-folder entry would start a second (harmless) guard
    return status()


def disable():
    _ps(f"Unregister-ScheduledTask -TaskName {_quote(TASK)} -TaskPath {_quote(FOLDER)} -Confirm:$false -ErrorAction SilentlyContinue")
    _LEGACY.unlink(missing_ok=True)
    return status()


def autostart(action):
    return {"on": enable, "off": disable, "status": status}[action]()
