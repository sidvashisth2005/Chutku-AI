"""App atlases (App Mastery A1): what Chutku knows about one app, as checked-in JSON (chutku/apps/atlas/<app>.json).

An atlas lists the app's ways in and its actions. Each action is a short, fixed list of steps (see runner.py) with a
risk class and a check that it worked. `validate` refuses anything malformed or unsafe: unknown step verbs, URI
schemes the app does not own, programs that are not the app's own, parameters a step uses but the action does not
declare. A refused atlas is not loaded at all (fail closed) and its problem is reported.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

ATLAS_DIR = Path(__file__).resolve().parent / "atlas"
RISK = {"safe": 1, "changes": 2, "consequential": 3, "destructive": 4}
VERBS = {"focus", "launch", "uri", "cli", "keys", "type", "click_text", "wait_text", "play_page", "sleep", "media",
         "settings_uri", "do"}
CHECKS = {"media_playing", "media_paused", "media_changed", "title_in_page", "window_title_contains", "ocr_contains",
          "process_running", "process_gone", "window_open", "playing_on_page", "heading", "title_lacks", "title_has_file",
          "has_element"}
# App Mastery 2: {"do": "<element name>", "action": ...} presses an element of the app's window by its name through UI
# Automation (desktop.do): no mouse, no keys, so it works behind the owner's window. Consequential names are refused.
DO_ACTIONS = {"click", "set_text", "toggle", "expand", "collapse"}
BACKGROUND_VERBS = {"do", "sleep"}
PARAM_TYPES = {"text", "number", "path"}
_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class AtlasError(ValueError):
    pass


def _slots(value):
    if isinstance(value, str):
        return set(_SLOT.findall(value))
    if isinstance(value, dict):
        return set().union(*(_slots(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_slots(v) for v in value)) if value else set()
    return set()


def validate(atlas: dict) -> dict:
    """Return the atlas unchanged, or raise AtlasError naming the first problem."""
    if not isinstance(atlas, dict) or not _ID.match(str(atlas.get("app", ""))):
        raise AtlasError("atlas needs an 'app' id (lowercase letters, digits, _)")
    app = atlas["app"]
    window = atlas.get("window")
    if not isinstance(window, dict) or not (window.get("exe") or window.get("title")):
        raise AtlasError(f"{app}: 'window' needs exe and/or title to find the app's window")
    schemes = set(atlas.get("uri_schemes") or [])
    programs = atlas.get("cli") or {}
    if not isinstance(programs, dict):
        raise AtlasError(f"{app}: 'cli' must map a short name to the program's file name")
    actions = atlas.get("actions")
    if not isinstance(actions, list) or not actions:
        raise AtlasError(f"{app}: no actions")
    seen = set()
    for action in actions:
        where = f"{app}.{action.get('id')}"
        if not _ID.match(str(action.get("id", ""))) or action["id"] in seen:
            raise AtlasError(f"{where}: missing or duplicate id")
        seen.add(action["id"])
        if action.get("risk") not in RISK:
            raise AtlasError(f"{where}: risk must be one of {', '.join(RISK)}")
        if not isinstance(action.get("title"), str) or not action["title"].strip():
            raise AtlasError(f"{where}: needs a title")
        params = action.get("params") or {}
        if not isinstance(params, dict) or any(not _ID.match(k) or (v or {}).get("type", "text") not in PARAM_TYPES
                                               for k, v in params.items()):
            raise AtlasError(f"{where}: params must be {{name: {{type: text|number|path}}}}")
        steps = action.get("steps")
        if not isinstance(steps, list) or not steps:
            raise AtlasError(f"{where}: needs steps")
        for step in steps:
            if not isinstance(step, dict) or len(set(step) & VERBS) != 1:
                raise AtlasError(f"{where}: each step has exactly one verb of {sorted(VERBS)}")
            verb = (set(step) & VERBS).pop()
            if verb == "uri":
                scheme = str(step["uri"]).split(":", 1)[0].casefold()
                if scheme not in schemes:
                    raise AtlasError(f"{where}: URI scheme '{scheme}' is not one of {app}'s own {sorted(schemes)}")
            if verb == "settings_uri" and not re.fullmatch(r"ms-settings:[a-z0-9\-_.]*", str(step["settings_uri"])):
                raise AtlasError(f"{where}: settings_uri must be ms-settings:<page>")
            if verb == "cli":
                command = step["cli"]
                if not isinstance(command, list) or not command or command[0] not in programs:
                    raise AtlasError(f"{where}: cli must start with one of {app}'s programs {sorted(programs)}")
            if verb == "keys":
                from chutku.tools.free_input import parse_keys
                try:
                    parse_keys(step["keys"])
                except ValueError as error:
                    raise AtlasError(f"{where}: {error}") from error
            area = step.get("area")
            if area is not None and not (isinstance(area, list) and len(area) == 4
                                         and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in area)
                                         and area[0] < area[2] and area[1] < area[3]):
                raise AtlasError(f"{where}: area is [left, top, right, bottom] as fractions of the window")
            if verb == "sleep" and not (isinstance(step["sleep"], (int, float)) and 0 < step["sleep"] <= 5):
                raise AtlasError(f"{where}: sleep is 0-5 seconds")
            if verb == "play_page" and step["play_page"] not in (True, "playlist"):
                raise AtlasError(f"{where}: play_page is true or 'playlist' (open the first playlist result first)")
            if verb == "media" and step["media"] not in {"play", "pause", "play_pause", "next", "previous"}:
                raise AtlasError(f"{where}: media is play/pause/play_pause/next/previous")
            if verb == "launch" and step["launch"] not in (True, "behind"):
                raise AtlasError(f"{where}: launch is true (in front) or 'behind' (behind the owner's window)")
            if verb == "do":
                from chutku.tools.screen_vision import RISKY
                name = step["do"]
                if not isinstance(name, str) or not name.strip() or len(name) > 120:
                    raise AtlasError(f"{where}: do names the element (1-120 characters)")
                if step.get("action", "click") not in DO_ACTIONS:
                    raise AtlasError(f"{where}: do action is one of {sorted(DO_ACTIONS)}")
                if (step.get("action") == "set_text") != ("text" in step):
                    raise AtlasError(f"{where}: do set_text needs text, and only set_text takes text")
                if RISKY.search(fill_free(name)):
                    raise AtlasError(f"{where}: '{name}' looks consequential: do never presses it")
        used = _slots(steps) | _slots(action.get("check") or {})
        if used - set(params):
            raise AtlasError(f"{where}: steps use undeclared params {sorted(used - set(params))}")
        check = action.get("check") or {}
        if not isinstance(check, dict) or set(check) - CHECKS:
            raise AtlasError(f"{where}: check keys must be from {sorted(CHECKS)}")
        if not check and action["risk"] != "safe":
            raise AtlasError(f"{where}: a {action['risk']} action needs a check")
        drill = action.get("drill") or {}
        if not isinstance(drill, dict) or set(drill) - set(params):
            raise AtlasError(f"{where}: drill values must be for declared params")
        lab = action.get("lab") or {}
        pair = lab.get("pair", False) if isinstance(lab, dict) else None
        if not isinstance(lab, dict) or set(lab) - {"skip", "pair", "setup", "after"} or not (pair in (True, False)
                                                                                            or pair in (1, 2, 3)):
            raise AtlasError(f"{where}: lab is {{skip: reason}}, {{pair: true|1-3}}, {{setup|after: action id}}")
        for role in ("setup", "after"):
            if lab.get(role):
                helper = next((a for a in actions if a.get("id") == lab[role]), None)
                if not helper or helper.get("risk") != "safe" or helper.get("params"):
                    raise AtlasError(f"{where}: lab {role} must be a safe action without parameters")
        if action.get("fallback"):
            # 20x plan: when the action's text never appeared (nothing clicked), this other action runs instead
            other = next((a for a in actions if a.get("id") == action["fallback"]), None)
            if not other or other is action or other.get("risk") != "safe" or other.get("fallback")                     or set(other.get("params") or {}) - set(params):
                raise AtlasError(f"{where}: fallback must be another safe action, without its own fallback, "
                                 "using only this action's params")
        if _slots(action.get("done") or "") - set(params):
            raise AtlasError(f"{where}: the done reply may only use declared params")
        phrases = action.get("phrases") or []
        if not isinstance(phrases, list) or any(_slots(p) - set(params) for p in phrases):
            raise AtlasError(f"{where}: phrases may only use declared params")
    return atlas


def fill_free(text):
    """The text with {slots} removed (a risky word must not hide next to a slot)."""
    return _SLOT.sub(" ", str(text))


def background_only(action: dict) -> bool:
    """Steps that never need the screen, mouse or keyboard: UI Automation `do` steps (and pauses), after the app was
    opened behind the owner's window. Such an action runs in its app's own lane, beside other tasks."""
    steps = action.get("steps") or []
    return any("do" in s for s in steps) and all(
        (set(s) & VERBS) <= BACKGROUND_VERBS or s.get("launch") == "behind" for s in steps)


def load_all(directory: Path = ATLAS_DIR) -> tuple[dict, dict]:
    """({app: atlas} for every valid atlas, {file: error} for every refused one)."""
    atlases, errors = {}, {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            atlas = validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:   # AtlasError and JSON errors are ValueErrors
            errors[path.name] = str(error)
            continue
        atlases[atlas["app"]] = atlas
    return atlases, errors


def param_schema(action: dict) -> dict:
    properties = {}
    for name, spec in (action.get("params") or {}).items():
        kind = (spec or {}).get("type", "text")
        properties[name] = {"type": "number"} if kind == "number" else {"type": "string", "minLength": 1,
                                                                         "maxLength": 300}
    return {"type": "object", "properties": properties, "required": sorted(properties),
            "additionalProperties": False}
