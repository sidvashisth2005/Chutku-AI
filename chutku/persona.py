"""Who Chutku is (owner, 2026-10-05): female, and her name is छुटकू ("Chhutku"), not चुटकू.

- IDENTITY: one line every model prompt that writes Chutku's own words starts from.
- feminine(text): a deterministic guard on model-written replies: masculine first-person Hindi forms about herself
  ("kar raha hoon", "bhej dunga", "samajh gaya") become feminine. Text inside quotes is left alone, because that is
  usually the owner's own message being repeated ("main late aaunga" sent to Pita Shri).
"""
from __future__ import annotations

import re

NAME_HINDI = "छुटकू"
IDENTITY = ("You are Chutku (छुटकू, said \"Chhutku\"), the owner's female AI companion. When you speak Hindi or "
            "Hinglish about yourself, always use feminine forms: \"kar rahi hoon\", \"kar dungi\", \"samajh gayi\", "
            "\"main sakti hoon\", \"main ready hoon\"; never \"raha\", \"dunga\", \"gaya\", \"sakta\".")

_SIMPLE = {"gaya": "gayi", "chuka": "chuki", "sakta": "sakti", "leta": "leti", "deta": "deti", "karta": "karti",
           "rehta": "rehti", "samjha": "samjhi"}
_QUOTED = re.compile(r"(\"[^\"]*\"|“[^”]*”|'[^']{3,}')")
# Words ending in -unga that are not first-person verbs.
_KEEP = {"munga", "punga", "lunga", "jhunga", "bhunga"}


def _fix(part):
    def unga(match):
        word = match.group(0)
        return word if word.casefold() in _KEEP else match.expand(r"\1ungi")
    part = re.sub(r"\b(r)aha (hoon|hun|hu|tha)\b", r"\1ahi \2", part, flags=re.I)
    part = re.sub(r"\b(r)ha (hoon|hun|hu|tha)\b", r"\1hi \2", part, flags=re.I)
    part = re.sub(r"\b(\w+)unga\b", unga, part, flags=re.I)
    part = re.sub(r"\b(gaya|chuka|sakta|leta|deta|karta|rehta|samjha) (hoon|hun|hu)\b",
                  lambda m: _SIMPLE[m.group(1).casefold()] + " " + m.group(2), part, flags=re.I)
    part = re.sub(r"\b(main|maine)( \w+)? gaya\b", lambda m: m.group(1) + (m.group(2) or "") + " gayi", part,
                  flags=re.I)
    return re.sub(r"\b(rahi|rhi|gayi|chuki|sakti|leti|deti|karti|rehti|samjhi) tha\b", r"\1 thi", part, flags=re.I)


def feminine(text):
    """Chutku's own Hinglish in feminine forms; quoted text (the owner's words) is never changed."""
    if not text:
        return text
    pieces = _QUOTED.split(text)
    return "".join(piece if index % 2 else _fix(piece) for index, piece in enumerate(pieces))
