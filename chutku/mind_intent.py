"""Instant phrases for the owner's personal memory (chutku/mind.py), English and Hinglish.

    "AK is my gf" / "AK meri gf hai" / "remember Sharma Sir is my DL wale sir"   -> mind.person (nickname)
    "mammi ka number +91 98xxx xxxxx hai" / "save mammi's number +91..."         -> mind.person (phone)
    "mammi ka email mom@example.com hai" / "save mammi's email mom@example.com"   -> mind.person (email)
    "my home is in Pune" / "I live in Pune" / "mera ghar Pune mein hai"          -> mind.fact
    "add assignment: DBMS report by Friday" / "my skills: python, react"         -> mind.add
    "show my assignments" / "who is my gf" / "what do you know about me"         -> mind.show / mind.who
    "assignment 2 done"                                                          -> mind.done
    "send hi to mammi" / "gf ko good night bhejo" (no app named; person known)   -> message.send on WhatsApp

Returns (tool, arguments, purpose, reply, finish) or None.
"""
from __future__ import annotations

import re

from chutku import mind

from chutku.intents.lexicon import LEAD as _P, TAIL as _T   # one Hinglish vocabulary for every parser
_PERSON_WORDS = re.compile(
    r"\b(?:gf|bf|girl ?friend|boy ?friend|mom|mummy|mammi|mummi|mumma|maa|mother|dad|papa|father|pita\w*|bro|brother|bhai\w*|"
    r"sis|sister|behen|didi|wife|husband|friend|dost|sir|ma'?am|madam|mam|teacher|boss|manager|uncle|aunty|aunt|chacha|"
    r"chachi|mama|mami|nana|nani|dada|dadi|cousin|roommate|wale|waale|vale)\b", re.I)
_LIST = r"(?P<list>assignments?|homework|schedule|timetable|classes|skills?|domains?|interests?|projects?|goals?)"
_PATTERNS = [
    ("alias", re.compile(_P + r"(?:remember (?:that )?)?(?P<name>[^,.]{1,40}?) (?:is|are) my (?P<alias>[^,.]{1,40}?)" + _T, re.I)),
    ("alias", re.compile(_P + r"(?P<name>[^,.]{1,40}?) (?:meri|mera|mere) (?P<alias>[^,.]{1,40}?) (?:hai|he|h|hain)" + _T, re.I)),
    ("alias_rev", re.compile(_P + r"(?:remember (?:that )?)?my (?P<alias>[^,.]{1,40}?) is (?:called |named )?(?P<name>[^,.]{1,40}?)"
                             r"(?: on whats ?app)?" + _T, re.I)),
    ("alias_rev", re.compile(_P + r"(?:meri|mera|mere) (?P<alias>[^,.]{1,40}?) (?:ka naam |ki naam )?(?P<name>[^,.]{1,40}?) (?:hai|he|h)" + _T, re.I)),
    ("phone", re.compile(_P + r"(?:remember |save |note )?(?:my )?(?P<name>[^,.]{1,40}?)(?:'s| ka| ki| ke) (?:phone |mobile |whats ?app )?"
                         r"(?:number|no\.?)(?: is| hai| he|:)? (?P<phone>\+?[\d][\d -]{6,18}\d)(?: hai| he| h)?" + _T, re.I)),
    ("email", re.compile(_P + r"(?:remember |save |note )?(?:my )?(?P<name>[^,.@]{1,40}?)(?:'s| ka| ki| ke) (?:e-?mail|mail)"
                         r"(?: id| address)?(?: is| hai| he|:)? (?P<email>[^\s@]+@[^\s@]+?)(?: hai| he| h)?" + _T, re.I)),
    ("home", re.compile(_P + r"(?:remember (?:that )?)?(?:my (?:home|house) is (?:in |at )?|i live (?:in|at) |"
                        r"(?:mera|meri) (?:ghar|home) (?P<x>)?)(?P<value>[^.]{2,120}?)(?: (?:mein|me|pe) (?:hai|he|h)| hai| he)?" + _T, re.I)),
    ("add", re.compile(_P + r"(?:add (?:an? |new )?|new |naya |nayi )" + _LIST + r"\s*(?:[:,-]|to do)?\s+(?P<text>.{2,300}?)" + _T, re.I)),
    ("add", re.compile(_P + r"add (?P<text>.{2,300}?) to my " + _LIST + _T, re.I)),
    ("add", re.compile(_P + r"(?:my )?" + _LIST + r"\s*:\s*(?P<text>.{2,300}?)" + _T, re.I)),
    ("add_many", re.compile(_P + r"my (?P<list>skills|domains|interests) (?:are|include) (?P<text>.{2,300}?)" + _T, re.I)),
    ("done", re.compile(_P + r"(?:mark )?" + _LIST + r" (?P<id>\d{1,3}) (?:as )?(?:done|complete|completed|ho gaya|ho gya|khatam)" + _T, re.I)),
    ("show", re.compile(_P + r"(?:show|list|tell me|what are|what'?s|whats|what is) (?:me )?(?:all )?my " + _LIST
                        + r"(?: for (?:today|this week))?" + _T, re.I)),
    ("show", re.compile(_P + r"(?:mere|meri|mera) " + _LIST + r" (?:dikhao|batao|kya hai|kya hain)" + _T, re.I)),
    ("about", re.compile(_P + r"(?:what do you (?:know|remember) about me|show (?:my )?(?:memory|mind|brain|mind ?map)|"
                         r"who am i|mere baare mein kya pata hai|tumhe mere baare mein kya pata hai)" + _T, re.I)),
    ("who", re.compile(_P + r"(?:who is|who'?s) (?:my )?(?P<name>[^,.?]{1,40}?)" + _T, re.I)),
    ("who", re.compile(_P + r"(?:meri|mera|mere) (?P<name>[^,.?]{1,40}?) kaun (?:hai|he|h)" + _T, re.I)),
    ("send", re.compile(_P + r"(?:send|text|message|msg)\s+(?:a\s+)?(?P<text>.{1,300}?)\s+to\s+(?:my\s+)?(?P<to>[^,.]{1,40}?)" + _T, re.I)),
    ("send", re.compile(_P + r"(?:message|text|ping)\s+(?:my\s+)?(?P<to>[^,.]{1,40}?)\s+(?:saying|that|:|-)\s*(?P<text>.{1,300}?)" + _T, re.I)),
    ("send", re.compile(_P + r"(?:meri |mera |mere )?(?P<to>[^,.]{1,40}?)\s+ko\s+(?P<text>.{1,300}?)\s+(?:bhejo|bhej do|bhejdo|bol do|bolo|send karo)" + _T, re.I)),
]
from chutku.intents.lexicon import NO_TEXT as _NO_TEXT


def _person_word(alias):
    return bool(_PERSON_WORDS.search(alias)) or mind.norm(alias) in {w for group in mind._SAME for w in group}


def parse_mind(goal: str):
    text = " ".join(goal.split())
    for kind, pattern in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        g = {k: (v or "").strip(" '\"“”") for k, v in match.groupdict().items()}
        if kind in ("alias", "alias_rev"):
            name, alias = g["name"], g["alias"]
            if (not _person_word(alias) or not name or _PERSON_WORDS.fullmatch(name.casefold())
                    or re.match(r"(?:who|what|where|which|kaun|kya|is|are)\b", name, re.I)):
                continue  # "my city is Pune" is a fact, not a person
            existing = mind.default().find_person(name)
            name = existing["name"] if existing else name
            return ("mind.person", {"name": name, "aliases": [alias]}, f"Remember {name} as your {alias}",
                    f"Got it: {alias} = {name}.", True)
        if kind == "phone":
            existing = mind.default().find_person(g["name"])
            name = existing["name"] if existing else g["name"]
            phone = re.sub(r"[ -]", "", g["phone"])
            arguments = {"name": name, "phone": phone}
            if not existing and _person_word(g["name"]):
                arguments["aliases"] = [g["name"]]
            return ("mind.person", arguments, f"Save {name}'s number", f"Saved {name}'s number.", True)
        if kind == "email":
            if not mind.EMAIL.fullmatch(g["email"]):
                return None
            existing = mind.default().find_person(g["name"])
            name = existing["name"] if existing else g["name"]
            arguments = {"name": name, "email": g["email"]}
            if not existing and _person_word(g["name"]):
                arguments["aliases"] = [g["name"]]
            return ("mind.person", arguments, f"Save {name}'s email", f"Saved {name}'s email.", True)
        if kind == "home":
            return ("mind.fact", {"key": "home", "value": g["value"]}, "Remember where you live",
                    f"Got it: home is {g['value']}.", True)
        if kind in ("add", "add_many"):
            name = mind.LIST_WORDS.get(mind.norm(g["list"]), None)
            if name is None or g["text"].casefold() in _NO_TEXT:
                return None
            return ("mind.add", {"list": name, "text": g["text"]}, f"Add to your {name}", f"Added to your {name}.", True)
        if kind == "done":
            name = mind.LIST_WORDS.get(mind.norm(g["list"]))
            return ("mind.done", {"list": name, "id": int(g["id"])}, f"Mark {name} {g['id']} done",
                    f"Marked {name} {g['id']} done.", True) if name else None
        if kind == "show":
            name = mind.LIST_WORDS.get(mind.norm(g["list"]))
            return ("mind.show", {"part": name}, f"Show your {name}", "", False) if name else None
        if kind == "about":
            return ("mind.show", {"part": "all"}, "Show what Chutku remembers about you", "", False)
        if kind == "who":
            if mind.default().find_person(g["name"]) is None and not _person_word(g["name"]):
                return None  # "who is the president" is a general question
            return ("mind.who", {"name": g["name"]}, f"Look up {g['name']}", "", False)
        if kind == "send":
            to, body = g["to"], g["text"]
            if re.search(r"\b(?:whats ?app|telegram)\b", text, re.I) or body.casefold() in _NO_TEXT:
                return None  # with an app named, message_intent handles it
            person = mind.default().find_person(to)
            if person is None:
                return None  # only people the owner's memory knows: never a guess
            arguments = {"app": "whatsapp", "to": to, "text": body}
            return ("message.send", arguments, f"Send a WhatsApp message to {person['name']}",
                    f"Message for {person['name']} ({to}) on WhatsApp: “{body}”.", False)
    return None
