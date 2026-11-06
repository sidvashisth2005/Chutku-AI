"""Hands-free approvals: Chutku asks a pending step out loud and the owner answers "haan" / "nahi".

Owner decision (2026-10-01, repeated 2026-10-03): confirmation may be a click or a spoken yes.
A spoken answer approves only when it is short, contains a clear yes word and no no/stop word;
"nahi / no / ruko / cancel" cancels; anything else is asked once more and then left to the screen.
"""
from __future__ import annotations

import re

from chutku.voice.live import NO, SHORT_YES, YES

MAX_YES_WORDS = 8  # "haan bhej do yaar" is fine; a long sentence from a TV in the background is not a yes


# "Don't keep asking" is consent, not a no (live 2026-11-05: "approval mat maangna" + four yeses were all refused,
# because "mat" counted as no). It also pre-approves the rest of the task (agent_loop.TRUST_TASK).
DONT_ASK = re.compile(r"\b(?:approval|apruval|apruwal|permission|paramishan|parmission|ijaazat|ijazat|puch\w*|pooch\w*|"
                      r"confirm\w*)\b.{0,25}?\bmat\b|\bmat\s+(?:pucho|poocho|puchna|poochna|puchho|maang\w*|mang\w*)\b|"
                      r"\b(?:don'?t|do not|stop|no need to)\s+(?:keep\s+)?ask(?:ing)?\b|\bbaar[- ]baar\s+mat\b", re.I)
# "I already said yes" said again in frustration: "yes bol to diya", "haan bola na".
SAID_YES = re.compile(r"\b(?:yes|yas|haan|han|ha)\s+(?:bol|bola|keh|kaha)\s*(?:to\s+)?(?:diya|diyaa|di|na|naa|tha)\b", re.I)


def decide(heard):
    """True for a clear short yes, False for a clear no, None when unclear (Hindi script is read as Hinglish)."""
    from chutku.translit import roman
    text = " ".join(roman(heard or "").split())
    if not text:
        return None
    if DONT_ASK.search(text) or SAID_YES.search(text):
        return True
    text = re.sub(r"\byas\b", "yes", text, flags=re.I)   # यस, the Hindi-script spelling of "yes"
    if NO.search(text):
        return False
    if YES.search(text) and len(text.split()) <= MAX_YES_WORDS:
        return True
    if SHORT_YES.search(text) and len(text.split()) <= 3:
        return True
    if re.sub(r"[^a-z]", "", text.casefold()) in _SOUND_YES:  # "hnn" alone, as Whisper writes it
        return True
    return None


_SOUND_YES = {"hmm", "hm", "hmmm", "hnn", "hn", "hnnn", "haa", "ha", "haanji", "hanji", "ji", "hamm", "hum", "humm",
              "haan", "han", "ok", "yes"}


def _name(path):
    return re.split(r"[\\/]", str(path).rstrip("\\/"))[-1] or str(path)


def spoken_question(approval):
    """What will happen, in plain words, ending with "haan ya na?"."""
    tool = approval.get("tool", "")
    args = approval.get("arguments") or {}
    if tool == "message.send":
        app = {"whatsapp": "WhatsApp", "telegram": "Telegram"}.get(args.get("app"), "the app")
        ask = f"Send “{str(args.get('text', ''))[:80]}” to {args.get('to')} on {app}?"
    elif tool == "filesystem.recycle":
        ask = f"Move {_name(args.get('path', 'that item'))} to the Recycle Bin?"
    elif tool == "filesystem.delete_permanent":
        ask = f"Permanently delete {_name(args.get('path', 'that item'))}? This cannot be undone."
    elif tool in {"apps.quit", "apps.close", "windows.close"}:
        ask = f"Close {args.get('name') or 'that window'}?"
    elif tool == "files.organize":
        ask = f"Sort the files in {_name(args.get('path', 'that folder'))} into folders?"
    elif tool.startswith("power."):
        ask = "Change the power state of the PC (shut down, restart or sleep)?"
    elif tool == "code.build_project":
        ask = "Build that app now? It writes code and runs it."
    elif tool == "memory.forget":
        ask = f"Forget the note {args.get('key')}?"
    else:
        consequence = str(approval.get("consequence") or tool).rstrip(".")
        ask = f"{consequence[:140]}. Shall I go ahead?"
    return ask + " Haan ya na?"
