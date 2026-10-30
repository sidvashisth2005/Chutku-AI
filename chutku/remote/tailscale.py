"""The owner's tailnet is the only way in (W6 / HERMES_PLAN P1).

`tailscale serve --bg --https=443 http://127.0.0.1:<port>` publishes the phone server only inside the owner's tailnet
at https://<laptop>.<tailnet>.ts.net with a real certificate: no firewall port, no 0.0.0.0, no router setup.
Funnel (public internet) is forbidden: if it ever points at the phone server, everything stops. Chutku never installs
Tailscale silently; without it, remote stays off with clear steps.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

STEPS = ("Install Tailscale on this laptop (https://tailscale.com/download/windows) and on your phone (Play Store / "
         "App Store), and sign in with the SAME account on both. Then say \"phone connect karo\" again.")


def executable():
    found = shutil.which("tailscale")
    if found:
        return found
    for folder in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        candidate = Path(folder) / "Tailscale" / "tailscale.exe"
        if folder and candidate.is_file():
            return str(candidate)
    return None


def run(args, *, runner=None, timeout=20):
    """(returncode, stdout). runner(args) -> (code, out) lets tests use a fake CLI."""
    if runner is not None:
        return runner(args)
    exe = executable()
    if exe is None:
        return 127, ""
    done = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    return done.returncode, done.stdout


def status(*, runner=None):
    """{"installed", "logged_in", "host" (MagicDNS name), "login" (owner account)}."""
    code, out = run(["status", "--json"], runner=runner)
    if code == 127:
        return {"installed": False, "logged_in": False, "host": None, "login": None, "steps": STEPS}
    try:
        data = json.loads(out or "{}")
    except ValueError:
        data = {}
    me = data.get("Self") or {}
    host = str(me.get("DNSName") or "").rstrip(".") or None
    users = data.get("User") or {}
    owner = users.get(str(me.get("UserID"))) or {}
    login = owner.get("LoginName")
    running = data.get("BackendState") == "Running"
    return {"installed": True, "logged_in": bool(running and host and login), "host": host, "login": login,
            "steps": None if running else "Open Tailscale on this laptop and sign in."}


def serve_on(port, *, runner=None):
    code, _ = run(["serve", "--bg", "--https=443", f"http://127.0.0.1:{int(port)}"], runner=runner)
    return code == 0


def serve_off(*, runner=None):
    code, _ = run(["serve", "--https=443", "off"], runner=runner)
    return code == 0


def funnel_exposes(port, *, runner=None):
    """True when Tailscale Funnel (public internet) points at the phone server (or the answer is unreadable: fail
    closed)."""
    code, out = run(["funnel", "status", "--json"], runner=runner)
    if code == 127:
        return False
    if code != 0:
        return True
    try:
        data = json.loads(out or "{}")
    except ValueError:
        return True
    if not data.get("AllowFunnel"):
        return False
    text = json.dumps(data)
    return any(bool(on) for on in (data.get("AllowFunnel") or {}).values()) and str(int(port)) in text
