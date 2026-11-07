"""H18 busy mode (Hermes /queue, /steer, /btw): what a new message means while a task is already running.

Deterministic word rules (Hinglish and English); no model decides:
  stop   - the existing stop words (control_intent): unchanged, handled before this module
  steer  - "aur haan, ...", "also ...", "nahi, ...", "galat, ...", "uski jagah ...", "instead ...": the words are
           added to the running task. The planner reads them at its next round (CONTEXT.owner_said_now), never in the
           middle of a step. They are the owner's own words, so they carry no taint, and they cannot remove an ask:
           the policy kernel decides approvals, not the planner's context.
  later  - "... baad mein karna" / "... do it later": waits in line (never side by side) until the running task ends
  first  - "pehle ye karo ..." / "do this first ...": goes to the front of the line (the running step still ends)
  None   - anything else keeps today's behaviour: a plain question runs beside the task (observe only, Y3), an order
           runs in a side slot or waits in line (Z1)

shortcut: a bare leading "aur" ("aur volume badhao") is a new order, not a steer, so a second order never ends up
inside the first task; widen the steer words only if real use shows misses.
"""
from __future__ import annotations

import re

STEER = re.compile(r"^\s*(?:aur\s+(?:haan|ha|han|haa|suno|ye\s+bhi|yeh\s+bhi)|and\s+also|also|oh\s+and|plus|"
                   r"nahi|nahin|nhi|no|galat|wrong|uski\s+jagah|iski\s+jagah|instead|actually)\b[\s,:.!-]*", re.I)
# Only an explicit "do it later": "10 minute baad mein yaad dilana" / "remind me later" are timers, not this.
LATER = re.compile(r"[\s,]*\b(?:(?:ye|yeh|isko|is\s+ko)?\s*(?:baad\s+mein|baad\s+me|bad\s+me|baadmein)\s+"
                   r"(?:karna|karo|kar\s+dena|kar\s+lena)|iske\s+baad\s+(?:karna|karo|kar\s+dena)|"
                   r"do\s+(?:it|this|that)\s+(?:later|after\s+this|next))\s*[.!]?\s*$", re.I)
FIRST = re.compile(r"^\s*(?:pehle|pahle|pehele)\s+(?:ye|yeh|isko|is\s+ko)\s+karo\b[\s,:.!-]*|"
                   r"^\s*(?:do\s+this\s+first|first\s+do\s+this)\b[\s,:.!-]*", re.I)
MAX_NOTES = 5
NOTE_CHARS = 300


def route(text):
    """(kind, remaining text): kind is "steer", "later", "first" or None (see the module docstring)."""
    from chutku.translit import roman
    plain = " ".join(roman(text or "").split())
    match = FIRST.match(plain)
    if match and plain[match.end():].strip():
        return "first", plain[match.end():].strip()
    match = LATER.search(plain)
    if match and plain[:match.start()].strip():
        return "later", plain[:match.start()].strip()
    match = STEER.match(plain)
    if match and len(plain[match.end():].split()) >= 2:   # "nahi" or "also" alone is not guidance
        return "steer", plain[match.end():].strip()
    return None, plain


def add_note(session, text):
    """Attach the owner's guidance to a running session. Returns False when the session no longer runs."""
    with session.lock:
        if session.status not in {"planning", "running", "waiting_confirmation", "queued"}:
            return False
        session.owner_notes = (list(getattr(session, "owner_notes", [])) + [text[:NOTE_CHARS]])[-MAX_NOTES:]
        return True
