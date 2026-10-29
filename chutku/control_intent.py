"""Controlling Chutku in plain words (English / Hinglish): stop, pause, undo, repeat, help, "are you there".

kind(goal) -> "stop" | "pause" | "resume" | "undo" | "recent" | "repeat" | "help" | "presence" | None.
"stop"/"pause"/"resume" act on Chutku itself (the dashboard handles them before anything is queued, so "stop" never
waits behind the task it should stop). The others are instant quick-tier proposals.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from chutku.intents.lexicon import LEAD as _P, TAIL as _T   # one Hinglish vocabulary for every parser
_KINDS = [
    ("stop", r"(?:stop|stop it|stop that|stop everything|cancel|cancel it|cancel that|abort|ruko|ruk jao|ruk ja|bas|bas karo|"
             r"rehne do|chhodo|chodo|band karo sab|sab band karo|stop karo|cancel karo)"),
    ("pause", r"(?:pause (?:all )?actions|pause everything|pause chutku|freeze|sab rok do|actions rok do)"),
    ("resume", r"(?:resume|resume (?:actions|everything|chutku)|unpause|chalu ho jao|chalu ho ja|wapas chalu (?:ho jao|karo)|"
               r"kaam chalu karo|actions chalu karo)"),
    ("undo", r"(?:undo|undo (?:that|it|this|the last (?:thing|change|action)|last|last change)|revert (?:that|it)|"
             r"wapas karo|wapas kar do|vapas karo|pichla wapas karo|ulta karo)"),
    ("recent", r"(?:what did you (?:just )?do|what have you just done|abhi kya kiya|tumne abhi kya kiya|last kya kiya)"),
    ("repeat", r"(?:do (?:it|that) again|again|repeat(?: that| it)?|phir se(?: karo| kar do)?|dobara(?: karo| kar do)?|"
               r"ek baar aur|one more time)"),
    ("help", r"(?:help|help me|what can you do|what all can you do|what do you do|tum kya kya kar sakte ho|kya kya kar sakte ho|"
             r"madad|commands|how do i use you)"),
    ("presence", r"(?:are you there|you there|suno|sun rahe ho|sun raha hai|hello\?|chutku\??|wake up|jaago)"),
]
_COMPILED = [(kind, re.compile(_P + words + _T, re.I)) for kind, words in _KINDS]
PROJECT_ROOT = Path(__file__).resolve().parents[1]

HELP_TEXT = ("Just tell me, in English or Hinglish: open or close apps, play music, volume, WhatsApp people I know "
             "(\"mammi ko good night bhejo\"), files by path, PC checks (battery, space, internet), any shortcut or a "
             "click on screen, reminders, notes, weather, news, building an app, and remembering things about you. "
             "Control me with \"stop\", \"undo that\", \"do it again\". Give several orders at once; they run one "
             "by one.")
assert len(HELP_TEXT) <= 600


def kind(goal: str):
    from chutku.translit import roman
    text = " ".join(roman(str(goal)).split())
    for name, pattern in _COMPILED:
        if pattern.match(text):
            return name
    return None


def last_goal(base=None):
    """The previous request (data/last-task.json), for "do it again"."""
    try:
        data = json.loads((Path(base or PROJECT_ROOT) / "data" / "last-task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    goal = data.get("goal") if isinstance(data, dict) else None
    return goal if isinstance(goal, str) and goal.strip() and kind(goal) is None else None
