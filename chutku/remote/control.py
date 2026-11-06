"""Direct control from the phone (W6 / HERMES_PLAN P5-P7). The owner's own finger drives the mouse and keyboard, as in
any remote desktop, so the kernel cannot judge each input; these rules protect against a stolen or unlocked phone,
someone else on the tailnet, a forgotten session and typing into dangerous places:

1. Armed only at the laptop (dashboard or tray); never from the phone. Off by default.
2. A control session needs the PIN, lasts at most 30 minutes, and ends after 10 idle minutes.
3. Visible on the laptop: a red border round the screen plus the presence badge while a session is live.
4. The laptop always wins: real local mouse or keyboard input pauses remote input for 10 s; Ctrl+Alt+Shift+P ends
   the session and disarms control.
5. A command window (terminal, PowerShell, Run box...), Windows Security, the registry editor and similar need the
   PIN again for every Enter or paste.
6. Never: input to the secure desktop (UAC, lock screen), Ctrl+Alt+Del, or typing while the laptop is locked.
7. Every input is logged (origin phone_control); typed text only as its length and script.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import threading
import time

SESSION_MAX = 30 * 60
IDLE_MAX = 10 * 60
LOCAL_WINS_SECONDS = 10.0
DANGEROUS_APPS = frozenset({"cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "windowsterminal.exe",
                            "wt.exe", "conhost.exe", "openconsole.exe", "regedit.exe", "mmc.exe", "gpedit.msc",
                            "diskmgmt.msc", "securityhealthsystray.exe", "secHealthUI.exe".casefold(),
                            "taskmgr.exe", "bash.exe", "wsl.exe"})
DANGEROUS_TITLES = ("run", "windows security", "registry editor", "group policy", "disk management")
# Phone shortcut bar -> virtual keys. Ctrl+Alt+Del is deliberately absent (and refused by name).
VK = {"esc": 0x1B, "tab": 0x09, "enter": 0x0D, "backspace": 0x08, "delete": 0x2E, "left": 0x25, "up": 0x26,
      "right": 0x27, "down": 0x28, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "f5": 0x74,
      "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "space": 0x20,
      **{chr(c): ord(chr(c).upper()) for c in range(ord("a"), ord("z") + 1)},
      **{str(d): 0x30 + d for d in range(10)}}
COMBOS = {"ctrl+c", "ctrl+v", "ctrl+z", "ctrl+s", "ctrl+a", "ctrl+w", "ctrl+t", "alt+tab", "win+d", "win+e", "alt+f4",
          "ctrl+shift+t", "ctrl+f", "f5"}
REFUSED_COMBOS = {"ctrl+alt+delete", "ctrl+alt+del", "win+l"}


class ControlRefused(PermissionError):
    pass


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]


def last_input_tick():
    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return info.dwTime


def tick_now():
    return ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF


def session_locked():
    """True while Windows shows the lock screen / secure desktop (no input is possible then)."""
    try:
        desk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)   # DESKTOP_SWITCHDESKTOP
        if not desk:
            return True
        ctypes.windll.user32.CloseDesktop(desk)
        return False
    except OSError:
        return True


def foreground():
    from chutku.tools.everyday import Desktop
    desktop = Desktop()
    hwnd = desktop.foreground()
    info = desktop.describe(hwnd) if hwnd else {}
    import os
    return {"executable": os.path.basename(info.get("executable") or "").casefold(),
            "title": str(info.get("title") or "")[:120]}


def dangerous(window):
    exe, title = window.get("executable", ""), window.get("title", "").casefold()
    return exe in DANGEROUS_APPS or any(title == t or title.startswith(t + " ") for t in DANGEROUS_TITLES)


def script_of(text):
    if any("ऀ" <= ch <= "ॿ" for ch in text):
        return "Devanagari"
    return "Latin" if any(ch.isalpha() for ch in text) else "symbols"


class ControlSession:
    """One live phone control session. Injectors are patchable for tests (no real input)."""

    def __init__(self, base, *, clock=time.monotonic, inject=None, log=None, locked=None, window=None,
                 local_tick=None, now_tick=None, cursor=None):
        import sys
        module = sys.modules[__name__]    # looked up now, so tests can patch the module's functions
        self.base, self.clock = base, clock
        self.cursor = cursor or module.cursor_pos
        self.started = self.last_used = clock()
        self.inject = inject or module.Injector()
        self.log = log or _action_log(base)
        self.locked, self.window = locked or module.session_locked, window or module.foreground
        self.local_tick, self.now_tick = local_tick or module.last_input_tick, now_tick or module.tick_now
        self.our_ticks = []               # GetTickCount values when WE injected (local input = any other)
        self.paused_until = 0.0
        self.ended = threading.Event()

    def alive(self):
        now = self.clock()
        return not self.ended.is_set() and now - self.started < SESSION_MAX and now - self.last_used < IDLE_MAX

    def end(self, reason="ended"):
        if not self.ended.is_set():
            self.ended.set()
            self._log("session_end", {"reason": reason})

    def _check(self):
        if not self.alive():
            self.end("timeout")
            raise ControlRefused("The control session ended (30 min max, 10 min idle). Start it again with your PIN.")
        if self.locked():
            raise ControlRefused("The laptop is locked: control stops (the Windows password is never typed remotely).")
        tick = self.local_tick()
        if tick is not None and not any(abs((tick - t) & 0xFFFFFFFF) < 250 for t in self.our_ticks[-50:]):
            # the newest input on the laptop was not ours: someone is at the laptop
            if (self.now_tick() - tick) & 0xFFFFFFFF < LOCAL_WINS_SECONDS * 1000:
                self.paused_until = self.clock() + LOCAL_WINS_SECONDS
        if self.clock() < self.paused_until:
            raise ControlRefused("Someone is using the laptop right now: phone control waits 10 s.")
        self.last_used = self.clock()

    def _mark(self):
        self.our_ticks.append(self.now_tick())
        self.our_ticks = self.our_ticks[-200:]

    def _log(self, kind, details):
        try:
            self.log({"origin": "phone_control", "actor": "owner", "kind": kind, **details})
        except Exception:
            pass

    # -- pointer --------------------------------------------------------------------------------------------------
    def pointer(self, events, monitor):
        """events: [{"kind": tap|double|right|move|down|up|scroll, "x": 0..1, "y": 0..1, "dy": int}].
        Z5 trackpad: {"kind": "nudge", "dx": px, "dy": px} moves from where the cursor is, and "at": "cursor" clicks
        or scrolls where it is; both stay on the streamed monitor."""
        self._check()
        window = self.window()
        done = 0
        for event in events[:60]:
            kind = event.get("kind")
            if kind not in {"tap", "double", "right", "move", "down", "up", "scroll", "nudge"}:
                raise ControlRefused(f"Unknown input {kind!r}.")
            if kind == "nudge":
                cx, cy = self.cursor()
                x, y = on_monitor(monitor, cx + _delta(event.get("dx")), cy + _delta(event.get("dy")))
                self.inject.pointer("move", x, y, 0)
            else:
                x, y = on_monitor(monitor, *self.cursor()) if event.get("at") == "cursor" else \
                    to_pixels(monitor, event.get("x"), event.get("y"))
                self.inject.pointer(kind, x, y, int(event.get("dy", 0)))
            self._mark()
            done += 1
            if kind not in ("move", "nudge"):
                self._log(kind, {"x": x, "y": y, "app": window.get("executable"), "title": window.get("title")})
        return {"done": done}

    # -- keyboard -------------------------------------------------------------------------------------------------
    def text(self, text, *, enter=False, pin_ok=False):
        self._check()
        if not isinstance(text, str) or len(text) > 2000:
            raise ControlRefused("Send at most 2000 characters at a time.")
        window = self.window()
        if enter and dangerous(window) and not pin_ok:
            raise ControlRefused(f"{window.get('executable') or 'This window'} can run commands: Enter needs your PIN.")
        self.inject.text(text)
        if enter:
            self.inject.keys(["enter"])
        self._mark()
        self._log("text", {"characters": len(text), "script": script_of(text), "enter": bool(enter),
                           "app": window.get("executable")})
        return {"typed": len(text)}

    def keys(self, combo, *, pin_ok=False):
        self._check()
        combo = str(combo).casefold().replace(" ", "")
        if combo in REFUSED_COMBOS or ("ctrl" in combo and "alt" in combo and ("del" in combo)):
            raise ControlRefused("That key combination is never sent from the phone.")
        parts = combo.split("+")
        if combo not in COMBOS and not (len(parts) == 1 and parts[0] in VK) and not all(p in VK for p in parts):
            raise ControlRefused(f"Unknown key {combo!r}.")
        window = self.window()
        if dangerous(window) and ("enter" in parts or combo == "ctrl+v") and not pin_ok:
            raise ControlRefused(f"{window.get('executable') or 'This window'} can run commands: this needs your PIN.")
        self.inject.keys(parts)
        self._mark()
        self._log("keys", {"combo": combo, "app": window.get("executable")})
        return {"sent": combo}


def to_pixels(monitor, x, y):
    """Normalised 0..1 point on the streamed monitor -> physical screen pixels."""
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)) \
            or not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ControlRefused("A point must be between 0 and 1.")
    left, top, width, height = monitor
    return int(round(left + x * (width - 1))), int(round(top + y * (height - 1)))


def _delta(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 400:
        raise ControlRefused("A trackpad move must be at most 400 pixels.")
    return int(value)


def on_monitor(monitor, x, y):
    left, top, width, height = monitor
    return min(max(int(x), left), left + width - 1), min(max(int(y), top), top + height - 1)


def cursor_pos():
    from chutku import vision
    point = w.POINT()
    with vision.dpi_aware() as user32:
        user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


class Injector:
    """Real Windows input (SendInput). Only constructed in a live control session."""

    def pointer(self, kind, x, y, dy=0):
        from chutku import vision
        with vision.dpi_aware() as user32:
            user32.SetCursorPos(int(x), int(y))
        if kind == "tap":
            vision.click_at(x, y)
        elif kind == "double":
            vision.click_at(x, y, double=True)
        elif kind == "right":
            vision.click_at(x, y, button="right")
        elif kind == "down":
            vision._send((0x0002, 0))
        elif kind == "up":
            vision._send((0x0004, 0))
        elif kind == "scroll":
            vision.scroll_at(x, y, max(-15, min(15, dy)))

    def text(self, text):
        from chutku.tools.desktop_controls import type_unicode
        type_unicode(text)

    def keys(self, parts):
        from chutku.tools.desktop_controls import press_combo
        press_combo([VK[p] for p in parts])


def _action_log(base):
    from pathlib import Path
    from chutku.core.action_log import ActionLog
    log = ActionLog(Path(base) / "data" / "actions.log.jsonl")
    return lambda record: log.append({"tool": "remote.control", "state": "COMPLETED", **record})


def primary_monitor():
    """(left, top, width, height) of the monitor the stream shows (the one holding the foreground window)."""
    from chutku import vision
    shot = vision.capture()
    return shot.left, shot.top, shot.width, shot.height
