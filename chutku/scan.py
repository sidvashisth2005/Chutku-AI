"""Content scan for anything Chutku saves and later reads back into her prompt (Phase 3b H3).

A saved fact, note, list item or scheduled-task goal is shown to the planner again and again, so text that hides
characters or reads like an instruction to the assistant is refused before it is saved. Idea from hermes-agent's
memory and cron-prompt scanning (MIT, Nous Research). The instruction test is the same one S15 applies to content
Chutku reads (`agent_loop._INSTRUCTION_LINE`), so there is one definition.
"""
from __future__ import annotations

import re
import unicodedata

# Zero-width and direction-changing characters: invisible on screen, but the model reads them.
_HIDDEN = re.compile("[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
_JOINERS = re.compile("[\u200c\u200d]")    # ZWNJ / ZWJ: needed inside Hindi words (e.g. क्\u200dष), suspicious elsewhere
_DEVANAGARI = re.compile("[ऀ-ॿ]")


def hidden_characters(text: str) -> list[str]:
    """Code points like U+200B that would hide text; joiners count only outside Devanagari."""
    found = [f"U+{ord(ch):04X}" for ch in _HIDDEN.findall(text)]
    for match in _JOINERS.finditer(text):
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if not (_DEVANAGARI.match(before) and _DEVANAGARI.match(after)):
            found.append(f"U+{ord(match.group()):04X}")
    return found


def instruction_lines(text: str) -> int:
    from chutku.agent_loop import _INSTRUCTION_LINE
    return sum(1 for line in unicodedata.normalize("NFKC", text).splitlines() if _INSTRUCTION_LINE.search(line))


def threats(text) -> list[str]:
    """Reasons this text must not be saved for Chutku to read later ([] when it is fine)."""
    if not isinstance(text, str) or not text:
        return []
    reasons = []
    hidden = hidden_characters(text)
    if hidden:
        reasons.append("hidden characters " + ", ".join(sorted(set(hidden))[:5]))
    if instruction_lines(text):
        reasons.append("it reads like an instruction to the assistant")
    return reasons


def check(*texts, instructions=True) -> None:
    """Raise ValueError with a plain reason when any text must not be saved. instructions=False only checks for hidden
    characters: a scheduled-task goal or a to-do is the owner's own order, so imperative wording is expected there."""
    for text in texts:
        reasons = threats(text) if instructions else (
            ["hidden characters " + ", ".join(sorted(set(hidden_characters(text)))[:5])]
            if isinstance(text, str) and hidden_characters(text) else [])
        if reasons:
            raise ValueError("Save nahi kiya: " + "; ".join(reasons) + ".")
