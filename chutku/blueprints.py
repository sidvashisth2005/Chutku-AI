"""H23 blueprints (Hermes /blueprint): ready-made automations with a few slots.

A blueprint creates nothing of its own. It expands into ordinary `task.schedule` steps, so the agent session shows
exactly what will be created, every step passes the policy kernel, and each one can be undone with task.cancel. At
run time each scheduled goal is a normal request with the normal asks (e.g. tidying Downloads still asks).

    "automations dikhao" / "kaun si automations hain"         -> blueprint.list
    "subah ka briefing set karo 8 baje" / "morning briefing at 7:30"
    "har hafte backup set karo" / "weekly backup"
    "weekly insights set karo" / "downloads har hafte saaf karna"
    "har roz cricket ki news batana" / "news digest: cricket"
    "research watch: free pdf editors"                        -> needs H15 (board), one result a day
    "automation <name> time=07:30 day=sun topic=..."           -> any blueprint by name with explicit slots

shortcut: suggestions from habits (suggest.py) and a dashboard "Automations" tab are not built; the catalog is spoken.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import re

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

DAY = 24 * 60
WEEK = 7 * DAY
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
        "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "shukravar": 4, "shanivar": 5, "ravivar": 6}

CATALOG = {
    "morning-briefing": {"about": "Every morning: weather, headlines and today's reminders", "every": DAY,
                         "slots": {"time": "08:00"}, "goal": "aaj ka weather, news aur meri reminders batao"},
    "news-digest": {"about": "Every day: headlines about a topic", "every": DAY,
                    "slots": {"time": "09:00", "topic": None}, "goal": "{topic} ki latest news batao"},
    "weekly-backup": {"about": "Every week: a backup of Chutku's memory (H25)", "every": WEEK,
                      "slots": {"day": "sun", "time": "21:00"}, "goal": "backup bana lo"},
    "weekly-insights": {"about": "Every week: what Chutku did for you (H7)", "every": WEEK,
                        "slots": {"day": "sun", "time": "20:00"}, "goal": "is hafte kya kiya"},
    "downloads-tidy": {"about": "Every week: tidy the Downloads folder (it still asks before moving files)",
                       "every": WEEK, "slots": {"day": "sun", "time": "11:00"}, "goal": "organize my downloads"},
    "research-watch": {"about": "Every day: research a topic on the web and report (H15)", "every": DAY,
                       "slots": {"time": "10:00", "topic": None}, "goal": "research karke batao {topic}"},
}
_TIME = re.compile(r"^(?P<h>[01]?\d|2[0-3])(?::(?P<m>[0-5]\d))?$")


def _next(slots, every, now):
    match = _TIME.match(str(slots.get("time", "")))
    if match is None:
        raise ValueError("time must look like 08:00 or 7:30.")
    when = now.replace(hour=int(match["h"]), minute=int(match["m"] or 0), second=0, microsecond=0)
    if every == WEEK:
        text = str(slots.get("day", "")).casefold()
        day = DAYS.get(text, DAYS.get(text[:3]))
        if day is None:
            raise ValueError("day must be a weekday such as sun or mon.")
        when += timedelta(days=(day - when.weekday()) % 7)
    while when <= now:
        when += timedelta(days=7 if every == WEEK else 1)
    return when


def build(name, given=None, now=None):
    """The exact task.schedule steps a blueprint creates. Raises ValueError on an unknown name or a bad slot."""
    blueprint = CATALOG.get(str(name).casefold())
    if blueprint is None:
        raise ValueError(f"There is no automation called {name}. Say 'automations dikhao' for the list.")
    given = {k.casefold(): str(v).strip() for k, v in (given or {}).items() if str(v).strip()}
    unknown = set(given) - set(blueprint["slots"])
    if unknown:
        raise ValueError(f"{name} has no slot {', '.join(sorted(unknown))}.")
    slots = {**blueprint["slots"], **given}
    missing = [slot for slot, value in slots.items() if value is None]
    if missing:
        raise ValueError(f"{name} needs: {', '.join(missing)}.")
    topic = slots.get("topic")
    if topic is not None and not re.fullmatch(r"[\w .,&+'-]{2,60}", topic):
        raise ValueError("The topic must be 2 to 60 plain characters.")
    when = _next(slots, blueprint["every"], now or datetime.now())
    goal = blueprint["goal"].format(**slots)
    return [{"tool": "task.schedule", "arguments": {"goal": goal, "at": when.strftime("%Y-%m-%dT%H:%M"),
                                                    "every_minutes": blueprint["every"]},
             "purpose": f"Automation {name}: {goal} ({'daily' if blueprint['every'] == DAY else 'weekly'})"}]


# Natural phrases -> (blueprint, slot names in the match)
_CLOCK = r"(?P<time>(?:[01]?\d|2[0-3])(?::[0-5]\d)?)\s*(?:baje|bje|am|pm|o'?clock)?"
PHRASES = [
    ("morning-briefing", re.compile(rf"^(?:subah\s+ka\s+briefing|morning\s+briefing)(?:\s+set\s+karo|\s+lagao)?"
                                    rf"(?:\s+(?:at\s+)?{_CLOCK})?(?:\s+set\s+karo|\s+lagao|\s+pe|\s+par)?\s*[.!]?$", re.I)),
    ("weekly-backup", re.compile(r"^(?:har\s+hafte\s+backup(?:\s+(?:set\s+karo|lena|lo|banana))?|weekly\s+backup"
                                 r"(?:\s+set\s+karo|\s+on)?)\s*[.!]?$", re.I)),
    ("weekly-insights", re.compile(r"^(?:weekly\s+insights?|har\s+hafte\s+(?:ki\s+)?report)(?:\s+set\s+karo|\s+on|"
                                   r"\s+dena)?\s*[.!]?$", re.I)),
    ("downloads-tidy", re.compile(r"^(?:downloads?\s+har\s+hafte\s+(?:saaf|tidy)\s+(?:karna|karo)|weekly\s+downloads?\s+"
                                  r"(?:tidy|cleanup))\s*[.!]?$", re.I)),
    ("news-digest", re.compile(r"^(?:har\s+(?:roz|din)\s+(?P<topic>[\w .&+'-]{2,40}?)\s+ki\s+news\s+(?:batana|bata\s+dena|"
                               r"dena)|news\s+digest\s*[:\-]\s*(?P<topic2>[\w .&+'-]{2,40}))\s*[.!]?$", re.I)),
    ("research-watch", re.compile(r"^research\s+watch\s*[:\-]\s*(?P<topic>[\w .&+'-]{2,60})\s*[.!]?$", re.I)),
]
EXPLICIT = re.compile(r"^(?:automation|blueprint)\s+(?P<name>[a-z-]{3,30})(?P<slots>(?:\s+[a-z]+=[^\s=]+)*)\s*$", re.I)
LIST = re.compile(r"^(?:(?:kaun\s*si|kya\s+kya)\s+automations?\s+(?:hain|hai|hai\s+tumhare\s+paas)|automations?\s+"
                  r"(?:dikhao|batao|list)|(?:show|list)\s+(?:the\s+)?(?:automations|blueprints))\s*[?.!]?$", re.I)


def parse(text, now=None):
    """A quick-tier proposal for an automation phrase, or None. A bad slot gives an honest clarify."""
    text = " ".join(str(text).split())
    if LIST.match(text):
        return {"status": "continue", "reply": "", "declared_plan": ["List the automations"],
                "next_steps": [{"tool": "blueprint.list", "arguments": {}, "purpose": "List the automations"}],
                "finish": False}
    name, slots = None, {}
    match = EXPLICIT.match(text)
    if match:
        name = match["name"].casefold()
        slots = dict(part.split("=", 1) for part in match["slots"].split())
    else:
        for candidate, pattern in PHRASES:
            found = pattern.match(text)
            if found:
                name = candidate
                slots = {("topic" if k == "topic2" else k): v for k, v in found.groupdict().items() if v}
                break
    if name is None:
        return None
    try:
        steps = build(name, slots, now)
    except ValueError as error:
        return {"status": "clarify", "reply": str(error), "declared_plan": [], "next_steps": [], "finish": False}
    return {"status": "continue", "reply": f"Automation {name} set: {steps[0]['purpose'].split(': ', 1)[1]}, "
                                           f"pehli baar {steps[0]['arguments']['at'].replace('T', ' ')}.",
            "declared_plan": [s["purpose"] for s in steps], "next_steps": steps, "finish": True}


def _list(_arguments, _context):
    rows = [{"name": name, "about": item["about"],
             "slots": {slot: value if value is not None else "(required)" for slot, value in item["slots"].items()}}
            for name, item in CATALOG.items()]
    summary = "Automations: " + "; ".join(f"{r['name']} ({r['about'].lower()})" for r in rows) + \
              ". Bolo jaise 'subah ka briefing set karo 8 baje' ya 'automation news-digest topic=cricket'."
    return ToolResult({"automations": rows, "summary": summary}, Verification.PASS)


def register_blueprint_tools(registry):
    registry.register(Tool("blueprint.list", "List the ready-made automations (blueprints) and their slots. Creating "
                           "one is task.schedule steps.", Risk.OBSERVATION, _list,
                           argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable"))
