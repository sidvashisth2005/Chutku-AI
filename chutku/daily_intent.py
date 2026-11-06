"""Everyday Hinglish the owner actually says (found by a 45-phrase real-life sweep on 2026-10-04: 21 missed).

    "agla gaana" / "pichla gaana"                      -> media.control next / previous
    "volume thoda badhao" / "awaaz thodi kam karo"     -> audio.volume up / down
    "brightness full karo" / "screen ki brightness 50 karo" -> display.brightness set
    "screenshot lo" / "take a screenshot"              -> Win+PrintScreen (Windows saves it to Pictures\\Screenshots)
    "10 minute ka timer lagao"                         -> reminder.set in N minutes
    "kal subah 7 baje ka alarm lagao" / "mujhe 5 baje yaad dilana meeting hai" -> reminder.set at a time
    "cricket score kya hai"                            -> a Google search for the live score
    "kya chal raha hai screen pe" / "yeh kya hai"      -> screen.understand (what was on screen)
    "mammi ko call karo" / "recycle bin khali karo"    -> an honest instant answer (not supported / asks)

Returns (tool, arguments, purpose, reply, finish) or, for an answer only, ("", {}, "", reply, True); else None.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import re

from chutku.intents.lexicon import LEAD as _P, TAIL as _T   # one Hinglish vocabulary for every parser
_DO = r"(?:karo|kar do|kardo|kar de|karna|do|de do)"

_MEDIA_APP = r"youtube|yt|spotify|brave|chrome|edge|firefox|vlc|browser"
_MEDIA_THING = r"(?:the\s+)?(?:video|song|music|track|gaana|gana|media)"
_PATTERNS = [
    # Z3 (2026-11-06): "pause youtube in brave" went through the planner (keys, screen, windows) and was slow.
    ("media_app", re.compile(_P + rf"(?P<verb>pause|resume|unpause|stop|next|skip|previous)"
                             rf"(?:\s+(?:the\s+)?(?P<a1>{_MEDIA_APP}))?(?:\s+(?:ka|ki|ke|wala|wali))?"
                             rf"(?:\s+{_MEDIA_THING})?"
                             rf"(?:\s+(?:in|on)\s+(?:the\s+)?(?P<a2>{_MEDIA_APP}))?" + _T, re.I)),
    ("media_app", re.compile(_P + rf"(?P<a1>{_MEDIA_APP})\s+(?:(?:pe|par|mein|me|ka|ki|ke|wala|wali)\s+)?"
                             rf"(?:(?P<thing>{_MEDIA_THING})\s+)?(?P<verb>pause|roko|rok do|resume|band|agla|next|skip|"
                             rf"pichla|previous)(?:\s+(?:video|song|gaana|gana|track))?"
                             rf"(?:\s+(?:karo|kar do|kardo|kar de|karna|do|chalao|lagao|bajao))?" + _T, re.I)),
    # Z3: the window in front, and Windows' own shortcuts, in one step.
    ("window", re.compile(_P + r"(?P<w>minimize|minimise|maximize|maximise|restore|close)\s+(?:this|the|current|my)\s+"
                          r"(?:window|app)" + _T, re.I)),
    ("window", re.compile(_P + r"(?:(?:ye|yeh|is|iss|this|current)\s+)?(?:window|app)\s+(?:ko\s+)?(?P<w>minimize|minimise|"
                          r"maximize|maximise|restore|chhota|chota|bada|band|left|right|left side|right side|left mein|"
                          r"right mein)\s*(?:" + _DO + r")?" + _T, re.I)),
    ("window", re.compile(_P + r"snap\s+(?:this\s+|the\s+)?(?:window\s+)?(?:to\s+the\s+)?(?P<w>left|right)" + _T, re.I)),
    ("os_keys", re.compile(_P + r"(?P<k>show\s+(?:the\s+)?desktop|desktop\s+dikhao|switch\s+(?:the\s+)?windows?|"
                           r"window\s+switch\s+karo|alt\s+tab|task\s+view(?:\s+(?:kholo|dikhao|open karo))?|"
                           r"saari\s+windows\s+dikhao|show\s+all\s+windows)" + _T, re.I)),
    # H24: standing goals. "goal: ...", "mere goals", "goal 2 ho gaya", "goal 2 hatao".
    ("goal_add", re.compile(_P + r"(?:goal|mera\s+goal\s+(?:hai|ye\s+hai)|naya\s+goal|new\s+goal|set\s+(?:a\s+)?goal)\s*[:\-]"
                            r"\s*(?P<text>.{3,300}?)" + _T, re.I)),
    ("goal_list", re.compile(_P + r"(?:mere\s+goals?(?:\s+(?:dikhao|batao|kya\s+hain))?|(?:show|list)\s+(?:my\s+)?goals|"
                             r"goals?\s+(?:dikhao|status|kahan\s+tak))" + _T, re.I)),
    ("goal_done", re.compile(_P + r"goal\s+(?P<n>\d{1,4})\s+(?:ho\s+gaya|pura\s+(?:ho\s+gaya|hua)|done|complete)" + _T, re.I)),
    ("goal_remove", re.compile(_P + r"goal\s+(?P<n>\d{1,4})\s+(?:hatao|hata\s+do|remove\s+karo|delete\s+karo)|"
                               r"remove\s+goal\s+(?P<n2>\d{1,4})" + _T, re.I)),
    # H25: memory backups. Restoring is never by voice: it needs Chutku stopped (chutku.cli backup restore).
    ("backup", re.compile(_P + r"(?P<b>(?:ek\s+)?backup\s+(?:bana\s+lo|banao|bana\s+do|le\s+lo|lo|karo|kar\s+do)|"
                          r"(?:take|make)\s+a\s+backup|back\s+up\s+(?:your|chutku'?s?)\s+memory)|(?P<l>backups?\s+"
                          r"(?:dikhao|list)|(?:show|list)\s+(?:my\s+)?backups)|(?P<r>backup\s+se\s+wapas\s+lao.*|"
                          r"restore\s+(?:a\s+|the\s+)?backup.*)" + _T, re.I)),
    # H17: reply style. "formal ho jao", "chhota jawab do", "masti mode", "normal ho jao".
    ("style", re.compile(_P + r"(?:(?P<formal>formal(?:\s+(?:ho\s+jao|bano|mode|baat\s+karo|raho))?|be\s+formal|"
                         r"talk\s+formally)|(?P<short>(?:chhota|chota|short)\s+jawab\s+(?:do|dena)|short\s+answers?|"
                         r"short\s+mode|be\s+brief)|(?P<masti>masti\s+(?:mode|karo|wali\s+baat)|be\s+playful|"
                         r"fun\s+mode)|(?P<normal>normal\s+(?:ho\s+jao|mode|baat\s+karo)|talk\s+normally))" + _T, re.I)),
    ("spotify", re.compile(_P + r"(?:spotify\s+(?:pe|par|mein|me)\s+(?P<q>.{2,150}?)\s+(?:chalao|bajao|lagao|play karo|sunao)|"
                           r"play\s+(?P<q2>.{2,150}?)\s+on\s+spotify|(?P<q3>.{2,150}?)\s+spotify\s+(?:pe|par)\s+(?:chalao|bajao|lagao))" + _T, re.I)),
    ("time", re.compile(_P + r"(?:mujhe\s+)?(?:batao|bata do|bolo)?\s*(?:abhi\s+)?(?:time|samay|kitne baje)\s+(?:kya|kitna)?\s*"
                        r"(?:hai|hua|ho gaya|ho gaye|hue)(?:\s+(?:batao|bata do))?" + _T, re.I)),
    ("next", re.compile(_P + r"(?:agla|next|dusra|doosra)\s+(?:gaana|gana|song|track)(?:\s+(?:chalao|lagao|bajao|play karo))?" + _T, re.I)),
    ("previous", re.compile(_P + r"(?:pichla|pichhla|previous|purana)\s+(?:gaana|gana|song|track)(?:\s+(?:chalao|lagao|bajao|play karo))?" + _T, re.I)),
    ("volume", re.compile(_P + r"(?:volume|awaaz|aawaz|awaz|sound)\s+(?:thoda|thodi|aur|zyada|bahut)?\s*"
                          r"(?P<dir>badhao|badha do|tez karo|tez kar do|up karo|kam karo|kam kar do|dheere karo|dheemi karo|down karo)" + _T, re.I)),
    ("bright_word", re.compile(_P + r"(?:screen\s+ki\s+)?brightness\s+(?P<word>full|poori|puri|max|maximum|zero|minimum|kam se kam|aadhi|half)\s*(?:" + _DO + r")?" + _T, re.I)),
    ("bright_level", re.compile(_P + r"(?:screen\s+ki\s+)?brightness\s+(?P<level>\d{1,3})\s*(?:%|percent|pe|par)?\s*" + _DO + _T, re.I)),
    ("screenshot", re.compile(_P + r"(?:take\s+a\s+screenshot|screenshot\s+(?:lo|le lo|le|lelo|le do|karo|kar do|khicho|khinch lo|bana do)|"
                              r"(?:ek\s+)?screenshot(?:\s+please)?|capture\s+(?:the\s+)?screen)" + _T, re.I)),
    ("timer", re.compile(_P + r"(?P<n>\d{1,3})\s*(?P<unit>minute|minutes|min|mins|ghante|ghanta|hour|hours)\s+(?:ka|ki)\s+"
                         r"(?:timer|alarm|reminder)\s+(?:lagao|laga do|set karo|set kar do|lagana)" + _T, re.I)),
    ("at_time", re.compile(_P + r"(?:mujhe\s+)?(?P<day>kal\s+|aaj\s+)?(?P<part>subah|savere|sham|shaam|raat|dopahar|dophar)?\s*(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*baje"
                           r"(?:\s+(?:ka|ki)\s+alarm\s+(?:lagao|laga do|set karo)|\s+alarm\s+(?:lagao|laga do)"
                           r"|\s+(?:mujhe\s+)?(?:yaad dilana|yaad dila dena|remind karna)(?:\s+ki)?\s+(?P<msg>.{2,150}?)"
                           r"|\s+(?P<msg2>.{2,150}?)\s+(?:yaad dilana|yaad dila dena|remind karna))" + _T, re.I)),
    ("at_time", re.compile(_P + r"mujhe\s+(?P<day>kal\s+|aaj\s+)?(?P<part>subah|savere|sham|shaam|raat|dopahar|dophar)?\s*(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*baje\s+"
                           r"yaad dilana(?:\s+ki)?\s+(?P<msg3>.{2,150}?)" + _T, re.I)),
    ("score", re.compile(_P + r"(?P<what>(?:india(?:\s+ka)?\s+)?(?:cricket|ipl|match|india|rcb|csk|mi)(?:\s+match)?)\s+(?:ka\s+)?(?:live\s+)?score(?:\s+(?:kya hai|batao|kitna hai|kya chal raha hai))?" + _T, re.I)),
    ("screen", re.compile(_P + r"(?:kya chal raha hai screen (?:pe|par)|screen (?:pe|par) kya chal raha hai|ye+h? kya hai|ye+h? kya h|"
                          r"isko samjhao|isme kya likha hai|ye+h? screen pe kya hai|ye+h? kya dikh raha hai|what is this)" + _T, re.I)),
    ("call", re.compile(_P + r"(?P<who>[\w ]{1,40}?)\s+ko\s+(?:call|phone|video call)\s+(?:karo|kar do|lagao|laga do)" + _T, re.I)),
    ("call", re.compile(_P + r"(?:call|phone|video call)\s+(?!it\s+(?:a day|a night|quits|off)\b)(?P<who>[\w ]{1,40}?)"
                        + _T, re.I)),
    ("empty_bin", re.compile(_P + r"(?:recycle bin|dustbin|bin)\s+(?:khali|saaf|empty)\s*(?:karo|kar do)?|empty (?:the )?recycle bin" + _T, re.I)),
]
_PARTS = {"subah": "am", "savere": "am", "dopahar": "pm", "dophar": "pm", "sham": "pm", "shaam": "pm", "raat": "pm"}


def _at(day, part, hour, minute, now=None):
    """'subah' = morning, 'dopahar'/'sham'/'raat' = afternoon/evening. Without one, the everyday Indian meaning:
    1-6 baje is afternoon/evening, 7-11 is morning, 12 is noon. A time already gone today means tomorrow."""
    now = now or datetime.now()
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if hour <= 12:
        if part:
            evening = _PARTS[part] == "pm"
        else:
            evening = 1 <= hour <= 6
        if evening and hour < 12:
            hour += 12
        elif not evening and hour == 12 and part in ("subah", "savere"):
            hour = 0
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day and day.strip() == "kal":
        return when + timedelta(days=1)
    return when if when > now else when + timedelta(days=1)


def parse_daily(goal, now=None):
    text = " ".join(goal.split())
    for kind, pattern in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        g = match.groupdict()
        if kind == "goal_add":
            return "goals.add", {"text": g["text"].strip()}, "Set a standing goal", "", False
        if kind == "goal_list":
            return "goals.list", {}, "Show the goals", "", False
        if kind == "goal_done":
            return "goals.done", {"id": int(g["n"])}, f"Goal {g['n']} done", "", False
        if kind == "goal_remove":
            number = int(g.get("n") or g.get("n2"))
            return "goals.remove", {"id": number}, f"Remove goal {number}", f"Goal {number} hata diya.", True
        if kind == "backup":
            if g.get("r"):
                return "", {}, "", ("Restore sirf laptop pe hota hai, Chutku band karke: Stop-Chutku.cmd, phir "
                                    "`chutku.cli backup list` aur `chutku.cli backup restore <zip>`. Pehle ek safety "
                                    "backup apne aap banta hai."), True
            if g.get("l"):
                return "backup.list", {}, "List the backups", "", False
            return "backup.create", {}, "Back up Chutku's memory", "Backup bana diya.", False
        if kind == "style":
            style = next(k for k in ("formal", "short", "masti", "normal") if g.get(k))
            return "settings.reply_style", {"style": style}, f"Reply style: {style}", {
                "formal": "Ji, ab se formal baat karungi.", "short": "Theek hai, chhote jawab.",
                "masti": "Masti mode on! 😄", "normal": "Theek hai, normal ho gayi."}[style], True
        if kind == "window":
            word = g["w"].casefold().split()[0]
            action = {"minimize": "minimize", "minimise": "minimize", "chhota": "minimize", "chota": "minimize",
                      "maximize": "maximize", "maximise": "maximize", "bada": "maximize", "restore": "restore",
                      "left": "snap_left", "right": "snap_right", "close": "close", "band": "close"}[word]
            if action == "close":
                return "windows.close_this", {}, "Close the window in front", "Window band kar di.", True
            return "windows.this", {"action": action}, f"Window: {action}", "Window " + {
                "minimize": "chhoti kar di.", "maximize": "badi kar di.", "restore": "pehle jaisi kar di.",
                "snap_left": "left mein laga di.", "snap_right": "right mein laga di."}[action], True
        if kind == "os_keys":
            said = g["k"].casefold()
            keys = "win+d" if "desktop" in said else "win+tab" if ("task" in said or "saari" in said or "all" in said) \
                else "alt+tab"
            return "keyboard.keys", {"keys": keys}, f"Press {keys}", "Ho gaya.", True
        if kind == "media_app":
            apps = [a.casefold() for a in (g.get("a2"), g.get("a1")) if a]
            verb = g["verb"].casefold()
            if not apps or (verb == "band" and not g.get("thing")):
                continue   # "pause" alone is the plain media step; "spotify band karo" closes the app
            app = next((a for a in apps if a not in ("youtube", "yt", "browser")), "browser")
            action = {"pause": "pause", "stop": "pause", "roko": "pause", "rok do": "pause", "band": "pause",
                      "resume": "play", "unpause": "play", "next": "next", "skip": "next", "agla": "next",
                      "pichla": "previous", "previous": "previous"}[verb]
            return "media.control", {"action": action, "app": app}, f"Media: {action} in {app}", \
                {"pause": "Paused.", "play": "Resumed.", "next": "Skipped to the next one.",
                 "previous": "Went back to the previous one."}[action], True
        if kind == "spotify":
            query = (g.get("q") or g.get("q2") or g.get("q3") or "").strip(" '\"")
            return "spotify.search", {"query": query}, f"Search Spotify for {query}", \
                f"Opened Spotify's search for “{query}”.", True
        if kind == "time":
            return "system.get_time", {}, "Read the time", "", False
        if kind in ("next", "previous"):
            return "media.control", {"action": kind}, f"Media: {kind}", \
                "Skipped to the next track." if kind == "next" else "Went back to the previous track.", True
        if kind == "volume":
            up = g["dir"].casefold().startswith(("badha", "tez", "up"))
            return "audio.volume", {"action": "up" if up else "down"}, "Volume " + ("up" if up else "down"), \
                "Turned the volume " + ("up." if up else "down."), True
        if kind == "bright_word":
            level = {"full": 100, "poori": 100, "puri": 100, "max": 100, "maximum": 100, "zero": 0, "minimum": 0,
                     "kam se kam": 0, "aadhi": 50, "half": 50}[g["word"].casefold()]
            return "display.brightness", {"action": "set", "level": level}, f"Set brightness to {level}%", \
                f"Brightness is now {level}%.", True
        if kind == "bright_level":
            level = int(g["level"])
            if level > 100:
                return None
            return "display.brightness", {"action": "set", "level": level}, f"Set brightness to {level}%", \
                f"Brightness is now {level}%.", True
        if kind == "screenshot":
            return "keyboard.keys", {"keys": "win+printscreen"}, "Take a screenshot", \
                "Took a screenshot; Windows saved it in Pictures\\Screenshots.", True
        if kind == "timer":
            n = int(g["n"])
            minutes = n * 60 if g["unit"].casefold().startswith(("ghant", "hour")) else n
            if not 1 <= minutes <= 1440:
                return None
            return "reminder.set", {"message": "Timer done", "in_minutes": minutes}, f"Set a {minutes}-minute timer", \
                f"Timer set for {minutes} minutes.", True
        if kind == "at_time":
            when = _at(g.get("day"), (g.get("part") or "").casefold() or None, int(g["h"]), int(g.get("m") or 0), now)
            if when is None:
                return None
            message = (g.get("msg") or g.get("msg2") or g.get("msg3") or "Alarm").strip(" '\".")
            return "reminder.set", {"message": message[:200], "at": when.strftime("%Y-%m-%dT%H:%M")}, "Set a reminder", \
                f"Okay, I'll remind you {when.strftime('%A at %I:%M %p')}.", True
        if kind == "score":
            what = g["what"].strip()
            query = f"{what} score" if "score" not in what.casefold() else what
            return "web.search", {"query": f"{query} live" if "live" not in query else query, "site": "google"}, \
                "Look up the live score", "Opened the live score.", True
        if kind == "screen":
            return "screen.ask", {"when": "hotkey_moment", "question": goal[:300]}, "Look at the screen", "", False
        if kind == "call":
            who = g["who"].strip()
            if who.casefold() in {"mujhe", "me", "us", "hume", "use", "usko"}:
                return None
            return "", {}, "", (f"I can't make calls yet. I can send {who} a WhatsApp message instead: "
                                f"say \"{who} ko … bhejo\"."), True
        if kind == "empty_bin":
            return "", {}, "", ("I don't empty the Recycle Bin myself, because that deletes files for good. "
                                "Open it and choose \"Empty Recycle Bin\" when you're sure."), True
    return None
