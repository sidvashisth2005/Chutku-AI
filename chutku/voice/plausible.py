"""Is a spoken transcript a request at all? (F4, 2026-10-29)

The owner's last real tries on 2026-10-24 were misheard as "Watch out brother." and "Basic presentation."; each ran a
45-58 s model plan that opened files and searched the web. A transcript that has no action word, no question, no app
or person Chutku knows and no instant phrase is now read back ("Maine suna '...' — yahi karna hai?") instead of run.
Only the spoken path uses this: typed text is always what the owner meant.
"""
from __future__ import annotations

import re

# Words that make a sentence a request or a question (English and Roman Hinglish, after chutku.translit.roman).
ACTION_WORDS = frozenset("""
open close quit exit play pause resume stop start launch run search find look show tell give send message call
reply read write type note remind reminder set turn switch increase decrease raise lower volume brightness mute
unmute next previous skip shuffle repeat lock shutdown restart sleep screenshot download install update create make
build delete remove move copy rename save check explain summarize summarise translate add list schedule cancel undo
help describe click scroll go change connect disconnect enable disable record organize organise clean empty
what which who whom whose when where why how is are am was were do does did can could will would should may shall
time date day weather news battery wifi bluetooth internet disk space storage
kholo khol band chalao chala chalu bajao baja roko ruko bhejo bhej batao bata bolo dikhao dikha dhundo dhoondo
khojo karo kar kardo karde do de likho likh padho padh suna sunao lagao laga hatao hata badhao badha ghatao ghata
banao bana yaad mitao saaf rakho rakh dekho dekh samjhao jao chalo lao le lo
kya kaun kab kahan kaise kitna kitne kitni kyun kyon konsa kaunsa kidhar
hello hi hey namaste morning evening goodnight thanks thank shukriya sorry bye
""".split())
APP_WORDS = frozenset("""
spotify youtube whatsapp telegram discord chrome brave edge firefox notepad calculator vscode code settings explorer
vlc steam epic word excel powerpoint outlook gmail teams zoom camera photos paint terminal powershell chatgpt
""".split())


def _words(text):
    from chutku.translit import roman
    return re.findall(r"[a-z0-9']+", roman(text or "").casefold())


def plausible(text, *, known_names=()):
    """True when this transcript could be something the owner asked Chutku to do or answer."""
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.rstrip().endswith("?"):
        return True
    words = _words(raw)
    if not words:
        return False
    if any(w in ACTION_WORDS or w in APP_WORDS for w in words):
        return True
    names = {n.casefold() for n in known_names if n}
    if names and any(w in names for w in words):
        return True
    from chutku import control_intent
    if control_intent.kind(raw) is not None:
        return True
    try:
        from chutku.quick_intents import quick_proposal
        return quick_proposal(raw) is not None
    except Exception:
        return False


def read_back(text):
    return f"Maine suna: \"{text.strip()[:120]}\". Kya yahi karna hai? Agar haan, to thoda saaf phir se bolo."
