"""Chutku's presence window (W4, 2026-10-29): the "Chutku Assistant" window in the corner of the screen. Its orb
listens, thinks and speaks with her, and it shows live captions and each step of the current task, and takes
approvals. Since 2026-11-01 it is a normal app window (Windows title bar, its own taskbar button, not on top).

It is the dashboard's own page /presence (same token, same origin, same CSP) shown in a WebView2 window through
pywebview, run as a child process of Chutku's core, so it closes with her. Without pywebview the Tk HUD
(chutku/hud.py) is used as before.

    python -m chutku.presence [dashboard link]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL = (360, 600)
MARGIN = 18
TITLE = "Chutku Assistant"   # unique: the core's hidden tray window is also called "Chutku"


def available():
    try:
        import webview  # noqa: F401  (pywebview)
        return True
    except Exception:
        return False


def presence_url(link):
    """The dashboard link "http://127.0.0.1:8765/#token=..." -> its presence page, keeping the token fragment."""
    origin, _, fragment = str(link).partition("#")
    if not origin.startswith("http://127.0.0.1:") or "token=" not in fragment:
        raise ValueError("Not a local Chutku dashboard link.")
    return origin.rstrip("/") + "/presence#" + fragment


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


def window_exists(title=TITLE):
    import ctypes
    return bool(ctypes.windll.user32.FindWindowW(None, title))


def bring_to_front(title=TITLE):
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def quit_chutku():
    """The owner closed the Chutku window (✕ or the taskbar's Close): every Chutku process ends, cleanly."""
    from chutku.core.action_control import ActionControl
    ActionControl(PROJECT_ROOT).quit()


def show_in_taskbar(title=None):
    title = title or TITLE
    """Give the window its own taskbar button with Chutku's icon (frameless windows can lack one)."""
    import ctypes
    import time
    user32 = ctypes.windll.user32
    for _ in range(50):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
        time.sleep(0.1)
    else:
        return
    GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x40000, 0x80
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.ShowWindow(hwnd, 0)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
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
    x, y = corner(FULL)
    window = webview.create_window(TITLE, presence_url(link), width=FULL[0], height=FULL[1], x=x, y=y,
                                   frameless=False, on_top=False, resizable=True, min_size=(300, 420),
                                   background_color="#070b12")
    window.events.closed += quit_chutku
    webview.start(show_in_taskbar, private_mode=True)


if __name__ == "__main__":
    main()
