"""Background Desk (App Mastery 2, owner 2026-11-10): Chutku works in apps BEHIND the owner's window while he keeps
working ("it must not hijack my screen, mouse or keyboard").

Measured on the owner's PC (scripts/background_probe.py, started outside VS Code like Chutku itself):
- agent-desktop's UI Automation actions inject no mouse or key event at all (a low-level hook counted 0), and work
  on a window that sits behind the owner's (not on a minimized one).
- Opening an app can take the foreground for a moment (Notepad, Calculator, Settings, Explorer, Paint: once each);
  handing it back without any key press took 17-165 ms. Later work in an already-open window took it 0 times for
  Notepad, Explorer and Settings.

So: wait for a pause in his typing, open the app minimized without activating it, un-minimize it BEHIND his window,
guard every step (any focus change is handed straight back with an unassigned key code that types nothing, never Alt), and keep the window there
for the next task (a warm pool).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import threading
import time

TYPING_PAUSE = 0.7    # seconds without the owner's keys/clicks before a step that may flash a window
PAUSE_LIMIT = 8.0     # never wait longer than this for a pause
RESTART_AFTER = 4.0   # a launch with no window yet is asked once more (normal launches show one in 1.3-2.2 s)
OPENED = {}           # hwnd -> {"app", "at"}: windows Chutku opened behind the owner's (the warm pool)
_lock = threading.Lock()


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def idle_seconds():
    class Last(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    last = Last()
    last.cbSize = ctypes.sizeof(Last)
    _user32().GetLastInputInfo(ctypes.byref(last))
    return (ctypes.windll.kernel32.GetTickCount() - last.dwTime) / 1000


def typing_pause(seconds=TYPING_PAUSE, limit=PAUSE_LIMIT, idle=idle_seconds, sleep=time.sleep):
    """Wait until the owner has not typed or clicked for `seconds` (at most `limit`). True when a pause came."""
    waited = 0.0
    while waited < limit:
        if idle() >= seconds:
            return True
        sleep(0.1)
        waited += 0.1
    return False


class FocusGuard:
    """While a background step runs, watch the foreground every 20 ms. Only when a window of the app CHUTKU is
    working in takes it, hand it straight back to the owner's window (never with a key his app would act on).
    His own switches are his: the first version pulled him back from Brave 9 times in 5 s (live 2026-11-10).
    `steals` lists (ms to give back, given back?)."""

    def __init__(self, foreground=None, give_back=None, interval=0.02, ours=None):
        self._foreground = foreground or (lambda: int(_user32().GetForegroundWindow() or 0))
        self._give_back = give_back or _give_back
        self._ours = ours or _chutkus_window
        self.interval = interval
        self.owner = 0
        self.steals = []
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self.owner = self._foreground()
        self._thread = threading.Thread(target=self._watch, name="chutku-focus-guard", daemon=True)
        self._thread.start()
        return self

    def _watch(self):
        while not self._stop.is_set():
            now = self._foreground()
            if self.owner and now and now != self.owner:
                if self._ours(now):
                    started = time.monotonic()
                    back = self._give_back(self.owner)
                    self.steals.append((round((time.monotonic() - started) * 1000), back))
                else:
                    self.owner = now      # the owner moved on: from now on his new window is the one to keep
            self._stop.wait(self.interval)

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join(1)
        now = self._foreground()
        if self.owner and now != self.owner and self._ours(now):   # one last check after the step
            self.steals.append((0, self._give_back(self.owner)))


_JUMPERS = {"applicationframehost.exe", "calculatorapp.exe", "notepad.exe", "explorer.exe", "mspaint.exe",
            "systemsettings.exe", "winword.exe", "excel.exe", "powerpnt.exe"}


def _chutkus_window(hwnd):
    """A window Chutku opened behind the owner, or one of an app the background lane drives (Store-app frames,
    Notepad, Explorer, Office...) that came forward with NO input from the owner in the last 0.3 s. A window he
    clicked or switched to himself is never taken from him."""
    if hwnd in OPENED:
        return True
    if idle_seconds() < 0.3:
        return False
    pid = w.DWORD()
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return False
    try:
        text = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(len(text))
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size))
        return bool(ok) and Path(text.value).name.casefold() in _JUMPERS
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _give_back(hwnd):
    from chutku.tools.windows_apps import WindowsDesktop
    try:
        WindowsDesktop().focus(hwnd, nudge="quiet")   # an unassigned key code: never Alt, never a typed key
    except OSError:
        return False
    return int(_user32().GetForegroundWindow() or 0) == hwnd


def park(hwnd):
    """Un-minimize without activating, then put the window at the bottom of the stack: behind every other window,
    still drivable (agent-desktop: a minimized window is not)."""
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
    return bool(user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10))   # HWND_BOTTOM, NOSIZE|NOMOVE|NOACTIVATE


def launch(app_id, windows, *, wait=20.0, popen=subprocess.Popen, pause=typing_pause, guard=FocusGuard,
           park_window=park, sleep=time.sleep, ours=None):
    """Open a Start-menu app (its AppID) behind the owner's window. `windows()` lists {"window_id", ...} of the
    visible windows; `ours(item)` says a new window belongs to this app (parallel lanes: another task's app may
    open a window in the same seconds, and it must not be taken for this one). Returns (the new window or None,
    the guard's steals)."""
    pause()
    before = {item["window_id"] for item in windows()}
    info = subprocess.STARTUPINFO() if os.name == "nt" else None
    if info is not None:
        info.dwFlags, info.wShowWindow = subprocess.STARTF_USESHOWWINDOW, 7   # SW_SHOWMINNOACTIVE
    explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"

    def start():
        popen([str(explorer), "shell:AppsFolder\\" + app_id], startupinfo=info,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with guard() as watching:
        start()
        new, started = None, time.monotonic()
        again = True
        while new is None and time.monotonic() < started + wait:
            sleep(0.25)
            new = next((item for item in windows() if item["window_id"] not in before and item.get("title")
                        and (ours is None or ours(item))), None)
            if new is None and again and time.monotonic() > started + min(wait / 2, RESTART_AFTER):
                # A Store app left suspended after its window closed (Settings, Calculator: live 2026-11-10) can
                # ignore the first start: ask once more.
                again = False
                start()
        if new is not None:
            park_window(new["window_id"])
            with _lock:
                OPENED[new["window_id"]] = {"app": app_id, "at": time.time()}
    return new, watching.steals


def guarded(action, *, pause=typing_pause, guard=FocusGuard):
    """Run one background step (a UI Automation call) after a typing pause, with the focus guard. Returns
    (result, steals)."""
    pause()
    with guard() as watching:
        result = action()
    return result, watching.steals


def opened():
    with _lock:
        return dict(OPENED)
