"""Understand "send a message" requests instantly, in the owner's words or the voice model's rewrite.

Handles typed English/Hinglish ("send hi to UB on whatsapp", "UB ko whatsapp pe hi bhejo") and the
Gemini Live rewrites seen in real sessions ("In WhatsApp, find the chat titled "UB" and send the
message "hi" to it."). Returns {"app", "to", "text"} or None when anything is unclear, so the model
(and, in any case, the on-screen approval card) handles it.
"""
from __future__ import annotations

import re

_APP = re.compile(r"\b(whats\s?app|telegram)\b", re.I)
_QUOTED = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{1,300})[\"“”'‘’]")
_NAMED = re.compile(r"\b(?:chat|user|contact|person|group)\s+(?:named|titled|called)\s+[\"“”'‘’]?([^\"“”'‘’,.]{1,40}?)[\"“”'‘’]?"
                    r"(?=\s+(?:and|on|in|via|saying)\b|[,.]|$)", re.I)
_TYPED = [
    # send hi to UB on whatsapp / send a message "hi" to UB on whatsapp
    re.compile(r"^(?:please\s+)?(?:send|text|message)\s+(?:a\s+)?(?:message\s+|msg\s+)?(?:saying\s+)?(?P<text>.{1,300}?)\s+"
               r"to\s+(?P<to>[^,.]{1,40}?)\s+(?:on|in|via|using)\s+(?P<app>whats\s?app|telegram)[\s.!]*$", re.I),
    # message UB on whatsapp saying hi / whatsapp UB: hi
    re.compile(r"^(?:please\s+)?(?:message|text|ping)\s+(?P<to>[^,.]{1,40}?)\s+(?:on|in|via)\s+(?P<app>whats\s?app|telegram)"
               r"\s*(?:saying|that|:|-)\s*(?P<text>.{1,300}?)[\s.!]*$", re.I),
    re.compile(r"^(?P<app>whats\s?app|telegram)\s+(?P<to>[^:,]{1,40}?)\s*[:,-]\s*(?P<text>.{1,300}?)[\s.!]*$", re.I),
    # UB ko whatsapp pe hi bhejo / UB ko hi bhej do whatsapp pe
    re.compile(r"^(?P<to>[^,.]{1,40}?)\s+ko\s+(?P<app>whats\s?app|telegram)\s+(?:pe|par|par\s+se|se)\s+(?P<text>.{1,300}?)\s+"
               r"(?:bhejo|bhej\s+do|bhejdo|send\s+karo|send\s+kar\s+do)[\s.!]*$", re.I),
    re.compile(r"^(?P<to>[^,.]{1,40}?)\s+ko\s+(?P<text>.{1,300}?)\s+(?:bhejo|bhej\s+do|bhejdo)\s+(?P<app>whats\s?app|telegram)"
               r"\s+(?:pe|par|se)[\s.!]*$", re.I),
]
from chutku.intents.lexicon import NO_TEXT as _NO_TEXT
_TO_ON_APP = re.compile(r"\bto\s+(?!it\b)([^\"“”'‘’,.]{1,40}?)\s+(?:on|in|via)\s+(?:whats\s?app|telegram)\b", re.I)
_FILLER = re.compile(r"^(?:the\s+)?(?:user|contact|chat|person)\s+(?:named|called|titled)\s+", re.I)


def _app_name(raw):
    return "telegram" if raw.casefold().startswith("tele") else "whatsapp"


def _clean(value):
    return value.strip().strip("\"“”'‘’").strip()


def parse_send(goal: str):
    from chutku.translit import roman
    text = " ".join(roman(goal).split())
    if not _APP.search(text) or not re.search(r"\b(?:send|message|text|msg|ping|bhej|bhejo)\b|:", text, re.I):
        return None
    for pattern in _TYPED if not _QUOTED.search(text) else ():  # quoted messages take the path below
        match = pattern.match(text)
        if match:
            to, body = _FILLER.sub("", _clean(match.group("to"))), _clean(match.group("text"))
            if to and body and len(to) <= 40 and not _APP.search(to) and body.casefold() not in _NO_TEXT:
                return {"app": _app_name(match.group("app")), "to": to, "text": body}
    # Voice-model rewrites: the message is quoted; the recipient is "named/titled X" or a quoted name after "to".
    named = _NAMED.search(text)
    quoted = [q.strip() for q in _QUOTED.findall(text)]
    message_quote = re.search(r"\b(?:message|text|saying|send)\s+[\"“”'‘’]([^\"“”'‘’]{1,300})[\"“”'‘’]", text, re.I)
    if not message_quote:
        return None
    body = message_quote.group(1).strip()
    to = _clean(named.group(1)) if named else None
    if to is None:
        others = [q for q in quoted if q != body]
        to_quote = re.search(r"\bto\s+[\"“”'‘’]([^\"“”'‘’]{1,40})[\"“”'‘’]", text, re.I)
        to_plain = _TO_ON_APP.search(text)
        to = (to_quote.group(1).strip() if to_quote else _FILLER.sub("", to_plain.group(1).strip()) if to_plain
              else others[0] if len(others) == 1 else None)
    if not to or not body or len(to) > 40:
        return None
    return {"app": _app_name(_APP.search(text).group(1)), "to": to, "text": body}


_APP_WORD = r"(?P<app>whats\s?app|telegram)"
_NAME = r"[\"“”'‘’]?(?P<to>[^\"“”'‘’,.?]{1,40}?)[\"“”'‘’]?"
_OPEN_CHAT = [
    # Live-model rewrites: search for "पिता श्री" in WhatsApp contact list
    re.compile(r"^(?:please\s+)?(?:search|look|find|dhundo|khojo)\s+(?:for\s+)?" + _NAME
               + r"\s+(?:in|on)\s+(?:my\s+)?" + _APP_WORD + r"(?:\s+(?:contact list|contacts|chats|chat list))?[\s.!?]*$", re.I),
    # open Pita Shri's chat on WhatsApp / open the chat with Pita Shri in WhatsApp
    re.compile(r"^(?:please\s+)?open\s+" + _NAME + r"(?:'s|s)?\s+(?:chat|conversation)\s+(?:on|in)\s+" + _APP_WORD
               + r"[\s.!?]*$", re.I),
    re.compile(r"^(?:please\s+)?open\s+(?:the\s+)?(?:chat|conversation)\s+with\s+" + _NAME + r"\s+(?:on|in)\s+"
               + _APP_WORD + r"[\s.!?]*$", re.I),
    # WhatsApp pe Pita Shri ki chat kholo / Pita Shri ki chat kholo whatsapp pe / Pita Shri ko whatsapp pe dhundo
    re.compile(r"^" + _APP_WORD + r"\s+(?:pe|par|mein|me)\s+" + _NAME + r"\s+(?:ki|ka|ke)\s+(?:chat|chats)\s+"
               r"(?:kholo|khol do|open karo|dikhao|nikalo)[\s.!?]*$", re.I),
    re.compile(r"^" + _NAME + r"\s+(?:ki|ka|ke)\s+(?:chat|chats)\s+(?:kholo|khol do|open karo|dikhao)\s+"
               + _APP_WORD + r"\s+(?:pe|par|mein|me)[\s.!?]*$", re.I),
    re.compile(r"^" + _NAME + r"\s+ko\s+" + _APP_WORD + r"\s+(?:pe|par|mein|me)\s+(?:dhundo|khojo|search karo|kholo)[\s.!?]*$", re.I),
]


def parse_open_chat(goal: str):
    """'search X in WhatsApp' / 'X ki chat kholo WhatsApp pe' -> {"app", "to"} (open the chat, send nothing)."""
    from chutku.translit import roman
    text = " ".join(roman(goal).split())
    for pattern in _OPEN_CHAT:
        match = pattern.match(text)
        if match:
            to = match.group("to").strip()
            if to and not re.fullmatch(r"(?:it|this|that|someone|contacts?|chats?|messages?)", to, re.I):
                return {"app": _app_name(match.group("app")), "to": to}
    return None


# Only explicit "send" words: "write a poem" or "write x into D:\\a.txt" must never become a message
# (caught by the full test run 2026-10-04).
_FOLLOW_UP_SEND = [
    re.compile(r"^(?:please\s+)?(?:send|message)\s+[\"“”'‘’]?(?P<text>[^\"“”]{1,500}?)[\"“”'‘’]?"
               r"(?:\s+(?:to (?:him|her|them|it)|there|usko|use))?[\s.!?]*$", re.I),
    re.compile(r"^[\"“”'‘’]?(?P<text>[^\"“”]{1,500}?)[\"“”'‘’]?\s+(?:bhejo|bhej do|bhejdo|send karo|send kar do|"
               r"bol do)[\s.!?]*$", re.I),
]
_NOT_A_MESSAGE = re.compile(r"[a-z]:\\|\binto\b|\bfile\b|\bfolder\b|\.(?:txt|docx?|pdf|py|md)\b", re.I)


def parse_follow_up_send(goal: str):
    """Right after a chat was opened: "hi bhej do" / "send good night" -> the message text, else None."""
    from chutku.translit import roman
    text = " ".join(roman(goal).split())
    if _APP.search(text) or re.search(r"\bto\s+\w", text, re.I) and not re.search(r"\bto (?:him|her|them|it)\b", text, re.I):
        return None  # names another app or person: the normal parser handles it
    if _NOT_A_MESSAGE.search(text):
        return None
    for pattern in _FOLLOW_UP_SEND:
        match = pattern.match(text)
        if match:
            body = match.group("text").strip()
            if body and body.casefold() not in _NO_TEXT:
                return body
    return None


_READ_CHAT = [
    re.compile(r"^(?:please\s+)?(?:what did|what has)\s+" + _NAME + r"\s+(?:say|said|send|sent|reply|replied|write|written)"
               r"(?:\s+(?:on|in)\s+" + _APP_WORD + r")?[\s.!?]*$", re.I),
    re.compile(r"^(?:please\s+)?(?:did|has)\s+" + _NAME + r"\s+(?:replied|reply|answered|messaged|texted)"
               r"(?:\s+(?:me|back))?(?:\s+(?:on|in)\s+" + _APP_WORD + r")?[\s.!?]*$", re.I),
    re.compile(r"^(?:please\s+)?(?:read|show|check)\s+(?:my\s+)?(?:chat|messages?)\s+(?:with|from)\s+" + _NAME
               + r"(?:\s+(?:on|in)\s+" + _APP_WORD + r")?[\s.!?]*$", re.I),
    re.compile(r"^" + _NAME + r"\s+(?:ne|ka|ki)\s+(?:kya\s+(?:bola|likha|bheja|kaha)|last message|reply)(?:\s+(?:kya\s+)?(?:hai|kiya))?"
               r"(?:\s+(?:whats\s?app|telegram)\s+(?:pe|par|mein))?[\s.!?]*$", re.I),
    re.compile(r"^(?:kya\s+)?" + _NAME + r"\s+ne\s+reply\s+(?:kiya|kara)(?:\s+kya)?[\s.!?]*$", re.I),
]


def parse_read_chat(goal: str):
    """'what did Pita Shri say' / 'did mammi reply' / 'UB ne kya bola' -> {"app", "to"} (read the chat)."""
    from chutku.translit import roman
    text = " ".join(roman(goal).split())
    for pattern in _READ_CHAT:
        match = pattern.match(text)
        if match:
            to = re.sub(r"^(?:kya|did|has)\s+", "", match.group("to").strip(), flags=re.I)
            if to and not re.fullmatch(r"(?:you|it|this|that|he|she|they|someone|everyone|anyone)", to, re.I):
                app = match.groupdict().get("app")
                return {"app": _app_name(app) if app else "whatsapp", "to": to}
    return None


_TELL = re.compile(r"^(?:please\s+)?(?P<to>[^,.?]{1,40}?)\s+ko\s+(?:bolo|bol do|bolna|keh do|kaho|bata do|batao|likh do)"
                   r"\s+(?:ki\s+)?(?P<text>.{1,300}?)[\s.!?]*$", re.I)
_TELL_TAIL = re.compile(r"^(?:please\s+)?(?P<to>[^,.?]{1,40}?)\s+ko\s+(?P<text>.{1,300}?)\s+(?:bolo|bol do|keh do|bata do)"
                        r"[\s.!?]*$", re.I)
_NOT_PEOPLE = {"mujhe", "mujhko", "hume", "humko", "use", "usko", "unko", "sabko", "me", "you", "chutku", "isko", "ise"}


def parse_tell(goal: str):
    """'Pita Shri ko bolo main late aaunga' -> a WhatsApp message (the owner's everyday way of saying "send")."""
    from chutku.translit import roman
    text = " ".join(roman(goal).split())
    for pattern in (_TELL, _TELL_TAIL):
        match = pattern.match(text)
        if match:
            to, body = match.group("to").strip(), match.group("text").strip(" \"'“”")
            if to.casefold() in _NOT_PEOPLE or not body or body.casefold() in _NO_TEXT or len(to.split()) > 4:
                return None
            return {"app": "whatsapp", "to": to, "text": body}
    return None

