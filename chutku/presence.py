"""Chutku's presence window (W4, 2026-10-29): the "Chutku Assistant" window in the corner of the screen. Its orb
listens, thinks and speaks with her, and it shows live captions and each step of the current task, and takes
approvals. Since 2026-11-01 it is a normal app window (Windows title bar, its own taskbar button, not on top).

It is the dashboard's own page /presence (same token, same origin, same CSP) shown in a WebView2 window through
pywebview, run as a child process of Chutku's core, so it closes with her. Without pywebview the Tk HUD
(chutku/hud.py) is used as before.

Y1 (owner, 2026-11-06: "minimal on screen"): a small rounded bar (/presence?view=bar: her eyes, the live line of
what the owner and Chutku say, an expand button), always on top, draggable, remembered where it was left.
It is hidden until wanted (owner, same day: "not always there"): Ctrl+Alt+C shows it and hides it again; while she
listens or works (Ctrl+Alt+Space) it appears by itself and goes away a few seconds after she is done, unless the
owner pinned it with Ctrl+Alt+C. Expand shows the full window; its "to bar" button goes back. A pending approval
always opens the full window.

    python -m chutku.presence [dashboard link]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL = (360, 600)
BAR = (300, 40)
TOGGLE_KEY = ("Ctrl+Alt+C", 0x0002 | 0x0001 | 0x4000, ord("C"))   # MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
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
        self.bar, self.full, self.view = bar, full, "none"   # "none": nothing on screen until wanted
        self.pinned = False            # shown with Ctrl+Alt+C: stays until Ctrl+Alt+C again
        self.lock = threading.Lock()

    def expand(self):
        return self._switch("full")

    def compact(self):
        return self._switch("bar")

    def toggle(self):
        """Ctrl+Alt+C: show the bar (pinned), or hide whatever Chutku window is showing."""
        if self.view == "none":
            self.pinned = True
            return self._switch("bar")
        self.pinned = False
        return self._switch("none")

    def peek(self):
        """She started listening or working: show the bar if nothing is showing (not pinned)."""
        return self._switch("bar") if self.view == "none" else {"view": self.view}

    def unpeek(self):
        """She is done: an unpinned bar goes away again. The full window and a pinned bar stay."""
        return self._switch("none") if self.view == "bar" and not self.pinned else {"view": self.view}

    def _switch(self, view):
        if self.bar is None or self.full is None or view == self.view:
            return {"view": self.view}
        self.view = view

        def apply():   # always the latest view, so two quick clicks cannot leave both windows shown
            with self.lock:
                try:
                    for window, name in ((self.bar, "bar"), (self.full, "full")):
                        if name == self.view:
                            window.show()
                    for window, name in ((self.bar, "bar"), (self.full, "full")):
                        if name != self.view:
                            window.hide()
                    _log(f"view -> {self.view}")
                except Exception as error:   # a window call failing on this thread would otherwise vanish silently
                    _log(f"view -> {self.view} failed: {error!r}")
        # js_api calls arrive while the page waits, so the change runs on its own thread (2026-10-30); the windows
        # themselves are NativeWindow handles, never pywebview objects (2026-11-06 deadlock).
        threading.Thread(target=apply, daemon=True).start()
        return {"view": view}


class NativeWindow:
    """Show or hide a window through Windows itself (ShowWindowAsync on its handle). pywebview's show()/hide() from
    another thread go through a .NET cross-thread call that deadlocked both windows live (2026-11-06: the bar and
    the full window were "not responding" after the first Ctrl+Alt+C); ShowWindowAsync only posts and returns."""

    def __init__(self, title, *, activate=False):
        self.title, self.activate = title, activate

    def _hwnd(self):
        import ctypes
        return ctypes.windll.user32.FindWindowW(None, self.title)

    def show(self):
        import ctypes
        hwnd = self._hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindowAsync(hwnd, 5 if self.activate else 4)   # SW_SHOW / SW_SHOWNOACTIVATE
            if self.activate:
                ctypes.windll.user32.SetForegroundWindow(hwnd)

    def hide(self):
        import ctypes
        hwnd = self._hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindowAsync(hwnd, 0)   # SW_HIDE


def _log(line):
    try:
        import time
        with (PROJECT_ROOT / "data" / "logs" / "presence.log").open("a", encoding="utf-8") as stream:
            stream.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def listen_for_toggle(bridge):
    """Ctrl+Alt+C toggles the bar from anywhere. Registered by this window process itself, so the switch is
    instant; if another program owns the combination, the bar still appears while she works (peek)."""
    import ctypes
    from ctypes import wintypes as w
    user32 = ctypes.WinDLL("user32", use_last_error=True)   # its own handle and types, as voice/handsfree.py does
    user32.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
    user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    if not user32.RegisterHotKey(None, 1, TOGGLE_KEY[1], TOGGLE_KEY[2]):
        _log(f"{TOGGLE_KEY[0]} is taken by another program (error {ctypes.get_last_error()})")
        return False
    _log(f"{TOGGLE_KEY[0]} toggles the bar")
    message = w.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        if message.message == 0x0312:   # WM_HOTKEY
            _log("hotkey: " + str(bridge.toggle()))
    return True


BUSY = frozenset({"listening", "thinking", "running", "speaking", "confirm", "clarify"})
QUIET_SECONDS = 6.0


class StateWatcher:
    """Shows the bar while she listens or works, hides it again QUIET_SECONDS after, and opens the full window for
    each new approval. In Python, not in the page: a hidden WebView2 window pauses its timers (2026-11-06: the
    hidden bar never noticed she was working)."""

    def __init__(self, bridge, link, fetch=None):
        origin, _, fragment = str(link).partition("#")
        self.bridge, self.url = bridge, origin.rstrip("/") + "/api/presence"
        self.origin, self.token = origin.rstrip("/"), fragment.partition("token=")[2]
        self.fetch = fetch or self._fetch
        self.quiet_since, self.expanded_for, self.video_for = None, "", ""

    def _fetch(self):
        import urllib.request
        request = urllib.request.Request(self.url, headers={"X-Chutku-Token": self.token, "Origin": self.origin})
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read())

    def step(self, now):
        state = self.fetch()
        pending = state.get("pending")
        key = f"{state.get('session_id')}|{(pending or {}).get('consequence') or (pending or {}).get('tool')}"             if pending else ""
        if key and key != self.expanded_for:   # an approval never waits unseen
            self.expanded_for = key
            self.bridge.expand()
        video = (state.get("video") or {}).get("id", "")
        if video and video != self.video_for:   # X13: a video asked for here plays in the full window
            self.video_for = video
            self.bridge.expand()
        if state.get("phase") in BUSY or pending:
            self.quiet_since = None
            self.bridge.peek()
        elif self.quiet_since is None:
            self.quiet_since = now
        elif now - self.quiet_since >= QUIET_SECONDS:
            self.bridge.unpeek()

    def run(self):
        import time
        while True:
            try:
                self.step(time.monotonic())
                time.sleep(0.3)
            except Exception:   # Chutku restarting: try again shortly
                time.sleep(2)


def _place_file():
    return PROJECT_ROOT / "data" / "presence.json"


def bar_place():
    """Where the owner last dragged the bar, if that spot is still on the screen; else the top centre."""
    try:
        x, y = json.loads(_place_file().read_text(encoding="utf-8"))["bar"]
        left, top, right, bottom = work_area()
        if left - BAR[0] // 2 <= x <= right - BAR[0] // 2 and top <= y <= bottom - BAR[1]:
            return int(x), int(y)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return top_centre(BAR)


def remember_place(x, y):
    try:
        _place_file().write_text(json.dumps({"bar": [int(x), int(y)]}), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass


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
    bridge = Bridge(NativeWindow(BAR_TITLE), NativeWindow(TITLE, activate=True))
    x, y = corner(FULL)
    full = webview.create_window(TITLE, presence_url(link), js_api=bridge, width=FULL[0], height=FULL[1],
                                        x=x, y=y, frameless=False, on_top=False, resizable=True, min_size=(300, 420),
                                        background_color="#070b12", hidden=True)
    x, y = bar_place()
    bar = webview.create_window(BAR_TITLE, presence_url(link, "bar"), js_api=bridge, width=BAR[0],
                                       height=BAR[1], x=x, y=y, frameless=True, easy_drag=True, on_top=True,
                                       resizable=False, min_size=BAR, background_color="#0b1220", hidden=True)
    try:   # remember where the owner drags it
        bar.events.moved += remember_place
    except AttributeError:
        pass
    for window in (full, bar):   # closing either one quits Chutku, as the window did before
        window.events.closed += quit_chutku

    def ready():
        show_in_taskbar(TITLE)
        show_in_taskbar(BAR_TITLE)
        round_corners(BAR_TITLE)
        threading.Thread(target=listen_for_toggle, args=(bridge,), daemon=True, name="bar-hotkey").start()
        threading.Thread(target=StateWatcher(bridge, link).run, daemon=True, name="bar-watch").start()
    webview.start(ready, private_mode=True)


if __name__ == "__main__":
    main()
