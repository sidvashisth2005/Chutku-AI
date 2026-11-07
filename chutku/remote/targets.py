"""What is on the laptop screen near a point, for the phone remote (owner 2026-11-08): smart tap, the magnetic
pointer and the zoom-to-text-field. Plain remote desktops only see pixels; Chutku reads the buttons, links and fields
through Windows UI Automation, so a tap a little off a small button still lands on it.

Read-only: this only looks. The click itself stays the owner's (control.py). One worker thread owns the UI
Automation object (COM is bound to its thread); a lookup that takes too long is skipped, never waited for.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import math
import threading

# UI Automation control type ids -> what the phone calls them
KINDS = {50000: "button", 50031: "button", 50002: "check", 50013: "check", 50003: "list", 50005: "link",
         50007: "item", 50011: "menu", 50019: "tab", 50024: "item", 50029: "item", 50004: "field"}
PARENTS = 3                 # text inside a button: walk up to the button
MAX_AREA = 0.25             # anything bigger than a quarter of the screen is a pane, not a target
RING = (0.5, 1.0)           # smart tap probes at half and full radius, 8 directions each

_pool = None
_lock = threading.Lock()
_local = threading.local()


def _uia():
    if getattr(_local, "ua", None) is None:
        import ctypes
        import comtypes
        import comtypes.client
        # physical pixels, like the screen capture and the taps (live 2026-11-08: at 125% display scaling a thread
        # that is not DPI aware gets every point and rectangle shrunk by 1.25, so lookups hit the wrong spot)
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
        comtypes.CoInitialize()
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
        _local.U = U
        _local.ua = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
        _local.walker = _local.ua.ControlViewWalker
    return _local


def _run(job, timeout):
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chutku-uia")
    try:
        return _pool.submit(job).result(timeout=timeout)
    except (FutureTimeout, OSError, ImportError, AttributeError, ValueError):
        return None
    except Exception:   # a COM error from an app that is closing: no target, never a failed click
        return None


def warm():
    """Start UI Automation in the background (~0.4 s the first time) so the first tap is not skipped."""
    _run(lambda: _uia() and None, 0)


def _target_at(x, y, screen_area):
    u = _uia()
    element = u.ua.ElementFromPoint(u.U.tagPOINT(int(x), int(y)))
    for _ in range(PARENTS + 1):
        if not element:
            return None
        kind = KINDS.get(element.CurrentControlType)
        rect = element.CurrentBoundingRectangle
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width > 0 and height > 0 and width * height > screen_area * MAX_AREA:
            return None
        if kind and width > 0 and height > 0 and element.CurrentIsEnabled:
            return {"kind": kind, "name": str(element.CurrentName or "")[:60], "rect": (rect.left, rect.top, width, height)}
        element = u.walker.GetParentElement(element)
    return None


def _distance(x, y, rect):
    left, top, width, height = rect
    dx = max(left - x, 0, x - (left + width - 1))
    dy = max(top - y, 0, y - (top + height - 1))
    return math.hypot(dx, dy)


def _aim(x, y, target):
    """Where to click: the tapped point when it is on the target; otherwise its middle (a field: the nearest point
    inside it, so the caret goes where you meant)."""
    left, top, width, height = target["rect"]
    if _distance(x, y, target["rect"]) == 0:
        return int(x), int(y)
    if target["kind"] == "field":
        inset = min(3, width // 2, height // 2)
        return (int(min(max(x, left + inset), left + width - 1 - inset)),
                int(min(max(y, top + inset), top + height - 1 - inset)))
    return left + width // 2, top + height // 2


def snap(x, y, radius, monitor, *, timeout=0.15):
    """The target a tap at (x, y) meant, within `radius` pixels: (click x, click y, target) or None (click as is)."""
    screen_area = monitor[2] * monitor[3]

    def job():
        here = _target_at(x, y, screen_area)
        if here or radius < 2:
            return here
        found = []
        for step in RING:
            for angle in range(8):
                px = x + math.cos(angle * math.pi / 4) * radius * step
                py = y + math.sin(angle * math.pi / 4) * radius * step
                target = _target_at(px, py, screen_area)
                if target and target not in found:
                    found.append(target)
        near = [t for t in found if _distance(x, y, t["rect"]) <= radius]
        return min(near, key=lambda t: _distance(x, y, t["rect"])) if near else None

    target = _run(job, timeout)
    if not target:
        return None
    return (*_aim(x, y, target), target)


def hover(x, y, monitor, *, timeout=0.05):
    """The target under the pointer (for the magnetic pointer and the highlight), or None."""
    return _run(lambda: _target_at(x, y, monitor[2] * monitor[3]), timeout)


def _plain(text):
    return " ".join("".join(ch if ch.isalnum() else " " for ch in str(text or "").casefold()).split())


def _bones(text):
    """The consonants only: spellings of the same word from Hindi script and English differ mostly in vowels."""
    return "".join(ch for ch in text if ch.isalpha() and ch not in "aeiouy")


def best_name(want, names):
    """Index of the name that best matches what was said (voice click), or None: exact, then whole words, then a close
    spelling (Whisper writes "sev" for "Save")."""
    import difflib
    want = _plain(want)
    if not want:
        return None
    best, score = None, 0.0
    for index, name in enumerate(names):
        name = _plain(name)
        if not name:
            continue
        if name == want:
            value = 1.0
        elif f" {want} " in f" {name} ":
            value = 0.9 - min(0.2, (len(name) - len(want)) / 200)   # "save" in "save as": the shorter wins
        elif len(_bones(want)) >= 2 and _bones(want) == _bones(name):
            value = 0.8                                              # Hindi script read back: "sev" = "Save"
        else:
            value = difflib.SequenceMatcher(None, want, name).ratio() * 0.85
        if value > score:
            best, score = index, value
    return best if score >= 0.6 else None


def find_by_name(name, monitor, *, timeout=2.0):
    """The clickable element in the front window whose name was said (voice click, owner 2026-11-08), or None. One
    cached UI Automation query: names, types and places come back together."""
    def job():
        import ctypes
        u = _uia()
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        root = u.ua.ElementFromHandle(hwnd)
        condition = None
        for type_id in KINDS:
            one = u.ua.CreatePropertyCondition(30003, type_id)          # UIA_ControlTypePropertyId
            condition = one if condition is None else u.ua.CreateOrCondition(condition, one)
        cache = u.ua.CreateCacheRequest()
        for prop in (30005, 30003, 30001, 30010, 30022):                 # name, type, rectangle, enabled, offscreen
            cache.AddProperty(prop)
        found = root.FindAllBuildCache(4, condition, cache)                  # TreeScope_Descendants
        left, top, width, height = monitor
        candidates = []
        for i in range(min(found.Length, 4000)):
            element = found.GetElement(i)
            rect = element.CachedBoundingRectangle
            if not element.CachedIsEnabled or element.CachedIsOffscreen or rect.right <= rect.left:
                continue
            if not (left <= rect.left < left + width and top <= rect.top < top + height):
                continue
            candidates.append({"kind": KINDS[element.CachedControlType], "name": str(element.CachedName or "")[:60],
                               "rect": (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)})
        index = best_name(name, [c["name"] for c in candidates])
        return None if index is None else candidates[index]
    return _run(job, timeout)


def text_at(x, y, *, timeout=0.8):
    """The paragraph of text under (x, y) for read aloud (owner 2026-11-08), or None: through the app's text pattern
    when it has one, else the text element's own words."""
    def job():
        u = _uia()
        point = u.U.tagPOINT(int(x), int(y))
        element = node = u.ua.ElementFromPoint(point)
        for _ in range(6):
            if not node:
                break
            try:
                pattern = node.GetCurrentPattern(10014)                      # UIA_TextPatternId
                if pattern:
                    text_range = pattern.QueryInterface(u.U.IUIAutomationTextPattern).RangeFromPoint(point)
                    text_range.ExpandToEnclosingUnit(4)                      # TextUnit_Paragraph
                    text = text_range.GetText(4000).strip()
                    if text:
                        return text
                    break
            except Exception:   # an app with a partial text pattern: the fallbacks below
                break
            node = u.walker.GetParentElement(node)
        node = element
        for _ in range(3):
            if not node:
                break
            if node.CurrentControlType == 50020 and str(node.CurrentName or "").strip():   # Text
                return str(node.CurrentName).strip()[:4000]
            if node.CurrentControlType == 50004:                             # a text box: its whole text
                try:
                    value = node.GetCurrentPattern(10002).QueryInterface(u.U.IUIAutomationValuePattern).CurrentValue
                    if str(value or "").strip():
                        return str(value).strip()[:4000]
                except Exception:
                    pass
            node = u.walker.GetParentElement(node)
        return None
    return _run(job, timeout)


def on_monitor(target, monitor):
    """The target with its rectangle as 0..1 of the streamed monitor (what the phone draws)."""
    left, top, width, height = target["rect"]
    mleft, mtop, mwidth, mheight = monitor
    return {"kind": target["kind"], "name": target["name"],
            "rect": [round((left - mleft) / mwidth, 4), round((top - mtop) / mheight, 4),
                     round(width / mwidth, 4), round(height / mheight, 4)]}
