"""Devanagari -> Roman letters, so Hindi the voice service writes in Hindi script ("हाँ", "पिता श्री", "भेज दो")
matches the owner's Roman-letter Hinglish everywhere ("haan", "pita shri", "bhej do").

Simple and predictable rather than scholarly: consonants carry an "a" that is dropped at the end of a word and
before a vowel sign; nasal marks become "n". Latin text passes through unchanged.
"""
from __future__ import annotations

import re

_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f", "ळ": "l",
}
_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o",
           "औ": "au", "ऑ": "o", "ॲ": "e"}
_SIGNS = {"ा": "aa", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
          "ॉ": "o", "ॅ": "e"}
_NASAL = {"ं": "n", "ँ": "n", "ः": "h"}
_HALANT, _NUKTA = "्", "़"
_DIGITS = {chr(0x0966 + d): str(d) for d in range(10)}
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def has_devanagari(text):
    return bool(_DEVANAGARI.search(text or ""))


def _word(word):
    out, i = [], 0
    while i < len(word):
        ch = word[i]
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if nxt == _NUKTA and ch + _NUKTA in _CONSONANTS:
            ch, i = ch + _NUKTA, i + 1
            nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch in _CONSONANTS:
            out.append(_CONSONANTS[ch])
            if nxt == _HALANT:
                i += 2
                continue
            if nxt in _SIGNS:
                out.append(_SIGNS[nxt])
                i += 2
                continue
            at_end = i + 1 >= len(word) or (nxt in _NASAL and i + 2 >= len(word))
            if not at_end:
                out.append("a")      # inherent vowel, dropped at the end of a word ("bhej", "shri")
            i += 1
            continue
        if ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _SIGNS:
            out.append(_SIGNS[ch])
        elif ch in _NASAL:
            out.append(_NASAL[ch])
        elif ch in _DIGITS:
            out.append(_DIGITS[ch])
        elif ch in (_HALANT, _NUKTA, "‍", "‌"):
            pass
        elif ch in "।॥":
            out.append(".")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _hinglish(word):
    """Everyday Hinglish spelling: a final long "aa" is written "a" ("pita", "kya"), except before a nasal ("haan")."""
    return re.sub(r"aa$", "a", word) if not word.endswith("aan") else word


def roman(text):
    """Hindi script -> Roman letters; anything else is returned unchanged."""
    if not has_devanagari(text):
        return text
    return re.sub(r"[ऀ-ॿ‌‍]+", lambda m: _hinglish(_word(m.group(0))), text)
