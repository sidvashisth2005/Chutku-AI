"""Notification-area (tray) icon: open the dashboard, pause/resume actions, emergency stop.

Plain Win32 through ctypes (no extra packages). Runs its own message loop on a daemon thread.
Every menu action reuses the same controls as the dashboard buttons.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import threading

WM_APP_TRAY = 0x8000 + 1
WM_CLOSE, WM_DESTROY = 0x0010, 0x0002
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
OPEN, TOGGLE, STOP, WINDOW = 1, 2, 3, 4

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


def menu_items(paused: bool, guard_active: bool):
    """(command, label, enabled) rows; None is a separator. Pure, so it is testable."""
    return [(0, "Chutku: actions paused" if paused else "Chutku: ready", False), None,
            (WINDOW, "Show Chutku window", True),
            (OPEN, "Open dashboard", True),
            (TOGGLE, "Resume actions" if paused else "Pause actions", True),
            (STOP, "Quit Chutku (close everything)" if guard_active else "Quit needs Start-Chutku.cmd", guard_active)]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                ("lpszClassName", w.LPCWSTR)]


class _NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]


class Tray(threading.Thread):
    def __init__(self, *, open_dashboard, toggle_pause, stop, is_paused, guard_active, show_window=None):
        super().__init__(name="chutku-tray", daemon=True)
        self.actions = {OPEN: open_dashboard, TOGGLE: toggle_pause, STOP: stop, WINDOW: show_window or open_dashboard}
        self.is_paused, self.guard_active = is_paused, guard_active
        self.ready, self.error, self.hwnd = threading.Event(), None, None
        self._proc = WNDPROC(self._window_proc)  # keep a reference for the lifetime of the window

    def run(self):
        try:
            self._create()
        except Exception as error:  # the tray is a convenience: never take Chutku down
            self.error = str(error)
            self.ready.set()
            return
        self.ready.set()
        user = ctypes.windll.user32
        message = w.MSG()
        while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user.TranslateMessage(ctypes.byref(message))
            user.DispatchMessageW(ctypes.byref(message))

    def close(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # -- win32 -------------------------------------------------------------------------
    def _create(self):
        from chutku.icon import ensure_icon
        user, kernel = ctypes.windll.user32, ctypes.windll.kernel32
        user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user.DefWindowProcW.restype = LRESULT
        user.CreateWindowExW.restype = w.HWND
        user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        user.LoadImageW.restype = w.HANDLE
        user.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
        user.CreatePopupMenu.restype = w.HMENU
        user.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID]
        kernel.GetModuleHandleW.restype = w.HINSTANCE
        instance = kernel.GetModuleHandleW(None)
        window_class = _WNDCLASS(lpfnWndProc=self._proc, hInstance=instance, lpszClassName="ChutkuTray")
        user.RegisterClassW(ctypes.byref(window_class))  # fails harmlessly if already registered
        self.hwnd = user.CreateWindowExW(0, "ChutkuTray", "Chutku", 0, 0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            raise ctypes.WinError()
        icon = user.LoadImageW(None, str(ensure_icon()), 1, 16, 16, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        self._data = _NOTIFYICONDATA(cbSize=ctypes.sizeof(_NOTIFYICONDATA), hWnd=self.hwnd, uID=1,
                                     uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_APP_TRAY,
                                     hIcon=icon, szTip="Chutku — click to open, right-click for options")
        if not ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data)):
            raise OSError("Windows refused the tray icon.")

    def _menu(self):
        user = ctypes.windll.user32
        menu = user.CreatePopupMenu()
        for item in menu_items(self._safe(self.is_paused), self._safe(self.guard_active)):
            if item is None:
                user.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                command, label, enabled = item
                user.AppendMenuW(menu, MF_STRING | (0 if enabled else MF_GRAYED), command, label)
        point = w.POINT()
        user.GetCursorPos(ctypes.byref(point))
        user.SetForegroundWindow(self.hwnd)  # so the menu closes when clicking elsewhere
        command = user.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                      point.x, point.y, 0, self.hwnd, None)
        user.DestroyMenu(menu)
        return command

    @staticmethod
    def _safe(function):
        try:
            return bool(function())
        except Exception:
            from chutku.core.log import get_logger
            get_logger("tray").exception("tray action failed")
            return False

    def _run_action(self, command):
        action = self.actions.get(command)
        if action is not None:
            threading.Thread(target=_quietly, args=(action,), daemon=True).start()  # keep the tray responsive

    def _window_proc(self, hwnd, message, wparam, lparam):
        user = ctypes.windll.user32
        if message == WM_APP_TRAY:
            if lparam == WM_LBUTTONUP:
                self._run_action(OPEN)
            elif lparam == WM_RBUTTONUP:
                self._run_action(self._menu())
            return 0
        if message == WM_CLOSE:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data))
            user.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(hwnd, message, wparam, lparam)


def _quietly(action):
    try:
        action()
    except Exception:
        from chutku.core.log import get_logger
        get_logger("tray").exception("tray action failed")
