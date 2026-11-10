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
import statistics
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

    def titles(self, window):
        """Titles of every window of the app (an app like VS Code can have several)."""
        from chutku.tools.everyday import Desktop
        desktop = Desktop()
        exe = (window.get("exe") or "").casefold()
        out = []
        for hwnd in desktop.windows():
            info = desktop.describe(hwnd)
            if exe and os.path.basename(info.get("executable") or "").casefold() == exe:
                out.append(info.get("title") or "")
        return out

    def launch(self, name, behind=False):
        from chutku.tools.everyday import _launch
        result = _launch({"name": name, **({"background": True} if behind else {})}, None)
        if str(getattr(result, "verification", "FAIL")) == "FAIL":
            raise StepFailed(f"could not open {name}")

    def do(self, window, name, action, text=None):
        """Press the element named `name` through UI Automation (desktop.do: consequential names refused there)."""
        from chutku.tools.desktop import _do
        arguments = {"app": _app_key(window), "name": name, "action": action, **({"text": text} if text is not None
                                                                                  else {})}
        result = _do(arguments, None)
        if result.verification.name == "FAIL":
            raise StepFailed(result.output.get("error") or f"could not {action} '{name}'")
        return result.output

    def has_element(self, window, name):
        from chutku.tools.desktop import _window, call
        try:
            found = call("find", "--window-id", _window(_app_key(window))["id"], "--text", name, "--limit", "5")
        except (OSError, LookupError):
            return False
        return any(name.casefold() in str(m.get("name", "")).casefold() for m in found.get("matches", []))

    def open_uri(self, uri):
        os.startfile(uri)   # the scheme was checked against the app's own schemes by the atlas validator

    def run_program(self, program, args):
        program = os.path.expandvars(program)
        path = program if os.path.isabs(program) else shutil.which(program)
        if not path or not os.path.isfile(path):
            raise StepFailed(f"{program} was not found")
        if os.path.splitext(path)[1].casefold() in {".cmd", ".bat"}:
            # cmd.exe would parse the arguments again (& | ^ in a path could run commands): never.
            raise StepFailed(f"{os.path.basename(path)} is a batch file; atlases must name the program's .exe")
        # ELECTRON_RUN_AS_NODE (inherited when Chutku is started from VS Code) makes Code.exe and other Electron
        # apps RUN a file argument as JavaScript instead of opening it (seen 2026-10-09): never pass it on.
        env = {k: v for k, v in os.environ.items() if k.upper() not in {"ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"}}
        subprocess.Popen([path, *args], shell=False, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

    def keys(self, text):
        from chutku.tools.desktop_controls import press_combo
        from chutku.tools.free_input import parse_keys
        for combo in parse_keys(text):
            press_combo(combo)
            time.sleep(0.15)

    def type(self, text):
        from chutku.tools import desktop_controls
        if desktop_controls.focused_is_password():   # owner rule: Chutku never types passwords (plan slice F3)
            raise StepFailed(desktop_controls.PASSWORD_REFUSAL)
        desktop_controls.type_unicode(text)

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
            raise StepFailed(f"'{name}'{' (' + kind + ')' if kind else ''} is not visible; nothing clicked.")
        if len(found) > 1:
            raise StepFailed(f"{len(found)} items read '{name}'; say which one.")
        x0, y0, x1, y1 = found[0]["rect"]
        vision.click_at((x0 + x1) // 2, (y0 + y1) // 2, double=double)
        time.sleep(1.2)
        return found[0]["text"]

    def play_page(self, rect, match=None, first=None):
        from chutku import vision
        from chutku.tools.visible import _press_play, green_play_button
        lines = self.ocr(rect)
        wanted = first_result(lines, rect, kinds={"playlist", "album"}) if first == "playlist" else None
        if wanted is not None:
            # A playlist search: open the first playlist result, so its own tracks are on the page and what starts
            # can be checked (the Top result card's button played songs that were not shown, live 2026-11-10).
            (x0, y0, x1, y1), _kind = wanted
            vision.click_at((x0 + x1) // 2, (y0 + y1) // 2)
            time.sleep(1.5)
            lines = self.ocr(rect)
        elif green_play_button(vision.capture(), rect) is None:
            # A search page shows no green button until a result is opened (live 2026-11-10): open the first
            # playlist/album result (its page has the button), or double-click the first song (that plays it).
            first = first_result(lines, rect)
            if first is not None:
                (x0, y0, x1, y1), kind = first
                vision.click_at((x0 + x1) // 2, (y0 + y1) // 2, double=kind == "song")
                time.sleep(1.5)
                if kind == "song":
                    return {"play_button": "song row (double-click)", "playing": True, "opened": "song"}
                lines = self.ocr(rect)
        return _press_play(None, rect, lines, match)

    def media(self, action, match=None):
        from chutku.tools.everyday import media
        return media(action, match)

    def process_running(self, exe):
        from chutku.tools.everyday import Desktop
        desktop = Desktop()
        return any(os.path.basename(desktop.describe(h).get("executable") or "").casefold() == exe.casefold()
                   for h in desktop.windows())


def _app_key(window):
    """How desktop.do names the app's window: its exe without .exe ("CalculatorApp"), else its title words."""
    return (window.get("exe") or "").removesuffix(".exe").removesuffix(".EXE") or window.get("title", "")


def _seen(lines, text):
    """``text`` is on screen: in a line, or as the one line OCR misread ("I-owKey" for "LowKey")."""
    from chutku.tools.visible import matches
    return any(text in l["text"].casefold() for l in lines) or bool(matches(lines, text)[1])


_RESULT_KIND = re.compile(r"^(playlist|album|song|single|ep)\b", re.I)


def first_result(lines, rect, kinds=None):
    """((title rect), kind) of the topmost search-result row in the page whose type label reads Playlist, Album or Song
    (Spotify prints the type in its own column on the same row); None when there is none."""
    left, top, right, bottom = rect
    page_left, page_right = left + (right - left) * 0.18, left + (right - left) * 0.82
    rows = []
    for label in lines:
        kind = _RESULT_KIND.match(label["text"].strip())
        x0, y0, x1, y1 = label["rect"]
        if not kind or not page_left <= x0 <= page_right or y1 > bottom - (bottom - top) * 0.15:
            continue
        titles = [l for l in lines if l is not label and l["rect"][2] < x0 and l["rect"][0] >= page_left
                  and abs((l["rect"][1] + l["rect"][3]) / 2 - (y0 + y1) / 2) <= 20 and len(l["text"].strip()) >= 2]
        if titles:
            title = min(titles, key=lambda l: l["rect"][0])
            kind = kind.group(1).casefold()
            kind = "album" if kind in {"single", "ep"} else kind
            if kinds is None or kind in kinds:
                rows.append((title["rect"], kind))
    return min(rows, key=lambda row: row[0][1]) if rows else None


def run(atlas, action, params, driver=None):
    """Run the action's steps then its check. Returns {"ok", "steps", "check", "error"?, "seconds", …}."""
    driver = driver or Driver()
    started = time.monotonic()
    window = atlas["window"]
    programs = atlas.get("cli") or {}
    out = {"app": atlas["app"], "action": action["id"], "steps": []}
    hwnd = None
    try:
        # The atlas app's own media session: with a movie playing in Brave, Windows' "current" session is Brave,
        # so a Spotify check passed on the movie (live 2026-11-10).
        from chutku.tools.everyday import MEDIA_APPS
        match = MEDIA_APPS.get(atlas["app"])
        before = _media_status(driver, match) if _uses_media(action) else {}
        for step in action["steps"]:
            verb = next(v for v in step if v in {"focus", "launch", "uri", "cli", "keys", "type", "click_text",
                                                 "wait_text", "play_page", "sleep", "media", "settings_uri", "do"})
            if step.get("if_title") or step.get("require_title"):
                # Keys only for the right page: "if_title" skips quietly (a clean-up Ctrl+W only on the page it
                # opened), "require_title" stops the action (YouTube keys only on a YouTube tab).
                current = hwnd or driver.find_window(window)
                title = driver.title(current) if current else ""
                wanted = fill(step.get("if_title") or step.get("require_title"), params)
                if wanted.casefold() not in (title or "").casefold():
                    if step.get("require_title"):
                        raise StepFailed(f"The {atlas.get('name', atlas['app'])} window is not on '{wanted}'; "
                                         "no keys were sent.")
                    out["steps"].append(f"{verb} (skipped: not on {wanted})")
                    continue
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
                name = atlas.get("launch", {}).get("start_menu") or atlas["app"]
                if step["launch"] == "behind":
                    if driver.find_window(window) is None:   # an open window is reused where it is
                        driver.launch(name, behind=True)
                else:
                    driver.launch(name)
                hwnd = _wait_window(driver, window, 15)
            elif verb == "do":
                driver.do(window, fill(step["do"], params), step.get("action", "click"),
                          fill(step["text"], params) if "text" in step else None)
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
                out["not_found"] = True            # until the click happened ("'Lowkey' (playlist) is not visible")
                out["clicked"] = driver.click_text(_area(driver.window_rect(hwnd), step.get("area")),
                                                   fill(step["click_text"], params), step.get("kind"),
                                                   **({"double": True} if step.get("double") else {}))
                out.pop("not_found", None)
            elif verb == "wait_text":
                hwnd = hwnd or driver.find_window(window)
                text = fill(step["wait_text"], params).casefold()
                deadline = time.monotonic() + float(step.get("timeout", 6))
                while not _seen(driver.ocr(_area(driver.window_rect(hwnd), step.get("area"))), text):
                    if time.monotonic() > deadline:
                        out["not_found"] = True
                        raise StepFailed(f"'{fill(step['wait_text'], params)}' did not appear; nothing clicked.")
                    time.sleep(0.5)
            elif verb == "play_page":
                hwnd = hwnd or driver.find_window(window)
                first = {"first": step["play_page"]} if isinstance(step["play_page"], str) else {}
                played = driver.play_page(driver.window_rect(hwnd), match, **first)
                out["play"] = played
                if played.get("error"):
                    raise StepFailed(played["error"])
            elif verb == "sleep":
                time.sleep(float(step["sleep"]))
            elif verb == "media":
                driver.media(step["media"], match)
            out["steps"].append(verb)
        out["check"] = _check(action.get("check") or {}, params, driver, window, hwnd, before, out, match)
        checks = out["check"]
        already = checks.get("heading") or (out.get("play") or {}).get("already_playing")
        if checks.get("media_changed") is False and already and checks.get("media_playing", True) \
                and before.get("status") == "Playing":
            # Asked for what was already playing (live 2026-11-10: "play lofi playlist" right after lofi started):
            # the right page is open and playing, so nothing had to change.
            checks["media_changed"] = True
            out["already_playing"] = True
        out["ok"] = all(out["check"].values())
        if not out["ok"]:
            failed = [name for name, ok in out["check"].items() if not ok]
            out["error"] = f"the steps ran but the check failed: {', '.join(failed)}"
    except (StepFailed, OSError, ValueError, KeyError) as error:
        out["ok"], out["error"] = False, str(error)
    other = next((a for a in atlas.get("actions", []) if a["id"] == action.get("fallback")), None)
    nothing_new = (out.get("check") or {}).get("media_changed") is False and not out.get("paused_wrong")
    if not out["ok"] and (out.get("not_found") or nothing_new) and other:
        # Owner's convos: "play Loki/lofi/Afterparty Hits playlist" failed when the exact name was not in the
        # library. Nothing was clicked, so the other way (Spotify's own search, which fixes misheard names) runs.
        second = run(atlas, other, params, driver)
        second.update(instead_of=action["id"], first_error=out["error"], steps=out["steps"] + second["steps"],
                      seconds=round(time.monotonic() - started, 2))
        return second
    out["seconds"] = round(time.monotonic() - started, 2)
    return out


PAGE_AREA = [0, 0, 1, 0.86]   # the window without its bottom player bar


def _area(rect, area):
    """Part of the window, as fractions [left, top, right, bottom] (e.g. only Spotify's library panel)."""
    if not area:
        return rect
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    return (int(left + width * area[0]), int(top + height * area[1]), int(left + width * area[2]),
            int(top + height * area[3]))


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


def is_heading(name, lines):
    """True when a line reads exactly `name` in text clearly bigger than the usual lines (a page title)."""
    heights = [l["rect"][3] - l["rect"][1] for l in lines if len(l.get("rect") or ()) == 4]
    if not heights:
        return False
    usual = statistics.median(heights)
    want = _norm(name)
    return any(_norm(l["text"]) == want and l["rect"][3] - l["rect"][1] >= 1.5 * usual for l in lines)


def _uses_media(action):
    return bool({"media_playing", "media_changed", "media_paused", "playing_on_page"}
                & set(action.get("check") or {}))


def _media_status(driver, match=None):
    try:
        return driver.media("status", match) or {}
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


def _check(check, params, driver, window, hwnd, before, out, match=None):
    results = {}
    if not check:
        return results
    media_checks = {"media_playing", "media_changed", "media_paused", "playing_on_page"}
    after = _media_status(driver, match) if media_checks & set(check) else {}
    for name, value in check.items():
        value = fill(value, params)
        if name == "media_playing":
            deadline = time.monotonic() + 4
            while after.get("status") != "Playing" and time.monotonic() < deadline:
                time.sleep(0.5)
                after = _media_status(driver, match)
            results[name] = after.get("status") == "Playing"
        elif name == "media_paused":
            deadline = time.monotonic() + 3
            while after.get("status") not in {"Paused", "Stopped"} and time.monotonic() < deadline:
                time.sleep(0.4)
                after = _media_status(driver, match)
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
                after = _media_status(driver, match)
            current = driver.find_window(window) or hwnd
            # Not the player bar at the bottom: it always shows the current song, so it proves nothing.
            lines = driver.ocr(_area(driver.window_rect(current), PAGE_AREA)) if current else []
            results[name] = after.get("status") == "Playing" and on_page(after.get("title") or "", lines)
            started_new = before.get("status") != "Playing" or after.get("title") != before.get("title")
            if not results[name] and after.get("status") == "Playing" and started_new:
                driver.media("pause", match)   # something else started: stop it rather than play the wrong thing
                out["paused_wrong"] = after.get("title")
        elif name == "heading":
            # The page that opened has this name as its big title (a playlist or artist page), not just a list row.
            current = driver.find_window(window) or hwnd
            results[name] = bool(current) and is_heading(value, driver.ocr(_area(driver.window_rect(current), PAGE_AREA)))
        elif name == "title_lacks":
            current = driver.find_window(window) or hwnd
            results[name] = not current or str(value).casefold() not in (driver.title(current) or "").casefold()
        elif name == "title_has_file":
            # A window of the app shows this file or folder's name in its title (VS Code: "README.md - Chutku").
            wanted = os.path.basename(str(value).rstrip("\\/")).casefold()
            deadline = time.monotonic() + 5
            while True:
                titles = driver.titles(window) if hasattr(driver, "titles") else [driver.title(hwnd)]
                results[name] = bool(wanted) and any(wanted in t.casefold() for t in titles)
                if results[name] or time.monotonic() > deadline:
                    break
                time.sleep(0.5)
        elif name == "window_title_contains":
            current = driver.find_window(window) or hwnd
            results[name] = bool(current) and str(value).casefold() in driver.title(current).casefold()
        elif name == "ocr_contains":
            current = driver.find_window(window) or hwnd
            results[name] = bool(current) and any(str(value).casefold() in l["text"].casefold()
                                                  for l in driver.ocr(driver.window_rect(current)))
        elif name == "window_open":
            results[name] = driver.find_window(window) is not None
        elif name == "has_element":
            # The page the action opened shows this element (read through UI Automation, behind his window too).
            deadline = time.monotonic() + 4
            while not (found := driver.has_element(window, str(value))) and time.monotonic() < deadline:
                time.sleep(0.4)
            results[name] = found
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
