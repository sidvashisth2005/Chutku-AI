"""WindowsDesktop, register_windows_apps: open/focus/close app windows, verified."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from pathlib import Path
import os
import subprocess
import sys
import time

from chutku.tools.registry import Risk, Tool, ToolResult, Verification


APPS = {
    "notepad": {"launcher": "notepad.exe", "process": "notepad.exe", "package": "microsoft.windowsnotepad_"},
    "calculator": {"launcher": "calc.exe", "process": "calculatorapp.exe", "package": "microsoft.windowscalculator_"},
}

_APP_SCHEMA = {
    "type": "object",
    "properties": {"app": {"type": "string", "enum": sorted(APPS)}},
    "required": ["app"],
    "additionalProperties": False,
}


def validate_app(arguments):
    if set(arguments) != {"app"} or not isinstance(arguments["app"], str) or arguments["app"] not in APPS:
        raise ValueError("Choose exactly one supported app: notepad or calculator. Arbitrary paths and arguments are not accepted.")


class WindowsDesktop:
    """Small native adapter. No shell commands, guessed titles or synthetic clicks."""
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Application control requires a Windows desktop session.")
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        signatures = [
            (self.u, "EnumWindows", [self.callback_type, w.LPARAM], w.BOOL),
            (self.u, "EnumChildWindows", [w.HWND, self.callback_type, w.LPARAM], w.BOOL),
            (self.u, "IsWindowVisible", [w.HWND], w.BOOL),
            (self.u, "IsWindow", [w.HWND], w.BOOL),
            (self.u, "IsIconic", [w.HWND], w.BOOL),
            (self.u, "GetWindowThreadProcessId", [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            (self.u, "GetWindowTextW", [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.u, "SendMessageTimeoutW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
            (self.u, "SetForegroundWindow", [w.HWND], w.BOOL),
            (self.u, "BringWindowToTop", [w.HWND], w.BOOL),
            (self.u, "AttachThreadInput", [w.DWORD, w.DWORD, w.BOOL], w.BOOL),
            (self.u, "GetForegroundWindow", [], w.HWND),
            (self.u, "ShowWindowAsync", [w.HWND, ctypes.c_int], w.BOOL),
            (self.u, "PostMessageW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            (self.k, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self.k, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.k, "CloseHandle", [w.HANDLE], w.BOOL),
            (self.k, "GetSystemDirectoryW", [w.LPWSTR, w.UINT], w.UINT),
            (self.k, "GetCurrentThreadId", [], w.DWORD),
        ]
        for library, name, arguments, result in signatures:
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result
        text = ctypes.create_unicode_buffer(32768)
        length = self.k.GetSystemDirectoryW(text, len(text))
        if not 0 < length < len(text):
            raise OSError("Could not resolve the Windows system directory.")
        self.system_dir = Path(text.value)

    def _image(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            text = ctypes.create_unicode_buffer(32768)
            size = w.DWORD(len(text))
            return text.value if self.k.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)) else None
        finally:
            self.k.CloseHandle(handle)

    def _matches(self, image: str, app: str) -> bool:
        path = Path(image)
        spec = APPS[app]
        if app == "notepad" and path == self.system_dir / "notepad.exe":
            return True
        # Packaged Windows apps can have a different PID from the system launcher.
        package_root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WindowsApps"
        try:
            relative = path.relative_to(package_root)
        except ValueError:
            return False
        return (len(relative.parts) >= 2 and relative.parts[0].casefold().startswith(spec["package"])
                and path.name.casefold() == spec["process"])

    def windows(self, app: str):
        matches = []
        scanned = 0
        @self.callback_type
        def collect(hwnd, _):
            nonlocal scanned
            scanned += 1
            if scanned > 500:
                return False
            if not self.u.IsWindowVisible(hwnd):
                return True
            pid = w.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            image = self._image(pid.value)
            if image and Path(image) == self.system_dir / "ApplicationFrameHost.exe":
                # Some packaged applications place their CoreWindow beneath a
                # trusted system frame. Identify its child by process image,
                # never by the frame's user-controlled title alone.
                children = []
                child_count = 0
                @self.callback_type
                def child_identity(child, _):
                    nonlocal child_count
                    child_count += 1
                    if child_count > 100:
                        return False
                    child_pid = w.DWORD()
                    self.u.GetWindowThreadProcessId(child, ctypes.byref(child_pid))
                    child_image = self._image(child_pid.value)
                    if child_image and self._matches(child_image, app):
                        children.append((child_pid.value, child_image))
                    return True
                self.u.EnumChildWindows(hwnd, child_identity, 0)
                if children:
                    pid.value, image = children[0]
            if image and self._matches(image, app):
                text = ctypes.create_unicode_buffer(513)
                self.u.GetWindowTextW(hwnd, text, len(text))
                if text.value:
                    matches.append({"window_id": int(hwnd), "process_id": pid.value, "title": text.value,
                                    "image": image, "minimized": bool(self.u.IsIconic(hwnd))})
            return True
        if not self.u.EnumWindows(collect, 0) and scanned <= 500:
            raise OSError("Cannot inspect this Windows desktop. Run Chutku in your normal desktop session.")
        if scanned > 500:
            raise OSError("Window enumeration exceeded its bounded limit; no action was taken.")
        return matches

    def responsive(self, hwnd):
        value = ctypes.c_size_t()
        return bool(self.u.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x2, 250, ctypes.byref(value)))

    def exact_window(self, window_id, process_id, executable):
        """Rebind one ordinary top-level window by immutable OS identities, never title."""
        if type(window_id) is not int or type(process_id) is not int or not self.u.IsWindow(window_id):
            return None
        if not self.u.IsWindowVisible(window_id):
            return None
        actual_pid = w.DWORD()
        self.u.GetWindowThreadProcessId(window_id, ctypes.byref(actual_pid))
        image = self._image(actual_pid.value)
        try:
            same_image = image is not None and Path(image).resolve() == Path(executable).resolve()
        except OSError:
            same_image = False
        if actual_pid.value != process_id or not same_image:
            return None
        return {"window_id": window_id, "process_id": process_id, "image": image,
                "minimized": bool(self.u.IsIconic(window_id))}

    def launch(self, app):
        executable = self.system_dir / APPS[app]["launcher"]
        if not executable.is_file():
            raise OSError("This supported Windows application is not installed.")
        subprocess.Popen([str(executable)], shell=False, cwd=str(self.system_dir),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def focus(self, hwnd, nudge=True):
        """Bring hwnd to the front. nudge=True may tap Alt to earn Windows' focus right; nudge="quiet" taps an
        unassigned key code instead (0xB9 types nothing and opens no menu): used to hand the owner's own window back
        after a background app jumped forward while he may be typing; nudge=False never injects anything."""
        if self.u.IsIconic(hwnd):
            # Synchronous restore: with ShowWindowAsync, Windows reported the window as foreground while another
            # app still covered it on screen (WhatsApp sends failed that way, 2026-10-04).
            self.u.ShowWindow(hwnd, 9)  # SW_RESTORE
        foreground = self.u.GetForegroundWindow()
        current_thread = self.k.GetCurrentThreadId()
        target_thread = self.u.GetWindowThreadProcessId(hwnd, None)
        foreground_thread = self.u.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = []
        try:
            for thread in {target_thread, foreground_thread}:
                if thread and thread != current_thread and self.u.AttachThreadInput(current_thread, thread, True):
                    attached.append(thread)
            self.u.BringWindowToTop(hwnd)
            self.u.SetForegroundWindow(hwnd)
            if self.u.GetForegroundWindow() != hwnd and nudge:
                # Windows only lets the process that had the last input take focus. Scheduled tasks, the phone
                # and the API have none (live 2026-11-05: Settings stayed in front of Notepad), so one Alt tap
                # counts as that input, then try again.
                keybd_event = ctypes.windll.user32.keybd_event
                key = 0xB9 if nudge == "quiet" else 0x12   # unassigned code, or VK_MENU (Alt)
                keybd_event(key, 0, 0, 0)
                keybd_event(key, 0, 0x0002, 0)   # KEYEVENTF_KEYUP
                self.u.SetForegroundWindow(hwnd)
        finally:
            for thread in attached:
                self.u.AttachThreadInput(current_thread, thread, False)

    def close(self, hwnd):
        if not self.u.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
            raise ctypes.WinError(ctypes.get_last_error())

    def foreground(self):
        return int(self.u.GetForegroundWindow() or 0)


def _observed(app, window, desktop, require_focus=False):
    responsive = desktop.responsive(window["window_id"])
    focused = desktop.foreground() == window["window_id"]
    verified = responsive and (focused or not require_focus)
    output = {"app": app, "window_id": window["window_id"], "process_id": window["process_id"],
              "visible": True, "responsive": responsive, "focused": focused,
              "title": window["title"], "uia": "NOT_PROBED"}
    if not verified:
        output["error"] = "Windows did not grant foreground focus." if responsive else "The application window is not responding."
    return ToolResult(output, Verification.PASS if verified else Verification.UNKNOWN,
                      output | {"title": "[REDACTED]"})


def _status(args, _):
    desktop = WindowsDesktop()
    windows = desktop.windows(args["app"])
    items = [{"window_id": window["window_id"], "process_id": window["process_id"],
              "title": window["title"], "responsive": desktop.responsive(window["window_id"])} for window in windows[:10]]
    return ToolResult({"app": args["app"], "app_windows": items, "running": bool(items)}, Verification.PASS,
                      {"app": args["app"], "count": len(items), "titles": "[REDACTED]"})


def _open(args, _):
    app = args["app"]
    desktop = WindowsDesktop()
    windows = desktop.windows(app)
    if len(windows) > 1:
        return ToolResult({"error": "Multiple windows match this app. Select the desired window manually; no new app was launched."}, Verification.FAIL)
    if not windows:
        desktop.launch(app)
    deadline = time.monotonic() + 10
    stable_id, stable_since = None, 0
    while time.monotonic() < deadline:
        windows = desktop.windows(app)
        if windows and desktop.responsive(windows[0]["window_id"]):
            window_id = windows[0]["window_id"]
            if stable_id != window_id:
                stable_id, stable_since = window_id, time.monotonic()
            if time.monotonic() - stable_since < 0.75:
                time.sleep(0.1)
                continue
            # Observe again in the runtime verifier; a returned launcher PID is insufficient.
            return ToolResult({"app": app, "window_id": window_id}, Verification.UNKNOWN)
        else:
            stable_id = None
        time.sleep(0.1)
    return ToolResult({"error": "The app was requested, but no matching visible window appeared within 10 seconds."}, Verification.FAIL)


def _focus(args, _):
    desktop = WindowsDesktop()
    windows = desktop.windows(args["app"])
    if len(windows) != 1:
        return ToolResult({"error": "Focus requires exactly one matching app window. Open the app or resolve multiple windows first."}, Verification.FAIL)
    hwnd = windows[0]["window_id"]
    desktop.focus(hwnd)
    deadline = time.monotonic() + 1
    while desktop.foreground() != hwnd and time.monotonic() < deadline:
        time.sleep(0.05)
    return ToolResult({"app": args["app"], "window_id": hwnd}, Verification.UNKNOWN)


def _close(args, _):
    desktop = WindowsDesktop()
    windows = desktop.windows(args["app"])
    if len(windows) != 1:
        return ToolResult({"error": "Close requires exactly one matching app window; no close message was sent."},
                          Verification.FAIL)
    window = windows[0]
    desktop.close(window["window_id"])
    return ToolResult({"app": args["app"], "window_id": window["window_id"],
                       "process_id": window["process_id"]}, Verification.UNKNOWN)


def verify_window(args, result, _, require_focus=False):
    desktop = WindowsDesktop()
    window = next((item for item in desktop.windows(args["app"])
                   if item["window_id"] == result.output.get("window_id")), None)
    if window is None:
        return ToolResult({"error": "The app window disappeared before independent verification."}, Verification.UNKNOWN)
    return _observed(args["app"], window, desktop, require_focus)


def verify_closed(args, result, _):
    desktop = WindowsDesktop()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        windows = desktop.windows(args["app"])
        if not windows:
            return ToolResult({"app": args["app"], "closed": True,
                               "window_id": result.output.get("window_id")}, Verification.PASS)
        time.sleep(0.1)
    return ToolResult({"app": args["app"], "closed": False,
                       "error": "The app still has a matching visible window; it may be showing a save dialog."},
                      Verification.UNKNOWN)


def register_windows_apps(registry):
    registry.register(Tool("apps.status", "Inspect verified process identity and visible windows for Notepad or Calculator.",
        Risk.OBSERVATION, _status, validate_app, argument_schema=_APP_SCHEMA,
        prerequisites=("interactive Windows desktop",), reversibility="not_applicable",
        success_predicate="matching_process_and_window_inventory_observed"))
    registry.register(Tool("apps.open", "Open Notepad or Calculator and independently verify a visible responsive window.",
        Risk.REVERSIBLE, _open, validate_app, verify=verify_window, argument_schema=_APP_SCHEMA,
        prerequisites=("interactive Windows desktop",), reversibility="compensatable",
        success_predicate="exact_app_window_visible_and_responsive"))
    registry.register(Tool("apps.focus", "Focus one Notepad or Calculator window and verify foreground ownership.",
        Risk.REVERSIBLE, _focus, validate_app,
        verify=lambda a, r, c: verify_window(a, r, c, require_focus=True), required_capability="desktop.input",
        argument_schema=_APP_SCHEMA,
        prerequisites=("exactly one matching visible app window",), reversibility="transient",
        success_predicate="exact_window_owns_foreground"))
    registry.register(Tool("apps.close", "Request graceful close of exactly one Notepad or Calculator window and verify it disappears.",
        Risk.EXTERNAL_SIDE_EFFECT, _close, validate_app, verify=verify_closed, required_capability="desktop.input",
        argument_schema=_APP_SCHEMA, prerequisites=("exactly one matching visible app window",),
        reversibility="irreversible_if_unsaved_state_is_discarded_by_the_app",
        success_predicate="no_matching_app_window_remains"))
