"""Act on what is already on the screen (owner, 2026-10-08): "After Party playlist screen pe hai, use play karo".

On 2026-10-07 Chutku searched Spotify again and again and played a *different* "Afterparty" playlist, although the
owner said it was already on the screen. Spotify's results showed seven look-alikes ("Afterparty" twice, "After
Party", "AFTERPARTY", "After party songs", ...). This tool never searches:

1. bring the named app to the front (if one is named) and read *its* window with Windows OCR (exact text + position);
2. pick the item whose text equals what the owner said, spacing included ("after party" -> "After Party", not
   "Afterparty"); two equal matches -> ask which one; no match -> say it is not visible (never a look-alike);
3. click it; for "play" also press the play button the vision model finds on the page that opened, and check that
   the media session now plays (Windows media controls).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import re
import time
import unicodedata

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

KINDS_SCHEMA = ("playlist", "song", "album", "artist", "podcast", "episode", "video")
_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "minLength": 1, "maxLength": 120},
    "app": {"type": "string", "maxLength": 60},
    "app_if_open": {"type": "string", "maxLength": 60},
    "action": {"type": "string", "enum": ["click", "open", "play"]},
    "kind": {"type": "string", "enum": list(KINDS_SCHEMA)}},
    "required": ["name"], "additionalProperties": False}


def norm(text, spaces=True):
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    text = " ".join(text.split())
    return text if spaces else text.replace(" ", "")


def matches(lines, name):
    """OCR lines ranked for `name`: exact text (spacing counts) first, then the same letters without spaces, then a
    line that contains the whole phrase. Returns (tier, [lines]) for the best non-empty tier, or (None, [])."""
    want, want_tight = norm(name), norm(name, spaces=False)
    exact = [l for l in lines if norm(l["text"]) == want]
    if exact:
        return "exact", exact
    tight = [l for l in lines if norm(l["text"], spaces=False) == want_tight]
    if tight:
        return "same letters", tight
    phrase = re.compile(rf"(?:^|\s){re.escape(want)}(?:\s|$)")
    contains = [l for l in lines if phrase.search(norm(l["text"]))]
    return ("contains", contains) if contains else (None, [])


KINDS = KINDS_SCHEMA


def kind_of(line, lines):
    """The item type shown on the small line just under a title ("Playlist • Siddhant", "Song • Don Toliver"),
    or None when no such line says it. Spotify lists songs, playlists and albums with the same title text."""
    x0, _y0, x1, y1 = line["rect"]
    for other in lines:
        ox0, oy0, _ox1, _oy1 = other["rect"]
        if other is not line and 0 <= oy0 - y1 <= 40 and abs(ox0 - x0) <= 60:
            for kind in KINDS:
                if re.search(rf"\b{kind}s?\b", other["text"], re.I):
                    return kind
    return None


def typed(lines, name, kind):
    """Exact-name matches whose type line says `kind` (all exact matches when no kind was asked)."""
    tier, found = matches(lines, name)
    if kind and found:
        found = [l for l in found if kind_of(l, lines) == kind]
    return tier if found else None, found


def _window_for(app):
    """(focuser, hwnd) of the first visible window whose program or title is the named app, else (None, None)."""
    from chutku.tools.everyday import Desktop
    from chutku.tools.windows_apps import WindowsDesktop
    desktop = Desktop()
    wanted = norm(app, spaces=False)
    for hwnd in desktop.windows():
        info = desktop.describe(hwnd)
        exe = norm((info.get("executable") or "").rsplit("\\", 1)[-1].rsplit(".", 1)[0], spaces=False)
        if wanted and (wanted == exe or wanted in norm(info.get("title") or "", spaces=False)):
            return WindowsDesktop(), hwnd
    return None, None


def _rect(hwnd):
    from chutku.vision import dpi_aware
    rect = w.RECT()
    with dpi_aware() as user32:   # physical pixels, the same space the clicks use
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _screen_rect():
    from chutku.vision import dpi_aware
    with dpi_aware() as user32:
        return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _ocr(rect):
    from chutku.tools.documents import ocr_lines
    left, top, right, bottom = rect
    lines = ocr_lines({"mode": "screen", "left": left, "top": top, "width": max(1, right - left),
                       "height": max(1, bottom - top)})
    # OCR boxes are relative to the captured area: make them screen coordinates.
    return [{"text": l["text"], "rect": (l["rect"][0] + left, l["rect"][1] + top, l["rect"][2] + left,
                                         l["rect"][3] + top)} for l in lines]


def _press_play(context, window_rect, page_lines):
    """On the page that opened, click its own play button (never the player bar at the bottom, which only resumes
    the current song), then check that what plays is one of the tracks shown on that page; otherwise pause again."""
    from chutku import vision
    from chutku.tools.everyday import media
    try:
        before = media("status")
    except OSError:
        before = {}
    shot = vision.capture()
    seen = vision.see(shot, "Where is the big green Play button of the playlist or album that is open (next to its "
                            "title, not the player bar at the bottom)?", None)
    vision.remember_seen(shot, seen["elements"])
    left, top, right, bottom = window_rect
    bar = bottom - (bottom - top) * 0.15        # the player bar: its play button only resumes the current song
    buttons = [e for e in seen["elements"] if re.search(r"\bplay\b", e["label"], re.I)
               and not re.search(r"\b(?:player|replay|playing|pause)\b", e["label"], re.I)
               and (e["rect"][1] + e["rect"][3]) / 2 < bar]
    if not buttons:
        return {"play_button": None, "playing": False,
                "error": "Opened it, but I could not find its own play button; press play yourself."}
    rect = buttons[0]["rect"]
    vision.click_at((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
    deadline = time.monotonic() + 5
    after = {}
    while time.monotonic() < deadline:
        time.sleep(0.5)
        try:
            after = media("status")
        except OSError:
            continue
        if after.get("status") == "Playing" and (before.get("status") != "Playing"
                                                 or after.get("title") != before.get("title")):
            break
    playing = after.get("status") == "Playing" and (before.get("status") != "Playing"
                                                    or after.get("title") != before.get("title"))
    shown = {norm(l["text"]) for l in page_lines}
    if playing and page_lines and norm(after.get("title") or "") not in shown:
        # Something started that is not on the page that opened: it is not what the owner asked for.
        try:
            media("pause")
        except OSError:
            pass
        return {"play_button": buttons[0]["label"], "playing": False, "now_playing": after.get("title"),
                "error": f"'{after.get('title')}' started, which is not on the page I opened, so I paused it."}
    return {"play_button": buttons[0]["label"], "playing": playing, "now_playing": after.get("title"),
            "artist": after.get("artist")}


def _act(arguments, context):
    name, action = arguments["name"], arguments.get("action", "click")
    app = arguments.get("app")
    if not app and arguments.get("app_if_open") and _window_for(arguments["app_if_open"])[1] is not None:
        app = arguments["app_if_open"]   # "play X" with Spotify open: read Spotify, not other windows' text
    rect = _screen_rect()
    if app:
        desktop, hwnd = _window_for(app)
        if hwnd is None:
            return ToolResult({"error": f"{app} is not open, so '{name}' cannot be on the screen. I did not search."},
                              Verification.FAIL)
        desktop.focus(hwnd)
        time.sleep(0.8)
        rect = _rect(hwnd)
    from chutku import vision
    kind = arguments.get("kind")
    lines = _ocr(rect)
    tier, found = typed(lines, name, kind)
    if not found and kind:
        # Search results mix songs, playlists and albums with the same title: open the filter for the asked type.
        chip = [l for l in lines if norm(l["text"]) in {kind + "s", kind}]
        if chip:
            cx0, cy0, cx1, cy1 = chip[0]["rect"]
            vision.click_at((cx0 + cx1) // 2, (cy0 + cy1) // 2)
            time.sleep(1.5)
            lines = _ocr(rect)
            tier, found = typed(lines, name, kind)
    if not found:
        same_name = [l for l in lines if norm(l["text"]) == norm(name)]
        others = sorted({kind_of(l, lines) or "unlabelled" for l in same_name})
        if kind and same_name:
            shown = " / ".join("something without a type label" if o == "unlabelled" else f"a {o}" for o in others)
            error = (f"I can see '{name}' on the screen, but as {shown}, not as a {kind}; I clicked nothing and did "
                     f"not search. Open the screen where the {kind} is shown and ask again.")
        else:
            error = f"'{name}' is not visible{' in ' + app if app else ''}; I clicked nothing and did not search."
        close = sorted({l["text"] for l in lines if norm(name, spaces=False)[:5] in norm(l["text"], spaces=False)})[:6]
        return ToolResult({"error": error, "similar_on_screen": close}, Verification.FAIL)
    if len(found) > 1:
        return ToolResult({"error": f"{len(found)} items read '{found[0]['text']}' on the screen; say which one "
                                    "(first, second ...).", "candidates": [l["text"] for l in found],
                           "match": tier}, Verification.FAIL)
    target = found[0]
    x0, y0, x1, y1 = target["rect"]
    before = vision.capture()
    vision.click_at((x0 + x1) // 2, (y0 + y1) // 2)
    time.sleep(1.2)
    after = vision.capture()
    output = {"clicked": target["text"], "kind": kind_of(target, lines), "match": tier,
              "at": [(x0 + x1) // 2, (y0 + y1) // 2], "screen_changed": vision.changed(before, after)}
    if action == "play":
        page = _ocr(rect)   # the page that opened: what plays must be one of its tracks
        output.update(_press_play(context, rect, page))
        return ToolResult(output, Verification.PASS if output.get("playing") else Verification.FAIL)
    return ToolResult(output, Verification.PASS if output["screen_changed"] else Verification.UNKNOWN)


def _validate(arguments):
    if set(arguments) - {"name", "app", "app_if_open", "action", "kind"} or not isinstance(arguments.get("name"), str) \
            or not 0 < len(arguments["name"].strip()) <= 120:
        raise ValueError("Give the name exactly as shown on screen (and optionally app and action).")
    if arguments.get("action", "click") not in {"click", "open", "play"}:
        raise ValueError("action is click, open or play.")


def register_visible_tools(registry):
    registry.register(Tool("screen.act_on_visible", "Act on an item that is ALREADY visible on screen (or in the "
        "named app's window), found by its exact text: click/open it, or play it (presses its play button and checks "
        "that music plays). Never searches. Use when the owner says it is on the screen / visible / 'jo dikh raha "
        "hai'. Fails, without guessing, if the exact text is not visible or appears twice.",
        Risk.REVERSIBLE, _act, _validate, required_capability="desktop.input", argument_schema=_SCHEMA,
        prerequisites=("interactive Windows desktop",), reversibility="transient",
        success_predicate="exact_visible_item_clicked_and_checked"))
