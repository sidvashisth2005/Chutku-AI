"""Chutku's presence window (W4, 2026-10-29): a frameless, always-on-top orb in the corner of the screen that
listens, thinks and speaks with her, shows live captions and each step of the current task, and takes approvals.

It is the dashboard's own page /presence (same token, same origin, same CSP) shown in a WebView2 window through
pywebview, run as a child process of Chutku's core, so it closes with her. When idle it shrinks to a small orb;
when anything happens it grows into a panel. Without pywebview the Tk HUD (chutku/hud.py) is used as before.

    python -m chutku.presence [dashboard link]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL = (360, 600)
COMPACT = (112, 112)
MARGIN = 18


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


class Bridge:
    """Called from presence.js (window.pywebview.api): grow into the panel or shrink to the orb."""

    def __init__(self):
        self.window = None
        self.compact = None

    # js_api calls arrive while the page waits; touching the window from that call froze it ("Python is not
    # responding", owner 2026-10-30), so every window change runs on its own thread.
    def _later(self, action):
        import threading
        threading.Thread(target=action, daemon=True).start()

    def size(self, compact):
        compact = bool(compact)
        if self.window is None or compact == self.compact:
            return {"compact": self.compact}
        self.compact = compact
        width, height = COMPACT if compact else FULL
        x, y = corner((width, height))

        def apply():
            self.window.resize(width, height)
            self.window.move(x, y)
        self._later(apply)
        return {"compact": compact}

    def minimize(self):
        if self.window is not None:
            self._later(self.window.minimize)

    def close(self):
        if self.window is not None:
            self._later(self.window.destroy)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    link = argv[0] if argv else json.loads((PROJECT_ROOT / "data" / "dashboard-session.json").read_text(
        encoding="utf-8"))["url"]
    import webview
    bridge = Bridge()
    x, y = corner(FULL)
    bridge.window = webview.create_window("Chutku", presence_url(link), js_api=bridge, width=FULL[0], height=FULL[1],
                                          x=x, y=y, frameless=True, on_top=True, easy_drag=False, resizable=False,
                                          background_color="#070b12")
    bridge.compact = False
    webview.start(private_mode=True)


if __name__ == "__main__":
    main()
