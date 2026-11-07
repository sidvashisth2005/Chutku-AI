"""How much may Chutku decide by herself for this one request? Read from the owner's own words (2026-11-06).

Owner: "I give the order and go for a coffee break; when I come back it must be done. Ask only when it is really
risky. If I say I am approving now, don't ask again for that task." So the request's words pick the autonomy:

  pre-approval ("bina puche kar do", "approval mat maangna", "main abhi approve kar raha hoon", "don't ask", "coffee
  break", frustration at being asked: "baar baar mat pucho")  -> "trusted": only very risky steps ask (kernel)
  caution ("dhyan se", "carefully", "puch ke karna", "ask me first")                         -> "auto_safe"

shortcut: these are word cues in Hinglish/English (Hindi script is romanised first), not a learned sentiment model;
upgrade to a classifier only if real requests show misses. Caution always wins over pre-approval.
"""
from __future__ import annotations

import re

from chutku.voice.approval import DONT_ASK

PRE_APPROVAL = re.compile(
    r"\b(?:bina\s+(?:puche|pooche|puchhe|approval|permission)|without\s+(?:asking|approval|permission)|"
    r"(?:main|mai|i)\s+(?:abhi\s+)?(?:approve|approval)\s+(?:de\s+)?(?:raha|rahi|kar\s+raha|kar\s+rahi|deta|deti|"
    r"karta|karti|de\s+diya|give|am\s+giving|have\s+given)|(?:sab|everything|all)\s+(?:kuch\s+)?(?:approved?|allowed)|"
    r"pre-?approved?|khud\s+(?:hi\s+)?(?:decide|kar\s+lena|kar\s+lo|dekh\s+lena)|coffee\s+break|"
    r"jab\s+tak\s+(?:main|mai)\s+(?:aata|aati|aaun|wapas))", re.I)
CAUTION = re.compile(r"\b(?:dhyan\s+se|dhyaan\s+se|carefully|careful|savdhani|puch\s*(?:ke|kar)|pooch\s*(?:ke|kar)|"
                     r"ask\s+me\s+(?:first|before)|confirm\s+(?:karke|first|with\s+me))\b", re.I)


# H21 (Hermes /reasoning): "think harder" for this one request.
THINK = re.compile(r"\b(?:dhyan\s+se\s+soch(?:o|na|ke)?|dhyaan\s+se\s+soch(?:o|na|ke)?|soch\s*(?:ke|kar|samajh\s+ke)\s+"
                   r"(?:batao|bolo|karo|jawab\s+do)|achhe\s+se\s+soch(?:o|ke)?|think\s+(?:carefully|hard(?:er)?|it\s+through)|"
                   r"take\s+your\s+time)\b", re.I)


def thinks(goal):
    """True when the owner asks Chutku to think harder about this request."""
    from chutku.translit import roman
    return bool(THINK.search(" ".join(roman(goal or "").split())))


def autonomy_for(goal, mode):
    """The mode this request runs in: the chosen mode, raised to "trusted" by a pre-approval or lowered to
    "auto_safe" by a caution. "review" (the owner chose to approve every step) is never raised."""
    from chutku.translit import roman
    text = " ".join(roman(goal or "").split())
    if CAUTION.search(text):
        return "auto_safe" if mode in {"owner", "trusted", "auto_edits"} else mode
    if mode != "review" and (PRE_APPROVAL.search(text) or DONT_ASK.search(text)):
        return "trusted"
    return mode


# H9: the owner picks the brain for this one request ("local se karo: aaj kya date hai", "gemini se pucho ...").
_LOCAL = r"(?:local|offline|laptop|bina\s+internet(?:\s+ke)?)"
_CLOUD = r"(?:gemini|cloud|online|groq)"
_DO = r"(?:se|model\s+se|brain\s+se)\s+(?:karo|kar\s+do|batao|bata\s+do|pucho|poocho|jawab\s+do|socho)"
_PREFIX = re.compile(rf"^\s*(?:(?P<local>{_LOCAL})|(?P<cloud>{_CLOUD}))\s+{_DO}\b[\s:,-]*|"
                     rf"^\s*(?:use\s+(?:the\s+)?(?:(?P<local2>local|offline)|(?P<cloud2>gemini|cloud))"
                     rf"(?:\s+(?:model|brain))?|ask\s+(?P<cloud3>gemini|the\s+cloud))\b[\s:,-]*", re.I)
_SUFFIX = re.compile(rf"[\s,]*\b(?:(?P<local>{_LOCAL})|(?P<cloud>{_CLOUD}))\s+{_DO}\s*[.!?]?\s*$", re.I)


def brain_choice(goal):
    """("local" | "cloud" | None, the request without the brain words). The words must come first or last, so
    "gemini se kya fark hai" (a question about Gemini) is not a choice."""
    from chutku.translit import roman
    text = " ".join(roman(goal or "").split())
    for pattern in (_PREFIX, _SUFFIX):
        match = pattern.search(text)
        if match is None:
            continue
        rest = (text[:match.start()] + " " + text[match.end():]).strip(" ,:-")
        if not rest:   # "local se karo" alone names no request
            return None, text
        groups = match.groupdict()
        local = any(groups.get(key) for key in ("local", "local2"))
        return ("local" if local else "cloud"), rest
    return None, text
