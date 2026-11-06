"""Chutku's presence window (W4, 2026-10-29): the "Chutku Assistant" window in the corner of the screen. Its orb
listens, thinks and speaks with her, and it shows live captions and each step of the current task, and takes
approvals. Since 2026-11-01 it is a normal app window (Windows title bar, its own taskbar button, not on top).

It is the dashboard's own page /presence (same token, same origin, same CSP) shown in a WebView2 window through
pywebview, run as a child process of Chutku's core, so it closes with her. Without pywebview the Tk HUD
(chutku/hud.py) is used as before.

Y1 (owner, 2026-11-06: "minimal on screen"): Chutku starts as a small rounded bar at the top centre of the screen
(/presence?view=bar: her eyes, one line of status, an expand button), always on top. Expand shows the full window
and hides the bar; the full window's "to bar" button does the reverse. Both windows exist from the start.

    python -m chutku.presence [dashboard link]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL = (360, 600)
BAR = (420, 52)
MARGIN = 18
TITLE = "Chutku Assistant"   # unique: the core's hidden tray window is also called "Chutku"
BAR_TITLE = "Chutku Bar"


def available():
    try:
        import webview  # noqa: F401  (pywebview)
        return True
    except Exception:
        return False


def presence_url(link, view=""):
    """The dashboard link "http://127.0.0.1:8765/#token=..." -> its presence page, keeping the token fragment.
    view="bar" gives the compact bar layout of the same page."""
    origin, _, fragment = str(link).partition("#")
    if not origin.startswith("http://127.0.0.1:") or "token=" not in fragment:
        raise ValueError("Not a local Chutku dashboard link.")
    return origin.rstrip("/") + "/presence" + ("?view=bar" if view == "bar" else "") + "#" + fragment


def work_area():
    """(left, top, right, bottom) of the primary screen without the taskbar."""
    try:
        import ctypes
        from ctypes import wintypes as w
        rect = w.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)   # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return 0, 0, 1920, 1040


def corner(size):
    left, top, right, bottom = work_area()
    return right - size[0] - MARGIN, bottom - size[1] - MARGIN


def top_centre(size):
    left, top, right, bottom = work_area()
    return left + (right - left - size[0]) // 2, top + 10


class Bridge:
    """presence.js calls these (window.pywebview.api): show the full window or the bar, never both."""

    def __init__(self, bar=None, full=None):
        self.bar, self.full, self.view = bar, full, "bar"
        self.lock = threading.Lock()

    def expand(self):
        return self._switch("full")

    def compact(self):
        return self._switch("bar")

    def _switch(self, view):
        if self.bar is None or self.full is None or view == self.view:
            return {"view": self.view}
        self.view = view

        def apply():   # always the latest view, so two quick clicks cannot leave both windows shown
            with self.lock:
                shown, hidden = (self.full, self.bar) if self.view == "full" else (self.bar, self.full)
                shown.show()
                hidden.hide()
        # js_api calls arrive while the page waits; touching a window from that call froze it ("Python is not
        # responding", owner 2026-10-30), so the change runs on its own thread.
        threading.Thread(target=apply, daemon=True).start()
        return {"view": view}


def window_exists(title=TITLE):
    import ctypes
    return bool(ctypes.windll.user32.FindWindowW(None, title))


def bring_to_front(title=TITLE):
    """The tray's "Show Chutku window": the bar when it is the one showing, else the full window."""
    import ctypes
    user32 = ctypes.windll.user32
    bar = user32.FindWindowW(None, BAR_TITLE)
    hwnd = bar if bar and user32.IsWindowVisible(bar) else user32.FindWindowW(None, title)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def quit_chutku():
    """The owner closed the Chutku window (✕ or the taskbar's Close): every Chutku process ends, cleanly."""
    from chutku.core.action_control import ActionControl
    ActionControl(PROJECT_ROOT).quit()


def _wait_for(title):
    import ctypes
    import time
    for _ in range(50):
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.1)
    return 0


def round_corners(title=BAR_TITLE):
    """Windows 11 rounded corners on the frameless bar (DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND).
    Windows 10 ignores it: the bar is then square."""
    import ctypes
    hwnd = _wait_for(title)
    if hwnd:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)


def show_in_taskbar(title=None):
    title = title or TITLE
    """Give the window its own taskbar button with Chutku's icon (frameless windows can lack one)."""
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = _wait_for(title)
    if not hwnd:
        return
    GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x40000, 0x80
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    visible = user32.IsWindowVisible(hwnd)   # the full window starts hidden behind the bar (Y1): keep it so
    user32.ShowWindow(hwnd, 0)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
    if visible:
        user32.ShowWindow(hwnd, 5)
    icon_path = str(Path(__file__).resolve().parent / "web" / "chutku.ico")
    for size, kind in ((16, 0), (32, 1)):   # ICON_SMALL, ICON_BIG
        icon = user32.LoadImageW(None, icon_path, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        if icon:
            user32.SendMessageW(hwnd, 0x80, kind, icon)                   # WM_SETICON


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    link = argv[0] if argv else json.loads((PROJECT_ROOT / "data" / "dashboard-session.json").read_text(
        encoding="utf-8"))["url"]
    import webview
    try:   # its own taskbar group and icon, not "Python"
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Chutku.Assistant")
    except Exception:
        pass
    bridge = Bridge()
    x, y = corner(FULL)
    bridge.full = webview.create_window(TITLE, presence_url(link), js_api=bridge, width=FULL[0], height=FULL[1],
                                        x=x, y=y, frameless=False, on_top=False, resizable=True, min_size=(300, 420),
                                        background_color="#070b12", hidden=True)
    x, y = top_centre(BAR)
    bridge.bar = webview.create_window(BAR_TITLE, presence_url(link, "bar"), js_api=bridge, width=BAR[0],
                                       height=BAR[1], x=x, y=y, frameless=True, easy_drag=True, on_top=True,
                                       resizable=False, min_size=BAR, background_color="#0b1220")
    for window in (bridge.full, bridge.bar):   # closing either one quits Chutku, as the window did before
        window.events.closed += quit_chutku

    def ready():
        show_in_taskbar(TITLE)
        show_in_taskbar(BAR_TITLE)
        round_corners(BAR_TITLE)
    webview.start(ready, private_mode=True)


if __name__ == "__main__":
    main()
