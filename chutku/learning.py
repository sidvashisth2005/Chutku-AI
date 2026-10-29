"""Chutku learns from the owner over time, locally and without any model calls (owner, 2026-10-04: "learn with time,
find new ways, remember my details").

- parse_event(text): "my exam is on 12 Oct" / "mera DBMS viva kal hai" / "meeting friday ko hai" -> a dated
  schedule item (relative days are turned into real dates, so "kal" stays correct tomorrow).
- parse_feedback(text): "good job" / "shabash" -> good, "galat kiya" / "wrong" -> bad, about Chutku's latest task.
  rate_latest(): stores the rating on that task's worked example; bad examples are never reused.
- after_session(): when a request failed and the owner's next request (within 10 min) succeeded, the failed
  wording is remembered with the plan that worked (a "new way" for next time).
- refresh_habits(): repeated requests at a similar time of day on 3+ different days become habits in mind.json,
  which feed suggestions (chutku/suggest.py) and the memory slice.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# -- dated events -------------------------------------------------------------------------------------------

_EVENT = (r"(?P<what>(?:[\w+&.-]+ ){0,3}?(?:exam|test|quiz|viva|interview|meeting|presentation|submission|deadline"
          r"|appointment|birthday|anniversary|class|lecture|practical|paper|flight|train|party|match))")
_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for m in names}
_DAYS = {d: i for i, names in enumerate([("monday", "somvar"), ("tuesday", "mangalvar"), ("wednesday", "budhvar"),
                                          ("thursday", "guruvar"), ("friday", "shukravar"), ("saturday", "shanivar"),
                                          ("sunday", "ravivar", "itvaar")]) for d in names}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY = "|".join(sorted(_DAYS, key=len, reverse=True))
_WHEN = (rf"(?P<when>(?:on |ko )?(?:\d{{1,2}}(?:st|nd|rd|th)? (?:{_MONTH})|(?:{_MONTH}) \d{{1,2}}(?:st|nd|rd|th)?"
         rf"|tomorrow|kal|parso|day after tomorrow|today|aaj|(?:next |is |agle |this )?(?:{_WEEKDAY})))")
_EVENT_PATTERNS = [
    re.compile(rf"^(?:my|mera|meri|mere|hamara|hamari)\s+{_EVENT}\s+(?:is |hai )?{_WHEN}(?:\s+(?:ko|hai|h|at .*|"
               rf"\d.*))*[\s.!]*$", re.I),
    re.compile(rf"^(?:my|mera|meri|mere)?\s*{_EVENT}\s+{_WHEN}\s+(?:ko\s+)?(?:hai|h|he)[\s.!]*$", re.I),
    re.compile(rf"^(?:i have|i've got|mujhe|mera|meri)?\s*(?:an? |ek )?{_EVENT}\s+{_WHEN}[\s.!]*$", re.I),
]


def resolve_day(when, today=None):
    today = today or date.today()
    w = when.casefold().replace("on ", "").replace("ko ", "").strip()
    w = re.sub(r"(\d)(?:st|nd|rd|th)", r"\1", w)
    if w in ("today", "aaj"):
        return today
    if w in ("tomorrow", "kal"):
        return today + timedelta(days=1)
    if w in ("parso", "day after tomorrow"):
        return today + timedelta(days=2)
    match = re.fullmatch(rf"(\d{{1,2}}) ({_MONTH})|({_MONTH}) (\d{{1,2}})", w)
    if match:
        day = int(match.group(1) or match.group(4))
        month = _MONTHS[match.group(2) or match.group(3)]
        try:
            target = date(today.year, month, day)
        except ValueError:
            return None
        return target if target >= today else date(today.year + 1, month, day)
    weekday = re.sub(r"^(?:next|is|agle|this) ", "", w)
    if weekday in _DAYS:
        ahead = (_DAYS[weekday] - today.weekday()) % 7 or 7
        if w.startswith(("next", "agle")) and ahead < 7:
            ahead += 7 if ahead <= 0 else 0
        return today + timedelta(days=ahead)
    return None


def parse_event(text, today=None):
    """("schedule", "DBMS viva — Mon 05 Oct 2026") for a stated dated event, else None."""
    clean = " ".join(str(text).split())
    if "?" in clean:
        return None    # "is my exam on monday?" is a question
    for pattern in _EVENT_PATTERNS:
        match = pattern.match(clean)
        if match:
            day = resolve_day(match.group("when"), today)
            if day is None:
                return None
            what = match.group("what").strip()
            what = re.sub(r"^(?:the|my|ki|ka)\s+", "", what, flags=re.I)
            return "schedule", f"{what} — {day.strftime('%a %d %b %Y')}"
    return None


# -- feedback -----------------------------------------------------------------------------------------------

_GOOD = re.compile(r"^(?:good job|great job|nice job|well done|good work|great work|shabash|shaabash|badhiya|"
                   r"bahut badhiya|mast|sahi kiya|sahi hai|perfect|ekdum sahi|thanks chutku|good boy)"
                   r"(?:\s+(?:chutku|yaar|bhai|re))?[\s.!]*$", re.I)
_BAD = re.compile(r"^(?:galat kiya|galat hai|ye galat hai|yeh galat hai|wrong|that'?s wrong|that was wrong|bad job|"
                  r"tune galat kiya|tumne galat kiya|not what i (?:asked|wanted)|maine ye nahi kaha tha|"
                  r"galat ho gaya|ulta kar diya)(?:\s+(?:chutku|yaar|bhai|re))?[\s.!]*$", re.I)


def parse_feedback(text):
    clean = " ".join(str(text).split())
    if _GOOD.match(clean):
        return "good"
    if _BAD.match(clean):
        return "bad"
    return None


def rate_latest(rating, base=None):
    """Rate Chutku's latest real task; returns the goal that was rated, or None."""
    from chutku import experience, recall
    base = Path(base or PROJECT_ROOT)
    latest = next((t for t in reversed(recall.turns(base, 200))
                   if t.get("tools") and parse_feedback(t["said"]) is None), None)
    if latest is None:
        return None
    def rate(rows):
        changed = False
        for row in rows:
            if row["goal"].casefold() == latest["said"].casefold():
                row["rating"] = rating
                changed = True
        return changed
    experience.update_rows(base, rate)
    if rating == "bad":
        from chutku import reflex
        reflex.on_bad_rating(base, latest["said"])   # a learned skill that planned it is switched off
    _feedback_log(base, latest["said"], rating)
    return latest["said"]


def _feedback_log(base, goal, rating):
    path = Path(base) / "data" / "feedback.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "goal": goal[:300], "rating": rating}, ensure_ascii=False)
                         + "\n")
    except OSError:
        pass


# -- learning from a rephrased retry ---------------------------------------------------------------------------

# Apps, sites and places a request can name. "open spotify" failing and then "play lofi on youtube" working are two
# different requests; "woh gaana lagao jo kal suna tha" failing and "play lofi on youtube" right after is a rephrase.
_NAMED_TARGETS = {"spotify", "youtube", "whatsapp", "telegram", "instagram", "discord", "chrome", "brave", "edge",
                  "firefox", "notepad", "calculator", "vlc", "steam", "epic", "code", "vscode", "word", "excel",
                  "powerpoint", "explorer", "settings", "gmail", "google", "maps", "amazon", "flipkart", "github",
                  "downloads", "desktop", "documents", "pictures", "music", "videos", "netflix", "hotstar", "prime"}
REPHRASE_SECONDS = 120


def _same_request(first, second, gap=None):
    """Two wordings of one request: most meaningful words shared (Jaccard >= 0.5), a shared distinctive name, or a
    quick rephrase (within 2 minutes) whose first wording named no app or site that the second one lacks."""
    from chutku import experience
    a, b = experience._words(first), experience._words(second)
    if not a or not b:
        return False
    if len(a & b) / len(a | b) >= 0.5:
        return True
    if (a & b) & _NAMED_TARGETS:
        return True
    named_first = a & _NAMED_TARGETS
    return gap is not None and gap <= REPHRASE_SECONDS and not (named_first - b)


class _Renamed:
    def __init__(self, session, goal):
        self.session, self.goal = session, goal

    def snapshot(self):
        return {**self.session.snapshot(), "goal": self.goal}


def after_session(base, session, runtime=None, *, window=600):
    """A failed request followed by a successful one: remember the failed wording with the plan that worked."""
    from chutku import experience, recall
    snap = session.snapshot()
    if snap["status"] != "done":
        return None
    rows = recall.turns(base, 50)
    previous = [t for t in rows if t["said"] != snap["goal"]]
    if not previous:
        return None
    last = previous[-1]
    if last.get("status") not in ("failed", "stopped", "clarify") or time.time() - last["at"] > window:
        return None
    if not _same_request(last["said"], snap["goal"], gap=time.time() - last["at"]):
        return None   # "open spotify" failed, then "play lofi on youtube" worked: two different requests
    if experience.record(base, _Renamed(session, last["said"]), runtime, replayable=False):
        return last["said"]
    return None


# -- habits -----------------------------------------------------------------------------------------------

def _habit_key(said):
    from chutku.recall import words
    return " ".join(sorted(words(said)))[:120]


def refresh_habits(base=None, *, now=None, min_days=3):
    """Find requests repeated on 3+ different days at a similar hour; store them in mind.json["habits"]."""
    from chutku.mind import Mind
    from chutku import recall
    base = Path(base or PROJECT_ROOT)
    now = now or time.time()
    since = now - 30 * 86400
    groups = defaultdict(list)
    for turn in recall.turns(base):
        if turn["at"] < since or turn.get("status") not in ("done", "said") or parse_feedback(turn["said"]):
            continue
        if not recall.owner_turn(turn):
            continue   # test and timing scripts are not the owner's habits (F7)
        key = _habit_key(turn["said"])
        if key:
            groups[key].append(turn)
    habits = {}
    for key, turns in groups.items():
        days = {datetime.fromtimestamp(t["at"]).date() for t in turns}
        if len(days) < min_days:
            continue
        hours = [datetime.fromtimestamp(t["at"]).hour for t in turns]
        hour = max(set(hours), key=hours.count)
        if sum(1 for h in hours if abs(h - hour) <= 1) < min_days:
            continue    # repeated, but at random times: not a time habit
        latest = max(turns, key=lambda t: t["at"])
        habits[key] = {"text": f"{latest['said'][:80]} (usually around {hour:02d}:00)", "said": latest["said"],
                       "hour": hour, "count": len(turns), "days": len(days), "last": latest["at"]}
    mind = Mind(base)
    mind._change(lambda data: data.__setitem__("habits", habits))
    return habits
