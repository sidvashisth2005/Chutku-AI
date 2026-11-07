"""The owner's personal memory ("mind"): people with their nicknames, facts about the owner, and lists.

Stored locally in data/mind.json (never sent anywhere by this module). Lookups are exact after normalising
("my gf", "meri gf", "GF" and "girlfriend" are the same key), never fuzzy: a message must never reach the wrong
person because two names looked alike.

    people: [{"name": "AK", "aliases": ["gf"], "relation": "girlfriend", "whatsapp": "AK", "phone": "", "email": ""}]
            ("email" is optional: only people the owner gave an address have it)
    facts:  {"home": "Pune, Maharashtra", ...}
    lists:  {"assignments": [{"id": 1, "text": "...", "done": false, "added": "2026-10-04"}], "schedule": [...], ...}
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import re
import threading

LISTS = ("assignments", "schedule", "skills", "domains", "projects", "goals", "notes")
LIST_WORDS = {
    "assignment": "assignments", "assignments": "assignments", "homework": "assignments", "task": "assignments",
    "schedule": "schedule", "timetable": "schedule", "class": "schedule", "classes": "schedule", "routine": "schedule",
    "skill": "skills", "skills": "skills", "domain": "domains", "domains": "domains", "interest": "domains",
    "interests": "domains", "project": "projects", "projects": "projects", "goal": "goals", "goals": "goals",
    "note": "notes", "notes": "notes",
}
# Words with one meaning, so "mammi" finds the person saved as "mummy" or with relation "mother".
_SAME = [
    {"mom", "mummy", "mammi", "mummi", "mumma", "maa", "mother", "mommy", "ammi"},  # not "mama" (= uncle)
    {"dad", "papa", "pappa", "father", "pita", "pitaji", "pita ji", "pita shri", "daddy", "abbu"},
    {"gf", "girlfriend", "girl friend"},
    {"bf", "boyfriend", "boy friend"},
    {"bro", "brother", "bhai", "bhaiya", "bhaiyya"},
    {"sis", "sister", "behen", "didi"},
    {"wife", "biwi", "patni"},
    {"husband", "pati"},
]
EMAIL = re.compile(r"[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")   # no ?&%: mailto-safe
_FILLER = re.compile(r"^(?:my|meri|mere|mera|apni|apne|apna|the)\s+|\s+(?:ko|ka|ki|ke|se)$", re.I)
_lock = threading.Lock()
from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)


def default():
    """The owner's mind store (tests point PROJECT_ROOT at a temporary folder)."""
    return Mind(PROJECT_ROOT)


def norm(text):
    """Lower-case, single-spaced, without "my/meri/mere" in front or "ko/ka" behind; Hindi script as Hinglish."""
    from chutku.translit import roman
    text = " ".join(roman(str(text)).casefold().replace("’", "'").split())
    text = re.sub(r"[^\w\s'+]", "", text).strip()
    previous = None
    while previous != text:
        previous, text = text, _FILLER.sub("", text).strip()
    return re.sub(r"\b(?:waale|vaale|vale)\b", "wale", text)


def _family(word):
    for group in _SAME:
        if word in group:
            return group
    return {word}


class Mind:
    def __init__(self, base):
        self.path = Path(base) / "data" / "mind.json"

    # -- storage -------------------------------------------------------------------------
    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("people", [])
        data.setdefault("facts", {})
        lists = data.setdefault("lists", {})
        for name in LISTS:
            lists.setdefault(name, [])
        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)  # never a half-written file

    def _change(self, edit):
        with _lock:
            data = self.load()
            result = edit(data)
            self._save(data)
            return result

    # -- people ----------------------------------------------------------------------------
    def find_person(self, text, data=None):
        """The one saved person this name, nickname or relation means; None if unknown or ambiguous."""
        wanted = norm(text)
        if not wanted:
            return None
        keys = _family(wanted)
        found = []
        for person in (data or self.load())["people"]:
            names = {norm(person.get("name", "")), norm(person.get("whatsapp", "")), norm(person.get("relation", ""))}
            names |= {norm(alias) for alias in person.get("aliases", [])}
            names.discard("")
            if any(name in keys or _family(name) & keys for name in names):
                found.append(person)
        return found[0] if len(found) == 1 else None

    def identity_change(self, name, *, whatsapp="", phone=""):
        """Which saved contact detail (phone or WhatsApp chat name) remembering this would overwrite, or None.

        Messages to remembered people go out without asking, so changing where they go must be the owner's choice."""
        name = " ".join(str(name or "").split())
        person = next((p for p in self.load()["people"] if norm(p.get("name", "")) == norm(name)), None)
        if person is None:
            return None
        phone = re.sub(r"[ -]", "", str(phone or ""))
        if phone and person.get("phone") and phone != re.sub(r"[ -]", "", person["phone"]):
            return "phone"
        whatsapp = " ".join(str(whatsapp or "").split())
        if whatsapp and person.get("whatsapp") and norm(whatsapp) != norm(person["whatsapp"]):
            return "WhatsApp chat name"
        return None

    def remember_person(self, name, *, aliases=(), relation="", whatsapp="", phone="", note="", email=""):
        """Add a person or merge into the existing one with that name (aliases are added, never dropped)."""
        name = " ".join(str(name).split())
        if not name or len(name) > 60:
            raise ValueError("Give the person's name (up to 60 characters).")
        phone = re.sub(r"[ -]", "", str(phone or ""))
        if phone and not re.fullmatch(r"\+?\d{8,15}", phone):
            raise ValueError("A phone number is 8-15 digits, optionally starting with +.")
        email = str(email or "").strip()
        if email and (len(email) > 254 or not EMAIL.fullmatch(email)):
            raise ValueError("That does not look like an email address (name@example.com).")
        from chutku import scan   # saved text is read back into her prompt: no hidden characters or orders (H3)
        scan.check(name, relation, whatsapp, note, *[str(a) for a in aliases])

        def edit(data):
            person = next((p for p in data["people"] if norm(p["name"]) == norm(name)), None)
            if person is None:
                person = {"name": name, "aliases": [], "relation": "", "whatsapp": "", "phone": "", "notes": []}
                data["people"].append(person)
            for alias in aliases:
                alias = " ".join(str(alias).split())
                if alias and norm(alias) not in {norm(a) for a in person["aliases"]} and norm(alias) != norm(name):
                    person["aliases"].append(alias)
            for key, value in (("relation", relation), ("whatsapp", whatsapp), ("phone", phone), ("email", email)):
                if value:
                    person[key] = " ".join(str(value).split())
            if note:
                person.setdefault("notes", []).append(note)
            # A nickname now on this person stops pointing at anyone else (newest statement wins).
            mine = {norm(a) for a in person["aliases"]}
            for other in data["people"]:
                if other is not person:
                    other["aliases"] = [a for a in other["aliases"] if norm(a) not in mine]
            return dict(person)
        return self._change(edit)

    # -- facts and lists --------------------------------------------------------------------
    def set_fact(self, key, value):
        key, value = norm(key), " ".join(str(value).split())
        if not key or not value or len(key) > 60 or len(value) > 500:
            raise ValueError("Give a short name and a value.")
        from chutku import scan
        scan.check(key, value)
        return self._change(lambda data: data["facts"].__setitem__(key, value) or {key: value})

    def add(self, list_name, text):
        list_name = LIST_WORDS.get(norm(list_name), list_name)
        text = " ".join(str(text).split())
        if list_name not in LISTS or not text or len(text) > 500:
            raise ValueError(f"Lists are: {', '.join(LISTS)}.")
        from chutku import scan
        scan.check(text, instructions=False)   # a to-do is the owner's own order

        def edit(data):
            items = data["lists"][list_name]
            if any(norm(i["text"]) == norm(text) and not i.get("done") for i in items):
                raise ValueError(f"Ye pehle se {list_name} mein hai.")
            item = {"id": max((i["id"] for i in items), default=0) + 1, "text": text, "done": False,
                    "added": date.today().isoformat()}
            items.append(item)
            return {"list": list_name, **item}
        return self._change(edit)

    def mark_done(self, list_name, item_id, done=True):
        list_name = LIST_WORDS.get(norm(list_name), list_name)

        def edit(data):
            for item in data["lists"].get(list_name, []):
                if item["id"] == item_id:
                    item["done"] = done
                    return {"list": list_name, **item}
            raise ValueError(f"No item {item_id} in {list_name}.")
        return self._change(edit)

    def forget(self, kind, key):
        """Remove a person, a fact or a list item (the caller asks the owner first: this is a deletion)."""
        def edit(data):
            if kind == "person":
                person = self.find_person(key, data)
                if person is None:
                    raise ValueError(f"I don't know anyone called {key}.")
                data["people"].remove(person)
                return {"forgot": person["name"]}
            if kind == "fact":
                if data["facts"].pop(norm(key), None) is None:
                    raise ValueError(f"No saved fact called {key}.")
                return {"forgot": norm(key)}
            list_name, _, number = str(key).partition(":")
            list_name = LIST_WORDS.get(norm(list_name), list_name)
            items = data["lists"].get(list_name, [])
            match = [i for i in items if str(i["id"]) == number.strip()]
            if not match:
                raise ValueError(f"No item {number} in {list_name}.")
            items.remove(match[0])
            return {"forgot": f"{list_name} {number}"}
        return self._change(edit)

    def summary(self):
        data = self.load()
        return {"people": data["people"], "facts": data["facts"],
                "lists": {name: items for name, items in data["lists"].items() if items}}
