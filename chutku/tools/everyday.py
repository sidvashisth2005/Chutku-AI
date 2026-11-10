"""Everyday desktop actions: installed apps, files, web, windows and media.

Every action binds an exact target (Start-menu AppID, granted file path,
validated http(s) URL, HWND+PID+executable, current media session) and is
verified by re-observing the desktop afterwards. No shell strings are built.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import quote_plus, urlsplit

from chutku.core.paths import sandbox_target
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

LAUNCH_WAIT_SECONDS = 15
_UNINSTALL = re.compile(r"\b(?:uninstall|unins\d*|uninst|remove)\b", re.IGNORECASE)
BLOCKED_OPEN_EXTENSIONS = frozenset({
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".msi", ".msp", ".msc", ".lnk", ".scr", ".pif", ".reg", ".hta", ".jar", ".cpl", ".dll", ".sys", ".inf",
    ".application", ".appref-ms", ".url", ".gadget", ".msix", ".appx", ".appinstaller", ".ocx", ".sct",
})
SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "bing": "https://www.bing.com/search?q={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
    "maps": "https://www.google.com/maps/search/{}",
    "github": "https://github.com/search?q={}",
    "flights": "https://www.google.com/travel/flights?q={}",
    "amazon": "https://www.amazon.in/s?k={}",
    "flipkart": "https://www.flipkart.com/search?q={}",
    "images": "https://www.bing.com/images/search?q={}",
}


# -- helpers ------------------------------------------------------------------

def _powershell(script, request, timeout=12):
    if sys.platform != "win32":
        raise OSError("This action requires Windows.")
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                               input=json.dumps(request), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or len(completed.stdout) > 2_000_000:
        raise OSError("A fixed Windows query failed.")
    try:
        # Windows PowerShell 5.1 can emit raw control characters inside JSON strings.
        return json.loads(completed.stdout.lstrip("\ufeff") or "null", strict=False)
    except json.JSONDecodeError as error:
        raise OSError("A fixed Windows query returned invalid output.") from error


_START_APPS = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
@(Get-StartApps | ForEach-Object { [pscustomobject]@{ name = [string]$_.Name; app_id = [string]$_.AppID } }) |
    ConvertTo-Json -Compress
'''


_APPS_CACHE = {"apps": None, "at": 0.0, "refreshing": False}
_APPS_LOCK = threading.Lock()
APPS_FRESH_SECONDS = 300


def start_apps(fresh=False):
    """The Start-menu app list. Reading it costs ~1.5 s, so a copy is kept: older than 5 minutes it is
    still returned at once and refreshed in the background. fresh=True always reads it now (used when a
    name was not found, so a just-installed app is never missed)."""
    with _APPS_LOCK:
        apps, age = _APPS_CACHE["apps"], time.monotonic() - _APPS_CACHE["at"]
        stale = apps is not None and age > APPS_FRESH_SECONDS and not _APPS_CACHE["refreshing"]
        if stale:
            _APPS_CACHE["refreshing"] = True
    if apps is None or fresh:
        return _refresh_apps()
    if stale:
        threading.Thread(target=_refresh_apps, name="chutku-apps-refresh", daemon=True).start()
    return apps


def _refresh_apps():
    try:
        apps = _read_start_apps()
        with _APPS_LOCK:
            _APPS_CACHE.update(apps=apps, at=time.monotonic())
        return apps
    finally:
        with _APPS_LOCK:
            _APPS_CACHE["refreshing"] = False


def _read_start_apps():
    rows = _powershell(_START_APPS, {}, timeout=20)
    rows = rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else []
    return [{"name": r["name"], "app_id": r["app_id"]} for r in rows
            if isinstance(r, dict) and isinstance(r.get("name"), str) and isinstance(r.get("app_id"), str)
            and r["name"] and r["app_id"]]


class Desktop:
    """Top-level window observation by OS identity."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Window control requires a Windows desktop session.")
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        for library, name, args, result in [
            (self.u, "EnumWindows", [self.callback, w.LPARAM], w.BOOL),
            (self.u, "IsWindow", [w.HWND], w.BOOL),
            (self.u, "IsWindowVisible", [w.HWND], w.BOOL),
            (self.u, "IsIconic", [w.HWND], w.BOOL),
            (self.u, "IsZoomed", [w.HWND], w.BOOL),
            (self.u, "GetWindowTextW", [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.u, "GetWindowThreadProcessId", [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            (self.u, "GetForegroundWindow", [], w.HWND),
            (self.u, "ShowWindowAsync", [w.HWND, ctypes.c_int], w.BOOL),
            (self.u, "PostMessageW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            (self.u, "GetWindow", [w.HWND, w.UINT], w.HWND),
            (self.u, "GetWindowRect", [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.u, "SetWindowPos", [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      w.UINT], w.BOOL),
            (self.u, "MonitorFromWindow", [w.HWND, w.DWORD], w.HMONITOR),
            (self.k, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self.k, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.k, "CloseHandle", [w.HANDLE], w.BOOL),
        ]:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result

    def image(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            text = ctypes.create_unicode_buffer(32768)
            size = w.DWORD(len(text))
            return text.value if self.k.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)) else None
        finally:
            self.k.CloseHandle(handle)

    def describe(self, hwnd):
        text = ctypes.create_unicode_buffer(513)
        self.u.GetWindowTextW(hwnd, text, len(text))
        pid = w.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {"window_id": int(hwnd), "process_id": pid.value, "title": text.value,
                "executable": self.image(pid.value), "minimized": bool(self.u.IsIconic(hwnd)),
                "maximized": bool(self.u.IsZoomed(hwnd))}

    def windows(self, limit=150):
        found = []

        @self.callback
        def collect(hwnd, _):
            # Visible, titled, unowned top-level windows are what users call "windows".
            if self.u.IsWindowVisible(hwnd) and not self.u.GetWindow(hwnd, 4):
                text = ctypes.create_unicode_buffer(2)
                if self.u.GetWindowTextW(hwnd, text, 2):
                    found.append(int(hwnd))
            return len(found) < limit

        self.u.EnumWindows(collect, 0)
        return found

    def foreground(self):
        return int(self.u.GetForegroundWindow() or 0)

    def exact(self, window_id, process_id, executable):
        if type(window_id) is not int or not self.u.IsWindow(window_id) or not self.u.IsWindowVisible(window_id):
            return None
        info = self.describe(window_id)
        try:
            same = info["executable"] is not None and \
                Path(info["executable"]).resolve() == Path(executable).resolve()
        except OSError:
            same = False
        return info if info["process_id"] == process_id and same else None


def _titles(desktop):
    return {hwnd: desktop.describe(hwnd)["title"] for hwnd in desktop.windows()}


def _await_new_window(desktop, before_windows, before_foreground, *, expect_executable=None, before_titles=None):
    """Poll for a new top-level window, a changed foreground window or (for an
    existing browser receiving a new tab) a changed title of an expected window."""
    deadline = time.monotonic() + LAUNCH_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.25)
        current = desktop.windows()
        new = [hwnd for hwnd in current if hwnd not in before_windows]
        foreground = desktop.foreground()
        candidates = new + ([foreground] if foreground and foreground != before_foreground else [])
        if before_titles is not None:
            candidates += [hwnd for hwnd in current if hwnd in before_titles]
        for hwnd in candidates:
            info = desktop.describe(hwnd)
            if not info["title"]:
                continue
            if expect_executable and (info["executable"] or "").casefold() != expect_executable.casefold():
                continue
            if hwnd in new:
                return info, "new_window"
            if hwnd == foreground and hwnd != before_foreground:
                return info, "foreground_changed"
            if before_titles is not None and before_titles.get(hwnd) != info["title"]:
                return info, "window_title_changed"
    return None, None


def _window_verifier(_arguments, result, _context):
    """Independent re-observation: the reported window must still exist and be visible."""
    window = result.output.get("window") or {}
    desktop = Desktop()
    if not window or not desktop.exact(window.get("window_id"), window.get("process_id"), window.get("executable") or ""):
        return ToolResult(result.output | {"error": "The window seen after launch is no longer present."},
                          Verification.UNKNOWN, result.audit_output)
    return ToolResult(result.output, Verification.PASS, result.audit_output)


def _launched(output, info, how):
    output = output | {"window": {k: info[k] for k in ("window_id", "process_id", "executable", "title")},
                       "observed": how}
    return ToolResult(output, Verification.UNKNOWN,
                      output | {"window": {"process_id": info["process_id"], "title": "[REDACTED]"}})


# -- apps -------------------------------------------------------------------------

_INSTALLED_SCHEMA = {"type": "object", "properties": {"query": {"type": "string", "maxLength": 80}},
                     "additionalProperties": False}
_LAUNCH_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "minLength": 1, "maxLength": 120},
    "app_id": {"type": "string", "minLength": 1, "maxLength": 400},
    "background": {"type": "boolean"}}, "additionalProperties": False}


def _validate_installed(arguments):
    if set(arguments) - {"query"} or not isinstance(arguments.get("query", ""), str) or len(arguments.get("query", "")) > 80:
        raise ValueError("Provide an optional query of at most 80 characters.")


def _validate_launch(arguments):
    if not isinstance(arguments.get("background", False), bool):
        raise ValueError("background must be true or false.")
    target = {k: v for k, v in arguments.items() if k != "background"}
    if len(target) != 1 or not set(target) <= {"name", "app_id"}:
        raise ValueError("Provide exactly one of name or app_id from the installed-app list.")
    value = next(iter(target.values()))
    if not isinstance(value, str) or not value.strip() or len(value) > 400:
        raise ValueError("The app name or app_id is invalid.")


def _installed(arguments, _context):
    query = arguments.get("query", "").casefold().strip()
    def matching(source):
        found = [a for a in source if not _UNINSTALL.search(a["name"]) and not _UNINSTALL.search(a["app_id"])]
        return [a for a in found if query in a["name"].casefold()] if query else found
    apps = matching(start_apps())
    if query and not apps:
        apps = matching(start_apps(fresh=True))  # "not installed" is only said after a fresh look
    apps.sort(key=lambda a: a["name"].casefold())
    return ToolResult({"query": arguments.get("query", ""), "apps": apps[:60], "count": len(apps),
                       "truncated": len(apps) > 60}, Verification.PASS,
                      {"count": len(apps)})


_FILLER_WORDS = {"browser", "app", "application", "software", "program", "the", "my", "wala", "wali", "waala",
                 # spoken Hinglish around a name (owner's convos 2026-11-10: "Ato mera brave open kar")
                 "ato", "arre", "are", "mera", "meri", "mere", "apna", "apni", "yaar", "zara", "jara", "please", "pls",
                 "open", "kholo", "khol", "kar", "karo", "do", "de", "chalao", "start", "launch"}


def _closest_app(said, apps, cutoff=0.66):
    """Apps whose name (or first word) is closest to what was said, when one is clearly ahead of the rest."""
    import difflib
    scores = []
    for app in apps:
        name = " ".join(app["name"].casefold().split())
        first = (re.findall(r"[a-z0-9+]+", name) or [""])[0]
        scores.append((max(difflib.SequenceMatcher(None, said, name).ratio(),
                           difflib.SequenceMatcher(None, said, first).ratio()), app))
    scores.sort(key=lambda item: -item[0])
    if not scores or scores[0][0] < cutoff or (len(scores) > 1 and scores[1][0] >= scores[0][0] - 0.05):
        return []
    return [scores[0][1]]


def resolve_app(arguments, apps):
    """Bind a request to exactly one Start-menu entry; never a free-form command."""
    if "app_id" in arguments:
        matches = [a for a in apps if a["app_id"] == arguments["app_id"]]
    else:
        wanted = " ".join(arguments["name"].casefold().split())
        wanted = {"vs code": "visual studio code", "vscode": "visual studio code", "ms word": "word",
                  "ms excel": "excel", "powerpoint": "powerpoint"}.get(wanted, wanted)   # spoken short names
        matches = [a for a in apps if " ".join(a["name"].casefold().split()) == wanted]
        if not matches:
            matches = [a for a in apps if wanted in a["name"].casefold()]
        if not matches:  # "brave browser" -> Brave: drop filler words, then every word of the app name must be said
            said = [w for w in re.findall(r"[a-z0-9+]+", wanted) if w not in _FILLER_WORDS]
            stripped = " ".join(said)
            matches = [a for a in apps if stripped and " ".join(a["name"].casefold().split()) == stripped] or \
                [a for a in apps if (words := re.findall(r"[a-z0-9+]+", a["name"].casefold()))
                 and set(words) <= set(said) and len(words) >= len(said) - 1]
        if not matches and said:   # every word of one app's name was said, among other words ("ato mera brave")
            matches = [a for a in apps if (words := re.findall(r"[a-z0-9+]+", a["name"].casefold()))
                       and set(words) <= set(said)]
        if not matches and said:   # a misheard name ("sport" -> Spotify): the one clearly closest app, never a tie
            matches = _closest_app(" ".join(said), apps)
    unique = {a["app_id"]: a for a in matches}
    if len(unique) != 1:
        names = sorted({a["name"] for a in matches})[:8]
        raise ValueError(("Several installed apps match: " + ", ".join(names) + ". Name one exactly.")
                         if names else "No installed app matches that name. Use apps.installed to look it up.")
    app = next(iter(unique.values()))
    if _UNINSTALL.search(app["name"]) or _UNINSTALL.search(app["app_id"]):
        raise ValueError("Uninstallers are not launched by Chutku.")
    if app["app_id"].casefold().startswith(("http:", "https:")) or app["app_id"].casefold().endswith(".url"):
        raise ValueError("That Start-menu entry is a web link; use web.open instead.")
    return app


_SEARCH_HOSTS = {"searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe"}
_SEARCH_HEADER = re.compile(r"^(best match|apps?|folders?|documents?|search the web|settings|photos|videos|music|"
                            r"people|email|websites?|system)(?:\s+\d+\+?)?$", re.I)
_APP_SECTIONS = {"best match", "app", "apps"}


def _plain(text):
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def search_results(lines, rect):
    """Result names from a Windows search window, in the order shown, from the "Best match" and "Apps" sections
    only (never web results, folders, documents or the right-hand pane's buttons)."""
    left, top, right, _bottom = rect
    column = sorted((line for line in lines if line["rect"][0] < left + (right - left) * 0.5),
                    key=lambda line: line["rect"][1])
    names, section = [], None
    for line in column:
        text = line["text"].strip()
        header = _SEARCH_HEADER.match(text)
        if header:
            section = header.group(1).casefold()
            continue
        if section in _APP_SECTIONS and len(text) > 1:
            names.append(text)
    return names


def related(query, app_name):
    """Does the app name plausibly mean what was asked? A query word starts an app word ("calc" -> Calculator,
    "code" -> Visual Studio Code), or the query is the app's initials ("vs" -> Visual Studio). Windows search
    also returns loosely related things (Control Panel for "uninstall"); those are not opened."""
    asked = [w for w in re.findall(r"[a-z0-9]+", query.casefold()) if w not in {"app", "the", "my", "open"}]
    words = re.findall(r"[a-z0-9]+", app_name.casefold())
    initials = "".join(w[0] for w in words)
    return any(len(a) >= 2 and (any(w.startswith(a) for w in words) or initials.startswith(a)) for a in asked)


def pick_search_result(names, apps, query=None):
    """The first result (top, then 2nd, 3rd...) that is exactly an installed Start-menu app (and, given the
    query, plausibly the app that was asked for)."""
    by_name = {}
    for app in apps:
        if not _UNINSTALL.search(app["name"]) and not _UNINSTALL.search(app["app_id"]):
            by_name.setdefault(_plain(app["name"]), app)
    for name in names:
        variants = [name]
        first, _, rest = name.partition(" ")
        if len(first) == 1 and rest:
            variants.append(rest)                                   # OCR read the result's icon as a letter
        for variant in variants:
            app = by_name.get(_plain(variant))
            if app is not None and (query is None or related(query, app["name"])):
                return app
    return None


def search_start_menu(name, apps):
    """Ask Windows search for ``name`` like the owner would (Win key, type, read the results) and return the first
    result that is an installed app. Types only into Windows' own search box: if that box is not in front, nothing
    is typed."""
    from chutku import vision
    from chutku.tools.desktop_controls import press_combo, type_unicode
    if _UNINSTALL.search(name):
        raise ValueError("Uninstallers are not launched by Chutku.")
    desktop = Desktop()
    press_combo([0x5B])                                             # Win: open Start / search
    deadline, info = time.monotonic() + 2.5, None
    while time.monotonic() < deadline:
        time.sleep(0.15)
        candidate = desktop.describe(desktop.foreground())
        if Path(candidate.get("executable") or "").name.casefold() in _SEARCH_HOSTS:
            info = candidate
            break
    if info is None:
        raise ValueError("Windows search did not open, so nothing was typed. Try again, or say the app's full name.")
    try:
        type_unicode(name)
        box = w.RECT()
        names = []
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            time.sleep(0.4)                                         # results arrive while Windows searches
            if Path(desktop.describe(desktop.foreground()).get("executable") or "").name.casefold() not in _SEARCH_HOSTS:
                raise ValueError("Windows search closed before showing results; nothing was opened.")
            with vision.dpi_aware() as user32:
                user32.GetWindowRect(desktop.foreground(), ctypes.byref(box))
            rect = (box.left, box.top, box.right, box.bottom)
            names = search_results(vision.read_lines(vision.capture(), rect), rect)
            app = pick_search_result(names, apps, name)
            if app is not None:
                return app
        shown = ", ".join(names[:5]) or "no apps"
        raise ValueError(f"Windows search for '{name}' showed {shown}, and none of those is an installed app.")
    finally:
        press_combo([0x1B])                                         # Esc: close search before launching


def _browser_key(app_name):
    name = app_name.casefold()
    return next((key for key in ("brave", "chrome", "edge", "firefox") if key in name), None)


SINGLE_INSTANCE = {"spotify", "whatsapp", "telegram", "discord", "steam", "zoom", "slack", "teams", "signal"}


def _first_word(name):
    return (re.findall(r"[a-z0-9]+", name.casefold()) or [""])[0]


def open_app_window(desktop, name):
    """A visible, titled window of the named app (its program file starts with the app's first word), or None."""
    word = _first_word(name)
    if len(word) < 3:
        return None
    for hwnd in desktop.windows():
        info = desktop.describe(hwnd)
        if info.get("title") and Path(info.get("executable") or "").stem.casefold().startswith(word):
            return info
    return None


def existing_browser_window(desktop, key):
    """An open window of that browser (the owner's, not a new one), preferring one that is not minimized."""
    exe = BROWSERS[key][0]
    windows = [desktop.describe(hwnd) for hwnd in desktop.windows()]
    mine = [info for info in windows if Path(info.get("executable") or "").name.casefold() == exe and info.get("title")]
    mine.sort(key=lambda info: bool(info.get("minimized")))
    return mine[0] if mine else None


def _launch(arguments, _context):
    background = arguments.get("background") is True
    arguments = {k: v for k, v in arguments.items() if k != "background"}
    found_via = "start_menu"
    try:
        app = resolve_app(arguments, start_apps())
    except ValueError:
        apps = start_apps(fresh=True)                               # maybe installed since the last look
        try:
            app = resolve_app(arguments, apps)
        except ValueError as error:
            if "name" not in arguments:
                raise
            try:  # like the owner would: Windows search, then the 1st/2nd/3rd result that is an app
                app, found_via = search_start_menu(arguments["name"], apps), "windows_search"
            except (ValueError, OSError) as search_error:
                raise ValueError(f"{error} {search_error}") from search_error
    desktop = Desktop()
    key = _browser_key(app["name"])
    if key is not None:
        # A browser that is already open is brought to the front, not opened again: starting it as an app always
        # makes another window (owner, 2026-10-04: "use the already open Brave"). Pages open as new tabs in it.
        window = existing_browser_window(desktop, key)
        if window is not None:
            from chutku.tools.windows_apps import WindowsDesktop
            WindowsDesktop().focus(window["window_id"])
            return _launched({"app": app["name"], "app_id": app["app_id"], "found_via": found_via,
                              "reused_open_window": True}, window, "already_open_focused")
    running = open_app_window(desktop, app["name"])
    if background:
        return _launch_behind(desktop, app, found_via, running)
    if running is not None and _first_word(app["name"]) in SINGLE_INSTANCE:
        # Spotify, WhatsApp, Telegram...: one window only. Starting it again shows no new window and Windows keeps
        # it behind, so "Open sport" waited 15 s and failed (live 2026-11-10): bring the open one to the front.
        from chutku.tools.windows_apps import WindowsDesktop
        WindowsDesktop().focus(running["window_id"])
        return _launched({"app": app["name"], "app_id": app["app_id"], "found_via": found_via,
                          "reused_open_window": True}, running, "already_open_focused")
    before, foreground = set(desktop.windows()), desktop.foreground()
    explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
    subprocess.Popen([str(explorer), "shell:AppsFolder\\" + app["app_id"]], shell=False,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info, how = _await_new_window(desktop, before, foreground)
    if info is None and running is not None:   # it was already open: that window is the app the owner asked for
        from chutku.tools.windows_apps import WindowsDesktop
        WindowsDesktop().focus(running["window_id"])
        info, how = running, "already_open_focused"
    if info is None:
        return ToolResult({"app": app["name"], "error": "Launch was requested but no new or foreground window "
                           f"appeared within {LAUNCH_WAIT_SECONDS} seconds."}, Verification.FAIL)
    output = {"app": app["name"], "app_id": app["app_id"], "found_via": found_via}
    # Owner 2026-11-07: "open WhatsApp" from the phone opened it behind other windows. A request that did not start
    # with a key or click at this PC cannot take the foreground on its own; WindowsDesktop.focus gets past that.
    from chutku.tools.windows_apps import WindowsDesktop
    try:
        WindowsDesktop().focus(info["window_id"])
        output["in_front"] = desktop.foreground() == info["window_id"]
    except OSError:
        output["in_front"] = False
    info = _fresh_document(desktop, info, output)
    return _launched(output, info, how)


def _launch_behind(desktop, app, found_via, running):
    """Background Desk: the app is only a means for a task, so it opens BEHIND the owner's window (or an open one is
    reused there) and he keeps typing undisturbed. Later steps act on it through desktop.look/desktop.do."""
    from chutku import background_desk

    def windows():
        # agent-desktop's list: the frame Windows shows (ApplicationFrameHost for Store apps). Our own enumeration
        # also returns a Store app's inner CalculatorApp.exe window, and parking that one broke it (live 2026-11-10).
        from chutku.tools.desktop import call
        return [desktop.describe(int(item["id"].split("-")[1])) for item in call("list-windows")
                if item.get("visible", True) and str(item.get("id", "")).startswith("w-")]
    output = {"app": app["name"], "app_id": app["app_id"], "found_via": found_via, "background": True}
    word = _first_word(app["name"])
    running = next((info for info in windows() if info.get("title") and (
        info["title"].casefold() == app["name"].casefold()
        or Path(info.get("executable") or "").stem.casefold().startswith(word))), None)
    if running is not None:
        background_desk.park(running["window_id"])
        return _launched(output | {"reused_open_window": True}, running, "already_open_behind")
    info, steals = background_desk.launch(app["app_id"], windows)
    output["focus_taken_and_given_back"] = len(steals)
    if info is None:
        return ToolResult({**output, "error": "The app did not show a window behind yours within 20 seconds."},
                          Verification.FAIL)
    return _launched(output, info, "opened_behind")


_BLANK_TAB_EDITORS = {"notepad.exe"}  # editors that reopen the user's previous files at start


def _fresh_document(desktop, info, output):
    """Notepad restores the user's last files on start. Open a new blank tab so new text never lands in
    one of the user's documents (Ctrl+N only adds a tab; it changes no file)."""
    from chutku.tools.desktop_controls import _DOCUMENT_TITLE, press_combo
    from chutku.tools.windows_apps import WindowsDesktop
    if Path(info.get("executable") or "").name.casefold() not in _BLANK_TAB_EDITORS:
        return info
    deadline = time.monotonic() + 3.0  # restored tabs appear a moment after the window
    while True:
        time.sleep(0.4)
        current = desktop.describe(info["window_id"])
        if _DOCUMENT_TITLE.match(current["title"] or ""):
            break
        if time.monotonic() > deadline:
            return current
    WindowsDesktop().focus(info["window_id"])
    time.sleep(0.3)
    if desktop.foreground() == info["window_id"]:
        press_combo([0x11, 0x4E])  # Ctrl+N: new blank tab
        time.sleep(1.0)
    current = desktop.describe(info["window_id"])
    output["opened_blank_document"] = not _DOCUMENT_TITLE.match(current["title"] or "")
    if not output["opened_blank_document"]:
        output["warning"] = "The window shows an existing document; do not type into it."
    return current


# -- files ------------------------------------------------------------------------

def _validate_path(arguments):
    if set(arguments) != {"path"} or not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 1000:
        raise ValueError("Provide only path.")


def _open_file(arguments, context):
    target = sandbox_target(context.granted_root, arguments["path"])
    if not target.exists():
        return ToolResult({"error": "That file or folder does not exist."}, Verification.FAIL)
    if target.is_file() and target.suffix.casefold() in BLOCKED_OPEN_EXTENSIONS:
        return ToolResult({"error": "Chutku does not open programs, scripts, shortcuts or installers this way."},
                          Verification.FAIL)
    desktop = Desktop()
    before, foreground = set(desktop.windows()), desktop.foreground()
    os.startfile(str(target))  # default handler; no command line is composed
    info, how = _await_new_window(desktop, before, foreground)
    if info is None:
        return ToolResult({"path": str(target), "error": "No window showed the file within "
                           f"{LAUNCH_WAIT_SECONDS} seconds."}, Verification.FAIL)
    return _launched({"path": str(target), "kind": "folder" if target.is_dir() else "file"}, info, how)


# -- web --------------------------------------------------------------------------

_BROWSER_ARG = {"browser": {"type": "string", "enum": ["brave", "chrome", "edge", "firefox"]},
                "tab": {"type": "string", "enum": ["auto", "new", "same"]}}
TABS = ("auto", "new", "same")
_URL_SCHEMA = {"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}} | _BROWSER_ARG,
               "required": ["url"], "additionalProperties": False}
_SEARCH_SCHEMA = {"type": "object", "properties": {
    "query": {"type": "string", "minLength": 1, "maxLength": 300},
    "site": {"type": "string", "enum": sorted(SEARCH_ENGINES)}} | _BROWSER_ARG, "required": ["query"],
    "additionalProperties": False}


def _check_browser(arguments):
    if "browser" in arguments and arguments["browser"] not in ("brave", "chrome", "edge", "firefox"):
        raise ValueError("browser must be brave, chrome, edge or firefox.")
    if "tab" in arguments and arguments["tab"] not in TABS:
        raise ValueError("tab must be auto, new or same.")


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 33 or c in "<>\"`{}|\\^" for c in url):
        raise ValueError("Provide one plain http(s) URL without spaces.")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only http(s) URLs with a host and no embedded credentials are opened.")
    return url


def _validate_url(arguments):
    if "url" not in arguments or set(arguments) - {"url", "browser", "tab"}:
        raise ValueError("Provide url and optional browser and tab.")
    _check_browser(arguments)
    validate_url(arguments["url"])


def _validate_search(arguments):
    if set(arguments) - {"query", "site", "browser", "tab"} or "query" not in arguments:
        raise ValueError("Provide query and optional site, browser and tab.")
    _check_browser(arguments)
    if not isinstance(arguments["query"], str) or not 1 <= len(arguments["query"].strip()) <= 300:
        raise ValueError("query must contain 1 to 300 characters.")
    if arguments.get("site", "google") not in SEARCH_ENGINES:
        raise ValueError("Unsupported search site.")


def default_browser():
    """Ask Windows which executable handles https (what ShellExecute will actually use)."""
    try:
        query = ctypes.WinDLL("shlwapi").AssocQueryStringW
    except OSError:
        return None
    query.argtypes = [w.DWORD, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    query.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(1024)
    size = w.DWORD(len(buffer))
    if query(0, 2, "https", "open", buffer, ctypes.byref(size)) != 0:  # ASSOCSTR_EXECUTABLE
        return None
    return buffer.value or None


BROWSERS = {  # name -> (exe file name, usual install folders under Program Files / LocalAppData)
    "brave": ("brave.exe", (r"BraveSoftware\Brave-Browser\Application",)),
    "chrome": ("chrome.exe", (r"Google\Chrome\Application",)),
    "edge": ("msedge.exe", (r"Microsoft\Edge\Application",)),
    "firefox": ("firefox.exe", (r"Mozilla Firefox",)),
}


def browser_exe(name):
    """Full path of an installed browser (App Paths registry, then the usual install folders), or None."""
    if name not in BROWSERS or sys.platform != "win32":
        return None
    exe, folders = BROWSERS[name]
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe) as key:
                path = winreg.QueryValueEx(key, None)[0].strip('"')
                if Path(path).is_file():
                    return path
        except OSError:
            continue
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        for folder in folders:
            candidate = Path(root or "") / folder / exe
            if root and candidate.is_file():
                return str(candidate)
    return None


def preferred_browser():
    """The owner's browser for web tools (dashboard setting; Brave since 2026-10-04)."""
    from chutku.core.preferences import Preferences
    try:
        from chutku.core.paths import home
        return Preferences(home()).load().get("browser", "brave")
    except (OSError, ValueError):
        return "brave"


# The tab Chutku opened last. Owner (2026-10-05): "search lofi songs on youtube", then "search Latent season 2 on
# youtube" must use that same tab, not a new one, unless the owner asks for a new tab. The owner's own tabs are never
# overwritten: the tab is reused only while it is still the one showing (same window, same title as Chutku left it).
LAST_TAB = {"window_id": None, "title": None, "executable": None, "at": 0.0}
TAB_MEMORY_SECONDS = 3 * 3600


def _reusable_tab(desktop, exe, tab):
    """The browser window whose showing tab may be navigated in place, or None (then a new tab is opened)."""
    if tab == "new" or not exe:
        return None
    if LAST_TAB["window_id"] and time.monotonic() - LAST_TAB["at"] <= TAB_MEMORY_SECONDS:
        info = desktop.describe(LAST_TAB["window_id"])
        if info and info.get("title") and (info.get("executable") or "").casefold() == (exe or "").casefold():
            if tab == "same" or info["title"] == LAST_TAB["title"]:
                return info
    if tab == "same":   # the owner said "isi tab mein": the browser's current tab, even if Chutku did not open it
        key = _browser_key(Path(exe).stem)
        return existing_browser_window(desktop, key) if key else None
    return None


FOLLOW_SECONDS = 12


def page_tokens(url):
    """Words a tab title shows for this page: the site's name and, for searches, the query words."""
    from urllib.parse import parse_qs
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.").split(".")[0]
    words = {host} if len(host) > 2 else set()
    for values in parse_qs(parts.query).values():
        for value in values:
            words |= {w.casefold() for w in re.findall(r"\w{3,}", value)}
    return words


def _remember_tab(desktop, info, url=""):
    """Remember the tab now and keep following its renames in the background (live 2026-10-05: YouTube went
    "youtube.com/results…" → "YouTube" → "lofi songs - YouTube" and the second search did not match). A rename is
    followed only while the title still belongs to this page; anything else (the owner switched to their own tab) ends
    the following, so an owner's tab is never mistaken for Chutku's. Opening a site is never slowed down."""
    LAST_TAB.update(window_id=info["window_id"], executable=info.get("executable"), at=time.monotonic(),
                    title=info.get("title"))
    stamp, tokens = LAST_TAB["at"], page_tokens(url)

    def follow():
        deadline = time.monotonic() + FOLLOW_SECONDS
        while time.monotonic() < deadline and LAST_TAB["at"] == stamp:
            time.sleep(0.4)
            try:
                title = (desktop.describe(info["window_id"]) or {}).get("title")
            except Exception:
                return
            if not title or title == LAST_TAB["title"]:
                continue
            if tokens and not any(token in title.casefold() for token in tokens):
                return        # not this page any more: stop following, keep the last name that was
            if LAST_TAB["at"] == stamp:
                LAST_TAB["title"] = title
    threading.Thread(target=follow, name="chutku-tab-title", daemon=True).start()


def _navigate_in_place(desktop, info, url):
    """Ctrl+L, the URL, Enter in the browser's showing tab. Returns the window info once its title changed, or None."""
    from chutku.tools.desktop_controls import press_combo, type_unicode
    from chutku.tools.windows_apps import WindowsDesktop
    WindowsDesktop().focus(info["window_id"])
    time.sleep(0.4)
    if desktop.foreground() != info["window_id"]:
        return None          # never type unless that browser window is really in front
    before = info.get("title")
    press_combo([0x11, 0x4C])            # Ctrl+L: the address bar of the current tab
    time.sleep(0.2)
    type_unicode(url)
    time.sleep(0.1)
    press_combo([0x0D])
    deadline = time.monotonic() + LAUNCH_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.25)
        now = desktop.describe(info["window_id"])
        if now and now.get("title") and now["title"] != before:
            return now
    return None


def _open_url(url, browser=None, tab="auto"):
    choice = browser or preferred_browser()
    exe = browser_exe(choice) if choice != "default" else None
    note = None
    if exe is None:
        if choice != "default":
            note = f"{choice.capitalize()} was not found, so the Windows default browser was used."
        exe = default_browser()
    desktop = Desktop()
    reuse = _reusable_tab(desktop, exe, tab) if choice != "default" and note is None else None
    if reuse is not None:
        info = _navigate_in_place(desktop, reuse, url)
        if info is not None:
            _remember_tab(desktop, info, url)
            return _launched({"url": url, "host": urlsplit(url).hostname, "browser": exe, "tab": "same"}, info,
                             "same_tab_navigated")
        if tab == "same":
            return ToolResult({"error": "Could not use the current browser tab (the browser did not come to the "
                                        "front); nothing was typed.", "host": urlsplit(url).hostname},
                              Verification.FAIL)
    before, foreground = set(desktop.windows()), desktop.foreground()
    titles = _titles(desktop) if exe else None
    if exe and choice != "default" and note is None:
        from chutku.core.launch import popen_user_app
        popen_user_app([exe, url], shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.startfile(url)  # default handler; no command line is composed
    info, how = _await_new_window(desktop, before, foreground, expect_executable=exe, before_titles=titles)
    host = urlsplit(url).hostname
    if info is None:
        return ToolResult({"host": host, "error": "The browser did not show a window within "
                           f"{LAUNCH_WAIT_SECONDS} seconds."}, Verification.FAIL, {"host": host})
    output = {"url": url, "host": host, "browser": exe, "tab": "new"}
    if note:
        output["note"] = note
    _remember_tab(desktop, info, url)
    return _launched(output, info, how)


def _validate_spotify(arguments):
    if set(arguments) != {"query"} or not isinstance(arguments["query"], str) \
            or not 1 <= len(arguments["query"].strip()) <= 200:
        raise ValueError("Give the song, artist or playlist to search for (1-200 characters).")


def _spotify_search(arguments, _context):
    """Open Spotify's own search for the words ("spotify pe arijit singh chalao"); press play on the result."""
    desktop = Desktop()
    os.startfile("spotify:search:" + quote_plus(arguments["query"].strip()).replace("+", "%20"))  # Spotify's link
    # Success only when Spotify itself is in front: on 2026-10-04 the first launch ran Spotify's own updater
    # ("Spotify Installer"), which must not count as the search being open.
    deadline, info = time.monotonic() + 20, None
    while time.monotonic() < deadline:
        time.sleep(0.4)
        current = desktop.describe(desktop.foreground())
        if Path(current.get("executable") or "").name.casefold() == "spotify.exe" and current.get("title"):
            info = current
            break
    if info is None:
        return ToolResult({"error": "Spotify did not come up with its search (it may be updating; try again in a "
                                    "minute)."}, Verification.FAIL)
    return _launched({"query": arguments["query"], "app": "Spotify"}, info, "spotify_in_front")


def _web_open(arguments, _context):
    return _open_url(validate_url(arguments["url"]), arguments.get("browser"), arguments.get("tab", "auto"))


def _web_search(arguments, _context):
    site = arguments.get("site", "google")
    return _open_url(SEARCH_ENGINES[site].format(quote_plus(arguments["query"].strip())), arguments.get("browser"),
                     arguments.get("tab", "auto"))


# -- windows ----------------------------------------------------------------------

_WINDOW_IDENTITY = {"window_id": {"type": "integer", "minimum": 1}, "process_id": {"type": "integer", "minimum": 1},
                    "executable": {"type": "string", "minLength": 3, "maxLength": 1000}}
_MANAGE_SCHEMA = {"type": "object", "properties": _WINDOW_IDENTITY | {
    "action": {"type": "string", "enum": ["minimize", "maximize", "restore", "focus"]}},
    "required": ["window_id", "process_id", "executable", "action"], "additionalProperties": False}
_CLOSE_SCHEMA = {"type": "object", "properties": dict(_WINDOW_IDENTITY),
                 "required": ["window_id", "process_id", "executable"], "additionalProperties": False}


def _validate_identity(arguments, extra=()):
    if set(arguments) != {"window_id", "process_id", "executable", *extra}:
        raise ValueError("Provide the exact window_id, process_id and executable from windows.list.")
    if type(arguments["window_id"]) is not int or type(arguments["process_id"]) is not int \
            or not isinstance(arguments["executable"], str):
        raise ValueError("Window identity fields have invalid types.")


def _validate_manage(arguments):
    _validate_identity(arguments, ("action",))
    if arguments["action"] not in {"minimize", "maximize", "restore", "focus"}:
        raise ValueError("Unsupported window action.")


def _manage(arguments, _context):
    desktop = Desktop()
    window = desktop.exact(arguments["window_id"], arguments["process_id"], arguments["executable"])
    if window is None:
        return ToolResult({"error": "That exact window no longer exists; list windows again."}, Verification.FAIL)
    hwnd, action = arguments["window_id"], arguments["action"]
    was_minimized = bool(desktop.u.IsIconic(hwnd))
    if action == "focus":
        from chutku.tools.windows_apps import WindowsDesktop
        WindowsDesktop().focus(hwnd)
    else:
        desktop.u.ShowWindowAsync(hwnd, {"minimize": 6, "maximize": 3, "restore": 9}[action])
    checks = {"minimize": lambda: desktop.u.IsIconic(hwnd),
              "maximize": lambda: desktop.u.IsZoomed(hwnd),
              # Restoring a minimized window returns it to its previous (possibly maximized) size.
              "restore": (lambda: not desktop.u.IsIconic(hwnd)) if was_minimized else
                         (lambda: not desktop.u.IsIconic(hwnd) and not desktop.u.IsZoomed(hwnd)),
              "focus": lambda: desktop.foreground() == hwnd}
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not checks[action]():
        time.sleep(0.05)
    ok = bool(checks[action]())
    output = {"window_id": hwnd, "action": action, "state_observed": ok}
    if not ok:
        output["error"] = "Windows did not report the requested window state."
    return ToolResult(output, Verification.PASS if ok else Verification.UNKNOWN)


SNAP_POSITIONS = ("left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right",
                  "maximize", "center")
_SNAP_SCHEMA = {"type": "object", "properties": _WINDOW_IDENTITY | {
    "position": {"type": "string", "enum": list(SNAP_POSITIONS)}},
    "required": ["window_id", "process_id", "executable", "position"], "additionalProperties": False}
SNAP_TOLERANCE = 8   # px: some apps round their size (character cells, minimum sizes)


def _validate_snap(arguments):
    _validate_identity(arguments, ("position",))
    if arguments["position"] not in SNAP_POSITIONS:
        raise ValueError("Unsupported snap position.")


def snap_rect(position, work, size):
    """The visible (left, top, right, bottom) for a position inside the work area; center keeps the size."""
    left, top, right, bottom = work
    if position == "center":
        width, height = min(size[0], right - left), min(size[1], bottom - top)
        x, y = left + (right - left - width) // 2, top + (bottom - top - height) // 2
        return x, y, x + width, y + height
    mid_x, mid_y = (left + right) // 2, (top + bottom) // 2
    parts = position.split("_")
    x0, x1 = (left, mid_x) if "left" in parts else (mid_x, right) if "right" in parts else (left, right)
    y0, y1 = (top, mid_y) if "top" in parts else (mid_y, bottom) if "bottom" in parts else (top, bottom)
    return x0, y0, x1, y1


def _window_rect(desktop, hwnd):
    rect = w.RECT()
    if not desktop.u.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError("Windows did not report the window's position.")
    return rect.left, rect.top, rect.right, rect.bottom


def _visible_rect(hwnd, outer):
    """The frame the owner sees: Windows 10/11 windows have invisible resize borders outside it."""
    rect = w.RECT()
    if ctypes.WinDLL("dwmapi").DwmGetWindowAttribute(w.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)):
        return outer   # DWMWA_EXTENDED_FRAME_BOUNDS unavailable: treat the window rect as visible
    return rect.left, rect.top, rect.right, rect.bottom


def _work_area(desktop, hwnd):
    from chutku.vision import _MonitorInfo
    desktop.u.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
    if not desktop.u.GetMonitorInfoW(desktop.u.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):  # 2: NEAREST
        raise OSError("Windows did not report the window's monitor.")
    work = info.rcWork
    return work.left, work.top, work.right, work.bottom


def snap_plan(desktop, hwnd, position):
    """(work area, window rect to set) for a restored window; reads only."""
    work = _work_area(desktop, hwnd)
    outer = _window_rect(desktop, hwnd)
    seen = _visible_rect(hwnd, outer)
    target = snap_rect(position, work, (seen[2] - seen[0], seen[3] - seen[1]))
    return work, (target[0] - (seen[0] - outer[0]), target[1] - (seen[1] - outer[1]),
                  target[2] + (outer[2] - seen[2]), target[3] + (outer[3] - seen[3]))


def _wait(check, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not check():
        time.sleep(0.05)
    return bool(check())


def _snap(arguments, _context):
    from chutku.vision import dpi_aware
    desktop = Desktop()
    hwnd, position = arguments["window_id"], arguments["position"]
    if desktop.exact(hwnd, arguments["process_id"], arguments["executable"]) is None:
        return ToolResult({"error": "That exact window no longer exists; list windows again."}, Verification.FAIL)
    with dpi_aware():   # physical pixels for the monitor, the window and the check alike
        if position == "maximize":
            desktop.u.ShowWindowAsync(hwnd, 3)
            ok = _wait(lambda: desktop.u.IsZoomed(hwnd))
            output = {"window_id": hwnd, "position": position, "state_observed": ok}
            if not ok:
                output["error"] = "Windows did not report the window as maximized."
            return ToolResult(output, Verification.PASS if ok else Verification.UNKNOWN)
        for _ in range(2):   # a minimized window that was maximized restores to maximized first
            if desktop.u.IsIconic(hwnd) or desktop.u.IsZoomed(hwnd):
                desktop.u.ShowWindowAsync(hwnd, 9)
                _wait(lambda: not desktop.u.IsIconic(hwnd) and not desktop.u.IsZoomed(hwnd))
        if desktop.u.IsIconic(hwnd) or desktop.u.IsZoomed(hwnd):
            return ToolResult({"window_id": hwnd, "position": position,
                               "error": "The window could not be restored first."}, Verification.FAIL)
        work, (left, top, right, bottom) = snap_plan(desktop, hwnd, position)
        # SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS: a hung app cannot block Chutku
        desktop.u.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, 0x0004 | 0x0010 | 0x4000)
        observed = []

        def placed():
            observed[:] = _window_rect(desktop, hwnd)
            return all(abs(a - b) <= SNAP_TOLERANCE for a, b in zip(observed, (left, top, right, bottom)))
        ok = _wait(placed)
    output = {"window_id": hwnd, "position": position, "work_area": list(work),
              "requested_rect": [left, top, right, bottom], "observed_rect": observed, "state_observed": ok}
    if not ok:
        output["error"] = "The window did not take that position (it may have a minimum size or be elevated)."
    return ToolResult(output, Verification.PASS if ok else Verification.UNKNOWN)


THIS_ACTIONS = ("minimize", "maximize", "restore", "snap_left", "snap_right")
_THIS_SCHEMA = {"type": "object", "properties": {"action": {"type": "string", "enum": list(THIS_ACTIONS)}},
                "required": ["action"], "additionalProperties": False}


def _validate_this(arguments):
    if set(arguments) != {"action"} or arguments["action"] not in THIS_ACTIONS:
        raise ValueError("Choose minimize, maximize, restore, snap_left or snap_right.")


def _front_window():
    """Identity of the app window in front, or None (Chutku's own windows never count)."""
    desktop = Desktop()
    hwnd = desktop.foreground()
    info = desktop.describe(hwnd) if hwnd else {}
    if not info.get("executable") or info.get("title", "").startswith("Chutku"):
        return None
    return {k: info[k] for k in ("window_id", "process_id", "executable")}


_NO_FRONT = "No app window is in front (Chutku's own window does not count)."


def _close_this(arguments, context):
    identity = _front_window()
    return _close_window(identity, context) if identity else ToolResult({"error": _NO_FRONT}, Verification.FAIL)


def _this_window(arguments, context):
    """Z3: "minimize this window" in one step: the window in front, through the same checked code as windows.manage
    and windows.snap."""
    identity = _front_window()
    if identity is None:
        return ToolResult({"error": _NO_FRONT}, Verification.FAIL)
    action = arguments["action"]
    if action.startswith("snap_"):
        return _snap(identity | {"position": action.removeprefix("snap_")}, context)
    return _manage(identity | {"action": action}, context)


def _close_window(arguments, _context):
    desktop = Desktop()
    if desktop.exact(arguments["window_id"], arguments["process_id"], arguments["executable"]) is None:
        return ToolResult({"error": "That exact window no longer exists; nothing was closed."}, Verification.FAIL)
    desktop.u.PostMessageW(arguments["window_id"], 0x0010, 0, 0)  # WM_CLOSE: the app may ask to save
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not desktop.u.IsWindow(arguments["window_id"]) or not desktop.u.IsWindowVisible(arguments["window_id"]):
            return ToolResult({"window_id": arguments["window_id"], "closed": True}, Verification.PASS)
        time.sleep(0.1)
    return ToolResult({"window_id": arguments["window_id"], "closed": False,
                       "error": "The window is still open (it may be asking to save)."}, Verification.UNKNOWN)


# -- media ------------------------------------------------------------------------

_MEDIA = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($operation, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    if (-not $task.Wait(5000)) { throw 'Media session request timed out.' }
    $task.Result
}
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$manager = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$session = $manager.GetCurrentSession()
if ($request.match) {
    # Z3: the named app's own session (YouTube in Brave while Spotify is the "current" one); a playing one first.
    $found = @($manager.GetSessions() | Where-Object {
        $id = ([string]$_.SourceAppUserModelId).ToLower(); @($request.match | Where-Object { $id.Contains($_) }).Count })
    $session = @($found | Where-Object { [string]$_.GetPlaybackInfo().PlaybackStatus -eq 'Playing' }) + $found |
        Select-Object -First 1
}
if ($null -eq $session) { @{ session = $false } | ConvertTo-Json -Compress; exit 0 }
function Snapshot {
    $info = $session.GetPlaybackInfo()
    $props = Await ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
    @{ session = $true; app = [string]$session.SourceAppUserModelId; status = [string]$info.PlaybackStatus;
       title = [string]$props.Title; artist = [string]$props.Artist }
}
$accepted = $null
$before = if ([string]$request.action -ne 'status') { Snapshot } else { $null }
switch ([string]$request.action) {
    'status' { }
    'play_pause' { $accepted = Await ($session.TryTogglePlayPauseAsync()) ([bool]) }
    'play' { $accepted = Await ($session.TryPlayAsync()) ([bool]) }
    'pause' { $accepted = Await ($session.TryPauseAsync()) ([bool]) }
    'next' { $accepted = Await ($session.TrySkipNextAsync()) ([bool]) }
    'previous' { $accepted = Await ($session.TrySkipPreviousAsync()) ([bool]) }
    default { throw 'Unsupported media action.' }
}
$result = Snapshot
$result.accepted = $accepted
$result.before = $before
$result | ConvertTo-Json -Compress
'''
MEDIA_ACTIONS = ("play_pause", "play", "pause", "next", "previous")
# Z3: which media session an app name means (parts of the Windows app id, lower case).
_BROWSERS = ["brave", "chrome", "msedge", "firefox", "opera"]
MEDIA_APPS = {"brave": ["brave"], "chrome": ["chrome"], "edge": ["msedge"], "firefox": ["firefox"],
              "spotify": ["spotify"], "vlc": ["vlc"], "browser": _BROWSERS}
_MEDIA_SCHEMA = {"type": "object", "properties": {"action": {"type": "string", "enum": list(MEDIA_ACTIONS)},
                                                  "app": {"type": "string", "enum": list(MEDIA_APPS)}},
                 "required": ["action"], "additionalProperties": False}


def media(action, match=None):
    result = _powershell(_MEDIA, {"action": action} | ({"match": match} if match else {}))
    if not isinstance(result, dict):
        raise OSError("Media session returned an invalid response.")
    return result


def _validate_media(arguments):
    if not {"action"} <= set(arguments) <= {"action", "app"} or arguments["action"] not in MEDIA_ACTIONS \
            or arguments.get("app", "brave") not in MEDIA_APPS:
        raise ValueError("Choose one supported media action (and optionally one known app).")


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("This tool takes no arguments.")


def _media_status(_arguments, _context):
    state = media("status")
    return ToolResult(state, Verification.PASS, {k: state.get(k) for k in ("session", "status")})


def _media_control(arguments, _context):
    app = arguments.get("app")
    after = media(arguments["action"], MEDIA_APPS.get(app))   # one call: status before, the action, status after
    if not after.get("session"):
        missing = f"{app} is not playing anything" if app else "No app is currently exposing a media session"
        return ToolResult({"error": missing + " (no media session)."}, Verification.FAIL)
    before = after.get("before") or {}
    if after.get("accepted") is not True:
        return ToolResult({"error": "The media app refused that action.", "status": after.get("status")},
                          Verification.FAIL)
    expected = {"play": {"Playing"}, "pause": {"Paused", "Stopped"},
                "play_pause": {"Paused", "Stopped"} if before.get("status") == "Playing" else {"Playing"}}
    deadline = time.monotonic() + 3
    while True:
        if arguments["action"] in expected:
            ok = after.get("status") in expected[arguments["action"]]
        else:
            ok = after.get("title") != before.get("title")
        if ok or time.monotonic() > deadline:
            break
        time.sleep(0.4)
        after = media("status", MEDIA_APPS.get(app))
    output = {"action": arguments["action"], "before": before.get("status"), "after": after.get("status"),
              "title": after.get("title"), "app": after.get("app")}
    if not ok:
        output["error"] = "The media session did not report the expected change."
    return ToolResult(output, Verification.PASS if ok else Verification.UNKNOWN,
                      output | {"title": "[REDACTED]"})


# -- registration -----------------------------------------------------------------

def register_everyday_tools(registry):
    desktop = ("interactive Windows desktop",)
    registry.register(Tool("apps.installed", "List installed Start-menu apps (name, app_id); optional query filters by name.",
        Risk.OBSERVATION, _installed, _validate_installed, argument_schema=_INSTALLED_SCHEMA,
        prerequisites=desktop, reversibility="not_applicable", success_predicate="start_menu_inventory_returned"))
    registry.register(Tool("apps.launch", "Open any installed app by its exact Start-menu name (e.g. 'Spotify', "
        "'Visual Studio Code') or app_id; verifies a window appears. background=true opens it BEHIND the owner's "
        "window (use it when the app is only a means for the task, then desktop.look/desktop.do in it): he keeps "
        "working undisturbed.",
        Risk.REVERSIBLE, _launch, _validate_launch, verify=_window_verifier, required_capability="apps.launch",
        argument_schema=_LAUNCH_SCHEMA, prerequisites=desktop, reversibility="compensatable",
        success_predicate="new_or_foreground_app_window_observed"))
    registry.register(Tool("files.open", "Open a document, media file or folder with its default app (not programs "
        "or scripts); verifies a window shows it.",
        Risk.REVERSIBLE, _open_file, _validate_path, verify=_window_verifier, resource_access="observe",
        required_capability="apps.launch", argument_schema={"type": "object", "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000}}, "required": ["path"],
            "additionalProperties": False},
        prerequisites=desktop, reversibility="compensatable", success_predicate="file_window_observed"))
    registry.register(Tool("web.open", "Open an http(s) URL in the owner's browser (Brave unless browser is given: "
        "brave, chrome, edge, firefox); verifies a browser window. tab: leave it out (reuses the tab Chutku opened "
        "last if it is still showing), 'new' only when the owner asks for a new tab, 'same' for 'this tab'.",
        Risk.REVERSIBLE, _web_open, _validate_url, verify=_window_verifier, required_capability="browser.navigate",
        argument_schema=_URL_SCHEMA, prerequisites=desktop, reversibility="transient",
        success_predicate="default_browser_window_observed", network_egress=True))
    registry.register(Tool("web.search", "Open a search in the owner's browser (or browser=brave/chrome/edge/firefox); "
        "site is google (default), youtube, bing, "
        "duckduckgo, wikipedia, maps, github, flights (e.g. 'flights from Delhi to Goa on 12 Oct'), amazon, flipkart "
        "or images.",
        Risk.REVERSIBLE, _web_search, _validate_search, verify=_window_verifier,
        required_capability="browser.navigate", argument_schema=_SEARCH_SCHEMA, prerequisites=desktop,
        reversibility="transient", success_predicate="default_browser_window_observed", network_egress=True))
    registry.register(Tool("spotify.search", "Open Spotify's search for a song, artist or playlist (the owner then "
        "presses play, or Chutku clicks the top result).", Risk.REVERSIBLE, _spotify_search, _validate_spotify,
        required_capability="apps.launch", argument_schema={"type": "object", "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["query"],
            "additionalProperties": False},
        prerequisites=desktop, reversibility="transient", success_predicate="spotify_window_observed"))
    registry.register(Tool("windows.manage", "Minimize, maximize, restore or focus one exact window from windows.list "
        "(window_id, process_id, executable); verifies the new state.",
        Risk.REVERSIBLE, _manage, _validate_manage, required_capability="desktop.input",
        argument_schema=_MANAGE_SCHEMA, prerequisites=desktop, reversibility="transient",
        success_predicate="requested_window_state_read_back"))
    registry.register(Tool("windows.snap", "Snap one exact window from windows.list (window_id, process_id, "
        "executable) to the left/right/top/bottom half or a corner of its own screen (top_left, top_right, "
        "bottom_left, bottom_right), maximize or center it; two windows side by side are two snaps. Verifies the "
        "new position.",
        Risk.REVERSIBLE, _snap, _validate_snap, required_capability="desktop.input",
        argument_schema=_SNAP_SCHEMA, prerequisites=desktop, reversibility="transient",
        success_predicate="window_rect_read_back_matches_position"))
    registry.register(Tool("windows.close", "Ask one exact window from windows.list to close (the app may ask to "
        "save); verifies it disappears.",
        Risk.EXTERNAL_SIDE_EFFECT, _close_window, _validate_identity, required_capability="desktop.input",
        argument_schema=_CLOSE_SCHEMA, prerequisites=desktop,
        reversibility="irreversible_if_unsaved_state_is_discarded_by_the_app",
        success_predicate="exact_window_no_longer_visible"))
    registry.register(Tool("windows.this", "Minimize, maximize, restore or snap left/right the app window in front "
        "(\"minimize this window\"); verifies the new state.",
        Risk.REVERSIBLE, _this_window, _validate_this, required_capability="desktop.input",
        argument_schema=_THIS_SCHEMA, prerequisites=desktop, reversibility="transient",
        success_predicate="requested_window_state_read_back"))
    registry.register(Tool("windows.close_this", "Ask the app window in front to close (\"close this window\"; the "
        "app may ask to save); verifies it disappears.",
        Risk.EXTERNAL_SIDE_EFFECT, _close_this, _validate_none, required_capability="desktop.input",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=desktop,
        reversibility="irreversible_if_unsaved_state_is_discarded_by_the_app",
        success_predicate="exact_window_no_longer_visible"))
    registry.register(Tool("media.status", "Show what is playing (app, title, artist, playing/paused).",
        Risk.OBSERVATION, _media_status, _validate_none, required_capability="audio.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="media_session_state_returned"))
    registry.register(Tool("media.control", "Play, pause, toggle, next or previous track in the current media app; "
        "verifies the playback change.",
        Risk.REVERSIBLE, _media_control, _validate_media, required_capability="audio.modify",
        argument_schema=_MEDIA_SCHEMA, reversibility="transient",
        success_predicate="media_session_state_changed_as_requested"))
