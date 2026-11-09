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
    if contains:
        return "contains", contains
    # OCR misreads (live 2026-11-10: "LowKey" read as "I-owKey", "lofi" as "Iofi"): the one clearly closest line
    import difflib
    scored = sorted(((difflib.SequenceMatcher(None, want_tight, norm(l["text"], spaces=False)).ratio(), i)
                     for i, l in enumerate(lines) if len(want_tight) >= 4), reverse=True)
    if scored and scored[0][0] >= 0.8 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.08):
        return "close", [lines[scored[0][1]]]
    return None, []


KINDS = KINDS_SCHEMA


def kind_of(line, lines):
    """The item type shown on the small line just under a title ("Playlist • Alex", "Song • Don Toliver"),
    or None when no such line says it. Spotify lists songs, playlists and albums with the same title text."""
    x0, _y0, x1, y1 = line["rect"]
    for other in lines:
        ox0, oy0, _ox1, _oy1 = other["rect"]
        if other is not line and 0 <= oy0 - y1 <= 40 and abs(ox0 - x0) <= 60:
            for kind in KINDS:
                if re.search(rf"\b{kind}s?\b", other["text"], re.I):
                    return kind
            if re.search(r"\b(?:single|ep)\b", other["text"], re.I):
                return "album"   # Spotify labels short albums "Single • artist" / "EP • artist"
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


def green_play_button(shot, window_rect):
    """Spotify's own big green play button (#1ED760) above the player bar, found by its colour in ~50 ms (the vision
    model took 70 s for this, live 2026-11-10). The topmost round green disc of button size, as a screen rect."""
    import numpy as np
    if getattr(shot, "pixels", None) is None:
        return None
    left, top, right, bottom = window_rect
    bar = int(bottom - (bottom - top) * 0.15)
    x0, y0 = max(0, left - shot.left), max(0, top - shot.top)
    x1, y1 = min(shot.width, right - shot.left), min(shot.height, bar - shot.top)
    if x1 - x0 < 40 or y1 - y0 < 40:
        return None
    px = shot.pixels[y0:y1:2, x0:x1:2, :3].astype(np.int16)   # every 2nd pixel: plenty for a 40+ px disc
    green = (px[..., 1] > 160) & (px[..., 0] < 110) & (px[..., 2] < 150) & (px[..., 1] - px[..., 0] > 90)
    ys, xs = np.nonzero(green)
    if not len(ys):
        return None
    seen, blobs = set(), []
    points = set(zip(ys.tolist(), xs.tolist()))
    for start in sorted(points):
        if start in seen:
            continue
        stack, blob = [start], []
        seen.add(start)
        while stack:
            y, x = stack.pop()
            blob.append((y, x))
            for nxt in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if nxt in points and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        by, bx = [p[0] for p in blob], [p[1] for p in blob]
        h, w = max(by) - min(by) + 1, max(bx) - min(bx) + 1
        if 12 <= w <= 50 and 12 <= h <= 50 and 0.75 <= w / h <= 1.33 and len(blob) >= 0.5 * w * h:
            blobs.append((min(by), min(bx), max(by), max(bx)))
    if not blobs:
        return None
    t, l, b, r = min(blobs)
    return (shot.left + x0 + 2 * l, shot.top + y0 + 2 * t, shot.left + x0 + 2 * r, shot.top + y0 + 2 * b)


def _press_play(context, window_rect, page_lines, match=None):
    """On the page that opened, click its own play button (never the player bar at the bottom, which only resumes
    the current song), then check that what plays is one of the tracks shown on that page; otherwise pause again.
    ``match`` names the app's own media session (Spotify), so a movie in the browser is never read or paused."""
    from chutku import vision
    from chutku.tools.everyday import media
    try:
        before = media("status", match)
    except OSError:
        before = {}
    shown_before = {norm(l["text"]) for l in page_lines}
    playing_title = norm(before.get("title") or "")
    if before.get("status") == "Playing" and playing_title and any(
            seen == playing_title or (len(seen) >= 20 and playing_title.startswith(seen)) for seen in shown_before):
        # Already playing one of this page's tracks: its green button is now a pause button (the lab's 2nd run
        # paused Kesariya, 2026-11-10). Nothing to press.
        return {"play_button": None, "playing": True, "already_playing": True, "now_playing": before.get("title"),
                "artist": before.get("artist")}
    shot = vision.capture()
    left, top, right, bottom = window_rect
    bar = bottom - (bottom - top) * 0.15        # the player bar: its play button only resumes the current song
    green = green_play_button(shot, window_rect)
    if green:
        buttons = [{"label": "Play (green)", "rect": green}]
    else:
        seen = vision.see(shot, "Where is the big green Play button of the playlist or album that is open (next to "
                                "its title, not the player bar at the bottom)?", None)
        vision.remember_seen(shot, seen["elements"])
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
            after = media("status", match)
        except OSError:
            continue
        if after.get("status") == "Playing" and (before.get("status") != "Playing"
                                                 or after.get("title") != before.get("title")):
            break
    playing = after.get("status") == "Playing" and (before.get("status") != "Playing"
                                                    or after.get("title") != before.get("title"))
    if playing:
        # Windows' media session shows the old title for a moment after play (live 2026-11-10: a stale
        # "Hymn for the Weekend" while Kesariya played): read it again before judging what plays.
        time.sleep(1.2)
        try:
            after = media("status", match) or after
        except OSError:
            pass
    shown = {norm(l["text"]) for l in page_lines}
    title = norm(after.get("title") or "")
    # Long titles wrap onto two lines on the page ('Kesariya (From "Brahmastra") - Tu Fuljhadiyo ...', live
    # 2026-11-10): a long page line (20+ letters) that starts the title counts. A short one never does: a song
    # "After Party (Don Toliver)" is not the "After Party" playlist's own track.
    on_page = any(seen == title or (len(seen) >= 20 and title.startswith(seen)) for seen in shown)
    if playing and page_lines and not on_page:
        # Something started that is not on the page that opened: it is not what the owner asked for.
        try:
            media("pause", match)
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
        from chutku.tools.everyday import MEDIA_APPS   # that app's own player, never the browser's movie
        output.update(_press_play(context, rect, page, MEDIA_APPS.get((app or "").casefold())))
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
        Risk.REVERSIBLE, lambda arguments, context: _act(arguments, context),   # looked up at call time
        _validate, required_capability="desktop.input", argument_schema=_SCHEMA,
        prerequisites=("interactive Windows desktop",), reversibility="transient",
        success_predicate="exact_visible_item_clicked_and_checked"))
