"""Instant keyboard/mouse phrases (English and Hinglish).

    "press ctrl+shift+t" / "ctrl shift t dabao" / "press down 5 times" / "alt tab karo"   -> keyboard.keys
    "click on Downloads" / "Downloads pe click karo" / "right click on Recycle Bin"        -> mouse.click
    "double click on Chrome" / "hover over Settings"                                      -> mouse.click / mouse.move

Descriptions that need understanding ("click the first video", "click that button") return None so the
screen-understanding path handles them.
"""
from __future__ import annotations

import re

from chutku.tools.free_input import parse_keys

from chutku.intents.lexicon import LEAD as _P, TAIL as _T   # one Hinglish vocabulary for every parser
_TIMES = r"(?:\s+(?P<n>\d{1,2})\s*(?:times|time|baar|bar|x))?"
_KEYS = [
    re.compile(_P + r"(?:press|hit|tap|send)\s+(?:the\s+)?(?P<keys>[a-z0-9+ ,.-]{1,60}?)(?:\s+keys?)?" + _TIMES + _T, re.I),
    re.compile(_P + r"(?P<keys>[a-z0-9+ ,.-]{1,60}?)" + _TIMES + r"\s+(?:dabao|daba do|press karo|press kar do|karo)" + _T, re.I),
]
_CLICK = [
    re.compile(_P + r"(?P<button>right|double|middle)?[- ]?click\s+(?:on\s+|at\s+)?(?P<text>.{1,60}?)" + _T, re.I),
    re.compile(_P + r"(?P<text>.{1,60}?)\s+(?:pe|par|per)\s+(?P<button>right |double )?click\s+(?:karo|kar do|kr do|kro)" + _T, re.I),
]
_HOVER = re.compile(_P + r"(?:hover\s+(?:over|on)|move\s+(?:the\s+)?(?:mouse|cursor|pointer)\s+(?:to|over|on))\s+"
                    r"(?P<text>.{1,60}?)" + _T, re.I)
_VAGUE = re.compile(r"^(?:the\s+)?(?:first|second|third|fourth|fifth|last|next|previous|\d+(?:st|nd|rd|th))\b|"
                    r"^(?:it|this|that|here|there|me|anywhere|somewhere|something|everything)$|"
                    r"^(?:this|that|the)\s+(?:one|button|link|thing)$", re.I)
_TRIM = re.compile(r"^(?:the|a|an)\s+|\s+(?:button|link|tab|icon|option|menu|item|text)$", re.I)


def _target(raw):
    text = raw.strip().strip("\"“”'‘’").strip()
    previous = None
    while previous != text:
        previous, text = text, _TRIM.sub("", text).strip()
    if not text or _VAGUE.search(text) or len(text.split()) > 6:
        return None
    return text


def parse_input(goal: str):
    """(tool, arguments, purpose, reply) or None."""
    text = " ".join(goal.split())
    for pattern in _CLICK:
        match = pattern.match(text)
        if match:
            target = _target(match.group("text"))
            if target is None:
                return None
            button = (match.group("button") or "").strip().casefold()
            arguments = {"text": target}
            if button == "right":
                arguments["button"] = "right"
            elif button == "middle":
                arguments["button"] = "middle"
            elif button == "double":
                arguments["double"] = True
            label = {"right": "Right-click", "double": "Double-click", "middle": "Middle-click"}.get(button, "Click")
            return "mouse.click", arguments, f"{label} “{target}”", f"{label}ed “{target}”."
    match = _HOVER.match(text)
    if match:
        target = _target(match.group("text"))
        return ("mouse.move", {"text": target}, f"Point at “{target}”", f"The pointer is on “{target}”.") if target else None
    for pattern in _KEYS:
        match = pattern.match(text)
        if not match:
            continue
        keys = match.group("keys").strip(" ,")
        try:
            parse_keys(keys)
        except ValueError:
            return None
        arguments = {"keys": keys}
        if match.group("n") and int(match.group("n")) > 1:
            arguments["repeat"] = min(30, int(match.group("n")))
        times = f" ×{arguments['repeat']}" if "repeat" in arguments else ""
        return "keyboard.keys", arguments, f"Press {keys}{times}", f"Pressed {keys}{times}."
    return None
