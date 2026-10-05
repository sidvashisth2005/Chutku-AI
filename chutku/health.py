"""PC health watch: battery, disk space and memory pressure, with rate-limited Windows toasts.

Read-only checks (no PowerShell, a few milliseconds). Alerts are remembered in
data/health-alerts.json so the same problem is not repeated: disk at most every 12 hours,
memory hourly, battery once per threshold crossed (20% then 10%) per discharge.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import subprocess
import time

DISK_LOW_PERCENT = 5.0
MEMORY_HIGH_PERCENT = 90
COOLDOWN = {"disk": 12 * 3600, "memory": 3600}


class _Power(ctypes.Structure):
    _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                ("saver", ctypes.c_ubyte), ("life", w.DWORD), ("full", w.DWORD)]


class _Memory(ctypes.Structure):
    _fields_ = [("length", w.DWORD), ("load", w.DWORD), ("total", ctypes.c_ulonglong),
                ("available", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                ("page_available", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                ("virtual_available", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]


def battery():
    status = _Power()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)) or status.flag == 128 \
            or status.percent == 255:
        return None  # no battery (desktop) or unknown
    return {"percent": int(status.percent), "charging": status.ac == 1}


def memory():
    status = _Memory()
    status.length = ctypes.sizeof(_Memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return {"used_percent": int(status.load), "free_gb": round(status.available / 1024 ** 3, 1)}


def readings():
    from chutku.tools.files_plus import disk_report
    return {"battery": battery(), "memory": memory(), "disk": disk_report()["drives"]}


def problems(data):
    """Current problems as (key, title, message, band) — band distinguishes battery thresholds."""
    found = []
    power = data.get("battery")
    if power and not power["charging"] and power["percent"] <= 20:
        band = 10 if power["percent"] <= 10 else 20
        found.append(("battery", "Battery low", f"Battery is at {power['percent']}%. Plug in the charger.", band))
    for drive in data.get("disk") or []:
        if drive["free_percent"] < DISK_LOW_PERCENT:
            found.append((f"disk:{drive['drive']}", f"{drive['drive'][0]}: drive almost full",
                          f"Only {drive['free_gb']} GB ({drive['free_percent']}%) left on {drive['drive'][0]}:. "
                          "Ask Chutku for the biggest files there, or empty the Recycle Bin.", None))
    mem = data.get("memory")
    if mem and mem["used_percent"] >= MEMORY_HIGH_PERCENT:
        found.append(("memory", "Memory nearly full", f"RAM is {mem['used_percent']}% used. Close apps you aren't "
                      "using, or ask Chutku what is using the most memory.", None))
    return found


def due(found, state, now=None):
    """Which problems should notify now, given what was already sent. Returns (alerts, new_state)."""
    now = time.time() if now is None else now
    state = dict(state)
    alerts = []
    if not any(key == "battery" for key, *_ in found):
        state.pop("battery", None)  # charging again or above 20%: re-arm the battery thresholds
    for key, title, message, band in found:
        last = state.get(key)
        if key == "battery":
            if last is not None and last <= band:
                continue
            state[key] = band
        else:
            cooldown = COOLDOWN["memory" if key == "memory" else "disk"]
            if last is not None and now - last < cooldown:
                continue
            state[key] = now
        alerts.append({"key": key, "title": title, "message": message})
    return alerts, state


_TOAST = r'''
$ErrorActionPreference = 'Stop'
$m = [Console]::In.ReadToEnd() | ConvertFrom-Json
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text/><text/></binding></visual></toast>')
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode([string]$m.title)) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode([string]$m.message)) | Out-Null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
'''


def notify(title, message):
    """Show a Windows toast. The text travels on stdin as JSON, never inside the script."""
    encoded = base64.b64encode(_TOAST.encode("utf-16-le")).decode("ascii")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          input=json.dumps({"title": "Chutku · " + title, "message": message}), text=True,
                          encoding="utf-8", errors="replace", capture_output=True, timeout=30,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    if done.returncode != 0:
        raise OSError("Windows did not show the notification.")


def check(base, *, send=notify):
    """One watch cycle: read, decide, notify, remember. Returns the alerts sent."""
    path = Path(base) / "data" / "health-alerts.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    alerts, state = due(problems(readings()), state)
    for alert in alerts:
        try:
            send(alert["title"], alert["message"])
        except (OSError, subprocess.SubprocessError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return alerts


def watch(base, stop_event, interval=300):
    """Background loop for the dashboard process; never raises."""
    delay = min(30, interval)  # first look shortly after start, then every interval
    while not stop_event.wait(delay):
        try:
            check(base)
        except Exception:
            pass
        delay = interval


def _health_tool(arguments, context):
    from chutku.tools.registry import ToolResult, Verification
    return ToolResult(readings(), Verification.PASS)


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This takes no arguments.")


def register_health_tools(registry):
    from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool
    registry.register(Tool("system.health", "Battery level and charging, RAM use and free disk space right now "
        "(fast, no admin rights needed).", Risk.OBSERVATION, _health_tool, _no_arguments,
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable", success_predicate="health_read"))
