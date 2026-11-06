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
