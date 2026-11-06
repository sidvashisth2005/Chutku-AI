"""Second opinion (H22, from Hermes `/review` and `/moa`): "pakka?" re-checks the last answer against public sources.

The request becomes a read-only research task (the session is observe_only: only R0 tools such as web.results and
web.read run), so a re-check can never change anything on the PC.
    "pakka?" / "sure ho?" / "double check karo"  -> the last question and answer, checked against up to 2 sources:
                                                    "Dono sahmat hain" or "Yahan fark hai: ..." with the sources
    "sab se poocho: <question>"                  -> answered from at least 2 independent sources, differences listed
"""
from __future__ import annotations

import re

_RECHECK = re.compile(r"^\W*(?:pakka(?:\s+hai)?|sach\s+mein|sure\s+(?:ho|hai|ho\s+na)|are\s+you\s+sure|"
                      r"double[\s-]check(?:\s+(?:karo|kar\s+do|it|that))?|(?:dobara\s+)?check\s+karke\s+batao)\W*$", re.I)
_ASK_ALL = re.compile(r"^\W*(?:sab\s+se\s+poocho|ask\s+everyone|multiple\s+sources\s+se\s+batao)\s*[:\-]\s*(?P<q>.{3,300})$",
                      re.I)


def rewrite(goal, base=None, origin="text"):
    """The research goal for a second-opinion request, or None when the goal is not one. A test script's "pakka?"
    re-checks the script's own last answer; the owner's re-checks the owner's."""
    asked = _ASK_ALL.match(goal or "")
    if asked:
        question = asked.group("q").strip()
        return (f"Answer this using at least 2 independent public web sources (web.results, then web.read), and say "
                f"plainly where they disagree, naming the sources: {question}")
    if not _RECHECK.match(goal or ""):
        return None
    from chutku import recall
    same = (lambda t: t.get("origin") == "script") if origin == "script" else recall.owner_turn
    last = next((t for t in reversed(recall.turns(base, 50)) if same(t) and t.get("reply")
                 and not _RECHECK.match(t.get("said", ""))), None)
    if last is None:
        return None
    return (f"Double-check an earlier answer with up to 2 public web sources (web.results, then web.read). "
            f"Question: \"{last['said'][:300]}\". Answer given: \"{last['reply'][:500]}\". "
            "Reply \"Dono sahmat hain\" if the sources agree with the answer, or \"Yahan fark hai: ...\" saying what "
            "differs, and name the sources.")
