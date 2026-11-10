"""Background Desk gate (App Mastery 2, step 1): can Chutku work in apps BEHIND the owner's window without touching
his screen, mouse or keyboard?

    python scripts/background_probe.py [--apps notepad,calculator,settings,explorer,paint,word]

Per app: note the owner's foreground window and cursor; launch the app without activating it; watch every 50 ms
whether the foreground was taken (and give it back at once); push the new window to the bottom of the window stack;
read its UI tree; do one harmless semantic action through agent-desktop (headless: no mouse, no keys); screenshot the
covered window; close only that window. Prints one JSON row per app and a summary. agent-desktop's own Windows notes:
"A window behind another window is drivable. A minimized one is not."
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.tools.desktop import call  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
HWND_BOTTOM, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 1, 0x1, 0x2, 0x10
WM_CLOSE = 0x0010

# app -> (how to start it, agent-desktop app_name prefix, one harmless semantic action: (role, name, verb))
APPS = {
    "notepad": (["notepad.exe"], "notepad", ("menuitem", "File", "expand")),
    "calculator": (["explorer.exe", "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"],
                   "calculatorapp", ("button", "Seven", "click")),
    "settings": (["explorer.exe", "ms-settings:about"], "settings", ("listitem", "Bluetooth & devices", "click")),
    "explorer": (["explorer.exe", r"D:\ChutkuPractice"], "explorer", ("treeitem", "This PC", "click")),
    "paint": (["mspaint.exe"], "mspaint", ("menuitem", "File", "expand")),
    "word": (["cmd.exe", "/c", "start", "", "winword.exe", "/q"], "winword", ("button", "Blank document", "click")),
}


class InjectedInput:
    """Counts mouse and key events that a PROGRAM injected (Windows marks them LLMHF_INJECTED / LLKHF_INJECTED), so
    the owner's own typing and mouse moves are not counted: the exact proof that nothing hijacked his input."""

    def __init__(self):
        self.mouse = self.keys = 0
        self.vks = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._ready = threading.Event()

    def _run(self):
        HOOK = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, w.WPARAM, w.LPARAM)

        class MS(ctypes.Structure):
            _fields_ = [("pt", w.POINT), ("data", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]

        class KB(ctypes.Structure):
            _fields_ = [("vk", w.DWORD), ("scan", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]
        user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        def on_mouse(code, wparam, lparam):
            if code >= 0 and ctypes.cast(lparam, ctypes.POINTER(MS)).contents.flags & 0x1:
                self.mouse += 1
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def on_key(code, wparam, lparam):
            if code >= 0 and ctypes.cast(lparam, ctypes.POINTER(KB)).contents.flags & 0x10:
                self.keys += 1
                self.vks.append(ctypes.cast(lparam, ctypes.POINTER(KB)).contents.vk)
            return user32.CallNextHookEx(None, code, wparam, lparam)
        self._callbacks = (HOOK(on_mouse), HOOK(on_key))
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOK, w.HINSTANCE, w.DWORD]
        user32.SetWindowsHookExW.restype = w.HHOOK
        self._hooks = [user32.SetWindowsHookExW(14, self._callbacks[0], None, 0),
                       user32.SetWindowsHookExW(13, self._callbacks[1], None, 0)]
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._ready.set()
        message = w.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            pass
        for hook in self._hooks:
            user32.UnhookWindowsHookEx(hook)

    def __enter__(self):
        self._thread.start()
        self._ready.wait(2)
        return self

    def __exit__(self, *_):
        user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT
        self._thread.join(2)


def typing_pause(seconds=1.5, limit=10.0):
    """Wait (at most `limit`) until the owner has not typed or clicked for `seconds`: a launch that grabs focus for
    a moment then cannot catch a keystroke."""
    class L(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    end = time.monotonic() + limit
    while time.monotonic() < end:
        last = L(); last.cbSize = 8
        user32.GetLastInputInfo(ctypes.byref(last))
        if (ctypes.windll.kernel32.GetTickCount() - last.dwTime) / 1000 >= seconds:
            return True
        time.sleep(0.1)
    return False


def cursor():
    point = w.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def foreground():
    return user32.GetForegroundWindow()


def windows():
    return {item["id"]: item for item in call("list-windows")}


def bottom(hwnd):
    return bool(user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def give_back(hwnd):
    from chutku.tools.windows_apps import WindowsDesktop
    try:
        WindowsDesktop().focus(hwnd, nudge=False)   # never an injected Alt while the owner may be typing
    except OSError:
        pass
    return foreground() == hwnd


def find_ref(tree, role, name):
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if str(node.get("role", "")).lower() == role and str(node.get("name", "")).strip().lower() == name.lower() \
                    and node.get("ref_id"):
                return node["ref_id"]
            stack.extend(node.get("children") or [])
    return None


def count(tree):
    stack, n = [tree], 0
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            n += 1
            stack.extend(node.get("children") or [])
    return n


def probe(app):
    start, prefix, (role, name, verb) = APPS[app]
    row = {"app": app}
    owner, mouse = foreground(), cursor()
    before = windows()
    stolen = []

    stolen_ms = []

    def watch(stop):
        while not stop.is_set():
            now = foreground()
            if now and now != owner:
                stolen.append(now)
                t = time.monotonic()
                back = give_back(owner)
                stolen_ms.append((round((time.monotonic() - t) * 1000), back))
            time.sleep(0.02)
    stop = threading.Event()
    watcher = threading.Thread(target=watch, args=(stop,), daemon=True)
    watcher.start()
    started = time.monotonic()
    row["waited_for_pause"] = not typing_pause()
    info = subprocess.STARTUPINFO()
    info.dwFlags, info.wShowWindow = subprocess.STARTF_USESHOWWINDOW, 7   # SW_SHOWMINNOACTIVE
    subprocess.Popen(start, startupinfo=info, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    new = None
    while time.monotonic() - started < 25 and new is None:
        time.sleep(0.3)
        for wid, item in windows().items():
            names = (str(item.get("app_name", "")).lower(), str(item.get("title", "")).lower())
            if wid not in before and item.get("title") and (names[0].startswith(prefix) or names[1] == prefix):
                new = item
    if new is None:
        stop.set()
        return row | {"error": "no new window in 25 s", "stolen_focus": len(set(stolen))}
    hwnd = int(new["id"].split("-")[1])
    user32.ShowWindow(hwnd, 4)     # SW_SHOWNOACTIVATE: un-minimize without taking focus (minimized is not drivable)
    row["layered_bottom"] = bottom(hwnd)
    row["launch_s"] = round(time.monotonic() - started, 1)
    time.sleep(2.0 if app in {"word", "settings"} else 1.0)   # WPF/UWP: read after the automation peer exists
    try:
        data = call("snapshot", "--window-id", new["id"], "--compact", "--timeout-ms", "8000")
        tree = data.get("tree") or {}
        row["uia_nodes"] = count(tree)
        ref = find_ref(tree, role, name)
        if ref is None:
            found = call("find", "--window-id", new["id"], "--text", name, "--limit", "5")
            ref = next((m.get("ref_id") for m in found.get("matches", []) if m.get("ref_id")), None)
        row["act_target"] = bool(ref)
        if ref:
            t = time.monotonic()
            result = call(verb, ref)
            row["act"] = result.get("outcome") or result.get("status") or "done"
            row["act_s"] = round(time.monotonic() - t, 2)
    except OSError as error:
        row["uia_error"] = str(error)[:160]
    # Warm pool: a later task reuses this window behind the owner's: no launch at all
    launch_steals = len(set(stolen))
    stolen.clear()
    try:
        time.sleep(0.5)
        t = time.monotonic()
        again = call("snapshot", "--window-id", new["id"], "--compact", "--timeout-ms", "8000")
        ref = find_ref(again.get("tree") or {}, role, name)
        if ref:
            call(verb, ref)
        row["reuse_s"] = round(time.monotonic() - t, 2)
    except OSError as error:
        row["reuse_error"] = str(error)[:120]
    row["reuse_stolen"] = len(set(stolen))
    try:
        shot = Path(tempfile.gettempdir()) / f"chutku-probe-{app}.png"
        call("screenshot", "--window-id", new["id"], str(shot))
        row["screenshot_kb"] = round(shot.stat().st_size / 1024)
        shot.unlink(missing_ok=True)
    except OSError as error:
        row["screenshot_error"] = str(error)[:120]
    stop.set()
    watcher.join(1)
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(1.0)
    row["stolen_focus"] = launch_steals
    row["given_back_ms"] = stolen_ms[:4]
    row["owner_still_in_front"] = foreground() == owner
    row["mouse_unmoved"] = cursor() == mouse
    return row


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--apps", default="notepad,calculator,settings,explorer,paint")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for app in [a.strip() for a in args.apps.split(",") if a.strip()]:
        with InjectedInput() as injected:
            row = probe(app)
        row["injected_mouse"], row["injected_keys"] = injected.mouse, injected.keys
        row.pop("mouse_unmoved", None)   # the owner's own hand moves it; injected events are the real test
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    ok = [r for r in rows if r.get("act") and r.get("reuse_stolen") == 0 and not r["injected_mouse"]
          and not r["injected_keys"]]
    print(json.dumps({"background_ok": [r["app"] for r in ok],
                      "screen_lane": [r["app"] for r in rows if r not in ok]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
