"""Suggestions, not just orders (owner, 2026-10-04): a card on the dashboard's Today page, and at most one Windows
popup per hour, never 23:00-08:00. Everything is local rules over the owner's memory; no model calls.

Sources:
- schedule items dated today/tomorrow ("DBMS viva — Mon 05 Oct 2026") -> offer a reminder;
- open assignments -> offer to show them;
- habits (chutku/learning.py) around this hour, not yet done today -> offer to do it now;
- low free space on C: -> offer the storage report.
Each suggestion carries `command`, a phrase Chutku's instant tier runs exactly; Accept sends it like a typed request.
"Not now" hides one suggestion for 7 days; 3 dismissals of a kind stop that kind.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
import time

from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
HIDE_SECONDS = 7 * 86400
STOP_AFTER_DISMISSALS = 3
TOAST_GAP_SECONDS = 3600
QUIET_HOURS = (23, 8)       # no popups from 23:00 to 08:00
LOW_C_GB = 10
_lock = threading.Lock()
_DATED = re.compile(r"^(?P<what>.+?) — \w{3} (?P<day>\d{2} \w{3} \d{4})$")


def _state_path(base):
    return Path(base) / "data" / "suggestions.json"


def load_state(base):
    try:
        state = json.loads(_state_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state.setdefault("hidden", {})        # id -> until (epoch)
    state.setdefault("dismissals", {})    # kind -> count
    state.setdefault("accepted", {})      # kind -> count
    state.setdefault("last_toast", 0)
    state.setdefault("toasted", {})       # id -> when
    return state


def _save_state(base, state):
    path = _state_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _id(kind, key):
    return kind + ":" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def candidates(base=None, *, now=None, free_c_gb=None):
    """Every suggestion that applies right now, most useful first (before dismissal filtering)."""
    from chutku.mind import Mind
    base = Path(base or PROJECT_ROOT)
    now = now or time.time()
    moment = datetime.fromtimestamp(now)
    today = moment.date()
    data = Mind(base).load()
    out = []
    for item in data["lists"].get("schedule", []):
        match = _DATED.match(item.get("text", ""))
        if item.get("done") or not match:
            continue
        try:
            day = datetime.strptime(match.group("day"), "%d %b %Y").date()
        except ValueError:
            continue
        what = match.group("what")
        if day == today and moment.hour < 20:
            out.append({"kind": "schedule", "id": _id("schedule", item["text"] + "today"),
                        "text": f"{what} is today. Want a reminder in 1 hour?",
                        "command": f"remind me in 60 minutes to get ready for {what}"})
        elif (day - today).days == 1:
            later = "at 7 pm" if moment.hour < 19 else "in 30 minutes"
            out.append({"kind": "schedule", "id": _id("schedule", item["text"]),
                        "text": f"{what} is tomorrow. Want a reminder {later} to prepare?",
                        "command": f"remind me {later} to prepare for {what}"})
    open_work = [i for i in data["lists"].get("assignments", []) if not i.get("done")]
    if open_work:
        names = ", ".join(i["text"] for i in open_work[:2]) + (" …" if len(open_work) > 2 else "")
        out.append({"kind": "assignments", "id": _id("assignments", f"{today}:{len(open_work)}"),
                    "text": f"{len(open_work)} open assignment{'s' if len(open_work) != 1 else ''}: {names}. "
                            "See them?", "command": "show my assignments"})
    from chutku import recall
    from chutku.learning import _habit_key
    done_today = {_habit_key(t["said"]) for t in recall.turns(base, 300)
                  if datetime.fromtimestamp(t["at"]).date() == today}
    for habit in (data.get("habits") or {}).values():
        if habit.get("hour") != moment.hour or _habit_key(habit["said"]) in done_today:
            continue
        out.append({"kind": "habit", "id": _id("habit", habit["said"] + str(today)),
                    "text": f"You usually say “{habit['said'][:60]}” around now. Do it?", "command": habit["said"]})
    from chutku import scheduled   # W6 (H23): a daily habit can become an automation (only on the owner's Accept)
    planned = {_habit_key(job["goal"]) for job in scheduled.active(base)}
    for habit in (data.get("habits") or {}).values():
        hour, said = habit.get("hour"), str(habit.get("said") or "")
        if not isinstance(hour, int) or not 0 <= hour <= 23 or not said or _habit_key(said) in planned:
            continue
        out.append({"kind": "automation", "id": _id("automation", said),
                    "text": f"You say “{said[:60]}” around {hour}:00 most days. Make it automatic every day at "
                            f"{hour}:00?", "command": f"har roz {hour}:00 baje {said}"})
    if free_c_gb is None:
        try:
            free_c_gb = shutil.disk_usage("C:\\").free / 1e9
        except OSError:
            free_c_gb = None
    if free_c_gb is not None and free_c_gb < LOW_C_GB:
        out.append({"kind": "storage", "id": _id("storage", str(today)),
                    "text": f"C: has only {free_c_gb:.1f} GB free. See what is taking space?",
                    "command": "what is taking space on my pc"})
    return out


def current(base=None, *, now=None, free_c_gb=None):
    """What to show: candidates minus hidden ones and stopped kinds."""
    base = Path(base or PROJECT_ROOT)
    now = now or time.time()
    state = load_state(base)
    return [s for s in candidates(base, now=now, free_c_gb=free_c_gb)
            if state["hidden"].get(s["id"], 0) < now
            and state["dismissals"].get(s["kind"], 0) < STOP_AFTER_DISMISSALS]


def respond(base, suggestion_id, action, *, now=None):
    """Owner pressed Accept or Not now. Returns the updated state's view of that suggestion."""
    if action not in ("accept", "dismiss") or not re.fullmatch(r"[a-z]+:[0-9a-f]{10}", str(suggestion_id)):
        raise ValueError("Give a suggestion id and action accept or dismiss.")
    now = now or time.time()
    kind = suggestion_id.split(":")[0]
    with _lock:
        state = load_state(base)
        state["hidden"][suggestion_id] = now + HIDE_SECONDS
        if action == "dismiss":
            state["dismissals"][kind] = state["dismissals"].get(kind, 0) + 1
        else:
            state["accepted"][kind] = state["accepted"].get(kind, 0) + 1
            state["dismissals"][kind] = 0        # an accepted kind is wanted: forget older "not now"s
        state["hidden"] = {k: v for k, v in state["hidden"].items() if v > now}
        _save_state(base, state)
    return {"id": suggestion_id, "action": action}


def quiet(hour):
    start, end = QUIET_HOURS
    return hour >= start or hour < end


def maybe_toast(base=None, *, now=None, send=None, free_c_gb=None):
    """At most one popup per hour, never in quiet hours, never the same suggestion twice. Returns what was shown."""
    base = Path(base or PROJECT_ROOT)
    now = now or time.time()
    if quiet(datetime.fromtimestamp(now).hour):
        return None
    with _lock:
        state = load_state(base)
        if now - state["last_toast"] < TOAST_GAP_SECONDS:
            return None
        fresh = [s for s in current(base, now=now, free_c_gb=free_c_gb) if s["id"] not in state["toasted"]]
        if not fresh:
            return None
        chosen = fresh[0]
        if send is None:
            from chutku.health import notify as send
        try:
            send("Suggestion", chosen["text"] + " (open the dashboard to accept)")
        except OSError:
            return None
        state["last_toast"] = now
        state["toasted"][chosen["id"]] = now
        state["toasted"] = {k: v for k, v in state["toasted"].items() if now - v < HIDE_SECONDS}
        _save_state(base, state)
    return chosen


def watch(base, stop_event, interval=600):
    """Background loop: refresh habits daily, offer at most one popup an hour. Never raises."""
    last_habits = 0.0
    while not stop_event.wait(min(60, interval) if last_habits == 0 else interval):
        try:
            if time.time() - last_habits > 86400:
                from chutku.learning import refresh_habits
                refresh_habits(base)
                last_habits = time.time()
            maybe_toast(base)
        except Exception:
            from chutku.core.log import get_logger
            get_logger("suggest").exception("suggestion check failed")
