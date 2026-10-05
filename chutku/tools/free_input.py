"""General keyboard and mouse for Chutku (owner request 2026-10-04): any shortcut, and clicks on anything visible.

    keyboard.keys   "ctrl+shift+t", "win+d", "f5", "alt+tab", "ctrl+k, ctrl+c" (a short sequence), repeat N times
    mouse.click     the text seen on screen ("Submit", "Downloads") or a point; left/right/middle, double
    mouse.drag      from a point/text to a point/text
    mouse.move      move the pointer (hover)

Text targets are found with local Windows OCR of the screen (never sent anywhere). Keys go to the window in front;
Windows itself blocks input into elevated (admin) windows, and Ctrl+Alt+Del cannot be sent.

``file_risk`` says when an input could change or delete files (saving, Delete/rename/cut/paste/drag in File
Explorer, clicking a "Delete"/"Uninstall"/"Save" button): owner mode asks first for those (the owner's rule).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

CTRL, SHIFT, ALT, WIN = 0x11, 0x10, 0x12, 0x5B
MODIFIERS = {"ctrl": CTRL, "control": CTRL, "shift": SHIFT, "alt": ALT, "win": WIN, "windows": WIN, "super": WIN,
             "cmd": WIN, "start": WIN}
KEYS = {
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "spacebar": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
    "right": 0x27, "printscreen": 0x2C, "prtsc": 0x2C, "capslock": 0x14, "numlock": 0x90, "menu": 0x5D, "apps": 0x5D,
    "plus": 0xBB, "equals": 0xBB, "=": 0xBB, "minus": 0xBD, "-": 0xBD, "comma": 0xBC, ",": 0xBC, "period": 0xBE,
    "dot": 0xBE, ".": 0xBE, "slash": 0xBF, "/": 0xBF, "backslash": 0xDC, "\\": 0xDC, "semicolon": 0xBA, ";": 0xBA,
    "quote": 0xDE, "'": 0xDE, "backtick": 0xC0, "grave": 0xC0, "`": 0xC0, "[": 0xDB, "]": 0xDD,
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD, "mute": 0xAD, "playpause": 0xB3, "nexttrack": 0xB0,
    "prevtrack": 0xB1, "previoustrack": 0xB1,
}
KEYS.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})   # virtual-key codes are the capitals
KEYS.update({str(d): 0x30 + d for d in range(10)})
KEYS.update({f"f{n}": 0x6F + n for n in range(1, 25)})
MAX_COMBOS, MAX_REPEAT = 6, 30
_DESTRUCTIVE_WORDS = re.compile(r"\b(?:delete|remove|uninstall|erase|discard|format|wipe|permanently|empty recycle bin|"
                                r"move to (?:the )?recycle bin|clear all|reset|save|save as|replace|overwrite|rename|"
                                r"hatao|mitao)\b", re.I)
_FILE_MANAGERS = {"explorer.exe"}
_APPROVAL_WORDS = re.compile(r"\b(?:approve|allow|confirm|grant|yes|haan|accept)\b", re.I)


def parse_keys(text):
    """'ctrl+shift+t, f5' -> [[CTRL, SHIFT, 0x54], [0x74]]; raises ValueError for anything unknown."""
    combos = []
    for part in re.split(r"\s*(?:,|\bthen\b|\bphir\b)\s*", str(text).strip().casefold()):
        if not part:
            continue
        names = [n for n in re.split(r"\s*\+\s*|\s+", part) if n]
        if not names:
            continue
        keys, mods = [], []
        for name in names:
            if name in MODIFIERS:
                code = MODIFIERS[name]
                if code not in mods:
                    mods.append(code)
            elif name in KEYS:
                keys.append(KEYS[name])
            else:
                raise ValueError(f"Unknown key '{name}'. Use names like ctrl, shift, alt, win, a-z, 0-9, f1-f24, "
                                 "enter, esc, tab, space, delete, up/down/left/right, pageup, home, end.")
        if not keys and not mods:
            continue
        if CTRL in mods and ALT in mods and 0x2E in keys:
            raise ValueError("Ctrl+Alt+Del cannot be sent by any program.")
        combos.append(mods + keys)
    if not combos or len(combos) > MAX_COMBOS:
        raise ValueError(f"Give 1-{MAX_COMBOS} key combinations, e.g. 'ctrl+shift+t' or 'ctrl+k, ctrl+c'.")
    return combos


def _foreground():
    from chutku.tools.everyday import Desktop
    desktop = Desktop()
    info = desktop.describe(desktop.foreground())
    return desktop, info, Path(info.get("executable") or "").name.casefold()


def _text_at(x, y):
    from chutku import vision
    with _hidden():
        shot = vision.capture()
    lines = vision.read_lines(shot, (x - 160, y - 30, x + 160, y + 30))
    hits = [line["text"] for line in lines if line["rect"][0] - 4 <= x <= line["rect"][2] + 4
            and line["rect"][1] - 4 <= y <= line["rect"][3] + 4]
    return " ".join(hits)


def opens_run_box(text):
    """True when these keys include Win+R (the Run box starts programs, so it asks first)."""
    return any({0x5B, 0x52} <= set(combo) or {0x5C, 0x52} <= set(combo) for combo in parse_keys(text))


def file_risk(tool_name, arguments):
    """Why this input could change or delete files (owner mode asks first), or None."""
    try:
        if tool_name == "keyboard.edit":
            action = arguments.get("action")
            if action == "save":
                return "Saving writes a file; this asks first."
            if action in {"delete", "cut", "paste", "undo", "redo"} and _foreground()[2] in _FILE_MANAGERS:
                return "In File Explorer this key moves or deletes files; this asks first."
            return None
        if tool_name == "keyboard.keys":
            combos = parse_keys(arguments.get("keys", ""))
            for combo in combos:
                if CTRL in combo and 0x53 in combo:                     # Ctrl+S / Ctrl+Shift+S
                    return "Saving writes a file; this asks first."
            in_files = _foreground()[2] in _FILE_MANAGERS
            risky = {0x2E, 0x71}                                        # Delete, F2 (rename)
            ctrl_risky = {0x44, 0x58, 0x56, 0x5A, 0x59}                 # Ctrl+D/X/V/Z/Y
            if in_files and any(set(c) & risky or (CTRL in c and set(c) & ctrl_risky) for c in combos):
                return "In File Explorer these keys delete, rename or move files; this asks first."
            return None
        if tool_name == "mouse.click":
            target = arguments.get("text") or _text_at(arguments.get("x", -1), arguments.get("y", -1))
            if target and _DESTRUCTIVE_WORDS.search(target):
                return f"Clicking “{target[:40]}” could delete or change files; this asks first."
            if target and _APPROVAL_WORDS.search(target):
                return f"Clicking “{target[:40]}” approves something; this asks first."
            return None
        if tool_name == "mouse.drag" and _foreground()[2] in _FILE_MANAGERS:
            return "Dragging in File Explorer moves files; this asks first."
    except (OSError, ValueError):
        return "Chutku could not check what this input would do; this asks first."  # fail closed
    return None


def _hidden():
    from chutku.hud import hud_hidden
    return hud_hidden()


# -- keyboard ----------------------------------------------------------------------------

def _validate_keys(arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"keys", "repeat"} or not isinstance(arguments.get("keys"), str):
        raise ValueError("Give keys (e.g. 'ctrl+shift+t') and optional repeat.")
    if "repeat" in arguments and not (type(arguments["repeat"]) is int and 1 <= arguments["repeat"] <= MAX_REPEAT):
        raise ValueError(f"repeat must be 1-{MAX_REPEAT}.")
    parse_keys(arguments["keys"])


def _keys(arguments, context):
    from chutku.tools.desktop_controls import command_window_reason, press_combo
    combos = parse_keys(arguments["keys"])
    try:
        _desktop, info, exe = _foreground()
        if not getattr(context, "approved", False) and command_window_reason(info):
            return ToolResult({"error": "The window in front is a command window; Chutku presses keys there only "
                                        "after you confirm."}, Verification.FAIL)
        for _ in range(arguments.get("repeat", 1)):
            for combo in combos:
                press_combo(combo)
                time.sleep(0.08)
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    output = {"keys": arguments["keys"], "repeat": arguments.get("repeat", 1), "app": exe,
              "window": (info.get("title") or "")[:120]}
    return ToolResult(output, Verification.PASS, output | {"window": "[REDACTED]"})


# -- mouse ---------------------------------------------------------------------------------

def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def find_text(lines, wanted, nth=None):
    """The screen point of the visible text ``wanted``: exact line first, else the words inside a longer line.
    Several matches need ``nth`` (1 = first, top to bottom, left to right)."""
    target = _norm(wanted)
    if not target:
        raise ValueError("Say which text to click.")
    exact = [line for line in lines if _norm(line["text"]) == target]
    matches = exact or [line for line in lines if re.search(rf"(?:^| ){re.escape(target)}(?: |$)", _norm(line["text"]))]
    matches.sort(key=lambda line: (line["rect"][1] // 12, line["rect"][0]))
    if not matches:
        raise ValueError(f"I can't see “{wanted}” on the screen.")
    if len(matches) > 1 and nth is None:
        raise ValueError(f"“{wanted}” appears {len(matches)} times on screen; say which one (1st, 2nd...).")
    if nth is not None and not 1 <= nth <= len(matches):
        raise ValueError(f"“{wanted}” appears only {len(matches)} time(s).")
    line = matches[(nth or 1) - 1]
    x0, y0, x1, y1 = line["rect"]
    text = _norm(line["text"])
    start = text.find(target) if line not in exact else 0
    if line not in exact and start >= 0 and text:  # point at the words inside the longer line
        centre = (start + len(target) / 2) / len(text)
        return int(x0 + (x1 - x0) * centre), (y0 + y1) // 2, line["text"]
    return (x0 + x1) // 2, (y0 + y1) // 2, line["text"]


def _screen_lines():
    from chutku import vision
    with _hidden():
        shot = vision.capture()
    return shot, vision.read_lines(shot, (shot.left, shot.top, shot.left + shot.width, shot.top + shot.height))


def _point(arguments, prefix=""):
    text = arguments.get(prefix + "text")
    if text:
        _shot, lines = _screen_lines()
        x, y, seen = find_text(lines, text, arguments.get(prefix + "nth"))
        return x, y, seen
    return arguments[prefix + "x"], arguments[prefix + "y"], None


def _validate_target(arguments, prefix=""):
    has_text = isinstance(arguments.get(prefix + "text"), str) and 1 <= len(arguments[prefix + "text"].strip()) <= 80
    has_xy = all(type(arguments.get(prefix + k)) is int and -20000 <= arguments[prefix + k] <= 20000 for k in "xy")
    if has_text == has_xy:
        raise ValueError(f"Give either {prefix}text (visible words) or {prefix}x and {prefix}y.")
    nth = arguments.get(prefix + "nth")
    if nth is not None and not (type(nth) is int and 1 <= nth <= 20):
        raise ValueError("nth must be 1-20.")


def _validate_click(arguments):
    allowed = {"text", "x", "y", "nth", "button", "double"}
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        raise ValueError("Give text or x/y, and optional nth, button (left/right/middle), double.")
    _validate_target(arguments)
    if arguments.get("button", "left") not in {"left", "right", "middle"} or type(arguments.get("double", False)) is not bool:
        raise ValueError("button is left, right or middle; double is true/false.")


def _click(arguments, _context):
    from chutku import vision
    from chutku.tools.desktop_controls import own_window_at
    try:
        x, y, seen = _point(arguments)
        if own_window_at(x, y):
            return ToolResult({"error": "That point is on Chutku's own window; Chutku never clicks there."},
                              Verification.FAIL)
        with _hidden():
            before = vision.capture()
            vision.click_at(x, y, arguments.get("button", "left"), arguments.get("double", False))
            time.sleep(0.35)
            after = vision.capture()
    except (OSError, ValueError, KeyError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult({"clicked": seen or f"point {x},{y}", "x": x, "y": y, "button": arguments.get("button", "left"),
                       "double": arguments.get("double", False), "screen_changed": vision.changed(before, after)},
                      Verification.PASS)


def _validate_drag(arguments):
    allowed = {f"{p}{k}" for p in ("from_", "to_") for k in ("text", "x", "y", "nth")}
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        raise ValueError("Give from_text or from_x/from_y, and to_text or to_x/to_y.")
    _validate_target(arguments, "from_")
    _validate_target(arguments, "to_")


def _drag(arguments, _context):
    from chutku import vision
    try:
        x0, y0, _ = _point(arguments, "from_")
        x1, y1, _ = _point(arguments, "to_")
        with _hidden(), vision.dpi_aware() as user32:
            user32.SetCursorPos(int(x0), int(y0))
            time.sleep(0.05)
            vision._send((0x0002, 0))                                  # left down
            for step in range(1, 21):                                  # glide so apps see a real drag
                user32.SetCursorPos(int(x0 + (x1 - x0) * step / 20), int(y0 + (y1 - y0) * step / 20))
                time.sleep(0.015)
            vision._send((0x0004, 0))                                  # left up
    except (OSError, ValueError, KeyError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult({"from": [x0, y0], "to": [x1, y1]}, Verification.PASS)


def _validate_move(arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"text", "x", "y", "nth"}:
        raise ValueError("Give text or x/y.")
    _validate_target(arguments)


def _move(arguments, _context):
    from chutku import vision
    try:
        x, y, seen = _point(arguments)
        with vision.dpi_aware() as user32:
            user32.SetCursorPos(int(x), int(y))
    except (OSError, ValueError, KeyError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult({"pointer": [x, y], "over": seen}, Verification.PASS)


def _target_schema(prefix=""):
    return {prefix + "text": {"type": "string", "minLength": 1, "maxLength": 80},
            prefix + "x": {"type": "integer"}, prefix + "y": {"type": "integer"},
            prefix + "nth": {"type": "integer", "minimum": 1, "maximum": 20}}


def register_free_input_tools(registry):
    registry.register(Tool("keyboard.keys", "Press any key combination(s) in the window in front, e.g. 'ctrl+shift+t', "
        "'win+d', 'alt+tab', 'f5', 'ctrl+k, ctrl+c' (up to 6, comma-separated), optionally repeated (repeat 1-30). "
        "Not for typing text (use keyboard.type_text).",
        Risk.EXTERNAL_SIDE_EFFECT, _keys, _validate_keys, required_capability="desktop.input",
        argument_schema={"type": "object", "properties": {"keys": {"type": "string", "minLength": 1, "maxLength": 80},
                                                          "repeat": {"type": "integer", "minimum": 1, "maximum": MAX_REPEAT}},
                         "required": ["keys"], "additionalProperties": False},
        prerequisites=("interactive Windows desktop",), reversibility="application_dependent",
        success_predicate="keys_delivered_to_foreground_window"))
    registry.register(Tool("mouse.click", "Click visible text on the screen (found with local OCR; nth picks among "
        "repeats) or a screen point x/y. button left/right/middle, double for a double-click.",
        Risk.EXTERNAL_SIDE_EFFECT, _click, _validate_click, required_capability="desktop.input",
        argument_schema={"type": "object", "properties": _target_schema() | {
            "button": {"type": "string", "enum": ["left", "right", "middle"]}, "double": {"type": "boolean"}},
            "additionalProperties": False},
        prerequisites=("interactive Windows desktop",), reversibility="application_dependent",
        success_predicate="click_delivered_at_located_target"))
    registry.register(Tool("mouse.drag", "Drag with the left button from visible text or a point to visible text or a "
        "point (e.g. a slider, a window edge, a file onto a folder).",
        Risk.EXTERNAL_SIDE_EFFECT, _drag, _validate_drag, required_capability="desktop.input",
        argument_schema={"type": "object", "properties": _target_schema("from_") | _target_schema("to_"),
                         "additionalProperties": False},
        prerequisites=("interactive Windows desktop",), reversibility="application_dependent",
        success_predicate="drag_delivered"))
    registry.register(Tool("mouse.move", "Move the mouse pointer over visible text or a point (hover, no click).",
        Risk.REVERSIBLE, _move, _validate_move, required_capability="desktop.input",
        argument_schema={"type": "object", "properties": _target_schema(), "additionalProperties": False},
        prerequisites=("interactive Windows desktop",), reversibility="transient",
        success_predicate="pointer_moved"))
