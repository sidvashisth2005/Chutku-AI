"""Scheduled tasks: "30 min baad X karna", "har 15 min X karna", "raat 12 baje X karna".

The order is saved in data/scheduled.json. A background thread in the running dashboard checks it every few seconds.
When a task is due, it is started as an ordinary request (same autonomy mode as the order, same safety checks, same
approvals). Meanwhile Chutku keeps talking and working normally: a due task that finds her busy waits in the normal
queue and runs right after the current work. A repeating task is planned again for its next time; one that was due
while Chutku was off runs once when she starts (if it is less than 6 hours late) and is never run several times
to "catch up".
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import secrets

from chutku.core.jsonstore import lock_for, write_json

FILE = ("data", "scheduled.json")
MAX_JOBS = 30
MAX_GOAL = 300
LATE_LIMIT = timedelta(hours=6)
TICK_SECONDS = 5
MODES = ("review", "auto_safe", "auto_edits", "owner")


def _path(base):
    return Path(base).joinpath(*FILE)


def load(base):
    try:
        data = json.loads(_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _fmt(when):
    return when.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")


def describe(job):
    when = _parse_time(job["next_at"])
    today = datetime.now().date()
    day = "today" if when.date() == today else "tomorrow" if when.date() == today + timedelta(days=1) else \
        when.strftime("%a %d %b")
    clock = when.strftime("%I:%M %p").lstrip("0")
    repeat = f", then every {_minutes_text(job['every_minutes'])}" if job.get("every_minutes") else ""
    return f"“{job['goal']}” at {clock} {day}{repeat}"


def _minutes_text(minutes):
    if minutes % 60 == 0:
        hours = minutes // 60
        return "hour" if hours == 1 else f"{hours} hours"
    return "minute" if minutes == 1 else f"{minutes} minutes"


def add(base, goal, first_at, *, every_minutes=None, mode="owner", origin="text"):
    goal = " ".join(str(goal).split())
    if not 1 <= len(goal) <= MAX_GOAL:
        raise ValueError(f"Describe the task in 1 to {MAX_GOAL} characters.")
    if mode not in MODES or origin not in {"text", "voice"}:
        raise ValueError("Unknown mode or origin.")
    if every_minutes is not None and not (type(every_minutes) is int and 1 <= every_minutes <= 7 * 24 * 60):
        raise ValueError("Repeat every 1 minute to 7 days.")
    if not datetime.now() - timedelta(minutes=1) <= first_at <= datetime.now() + timedelta(days=366):
        raise ValueError("The time must be in the future and within a year.")
    job = {"id": secrets.token_hex(3), "goal": goal, "next_at": _fmt(first_at.replace(microsecond=0)),
           "every_minutes": every_minutes, "mode": mode, "origin": origin,
           "created": _fmt(datetime.now().replace(microsecond=0)), "runs": 0, "history": [], "active": True}
    with lock_for(_path(base)):
        jobs = load(base)
        if sum(1 for j in jobs if j.get("active")) >= MAX_JOBS:
            raise ValueError(f"{MAX_JOBS} scheduled tasks are already waiting. Cancel some first.")
        jobs = [j for j in jobs if j.get("active")] + [j for j in jobs if not j.get("active")][-20:]
        jobs.append(job)
        write_json(_path(base), jobs)
    return job


def cancel(base, job_id=None):
    """Cancel one task by id, or every active one (job_id None). Returns the cancelled tasks."""
    with lock_for(_path(base)):
        jobs = load(base)
        cancelled = [j for j in jobs if j.get("active") and (job_id is None or j["id"] == job_id)]
        for job in cancelled:
            job["active"] = False
            job["ended"] = "cancelled"
        if cancelled:
            write_json(_path(base), jobs)
    return cancelled


def active(base):
    return sorted((j for j in load(base) if j.get("active")), key=lambda j: j["next_at"])


def take_due(base, now=None):
    """The tasks due now. Each is moved on first (next time, or finished), so a crash never runs it twice."""
    now = now or datetime.now()
    due, changed = [], False
    with lock_for(_path(base)):
        jobs = load(base)
        for job in jobs:
            if not job.get("active"):
                continue
            at = _parse_time(job["next_at"])
            if at > now:
                continue
            late = now - at
            changed = True
            if job.get("every_minutes"):
                step = timedelta(minutes=job["every_minutes"])
                following = at + step
                while following <= now:      # skipped times are not caught up: the next one is in the future
                    following += step
                job["next_at"] = _fmt(following)
            else:
                job["active"] = False
                job["ended"] = "ran"
            if late > LATE_LIMIT:
                job["history"] = (job.get("history") or [])[-4:] + [{"at": _fmt(now), "status": "missed",
                                                                    "late_minutes": int(late.total_seconds() // 60)}]
                if not job.get("every_minutes"):
                    job["ended"] = "missed"
                continue
            job["runs"] = job.get("runs", 0) + 1
            due.append(dict(job))
        if changed:   # only when a task moved on this tick (not every 5 s forever after one missed task)
            write_json(_path(base), jobs)
    return due


def note_run(base, job_id, status, session_id=None):
    with lock_for(_path(base)):
        jobs = load(base)
        for job in jobs:
            if job["id"] == job_id:
                job["history"] = (job.get("history") or [])[-4:] + [{"at": _fmt(datetime.now().replace(microsecond=0)),
                                                                    "status": status, "session": session_id}]
                write_json(_path(base), jobs)
                return


def watch(server, stop, tick=TICK_SECONDS):
    """Runs inside the dashboard: starts due tasks as normal requests, without blocking anything else."""
    from chutku.core.action_control import ActionControl
    from chutku.core.log import get_logger
    log = get_logger("scheduled")
    while not stop.wait(tick):
        try:
            from chutku import pause
            if ActionControl(server.base).paused or pause.engaged(server.base):
                continue   # paused by the owner: due tasks wait (one-off tasks run when resumed, if not too late)
            for job in take_due(server.base):
                try:
                    session = server.begin_session(job["goal"], job["mode"], job["origin"], silent=True,
                                                   speaker_check=False)
                    note_run(server.base, job["id"], "started", session.id)
                    _announce(job)
                except Exception:
                    log.exception("starting scheduled task %s failed", job["id"])
                    note_run(server.base, job["id"], "failed to start")
        except Exception:
            log.exception("checking scheduled tasks failed")


def _announce(job):
    try:
        from chutku.health import notify
        notify("Chutku: scheduled task", job["goal"][:120])
    except Exception:
        pass


# -- understanding "30 min baad ...", "har 15 min ...", "raat 12 baje ..." ---------------------------------------------

_UNIT = r"(?P<unit>minutes?|mins?|min|minute|ghante|ghanta|hours?|hrs?|hr|h|m)"
_FILL = r"(?:kar\s*dena|kr\s*dena|karna(?:\s+hai)?|krna(?:\s+h(?:ai)?)?|kar\s*do|kr\s*do|please|na)"
_EVERY_HEAD = re.compile(rf"^(?:har|every|each)\s+(?:(?P<n>\d{{1,4}})\s*)?{_UNIT}\s*(?:mein|me|main|pe|par|ke baad|baad)?"
                         rf"\s*[,:]?\s+(?P<goal>.+)$", re.I)
_EVERY_TAIL = re.compile(rf"^(?P<goal>.+?)[,\s]+(?:har|every|each)\s+(?:(?P<n>\d{{1,4}})\s*)?{_UNIT}"
                         rf"(?:\s+(?:mein|me|main|pe|par|ke baad|baad))?(?:\s+{_FILL})*$", re.I)
_IN_HEAD = re.compile(rf"^(?:(?:in|after)\s+(?P<n>\d{{1,4}})\s*{_UNIT}|(?P<n2>\d{{1,4}})\s*(?P<unit2>minutes?|mins?|min|"
                      rf"minute|ghante|ghanta|hours?|hrs?|hr)\s+(?:ke\s+)?(?:baad|bad|me|mein|main))\s*[,:]?\s+(?P<goal>.+)$",
                      re.I)
_IN_TAIL = re.compile(rf"^(?P<goal>.+?)\s+(?:(?:in|after)\s+(?P<n>\d{{1,4}})\s*{_UNIT}|(?P<n2>\d{{1,4}})\s*"
                      rf"(?P<unit2>minutes?|mins?|min|minute|ghante|ghanta|hours?|hrs?|hr)\s+(?:ke\s+)?(?:baad|bad))"
                      rf"(?:\s+{_FILL})*$", re.I)
_DAY = r"(?P<day>aaj|kal|today|tomorrow)"
_DAY2 = r"(?P<day2>aaj|kal|today|tomorrow)"
_PART = r"(?P<part>subah|dopahar|dophar|shaam|sham|raat|rat|morning|afternoon|evening|night)"
_CLOCK = r"(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ampm>am|pm|a\.m\.|p\.m\.)?"
_AT_HEAD = re.compile(rf"^(?:{_DAY}\s+)?(?:{_PART}\s+)?(?:(?:at|ko)\s+)?{_CLOCK}\s*(?:baje|bje|o'?clock)?"
                      rf"(?:\s+{_DAY2})?\s*[,:]?\s+(?P<goal>.+)$", re.I)
_AT_TAIL = re.compile(rf"^(?P<goal>.+?)\s+(?:{_DAY}\s+)?(?:{_PART}\s+)?(?:at\s+)?{_CLOCK}\s*(?:baje|bje|o'?clock)?"
                      rf"(?:\s+{_DAY2})?(?:\s+{_FILL})*$", re.I)
_BIRTHDAY = re.compile(r"\b(?:b'?day|birthday|janamdin|janmdin|wish)\b", re.I)
_REMINDER_WORDS = re.compile(r"\byaad\b|\bremind|\balarm\b|\btimer\b", re.I)
# "note that the meeting is at 5", "remember the exam is at 9 am": a fact to save, not an order for later.
_NOT_AN_ORDER = re.compile(r"^(?:note|remember|save|write down|jot|likh|add (?:a )?note)\b|"
                           r"\b(?:is|are|was|were|hai|hain|tha|thi|starts?|ends?)\s+(?:at\s+)?\d{1,2}(?:[:.]\d{2})?\s*"
                           r"(?:am|pm|baje)?\s*$", re.I)


def _minutes(n, unit):
    n = int(n) if n else 1
    unit = (unit or "").casefold()
    return n * 60 if unit.startswith(("h", "g")) else n


def _clean_goal(goal):
    goal = re.sub(rf"(?:\s+{_FILL})+$", "", goal.strip(" ,.:"), flags=re.I)
    return goal.strip(" ,.:")


def _clock_time(match, goal, now):
    """The next moment that fits "12 baje", "raat 11 baje", "9:30 pm", "kal subah 8 baje"."""
    hour, minute = int(match.group("h")), int(match.group("m") or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    ampm = (match.group("ampm") or "").replace(".", "").casefold()
    part = (match.group("part") or "").casefold()
    day = (match.group("day") or match.groupdict().get("day2") or "").casefold()
    if hour > 12 or hour == 0:
        candidates = [hour]
    elif ampm:
        candidates = [(hour % 12) + (12 if ampm == "pm" else 0)]
    elif part in {"subah", "morning"}:
        candidates = [hour % 12]
    elif part in {"dopahar", "dophar", "afternoon"}:
        candidates = [hour if hour == 12 else hour + 12]
    elif part in {"shaam", "sham", "evening"}:
        candidates = [(hour % 12) + 12]
    elif part in {"raat", "rat", "night"}:
        candidates = [0 if hour == 12 else hour if hour <= 4 else hour + 12]
    elif hour == 12:
        candidates = [0] if _BIRTHDAY.search(goal) else [12, 0]   # "12 baje wish kar dena" means midnight
    elif 1 <= hour <= 6:
        candidates = [hour + 12]   # the owner's convention: "5 baje" is evening
    else:
        candidates = [hour, hour + 12]
    base_day = now.date() + timedelta(days=1 if day in {"kal", "tomorrow"} else 0)
    options = []
    for h in candidates:
        when = datetime.combine(base_day, datetime.min.time()).replace(hour=h, minute=minute)
        if when <= now and day not in {"kal", "tomorrow", "aaj", "today"}:
            when += timedelta(days=1)
        if when > now:
            options.append(when)
    return min(options) if options else None


def parse(text, now=None):
    """{"goal", "at" (datetime), "every_minutes"} for a scheduling order, else None. Reminders ("yaad dilana",
    "remind me") are left to the reminder rules."""
    now = (now or datetime.now()).replace(microsecond=0)
    text = " ".join(str(text).split()).strip(" .!?")
    if not text or _REMINDER_WORDS.search(text) or _NOT_AN_ORDER.search(text):
        return None
    for pattern in (_EVERY_HEAD, _EVERY_TAIL):
        found = pattern.match(text)
        if found:
            minutes = _minutes(found.group("n"), found.group("unit"))
            goal = _clean_goal(found.group("goal"))
            bare_letter = found.group("unit").casefold() in {"m", "h"} and not found.group("n")
            if goal and 1 <= minutes <= 7 * 24 * 60 and not bare_letter:
                return {"goal": goal, "at": now + timedelta(minutes=minutes), "every_minutes": minutes}
    for pattern in (_IN_HEAD, _IN_TAIL):
        found = pattern.match(text)
        if found:
            n = found.group("n") or found.group("n2")
            unit = found.group("unit") or found.group("unit2")
            minutes = _minutes(n, unit)
            goal = _clean_goal(found.group("goal"))
            if goal and 1 <= minutes <= 366 * 24 * 60:
                return {"goal": goal, "at": now + timedelta(minutes=minutes), "every_minutes": None}
    for pattern in (_AT_HEAD, _AT_TAIL):
        found = pattern.match(text)
        if not found:
            continue
        has_marker = re.search(r"\b(?:baje|bje|o'?clock|am|pm|a\.m\.|p\.m\.)\b|\bat\s+\d", found.group(0), re.I) \
            or found.group("m")
        if not has_marker:
            continue   # a bare number ("open tab 2") is not a time
        goal = _clean_goal(found.group("goal"))
        when = _clock_time(found, goal, now) if goal else None
        if when is not None:
            return {"goal": goal, "at": when, "every_minutes": None}
    return None
