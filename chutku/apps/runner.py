"""Run one atlas action (App Mastery A1): its fixed steps, then its check, through a Driver.

The Driver does the real Windows work (find/focus/launch the app's window, open a URI, start the app's own program,
press keys, type, read the window with OCR, click exact text, press a page's play button, media controls). Tests
pass a fake Driver, so no test ever touches the owner's screen. Before keys or typing, the app's own window must be
in front; otherwise the step stops (keys never go to the wrong window).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from urllib.parse import quote

_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class StepFailed(RuntimeError):
    pass


def fill(value, params, encode=False):
    """Put parameter values into a step ("spotify:search:{query}"); URI values are URL-encoded."""
    if isinstance(value, str):
        return _SLOT.sub(lambda m: quote(str(params[m.group(1)]), safe="") if encode else str(params[m.group(1)]),
                         value)
    if isinstance(value, list):
        return [fill(v, params, encode) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, params, encode) for k, v in value.items()}
    return value


class Driver:
    """The real one (Windows)."""

    def find_window(self, window):
        from chutku.tools.everyday import Desktop
        desktop = Desktop()
        exe = (window.get("exe") or "").casefold()
        title = (window.get("title") or "").casefold()
        for hwnd in desktop.windows():
            info = desktop.describe(hwnd)
            name = os.path.basename(info.get("executable") or "").casefold()
            if (exe and name == exe) or (title and title in (info.get("title") or "").casefold()):
                return hwnd
        return None

    def focus(self, hwnd):
        from chutku.tools.windows_apps import WindowsDesktop
        WindowsDesktop().focus(hwnd)
        time.sleep(0.5)

    def foreground(self):
        import ctypes
        return int(ctypes.WinDLL("user32").GetForegroundWindow() or 0)

    def title(self, hwnd):
        from chutku.tools.everyday import Desktop
        return Desktop().describe(hwnd).get("title") or ""

    def launch(self, name):
        from chutku.tools.everyday import _launch
        result = _launch({"name": name}, None)
        if str(getattr(result, "verification", "FAIL")) == "FAIL":
            raise StepFailed(f"could not open {name}")

    def open_uri(self, uri):
        os.startfile(uri)   # the scheme was checked against the app's own schemes by the atlas validator

    def run_program(self, program, args):
        path = shutil.which(program) or program
        if not os.path.isabs(path) and not shutil.which(program):
            raise StepFailed(f"{program} was not found")
        subprocess.Popen([path, *args], shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

    def keys(self, text):
        from chutku.tools.desktop_controls import press_combo
        from chutku.tools.free_input import parse_keys
        for combo in parse_keys(text):
            press_combo(combo)
            time.sleep(0.15)

    def type(self, text):
        from chutku.tools.desktop_controls import type_unicode
        type_unicode(text)

    def window_rect(self, hwnd):
        from chutku.tools.visible import _rect
        return _rect(hwnd)

    def ocr(self, rect):
        from chutku.tools.visible import _ocr
        return _ocr(rect)

    def click_text(self, rect, name, kind, double=False):
        from chutku import vision
        from chutku.tools.visible import typed
        tier, found = typed(self.ocr(rect), name, kind)
        if not found:
            raise StepFailed(f"'{name}'{' (' + kind + ')' if kind else ''} is not visible; nothing clicked")
        if len(found) > 1:
            raise StepFailed(f"{len(found)} items read '{name}'; say which one")
        x0, y0, x1, y1 = found[0]["rect"]
        vision.click_at((x0 + x1) // 2, (y0 + y1) // 2, double=double)
        time.sleep(1.2)
        return found[0]["text"]

    def play_page(self, rect):
        from chutku.tools.visible import _press_play
        return _press_play(None, rect, self.ocr(rect))

    def media(self, action):
        from chutku.tools.everyday import media
        return media(action)

    def process_running(self, exe):
        from chutku.tools.everyday import Desktop
        desktop = Desktop()
        return any(os.path.basename(desktop.describe(h).get("executable") or "").casefold() == exe.casefold()
                   for h in desktop.windows())


def run(atlas, action, params, driver=None):
    """Run the action's steps then its check. Returns {"ok", "steps", "check", "error"?, "seconds", …}."""
    driver = driver or Driver()
    started = time.monotonic()
    window = atlas["window"]
    programs = atlas.get("cli") or {}
    out = {"app": atlas["app"], "action": action["id"], "steps": []}
    hwnd = None
    try:
        before = _media_status(driver) if _uses_media(action) else {}
        for step in action["steps"]:
            verb = next(v for v in step if v in {"focus", "launch", "uri", "cli", "keys", "type", "click_text",
                                                 "wait_text", "play_page", "sleep", "media", "settings_uri"})
            if step.get("unless"):
                # Toggles (a side panel) are pressed only when their screen is not already showing.
                current = hwnd or driver.find_window(window)
                text = fill(step["unless"], params).casefold()
                if current and any(text in l["text"].casefold() for l in driver.ocr(driver.window_rect(current))):
                    out["steps"].append(f"{verb} (already showing)")
                    continue
            if verb == "focus":
                hwnd = driver.find_window(window)
                if hwnd is None:
                    driver.launch(atlas.get("launch", {}).get("start_menu") or atlas["app"])
                    hwnd = _wait_window(driver, window, 15)
                driver.focus(hwnd)
            elif verb == "launch":
                driver.launch(atlas.get("launch", {}).get("start_menu") or atlas["app"])
                hwnd = _wait_window(driver, window, 15)
            elif verb in {"uri", "settings_uri"}:
                driver.open_uri(fill(step[verb], params, encode=True))
                time.sleep(1.0)
                hwnd = driver.find_window(window) or hwnd
            elif verb == "cli":
                command = fill(step["cli"], params)
                driver.run_program(programs[command[0]], command[1:])
                hwnd = _wait_window(driver, window, 15)
            elif verb in {"keys", "type"}:
                hwnd = hwnd or driver.find_window(window)
                if hwnd is None:
                    raise StepFailed(f"{atlas['app']} is not open")
                if driver.foreground() != hwnd:
                    driver.focus(hwnd)
                    if driver.foreground() != hwnd:
                        raise StepFailed(f"{atlas['app']} is not in front; no keys were sent")
                if verb == "keys":
                    driver.keys(step["keys"])
                else:
                    driver.type(fill(step["type"], params))
                time.sleep(float(step.get("wait", 0.3)))
            elif verb == "click_text":
                hwnd = hwnd or driver.find_window(window)
                out["clicked"] = driver.click_text(driver.window_rect(hwnd), fill(step["click_text"], params),
                                                   step.get("kind"), **({"double": True} if step.get("double") else {}))
            elif verb == "wait_text":
                hwnd = hwnd or driver.find_window(window)
                text = fill(step["wait_text"], params).casefold()
                deadline = time.monotonic() + float(step.get("timeout", 6))
                while not any(text in l["text"].casefold() for l in driver.ocr(driver.window_rect(hwnd))):
                    if time.monotonic() > deadline:
                        raise StepFailed(f"'{text}' did not appear")
                    time.sleep(0.5)
            elif verb == "play_page":
                hwnd = hwnd or driver.find_window(window)
                played = driver.play_page(driver.window_rect(hwnd))
                out["play"] = played
                if played.get("error"):
                    raise StepFailed(played["error"])
            elif verb == "sleep":
                time.sleep(float(step["sleep"]))
            elif verb == "media":
                driver.media(step["media"])
            out["steps"].append(verb)
        out["check"] = _check(action.get("check") or {}, params, driver, window, hwnd, before, out)
        out["ok"] = all(out["check"].values())
        if not out["ok"]:
            failed = [name for name, ok in out["check"].items() if not ok]
            out["error"] = f"the steps ran but the check failed: {', '.join(failed)}"
    except (StepFailed, OSError, ValueError, KeyError) as error:
        out["ok"], out["error"] = False, str(error)
    out["seconds"] = round(time.monotonic() - started, 2)
    return out


def _norm(text):
    return re.sub(r"[^\w]+", " ", str(text).casefold()).strip()


def on_page(title, lines):
    """True when the song title is one of the window's OCR lines (OCR may cut long titles: 'Lehnga (From "Jatt')."""
    want = _norm(title)
    if not want:
        return False
    for line in lines:
        seen = _norm(line["text"])
        if seen == want or (len(seen) >= 6 and want.startswith(seen)) or (len(want) >= 6 and seen.startswith(want)):
            return True
    return False


def _uses_media(action):
    return bool({"media_playing", "media_changed", "media_paused", "playing_on_page"} & set(action.get("check") or {}))


def _media_status(driver):
    try:
        return driver.media("status") or {}
    except OSError:
        return {}


def _wait_window(driver, window, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        hwnd = driver.find_window(window)
        if hwnd is not None:
            return hwnd
        time.sleep(0.5)
    raise StepFailed("the app window did not appear")


def _check(check, params, driver, window, hwnd, before, out):
    results = {}
    if not check:
        return results
    media_checks = {"media_playing", "media_changed", "media_paused", "playing_on_page"}
    after = _media_status(driver) if media_checks & set(check) else {}
    for name, value in check.items():
        value = fill(value, params)
        if name == "media_playing":
            deadline = time.monotonic() + 4
            while after.get("status") != "Playing" and time.monotonic() < deadline:
                time.sleep(0.5)
                after = _media_status(driver)
            results[name] = after.get("status") == "Playing"
        elif name == "media_paused":
            deadline = time.monotonic() + 3
            while after.get("status") not in {"Paused", "Stopped"} and time.monotonic() < deadline:
                time.sleep(0.4)
                after = _media_status(driver)
            results[name] = after.get("status") in {"Paused", "Stopped"}
        elif name == "media_changed":
            results[name] = after.get("title") != before.get("title") or after.get("status") != before.get("status")
        elif name == "title_in_page":
            results[name] = bool((out.get("play") or {}).get("playing"))
        elif name == "playing_on_page":
            # What plays must be one of the tracks the opened page shows (not a song from somewhere else).
            deadline = time.monotonic() + 4
            while after.get("status") != "Playing" and time.monotonic() < deadline:
                time.sleep(0.5)
                after = _media_status(driver)
            current = driver.find_window(window) or hwnd
            lines = driver.ocr(driver.window_rect(current)) if current else []
            results[name] = after.get("status") == "Playing" and on_page(after.get("title") or "", lines)
            started_new = before.get("status") != "Playing" or after.get("title") != before.get("title")
            if not results[name] and after.get("status") == "Playing" and started_new:
                driver.media("pause")   # something else started: stop it rather than play the wrong thing
                out["paused_wrong"] = after.get("title")
        elif name == "window_title_contains":
            current = driver.find_window(window) or hwnd
            results[name] = bool(current) and str(value).casefold() in driver.title(current).casefold()
        elif name == "ocr_contains":
            current = driver.find_window(window) or hwnd
            results[name] = bool(current) and any(str(value).casefold() in l["text"].casefold()
                                                  for l in driver.ocr(driver.window_rect(current)))
        elif name == "window_open":
            results[name] = driver.find_window(window) is not None
        elif name == "process_running":
            results[name] = driver.process_running(window.get("exe", ""))
        elif name == "process_gone":
            deadline = time.monotonic() + 5
            while driver.process_running(window.get("exe", "")) and time.monotonic() < deadline:
                time.sleep(0.5)
            results[name] = not driver.process_running(window.get("exe", ""))
    if after:
        out["now_playing"] = after.get("title")
    return results
