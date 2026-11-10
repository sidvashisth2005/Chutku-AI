"""App Mastery 2, step 5 (owner 2026-11-10: "practice over all the layouts dedicatedly: each button, what it does, how
it does, forward, backward, undo everything"): learn each app's pages and buttons through UI Automation and save
data/apps/<app>/uimap.json for the atlas generator. A plain script: no model, no Claude tokens.

    python scripts/app_survey.py [--apps notepad,calculator] [--probe] [--idle 60]

map (always): open the app behind the owner's window, read every element of its home page, visit each navigation
item (tabs, tree and list items in a navigation pane), read that page, and check that Back returns home (forward /
backward). Nothing is typed; consequential names (screen_vision.RISKY) and the extra DO_NOT_PRESS words are never
touched.

probe (--probe, and only while the owner is idle): on each page press every remaining safe element once, record what
changed (new elements, a new window, a state), then undo it (toggle again / collapse / Back / the new window's own
Close or Cancel) and check that the page is as before. The first change that cannot be undone stops probing that app
(it is reported, never "fixed" by guessing). Apps whose buttons change the real system (Settings, Task Manager, Store,
mail) are mapped only: their actions go through ms-settings links and Chutku's own setting tools.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chutku import background_desk  # noqa: E402
from chutku.tools import desktop  # noqa: E402
from chutku.tools.screen_vision import RISKY  # noqa: E402

# id: (Start-menu name, may be probed)
APPS = {
    "calculator": ("Calculator", True), "clock": ("Clock", True), "paint": ("Paint", True),
    "photos": ("Photos", True), "weather": ("Weather", True), "snipping": ("Snipping Tool", True),
    # mapped only: they restore or edit the owner's own files, make sound, or change the real system
    "notepad": ("Notepad", False), "media_player": ("Media Player", False), "sticky_notes": ("Sticky Notes (new)", False),
    "todo": ("Microsoft To Do", False), "explorer": ("File Explorer", False), "word": ("Word", False),
    "excel": ("Excel", False), "powerpoint": ("PowerPoint", False), "onenote": ("OneNote", False),
    "sound_recorder": ("Sound Recorder", False), "calendar": ("Calendar", False), "settings": ("Settings", False),
    "task_manager": ("Task Manager", False), "store": ("Microsoft Store", False), "outlook": ("Outlook", False),
    "mail": ("Mail", False), "vscode": ("Visual Studio Code", False), "vlc": ("VLC media player", False),
    "clipchamp": ("Microsoft Clipchamp", False),
}
NAV_ROLES = {"tab", "tabitem", "treeitem", "listitem", "option"}
OPENER = re.compile(r"^(?:open )?navigation$|^open menu$|^(?:main )?menu$", re.I)
PRESS_ROLES = {"button", "checkbox", "switch", "togglebutton", "menuitem", "splitbutton", "hyperlink", "radiobutton"}
# Beyond RISKY: things whose effect reaches outside the app or cannot be put back by the app itself.
DO_NOT_PRESS = re.compile(
    r"\b(?:clear|block|report|disconnect|forget|turn off|airplane|flight mode|bluetooth|wi-?fi|network|vpn|power|"
    r"sleep|hibernate|lock|exit|quit|end task|close all|sync|backup|restore|repair|troubleshoot|recover|save|"
    r"print|export|upload|download|record|camera|microphone|start recording|stop|new window|open in|account|"
    r"profile|feedback|rate|sign ?in|log ?in|minimi[sz]e|maximi[sz]e|close|move|rename|replace|set as|default|"
    r"pin|unpin|share|start|play|pause|resume|mute|volume|new|add|create|edit|paste|cut|undo|redo)\b", re.I)
PAGE_LIMIT, PROBE_LIMIT, APP_SECONDS = 20, 60, 360


def idle():
    return background_desk.idle_seconds()


def snapshot(window):
    data = desktop.call("snapshot", "--window-id", window["id"], "--compact", "--timeout-ms", "8000")
    elements = []

    def walk(node, path):
        name, role = str(node.get("name") or "")[:80], str(node.get("role") or "")
        if node.get("ref_id") and (name or role in PRESS_ROLES):
            elements.append({"ref": node["ref_id"], "role": role, "name": name, "path": path[-2:],
                             "actions": [a.lower() for a in node.get("available_actions", []) if a != "SetFocus"],
                             "states": [s for s in node.get("states", []) if s in {"checked", "selected", "expanded",
                                                                                     "disabled"}]})
        for child in node.get("children", []):
            walk(child, path + ([name] if name else []))
    walk(data.get("tree") or {}, [])
    return elements


def shape(elements):
    return sorted({(e["role"], e["name"]) for e in elements})


def act(ref, verb):
    """(delivery, focus steals). A refused or stale element is an answer, not a crash: ('error: ...', 0)."""
    try:
        data, steals = background_desk.guarded(lambda: desktop.call(desktop.VERBS[verb], ref))
    except OSError as error:   # AMBIGUOUS_TARGET (two same-named tabs), STALE_REF (the page redrew)
        return f"error: {str(error)[:120]}", 0
    return (data.get("disposition") or {}).get("delivery", ""), len(steals)


def touchable(element):
    name = element["name"]
    return bool(name) and not RISKY.search(name) and not DO_NOT_PRESS.search(name) and "disabled" not in element["states"]


def by_name(window, name, roles):
    return next((e for e in snapshot(window) if e["name"] == name and e["role"] in roles), None)


def windows():
    return {w["id"]: w for w in desktop.call("list-windows") if w.get("visible", True)}


def go_back(window, home):
    """Back to the home page: the Back button, else the first navigation item again. True when the shape returned."""
    back = by_name(window, "Back", {"button"})
    if back and "disabled" not in back["states"]:
        act(back["ref"], "click")
        time.sleep(0.6)
    return len(set(shape(snapshot(window))) ^ set(home)) <= max(3, len(home) // 10)


def read_menus(window, elements, report):
    """Open each top-level menu, note its items, close it again (a menu shows on top: owner idle only)."""
    menus = {}
    for menu in [e for e in elements if e["role"] in {"menuitem", "menubutton"} and "expand" in e["actions"]
                 and touchable(e) and e["name"] != "System"][:12]:
        before = set(shape(snapshot(window)))
        try:
            act(menu["ref"], "expand")
            time.sleep(0.5)
            items = sorted(f"{r}:{n}" for r, n in set(shape(snapshot(window))) - before)
            again = by_name(window, menu["name"], {menu["role"]})
            if again and "collapse" in again["actions"]:
                act(again["ref"], "collapse")
        except OSError as error:
            items = [f"error: {str(error)[:100]}"]
        menus[menu["name"]] = items[:60]
    report["menus"] = menus


def settle(window, seconds=10.0):
    """The app's real window once its page stopped changing: a splash window is replaced by the main one (Excel,
    Calendar: WINDOW_NOT_FOUND on the first id) and a page fills in over a few seconds (To Do read 4 elements)."""
    exe, deadline, last = window.get("app_name"), time.monotonic() + seconds, None
    while True:
        try:
            count = len(snapshot(window))
        except OSError:
            count = None
            again = [w for w in windows().values() if w.get("app_name") == exe and w.get("title")]
            window = again[0] if again else window
        if count is not None and count == last and count >= 8:
            return window
        if time.monotonic() > deadline:
            return window
        last = count
        time.sleep(1.0)


def survey_app(key, start_name, probe, launch, menus=False):
    started = time.monotonic()
    report = {"app": key, "start_menu": start_name, "at": datetime.now().isoformat(timespec="seconds"),
              "pages": {}, "probes": [], "problems": []}
    before = windows()
    info = launch(start_name)
    if not info:
        report["problems"].append("did not open behind the owner's window")
        return report
    window = next((w for w in windows().values() if w["id"] not in before and w.get("title")), None) \
        or next((w for w in windows().values() if w.get("title") == info.get("title")), None)
    if window is None:
        report["problems"].append("no window listed")
        return report
    opened_here = window["id"] not in before
    window = settle(window)
    report["window"] = {"exe": window.get("app_name"), "title": window.get("title")}
    try:
        home_elements = snapshot(window)
        opener = next((e for e in home_elements if e["role"] == "button" and OPENER.match(e["name"])), None)
        if opener:   # Calculator folds its modes behind "Open Navigation"
            act(opener["ref"], "click")
            time.sleep(0.6)
            home_elements = snapshot(window)
            report["navigation_opener"] = opener["name"]
        if menus:
            read_menus(window, home_elements, report)
            home_elements = snapshot(window)
        home = shape(home_elements)
        start = next((e["name"] for e in home_elements if e["role"] in NAV_ROLES and "selected" in e["states"]), None)
        report["pages"]["home"] = {"via": [], "elements": [f"{e['role']}:{e['name']}" for e in home_elements][:200]}
        report["lane"] = "uia" if len(home_elements) >= 8 else "ocr"
        nav = [e for e in home_elements if e["role"] in NAV_ROLES and touchable(e)
               and {"click", "select", "invoke"} & set(e["actions"])][:PAGE_LIMIT]
        for item in nav:
            if time.monotonic() - started > APP_SECONDS:
                report["problems"].append("time budget reached while mapping")
                break
            target = by_name(window, item["name"], NAV_ROLES)
            if target is None:
                continue
            verb = "select" if "select" in target["actions"] and "click" not in target["actions"] else "click"
            try:
                delivery, steals = act(target["ref"], verb)
            except OSError as error:
                report["pages"][item["name"]] = {"via": [item["name"]], "error": str(error)[:160]}
                continue
            time.sleep(0.6)
            page = snapshot(window)
            new = sorted(set(shape(page)) - set(home))
            report["pages"][item["name"]] = {"via": [item["name"]], "delivery": delivery, "focus_given_back": steals,
                                             "new_elements": [f"{r}:{n}" for r, n in new][:120]}
        if len(report["pages"]) > 1:
            back = by_name(window, "Back", {"button"})
            if (back is None or "disabled" in back["states"]) and start:
                again = by_name(window, start, NAV_ROLES)    # no Back button: going "back" = the item it started on
                if again:
                    act(again["ref"], "select" if "select" in again["actions"] and "click" not in again["actions"]
                        else "click")
                    time.sleep(0.6)
            report["back_returns_home"] = go_back(window, home)
            report["started_on"] = start
        if probe:
            probe_app(window, report, started)
    finally:
        if opened_here:
            ctypes.windll.user32.PostMessageW(int(window["id"].split("-")[1]), 0x0010, 0, 0)   # WM_CLOSE
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


def probe_app(window, report, started):
    """Press each safe element once, record its effect, undo it and check the page came back."""
    page = snapshot(window)
    base = set(shape(page))
    done = 0
    for element in [e for e in page if e["role"] in PRESS_ROLES | {"menuitem"} and touchable(e)]:
        if done >= PROBE_LIMIT or time.monotonic() - started > APP_SECONDS:
            break
        if idle() < 30:
            report["problems"].append("owner came back: probing paused for this app")
            break
        current = by_name(window, element["name"], {element["role"]})
        if current is None:
            continue
        acts = set(current["actions"])
        verb = "toggle" if "toggle" in acts else "expand" if "expand" in acts else "click" if "click" in acts else None
        if verb is None:
            continue
        before_windows = set(windows())
        try:
            delivery, _ = act(current["ref"], verb)
        except OSError as error:
            report["probes"].append({"name": element["name"], "role": element["role"], "verb": verb,
                                     "error": str(error)[:160]})
            continue
        time.sleep(0.6)
        done += 1
        new_windows = [w for i, w in windows().items() if i not in before_windows]
        after = snapshot(window)
        changed = set(shape(after)) ^ base
        entry = {"name": element["name"], "role": element["role"], "verb": verb, "delivery": delivery,
                 "opens_window": [w.get("title") for w in new_windows],
                 "shows": sorted(f"{r}:{n}" for r, n in set(shape(after)) - base)[:30],
                 "hides": sorted(f"{r}:{n}" for r, n in base - set(shape(after)))[:30]}
        entry["undo"] = undo(window, current, verb, new_windows, base)
        report["probes"].append(entry)
        if entry["undo"]["ok"] is False and changed:
            report["problems"].append(f"'{element['name']}' changed the app and could not be undone: probing stopped")
            break


def undo(window, element, verb, new_windows, base):
    """Put the app back: the same toggle again, collapse, close the dialog it opened (its own Close/Cancel), or Back."""
    how = None
    try:
        if verb == "toggle":
            again = by_name(window, element["name"], {element["role"]})
            if again:
                act(again["ref"], "toggle")
                how = "toggle again"
        elif verb == "expand":
            again = by_name(window, element["name"], {element["role"]})
            if again and "collapse" in again["actions"]:
                act(again["ref"], "collapse")
                how = "collapse"
        for opened in new_windows:
            closer = next((e for e in snapshot(opened) if e["role"] == "button"
                           and e["name"].casefold() in {"cancel", "close", "no", "not now"}), None)
            if closer:
                act(closer["ref"], "click")
                how = f"its {closer['name']} button"
        if how is None and set(shape(snapshot(window))) != base:
            back = by_name(window, "Back", {"button"})
            if back and "disabled" not in back["states"]:
                act(back["ref"], "click")
                how = "Back"
    except OSError as error:
        return {"ok": False, "how": how, "error": str(error)[:120]}
    time.sleep(0.6)
    restored = len(set(shape(snapshot(window))) ^ base) <= 2
    return {"ok": restored, "how": how or ("nothing needed" if restored else None)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--apps", default=",".join(APPS))
    parser.add_argument("--probe", action="store_true", help="also press safe elements and undo them (idle only)")
    parser.add_argument("--idle", type=float, default=60.0, help="seconds without input before probing an app")
    args = parser.parse_args(argv)
    from chutku.app import create_runtime
    summary = []
    with create_runtime(ROOT) as runtime:
        def launch(name):
            result = runtime.run("apps.launch", {"name": name, "background": True}, provenance="delegated",
                                 autonomy="owner")
            return (result.get("output") or {}).get("window") if str(result.get("state")) == "COMPLETED" else None
        for key in [k.strip() for k in args.apps.split(",") if k.strip() in APPS]:
            start_name, probable = APPS[key]
            probe = args.probe and probable
            while probe and idle() < args.idle:
                time.sleep(5)            # probing waits for the owner to be away; mapping does not
            try:
                report = survey_app(key, start_name, probe, launch, menus=idle() >= args.idle)
            except (OSError, LookupError, ValueError) as error:
                report = {"app": key, "problems": [f"{type(error).__name__}: {str(error)[:200]}"]}
            path = ROOT / "data" / "apps" / key / "uimap.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
            probes = report.get("probes", [])
            line = {"app": key, "lane": report.get("lane"), "pages": len(report.get("pages", {})),
                    "elements": len((report.get("pages", {}).get("home") or {}).get("elements", [])),
                    "back_ok": report.get("back_returns_home"), "probed": len(probes),
                    "undone": sum(1 for p in probes if (p.get("undo") or {}).get("ok")),
                    "seconds": report.get("seconds"), "problems": report.get("problems", [])}
            summary.append(line)
            print(json.dumps(line, ensure_ascii=False), flush=True)
    (ROOT / "data" / "apps" / "survey-summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False),
                                                                encoding="utf-8")


if __name__ == "__main__":
    main()
