"""Desktop controls with Mark-LIV parity: shortcuts, typing, volume, brightness,
lock, performance, wallpaper and largest files.

Keyboard input always targets one exact window. When Chutku's own chat page is in
front, the target is the window the user was using just before it (next in Z-order),
which is focused and verified first. Every action reads back what it can observe.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import heapq
import os
import re
from pathlib import Path
import subprocess
import time

from chutku.core.paths import sandbox_target
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

# -- keyboard ---------------------------------------------------------------------

CTRL, SHIFT, ALT, WIN = 0x11, 0x10, 0x12, 0x5B
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}

# name -> (keys, changes_foreground)
VIEW_SHORTCUTS = {
    "new_tab": ([CTRL, 0x54], False), "next_tab": ([CTRL, 0x09], False), "previous_tab": ([CTRL, SHIFT, 0x09], False),
    "reopen_closed_tab": ([CTRL, SHIFT, 0x54], False), "refresh": ([0x74], False), "back": ([ALT, 0x25], False),
    "forward": ([ALT, 0x27], False), "zoom_in": ([CTRL, 0xBB], False), "zoom_out": ([CTRL, 0xBD], False),
    "zoom_reset": ([CTRL, 0x30], False), "find": ([CTRL, 0x46], False), "fullscreen": ([0x7A], False),
    "scroll_top": ([CTRL, 0x24], False), "scroll_bottom": ([CTRL, 0x23], False), "page_up": ([0x21], False),
    "page_down": ([0x22], False), "scroll_up": ([0x26, 0x26, 0x26], False), "scroll_down": ([0x28, 0x28, 0x28], False),
    "copy": ([CTRL, 0x43], False), "select_all": ([CTRL, 0x41], False), "escape": ([0x1B], False),
    "snap_left": ([WIN, 0x25], False), "snap_right": ([WIN, 0x27], False), "show_desktop": ([WIN, 0x44], True),
    "switch_window": ([ALT, 0x09], True), "task_view": ([WIN, 0x09], True), "task_manager": ([CTRL, SHIFT, 0x1B], True),
    "run_dialog": ([WIN, 0x52], True), "file_explorer": ([WIN, 0x45], True), "windows_settings": ([WIN, 0x49], True),
    "windows_search": ([WIN, 0x53], True), "emoji_panel": ([WIN, 0xBE], False), "clipboard_history": ([WIN, 0x56], False),
}
EDIT_SHORTCUTS = {
    "paste": ([CTRL, 0x56], False), "cut": ([CTRL, 0x58], False), "undo": ([CTRL, 0x5A], False),
    "redo": ([CTRL, 0x59], False), "save": ([CTRL, 0x53], False), "delete": ([0x2E], False),
    "backspace": ([0x08], False), "close_tab": ([CTRL, 0x57], False),
}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _U)]


def _send(events):
    array = (_INPUT * len(events))(*events)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SendInput.argtypes = [w.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    if user.SendInput(len(events), array, ctypes.sizeof(_INPUT)) != len(events):
        raise OSError("Windows refused the keyboard input (a protected or elevated window may be in front).")


def _key(vk, up):
    flags = (0x2 if up else 0) | (0x1 if vk in _EXTENDED else 0)
    return _INPUT(type=1, ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))


def press_combo(keys):
    """Hold modifiers, tap the final key(s), release in reverse order."""
    modifiers = [k for k in keys if k in (CTRL, SHIFT, ALT, WIN)]
    others = [k for k in keys if k not in modifiers]
    events = [_key(k, False) for k in modifiers]
    for key in others:
        events += [_key(key, False), _key(key, True)]
    events += [_key(k, True) for k in reversed(modifiers)]
    _send(events)


TYPE_DELAY = 0.03  # Windows 11 Notepad (WinUI) drops or repeats characters sent faster than ~20 ms apart


def type_unicode(text):
    """Type text one character at a time like a person: the layout key (with Shift) when the
    keyboard has one, a Unicode packet otherwise (Devanagari, symbols)."""
    user = ctypes.WinDLL("user32")
    user.VkKeyScanW.restype = ctypes.c_short
    for char in text:
        scan = user.VkKeyScanW(ord(char)) if ord(char) < 0x10000 else -1
        vk, shift = scan & 0xFF, (scan >> 8) & 0xFF
        if scan != -1 and shift in (0, 1):
            events = ([_key(SHIFT, False)] if shift else []) + [_key(vk, False), _key(vk, True)] +                      ([_key(SHIFT, True)] if shift else [])
        else:
            encoded = char.encode("utf-16-le")
            events = [_INPUT(type=1, ki=_KEYBDINPUT(wVk=0, wScan=int.from_bytes(encoded[i:i + 2], "little"),
                                                    dwFlags=0x4 | flag, time=0, dwExtraInfo=0))
                      for i in range(0, len(encoded), 2) for flag in (0, 2)]
        _send(events)
        time.sleep(TYPE_DELAY)


def _is_chutku_page(info):
    return info is not None and "chutku" in (info.get("title") or "").casefold() and \
        Path(info.get("executable") or "").name.casefold() in {"msedge.exe", "chrome.exe", "brave.exe", "firefox.exe",
                                                                "opera.exe", "vivaldi.exe"}


def is_own_window(info):
    """Chutku's own dashboard page, HUD or tray: the agent never clicks there (it could approve its own step)."""
    if info is None:
        return False
    if _is_chutku_page(info):
        return True
    exe = Path(info.get("executable") or "").name.casefold()
    return exe in {"python.exe", "pythonw.exe"} and "chutku" in (info.get("title") or "").casefold()


def own_window_at(x, y):
    """True when the screen point (x, y) is on one of Chutku's own windows (fails closed: True if unknown)."""
    try:
        from chutku.tools.everyday import Desktop
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.restype = ctypes.c_void_p
        user32.WindowFromPoint.argtypes = [w.POINT]
        user32.GetAncestor.restype = ctypes.c_void_p
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        hwnd = user32.WindowFromPoint(w.POINT(int(x), int(y)))
        root = user32.GetAncestor(hwnd, 2) if hwnd else None  # GA_ROOT
        if not root:
            return False  # the bare desktop
        return is_own_window(Desktop().describe(int(root)))
    except (OSError, ValueError, AttributeError):
        return True


def _active_dialog(desktop, info):
    """If the window has a dialog open (Save As, Open, a prompt), input belongs to that dialog, as Windows
    itself would route it. Only a visible popup of the same process qualifies."""
    import ctypes
    user32 = ctypes.windll.user32
    user32.GetLastActivePopup.restype = ctypes.c_void_p
    popup = user32.GetLastActivePopup(ctypes.c_void_p(info["window_id"]))
    if popup and int(popup) != info["window_id"] and user32.IsWindowVisible(ctypes.c_void_p(popup)):
        dialog = desktop.describe(int(popup))
        if dialog["process_id"] == info["process_id"]:
            return dialog
    return info


def target_window(arguments):
    """Resolve and focus the exact window keyboard input goes to."""
    from chutku.tools.everyday import Desktop
    from chutku.tools.windows_apps import WindowsDesktop
    desktop = Desktop()
    if "window_id" in arguments:
        info = desktop.exact(arguments["window_id"], arguments.get("process_id"), arguments.get("executable", ""))
        if info is None:
            raise ValueError("That exact window no longer exists; list windows again.")
        info = _active_dialog(desktop, info)
    else:
        hwnd = desktop.foreground()
        info = desktop.describe(hwnd) if hwnd else None
        if info is None or not info["title"]:
            raise ValueError("No application window is in front. Say which window to use.")
        if _is_chutku_page(info):
            # The chat page is in front: use the window the user was working in before it.
            info = None
            for candidate in desktop.windows():
                described = desktop.describe(candidate)
                if candidate != hwnd and described["title"] and not described["minimized"] \
                        and not _is_chutku_page(described):
                    info = described
                    break
            if info is None:
                raise ValueError("Only Chutku's own page is open. Say which window to use.")
    if desktop.foreground() != info["window_id"]:
        WindowsDesktop().focus(info["window_id"])
        deadline = time.monotonic() + 1.5
        while desktop.foreground() != info["window_id"] and time.monotonic() < deadline:
            time.sleep(0.05)
        if desktop.foreground() != info["window_id"]:
            raise OSError("Windows did not bring the target window to the front; nothing was typed.")
    return desktop, info


_WINDOW_ARGS = {"window_id": {"type": "integer", "minimum": 1}, "process_id": {"type": "integer", "minimum": 1},
                "executable": {"type": "string", "minLength": 3, "maxLength": 1000},
                "document": {"type": "string", "minLength": 1, "maxLength": 200}}

# "CHAPTER 1.txt - Notepad", "report.docx - Word": a window showing an existing, named document.
_DOCUMENT_TITLE = re.compile(r"^\*?\s*(?P<name>[^\/:*?\"<>|]{1,150}\.[A-Za-z0-9]{1,8})\s+-\s+")


def guard_document(info, arguments):
    """Never type into, edit or save someone's existing document unless the request named it.
    (Apps like Notepad can reopen the user's files in a window Chutku just launched.)"""
    match = _DOCUMENT_TITLE.match(info.get("title") or "")
    if not match:
        return
    name = match.group("name").strip()
    wanted = str(arguments.get("document", "")).strip().casefold()
    if not wanted or wanted not in name.casefold():
        raise ValueError(f"This window is showing the existing document '{name}'. Chutku will not type into, edit or "
                         "save it unless the user named it. For new text, open a blank document first "
                         "(e.g. keyboard.shortcut new_tab in Notepad) and check the window title.")


def _shortcut_schema(names):
    return {"type": "object", "properties": {"action": {"type": "string", "enum": sorted(names)}} | _WINDOW_ARGS,
            "required": ["action"], "additionalProperties": False}


def _validate_window(arguments):
    identity = {"window_id", "process_id", "executable"} & set(arguments)
    if identity and identity != {"window_id", "process_id", "executable"}:
        raise ValueError("Give window_id, process_id and executable together, or none of them.")


def _make_shortcut(table):
    def validate(arguments):
        if set(arguments) - {"action", "window_id", "process_id", "executable", "document"} or                 arguments.get("action") not in table:
            raise ValueError("Choose one supported shortcut action.")
        _validate_window(arguments)

    def run(arguments, _context):
        keys, changes_foreground = table[arguments["action"]]
        try:
            desktop, info = target_window(arguments)
            if table is EDIT_SHORTCUTS:
                guard_document(info, arguments)
            before = desktop.foreground()
            press_combo(keys)
        except (OSError, ValueError) as error:
            return ToolResult({"error": str(error)}, Verification.FAIL)
        time.sleep(0.4)
        output = {"action": arguments["action"], "app": Path(info["executable"] or "").name,
                  "window": info["title"][:120]}
        if changes_foreground:
            ok = desktop.foreground() != before
            if not ok:
                output["error"] = "The expected window change was not observed."
        else:
            ok = bool(desktop.u.IsWindow(info["window_id"]))
            output["note"] = "Keys were delivered to this exact window; the app decides the effect."
            time.sleep(0.6)
            dialog = _active_dialog(desktop, info)
            if dialog["window_id"] != info["window_id"]:  # e.g. Ctrl+S on a new file opened "Save as"
                output["dialog_opened"] = dialog["title"][:80]
                output["next"] = ("A dialog is open. Type into it with keyboard.type_text (for Save as: the full "
                                  "file path), then keyboard.press_enter. Do not close the app before that.")
        return ToolResult(output, Verification.PASS if ok else Verification.UNKNOWN,
                          output | {"window": "[REDACTED]"})
    return validate, run


def _validate_type(arguments):
    if set(arguments) - {"text", "window_id", "process_id", "executable", "document"} or             not isinstance(arguments.get("text"), str):
        raise ValueError("Provide text (and optionally an exact window).")
    text = arguments["text"]
    if not 1 <= len(text) <= 1000 or any(ord(c) < 32 and c not in "\t" for c in text):
        raise ValueError("Text must be 1-1000 characters on one line (use keyboard.press_enter separately).")
    _validate_window(arguments)


# Windows where typed text runs as a command. Typing into them, or opening one, is confirmed on screen first
# (owner decision 2026-10-06); the check repeats when the keys are sent, in case the window changed meanwhile.
COMMAND_WINDOW_APPS = frozenset({"cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "windowsterminal.exe",
                                 "wt.exe", "conhost.exe", "openconsole.exe", "wsl.exe", "bash.exe", "mintty.exe",
                                 "python.exe", "py.exe"})
_COMMAND_APP_NAMES = re.compile(r"\b(?:cmd|command prompt|powershell|pwsh|terminal|wsl|bash|ubuntu|registry editor|"
                                r"regedit)\b", re.I)


def command_window_reason(info):
    """Why typing into this window asks first (it runs commands), or None."""
    exe = Path(str(info.get("executable") or "")).name.casefold()
    if exe in COMMAND_WINDOW_APPS:
        return "Typing into a command window asks first."
    if exe == "explorer.exe" and str(info.get("title") or "").strip().casefold() == "run":
        return "Typing into the Run box asks first."
    return None


def command_app_reason(name):
    """Why launching this app asks first (it is a command-line app), or None."""
    name = str(name or "")
    if _COMMAND_APP_NAMES.search(name) or Path(name).name.casefold() in COMMAND_WINDOW_APPS:
        return "Opening a command window asks first."
    return None


def _refuse_command_window(info, context):
    if not getattr(context, "approved", False) and command_window_reason(info):
        raise ValueError("The window in front is a command window; Chutku types there only after you confirm.")


def _type_text(arguments, context):
    try:
        desktop, info = target_window(arguments)
        guard_document(info, arguments)
        _refuse_command_window(info, context)
        type_unicode(arguments["text"])
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    time.sleep(0.2)
    still = desktop.foreground() == info["window_id"]
    output = {"typed_characters": len(arguments["text"]), "app": Path(info["executable"] or "").name,
              "window": info["title"][:120], "focus_kept": still}
    if not still:
        output["error"] = "Focus moved while typing; some characters may have gone elsewhere."
    return ToolResult(output, Verification.PASS if still else Verification.UNKNOWN,
                      output | {"window": "[REDACTED]"})


def _press_enter(arguments, context):
    try:
        desktop, info = target_window(arguments)
        guard_document(info, arguments)
        _refuse_command_window(info, context)
        press_combo([0x0D])
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    output = {"pressed": "Enter", "app": Path(info["executable"] or "").name, "window": info["title"][:80]}
    time.sleep(1.2)
    if desktop.u.IsWindow(info["window_id"]) and desktop.u.IsWindowVisible(info["window_id"]) and \
            info["title"].casefold() in {"save as", "open", "save", "save file", "open file", "export", "print"}:
        # The dialog is still there: the name/path was probably rejected (it may show an error).
        output["error"] = (f"The '{info['title']}' dialog is still open after Enter; the input may have been "
                           "rejected. Look at the screen (screen.understand) before continuing.")
        return ToolResult(output, Verification.UNKNOWN)
    return ToolResult(output, Verification.PASS)


# -- volume -----------------------------------------------------------------------

_VOLUME_ACTIONS = ("up", "down", "set", "mute", "unmute")


def _validate_volume(arguments):
    if set(arguments) - {"action", "level", "step"} or arguments.get("action") not in _VOLUME_ACTIONS:
        raise ValueError("Choose up, down, set, mute or unmute.")
    if arguments["action"] == "set" and not (type(arguments.get("level")) is int and 0 <= arguments["level"] <= 100):
        raise ValueError("set needs a level from 0 to 100.")
    if "step" in arguments and not (type(arguments["step"]) is int and 1 <= arguments["step"] <= 50):
        raise ValueError("step must be 1-50.")


def _volume(arguments, _context):
    from chutku.tools.system_controls import _valid_volume, _volume_call
    try:
        before = _volume_call({"action": "get"})
        if not _valid_volume(before):
            raise OSError("Windows returned an invalid volume state.")
        step, action = arguments.get("step", 10), arguments["action"]
        target = dict(before)
        if action == "up":
            target.update(level=min(100, before["level"] + step), muted=False)
        elif action == "down":
            target.update(level=max(0, before["level"] - step))
        elif action == "set":
            target.update(level=arguments["level"], muted=False)
        else:
            target["muted"] = action == "mute"
        after = _volume_call({"action": "set", **target})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    ok = _valid_volume(after) and after == target
    return ToolResult({"before": before, "after": after, "undo_hint": f"audio.volume set {before['level']}"},
                      Verification.PASS if ok else Verification.FAIL)


# -- brightness -------------------------------------------------------------------

_BRIGHTNESS = r'''
$ErrorActionPreference = 'Stop'
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($r.action -eq 'set') {
  $m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
  Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{Timeout=[uint32]1; Brightness=[byte]$r.level} | Out-Null
  Start-Sleep -Milliseconds 400
}
$b = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
@{ level = [int]$b.CurrentBrightness } | ConvertTo-Json -Compress
'''


def _brightness_call(request):
    from chutku.tools.everyday import _powershell
    value = _powershell(_BRIGHTNESS, request)
    if not isinstance(value, dict) or type(value.get("level")) is not int:
        raise OSError("This display does not report brightness (external monitors usually cannot be set).")
    return value["level"]


def _validate_brightness(arguments):
    if set(arguments) - {"action", "level", "step"} or arguments.get("action") not in {"up", "down", "set"}:
        raise ValueError("Choose up, down or set.")
    if arguments["action"] == "set" and not (type(arguments.get("level")) is int and 0 <= arguments["level"] <= 100):
        raise ValueError("set needs a level from 0 to 100.")
    if "step" in arguments and not (type(arguments["step"]) is int and 1 <= arguments["step"] <= 50):
        raise ValueError("step must be 1-50.")


def _brightness_status(_arguments, _context):
    try:
        return ToolResult({"level": _brightness_call({"action": "get"})}, Verification.PASS)
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)


def _brightness(arguments, _context):
    try:
        before = _brightness_call({"action": "get"})
        step = arguments.get("step", 10)
        target = {"up": min(100, before + step), "down": max(0, before - step)}.get(arguments["action"],
                                                                                arguments.get("level"))
        after = _brightness_call({"action": "set", "level": target})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    ok = abs(after - target) <= 2
    return ToolResult({"before": before, "after": after, "undo_hint": f"display.brightness set {before}"},
                      Verification.PASS if ok else Verification.FAIL)


# -- lock ---------------------------------------------------------------------------

def _lock(_arguments, _context):
    user = ctypes.WinDLL("user32", use_last_error=True)
    if not user.LockWorkStation():
        return ToolResult({"error": "Windows refused to lock."}, Verification.FAIL)
    time.sleep(1.0)
    # When the session is locked the interactive input desktop is no longer "Default".
    user.OpenInputDesktop.restype = w.HANDLE
    handle = user.OpenInputDesktop(0, False, 0x0001)
    locked = not handle
    if handle:
        name = ctypes.create_unicode_buffer(64)
        user.GetUserObjectInformationW(handle, 2, name, ctypes.sizeof(name), None)
        locked = name.value.casefold() != "default"
        user.CloseDesktop(handle)
    return ToolResult({"locked": locked}, Verification.PASS if locked else Verification.UNKNOWN)


# -- performance --------------------------------------------------------------------

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", w.DWORD), ("dwMemoryLoad", w.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _POWER(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", w.DWORD), ("BatteryFullLifeTime", w.DWORD)]


def _cpu_percent(interval=0.5):
    kernel = ctypes.WinDLL("kernel32")

    def sample():
        idle, kern, user = w.FILETIME(), w.FILETIME(), w.FILETIME()
        kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        value = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
        return value(idle), value(kern) + value(user)
    idle1, total1 = sample()
    time.sleep(interval)
    idle2, total2 = sample()
    busy = (total2 - total1) - (idle2 - idle1)
    return round(100 * busy / max(total2 - total1, 1), 1)


# ACPI thermal zones (root/wmi often needs admin, the perf counter class does not), then 1 s of network counters.
# Zones are the firmware's sensors near the CPU; values outside 5-125 C are firmware placeholders.
_TELEMETRY = r'''
$ErrorActionPreference = 'SilentlyContinue'
$c = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | ForEach-Object { $_.CurrentTemperature / 10 - 273.15 })
if (-not $c) { $c = @(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | ForEach-Object { $_.Temperature - 273.15 }) }
$c = @($c | Where-Object { $_ -ge 5 -and $_ -le 125 })
$s = (Get-Counter '\Network Interface(*)\Bytes Received/sec', '\Network Interface(*)\Bytes Sent/sec').CounterSamples
$net = $null
if ($s) { $net = [pscustomobject]@{
  down_mbps = [math]::Round((($s | Where-Object { $_.Path -like '*received*' } | Measure-Object CookedValue -Sum).Sum) * 8 / 1e6, 2)
  up_mbps = [math]::Round((($s | Where-Object { $_.Path -like '*sent*' } | Measure-Object CookedValue -Sum).Sum) * 8 / 1e6, 2) } }
[pscustomobject]@{ cpu_c = $(if ($c) { [math]::Round(($c | Measure-Object -Maximum).Maximum, 1) } else { $null }); network = $net } | ConvertTo-Json -Compress
'''
CPU_TEMP_MISSING = "CPU temperature isn't exposed on this PC without admin."


def _telemetry():
    """CPU temperature (or the honest reason it is missing) and current network throughput."""
    try:
        from chutku.tools.everyday import _powershell
        found = _powershell(_TELEMETRY, {}, timeout=10)
    except (OSError, subprocess.SubprocessError):
        found = None
    found = found if isinstance(found, dict) else {}
    output = {"cpu_temperature_c": found.get("cpu_c"), "network_mbps": found.get("network")}
    if output["cpu_temperature_c"] is None:
        output["cpu_temperature_note"] = CPU_TEMP_MISSING
    return output


def _performance(_arguments, _context):
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(1)
    telemetry = pool.submit(_telemetry)   # its 1 s network sample overlaps the CPU sample below
    pool.shutdown(wait=False)
    kernel = ctypes.WinDLL("kernel32")
    memory = _MEMORYSTATUSEX(dwLength=ctypes.sizeof(_MEMORYSTATUSEX))
    kernel.GlobalMemoryStatusEx(ctypes.byref(memory))
    power = _POWER()
    kernel.GetSystemPowerStatus(ctypes.byref(power))
    output = {"cpu_percent": _cpu_percent(),
              "memory": {"used_percent": memory.dwMemoryLoad,
                         "used_gib": round((memory.ullTotalPhys - memory.ullAvailPhys) / 1024**3, 1),
                         "total_gib": round(memory.ullTotalPhys / 1024**3, 1)},
              "battery": None if power.BatteryFlag == 128 or power.BatteryLifePercent == 255 else {
                  "percent": power.BatteryLifePercent, "charging": power.ACLineStatus == 1}}
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                               "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, util, used, total, temp = [part.strip() for part in done.stdout.strip().split(",")[:5]]
        output["gpu"] = {"name": name, "utilization_percent": int(util), "memory_used_mib": int(used),
                         "memory_total_mib": int(total), "temperature_c": int(temp)}
    except (OSError, ValueError, subprocess.SubprocessError):
        output["gpu"] = None
    try:
        from chutku.tools.everyday import _powershell
        top = _powershell(r'''
$ErrorActionPreference='Stop'
@(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 6 | ForEach-Object {
  [pscustomobject]@{ name = $_.ProcessName; memory_mib = [int]($_.WorkingSet64 / 1MB) } }) | ConvertTo-Json -Compress
''', {}, timeout=10)
        output["top_memory_processes"] = top if isinstance(top, list) else [top]
    except OSError:
        output["top_memory_processes"] = None
    output.update(telemetry.result())
    return ToolResult(output, Verification.PASS)


# -- wallpaper ----------------------------------------------------------------------

_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp"}


def _wallpaper_path():
    buffer = ctypes.create_unicode_buffer(520)
    ctypes.WinDLL("user32").SystemParametersInfoW(0x73, len(buffer), buffer, 0)
    return buffer.value


def _wallpaper_status(_arguments, _context):
    return ToolResult({"path": _wallpaper_path()}, Verification.PASS)


def _validate_path_only(arguments):
    if set(arguments) != {"path"} or not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 1000:
        raise ValueError("Provide only path.")


def _wallpaper_set(arguments, context):
    target = sandbox_target(context.granted_root, arguments["path"])
    if not target.is_file() or target.suffix.casefold() not in _IMAGE_TYPES:
        return ToolResult({"error": "Choose an existing .jpg, .png or .bmp image."}, Verification.FAIL)
    before = _wallpaper_path()
    if not ctypes.WinDLL("user32").SystemParametersInfoW(0x14, 0, str(target), 0x3):
        return ToolResult({"error": "Windows refused the wallpaper."}, Verification.FAIL)
    after = _wallpaper_path()
    ok = os.path.normcase(after) == os.path.normcase(str(target))
    return ToolResult({"before": before, "after": after, "undo_hint": f"desktop.wallpaper_set path={before}"},
                      Verification.PASS if ok else Verification.FAIL)


# -- largest files ------------------------------------------------------------------

def _validate_largest(arguments):
    if set(arguments) - {"path", "count"} or not isinstance(arguments.get("path", "."), str):
        raise ValueError("Provide path and optional count.")
    if "count" in arguments and not (type(arguments["count"]) is int and 1 <= arguments["count"] <= 50):
        raise ValueError("count must be 1-50.")


def _largest(arguments, context):
    from chutku.tools.filesystem_extended import MAX_SEARCH_ENTRIES, MAX_SEARCH_SECONDS, _SKIP_RECURSION
    start = sandbox_target(context.granted_root, arguments.get("path", "."))
    if not start.is_dir():
        return ToolResult({"error": "Path is not an existing folder."}, Verification.FAIL)
    count, heap, scanned, pending = arguments.get("count", 10), [], 0, [start]
    deadline, stopped = time.monotonic() + MAX_SEARCH_SECONDS, None
    while pending and stopped is None:
        folder = pending.pop()
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for child in children:
            scanned += 1
            if scanned > MAX_SEARCH_ENTRIES or time.monotonic() > deadline:
                stopped = "limit"
                break
            try:
                if child.is_symlink() or getattr(child.lstat(), "st_file_attributes", 0) & 0x400:
                    continue
                if child.is_dir():
                    if child.name.casefold() not in _SKIP_RECURSION:
                        pending.append(child)
                else:
                    size = child.stat().st_size
                    item = (size, str(child))
                    heapq.heappush(heap, item) if len(heap) < count else heapq.heappushpop(heap, item)
            except OSError:
                continue
    files = [{"full_path": p, "size_mib": round(s / 1024**2, 1)} for s, p in sorted(heap, reverse=True)]
    output = {"files": files, "scanned": scanned, "complete": stopped is None}
    return ToolResult(output, Verification.PASS, {"count": len(files), "scanned": scanned})


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This tool takes no arguments.")


# -- registration -------------------------------------------------------------------

def register_desktop_controls(registry):
    desktop = ("interactive Windows desktop",)
    view_validate, view_run = _make_shortcut(VIEW_SHORTCUTS)
    edit_validate, edit_run = _make_shortcut(EDIT_SHORTCUTS)
    registry.register(Tool("keyboard.shortcut", "Send a view/navigation shortcut to the window the user is using "
        "(new/next/previous tab, refresh, back, forward, zoom, find, fullscreen, scroll, copy, select all, snap, "
        "show desktop, switch window, task manager, run, file explorer, Windows settings/search).",
        Risk.REVERSIBLE, view_run, view_validate, required_capability="desktop.input",
        argument_schema=_shortcut_schema(VIEW_SHORTCUTS), prerequisites=desktop, reversibility="transient",
        success_predicate="keys_delivered_to_exact_focused_window_or_window_change_observed"))
    registry.register(Tool("keyboard.edit", "Send an editing shortcut to the window the user is using: paste, cut, "
        "undo, redo, save, delete, backspace, close_tab.",
        Risk.DATA_MODIFICATION, edit_run, edit_validate, required_capability="desktop.input",
        argument_schema=_shortcut_schema(EDIT_SHORTCUTS), prerequisites=desktop, reversibility="transient",
        success_predicate="keys_delivered_to_exact_focused_window"))
    registry.register(Tool("keyboard.type_text", "Type text into the focused field of the window the user is using "
        "(one line; use keyboard.press_enter to submit).",
        Risk.DATA_MODIFICATION, _type_text, _validate_type, frozenset({"text"}), required_capability="desktop.input",
        argument_schema={"type": "object", "properties": {"text": {"type": "string", "minLength": 1,
                                                                   "maxLength": 1000}} | _WINDOW_ARGS,
                         "required": ["text"], "additionalProperties": False},
        prerequisites=desktop, reversibility="transient", success_predicate="text_typed_with_focus_kept"))
    registry.register(Tool("keyboard.press_enter", "Press Enter in the window the user is using (may submit or send).",
        Risk.EXTERNAL_SIDE_EFFECT, _press_enter, _validate_window, required_capability="desktop.input",
        argument_schema={"type": "object", "properties": dict(_WINDOW_ARGS), "additionalProperties": False},
        prerequisites=desktop, reversibility="none", success_predicate="enter_delivered_to_exact_focused_window"))
    registry.register(Tool("audio.volume", "Turn the volume up/down (step, default 10), set it (level 0-100), "
        "mute or unmute; reads the result back.",
        Risk.REVERSIBLE, _volume, _validate_volume, required_capability="audio.modify",
        argument_schema={"type": "object", "properties": {
            "action": {"type": "string", "enum": list(_VOLUME_ACTIONS)},
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
            "step": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["action"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="volume_read_back_matches_target"))
    registry.register(Tool("display.brightness_status", "Read the laptop screen brightness (0-100).",
        Risk.OBSERVATION, _brightness_status, _no_arguments,
        required_capability="settings.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="brightness_read"))
    registry.register(Tool("display.brightness", "Turn screen brightness up/down (step, default 10) or set it "
        "(level 0-100); reads the result back.",
        Risk.REVERSIBLE, _brightness, _validate_brightness, required_capability="settings.modify",
        argument_schema={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["up", "down", "set"]},
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
            "step": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["action"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="brightness_read_back_matches_target"))
    registry.register(Tool("system.lock", "Lock the PC (Windows sign-in screen).",
        Risk.REVERSIBLE, _lock, _no_arguments,
        required_capability="desktop.input", argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=desktop,
        reversibility="transient", success_predicate="input_desktop_is_no_longer_default"))
    registry.register(Tool("system.performance", "Show CPU %, RAM, GPU load/memory/temperature, battery and the "
        "programs using the most memory.",
        Risk.OBSERVATION, _performance, _no_arguments,
        required_capability="process.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="performance_counters_read"))
    registry.register(Tool("desktop.wallpaper_status", "Show the current desktop wallpaper file.",
        Risk.OBSERVATION, _wallpaper_status, _no_arguments,
        required_capability="settings.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="wallpaper_path_read"))
    registry.register(Tool("desktop.wallpaper_set", "Set the desktop wallpaper to an image file (.jpg/.png/.bmp); "
        "the previous wallpaper is returned for undo.",
        Risk.REVERSIBLE, _wallpaper_set, _validate_path_only, resource_access="observe",
        required_capability="settings.modify",
        argument_schema={"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}},
                         "required": ["path"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="wallpaper_read_back_matches_file"))
    registry.register(Tool("filesystem.largest", "List the biggest files under a folder (count default 10).",
        Risk.OBSERVATION, _largest, _validate_largest, resource_access="observe",
        argument_schema={"type": "object", "properties": {"path": {"type": "string", "maxLength": 1000},
                                                          "count": {"type": "integer", "minimum": 1, "maximum": 50}},
                         "additionalProperties": False},
        reversibility="not_applicable", success_predicate="bounded_size_scan_completed"))
