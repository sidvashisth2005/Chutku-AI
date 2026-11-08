"""Reach this laptop after a restart (owner 2026-11-08: one click for every install, not only the owner's checkout).

The Phone tab's button runs setup_boot_access.ps1 (or remove_boot_access.ps1) through one Windows "Yes" prompt;
Chutku itself never runs elevated. A checkout keeps the scripts in scripts/, an installed app in boot_access/.
Chutku cannot read the SYSTEM tasks, so "on" means: the boot notice has written its log and the lock-screen helper
answers on 127.0.0.1:8767.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess

from chutku.core.paths import CODE_ROOT

STATUS = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ChutkuBoot" / "status" / "notify.log"
HELPER_PORT = 8767


def script(name):
    for folder in (CODE_ROOT / "scripts", CODE_ROOT / "boot_access"):
        if (folder / name).is_file():
            return folder / name
    return None


def _helper_answers():
    try:
        with socket.create_connection(("127.0.0.1", HELPER_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def status(*, log=STATUS, answers=_helper_answers):
    try:
        last = [line for line in log.read_text(encoding="utf-8-sig").splitlines() if line.strip()][-1]
    except (OSError, IndexError):
        last = None
    return {"on": last is not None and answers(), "last": last, "available": script("setup_boot_access.ps1") is not None}


def missing_step(base):
    """What must be done first, in plain words; None when the setup can run."""
    from chutku.gateway import telegram
    from chutku.remote.auth import RemoteStore
    if not telegram.token():
        return "First connect your Telegram bot (the Telegram card above): the 'Laptop is ON' message goes there."
    if telegram.paired(base) is None:
        return "First pair your phone with the Telegram bot (the Telegram card above)."
    if not RemoteStore(base).settings().get("host"):
        return "First press 'Connect my phone': the laptop must be signed in to Tailscale."
    return None


def run(base, on, *, launch=subprocess.Popen):
    """Start the elevated setup (on) or removal (off). Windows asks once; a window shows each step."""
    if on and (step := missing_step(base)):
        return {"started": False, "message": step}
    path = script("setup_boot_access.ps1" if on else "remove_boot_access.ps1")
    if path is None:
        return {"started": False, "message": "This copy of Chutku has no boot-access scripts."}
    inner = f"-NoProfile -ExecutionPolicy Bypass -File \"{path}\" -Quiet".replace("'", "''")   # inside '...'
    launch(["powershell.exe", "-NoProfile", "-Command",
            f"Start-Process powershell.exe -Verb RunAs -ArgumentList '{inner}'"],
           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"started": True, "message": "Windows asks once: click Yes. A window shows each step and closes by itself."}
