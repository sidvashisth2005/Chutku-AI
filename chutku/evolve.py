"""Evolve (master plan Y2, and the owner-profile part of Y4): Chutku studies her own week and proposes improvements.

Owner (2026-11-06): "Chutku must improve herself every day on her own ... plan everything first, propose it to me as
advice; if I approve, she adds it and tests it; if it works keep it, else revert."

1. Review (Night Shift job ``evolve_review``, or "khud ko improve karo"): reads the last 7 days of the local logs
   (conversations, actions, heard, experience; the ledger and voice timings when present) and counts evidence: failed
   or unverified steps, slow requests, model-planned requests that could be instant, misheard or ignored speech, asks
   the owner always approved or always refused, and habits. It refreshes the owner profile (habits in mind.json,
   learned instant skills, know_me on the real install). Nothing in the code changes.
2. Proposals: at most 3 new ones a day, each a full plan in data/evolve/proposals/<id>.json: title, evidence (counts,
   redacted examples), what would change, steps, tests, risk and undo. Offline they come from fixed templates; online
   Gemini may refine a code plan's steps from a short redacted summary (never raw logs).
3. Only advice: ``evolve.list`` shows them; ``evolve.approve <id>`` is user_only (typed, then a click; never the agent,
   never by voice); ``evolve.reject <id>``.
4. Applying (only after approval): kinds phrase / routine / preference write through the existing data paths at once;
   skill and code run in a separate process (``python -m chutku.evolve_apply``). Code changes are written and tested
   in a git worktree and merged only when the full suite passes and the boundary in evolve_apply allows the diff.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import bisect
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

PROJECT_ROOT = Path(__file__).resolve().parents[1]   # the code repository Evolve works on (git)
DAYS = 7
SLOW_SECONDS = 15
MAX_PER_DAY = 3
MIN_REPEATS = 3        # the model planned the very same request this often: worth an instant phrase
MIN_FAILS = 3          # a tool failed (or could not be checked) this often in a week: worth a fix
ID = re.compile(r"^[0-9a-f]{6}$")
DATA_LANE = ("phrase", "routine", "preference")   # applied at once through existing data paths, no code
BACKGROUND = ("skill", "code")                     # applied by chutku/evolve_apply.py in its own process
PREFERENCE_KEYS = frozenset({"stt_language", "browser", "voice_engine", "follow_up_seconds"})   # never a safety switch
PLAN_KEYS = ("id", "kind", "key", "title", "evidence", "change", "steps", "tests", "risk", "undo", "payload")
APPROVABLE = ("proposed", "approved", "failed")
_INSTANT = {"quick", "reflex", "replay"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def root(base):
    return Path(base) / "data" / "evolve"


def proposals_dir(base):
    return root(base) / "proposals"


# -- reading the week -------------------------------------------------------------------------------------------

_QUOTED = re.compile(r"[\"“”][^\"“”]{0,300}[\"“”]|(?<!\w)['‘][^'‘’]{1,100}['’](?!\w)")   # not "don't"


def redact(text, limit=80):
    """Short and without quoted text, addresses, paths, e-mails or long numbers."""
    text = " ".join(str(text or "").split())
    text = _QUOTED.sub('"…"', text)
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text)
    text = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)\S*", "<path>", text)
    text = re.sub(r"\d{3,}", "<n>", text)
    return text[:limit]


def _cloud_safe(text):
    """For anything a cloud model may see: redacted, and capitalised words inside a sentence (names) masked."""
    return re.sub(r"(?<=[a-z,] )[A-Z][\w-]+", "<Name>", redact(text, 100))


def _jsonl(path):
    from chutku.insights import _jsonl as read
    return read(path)


def _action_at(row):
    from chutku.insights import _action_time
    return _action_time(row)


def _week(base, now):
    """The owner's last 7 days: conversation turns, action rows, heard rows, voice timings."""
    from chutku import recall
    data, since = Path(base) / "data", now - DAYS * 86400
    every = [t for t in recall.turns(base, 100000) if since <= float(t.get("at") or 0) <= now]
    turns = [t for t in every if recall.owner_turn(t)]
    # An action belongs to the next logged turn (turns are logged when the request ends); actions that end in a
    # script's turn (live_check, trust tests) are not the owner's week.
    ends = sorted((float(t["at"]), recall.owner_turn(t)) for t in every)
    times = [at for at, _owner in ends]
    actions = []
    for row in _jsonl(data / "actions.log.jsonl"):
        at = _action_at(row)
        if at is None or not since <= at <= now:
            continue
        index = bisect.bisect_left(times, at)
        if index < len(ends) and ends[index][0] - at <= 600 and not ends[index][1]:
            continue
        actions.append(row | {"_at": at})
    heard = [h for h in _jsonl(data / "heard.jsonl") if since <= float(h.get("at") or 0) <= now]
    timings = [v for v in _jsonl(data / "voice-timings.jsonl") if since <= float(v.get("at") or 0) <= now]
    return turns, actions, heard, timings


def _ledger(base, since):
    """(tool, verdict) counts of FAIL and UNKNOWN outcomes since ``since``; empty when there is no ledger."""
    path = Path(base) / "data" / "ledger.db"
    if not path.is_file():
        return Counter()
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            rows = connection.execute("SELECT tool, verdict, COUNT(*) FROM outcomes WHERE at >= ? AND verdict != "
                                      "'PASS' GROUP BY tool, verdict", (since,)).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return Counter()
    return Counter({(tool, verdict): n for tool, verdict, n in rows})


def evidence(base, now=None):
    """Plain counts and redacted examples from the last 7 days. Reads only."""
    from chutku.experience import normal_goal
    now = now or time.time()
    turns, actions, heard, timings = _week(base, now)
    failed, messages = Counter(), defaultdict(list)
    for row in actions:
        if row.get("state") == "FAILED":
            failed[row["tool"]] += 1
            if row.get("message") and len(messages[row["tool"]]) < 3:
                messages[row["tool"]].append(row["message"])
    ledger = _ledger(base, now - DAYS * 86400)
    unverified = Counter({tool: n for (tool, verdict), n in ledger.items() if verdict == "UNKNOWN"})
    steps = {tool: {"failed": failed[tool], "unverified": unverified[tool],
                    "examples": [redact(m, 120) for m in messages[tool]]}
             for tool in sorted(set(failed) | set(unverified), key=lambda t: -(failed[t] + unverified[t]))}

    sessions = defaultdict(list)
    for row in actions:
        if row.get("session"):
            sessions[row["session"]].append(row)
    slow = []
    for rows in sessions.values():
        if any(r.get("state") == "WAITING_CONFIRMATION" for r in rows):
            continue   # waiting for the owner's click is not slowness
        span = max(r["_at"] for r in rows) - min(r["_at"] for r in rows)
        if span > SLOW_SECONDS:
            slow.append({"seconds": round(span, 1), "tools": sorted({r["tool"] for r in rows})[:4]})
    slow_voice = [{"seconds": v["seconds_to_first_audio"], "said": redact(v.get("goal"), 60)} for v in timings
                  if isinstance(v.get("seconds_to_first_audio"), (int, float))
                  and v["seconds_to_first_audio"] > SLOW_SECONDS]

    model = defaultdict(list)
    for turn in turns:
        planners = set(turn.get("planners") or [])
        if turn.get("status") == "done" and turn.get("tools") and planners and not planners <= _INSTANT:
            model[normal_goal(turn["said"])].append(turn)
    could_be_instant = []
    for key, group in model.items():
        tools = {tuple(t["tools"]) for t in group}
        if key and len(group) >= MIN_REPEATS and len(tools) == 1:
            could_be_instant.append({"key": key, "times": len(group), "tools": list(tools.pop()),
                                     "said": group[-1]["said"]})
    could_be_instant.sort(key=lambda c: -c["times"])

    decisions = Counter()
    for row in heard:
        decision = str(row.get("decision") or "")
        decisions["task" if decision.startswith("task:") else decision.split(":")[0].strip() or "unknown"] += 1
    spoken = [h for h in heard if str(h.get("decision") or "").startswith(("task", "command", "ignored", "approval"))]
    devanagari = sum(1 for h in spoken if re.search(r"[ऀ-ॿ]", str(h.get("text") or "")))
    unclear = Counter(normal_goal(t["said"]) for t in turns if t.get("origin") == "voice"
                      and t.get("status") in ("clarify", "failed") and not t.get("tools"))

    asks = defaultdict(lambda: {"asked": 0, "approved": 0, "refused": 0})
    for row in actions:
        if row.get("state") == "WAITING_CONFIRMATION":
            asks[row["tool"]]["asked"] += 1
        elif row.get("state") == "COMPLETED" and row.get("approved_on_screen"):
            asks[row["tool"]]["approved"] += 1
        elif row.get("state") == "DENIED" and str(row.get("message") or "").startswith("Cancelled"):
            asks[row["tool"]]["refused"] += 1
    always = {tool: dict(c) | {"always": "approved" if not c["refused"] else "refused"} for tool, c in asks.items()
              if c["approved"] + c["refused"] >= 3 and not (c["approved"] and c["refused"])}

    hours = Counter(datetime.fromtimestamp(float(t["at"])).hour for t in turns)
    apps = Counter(" ".join(str((r.get("arguments") or {}).get("name") or "").casefold().split())
                   for r in actions if r.get("tool") == "apps.launch" and r.get("state") == "COMPLETED")
    apps.pop("", None)
    phrases = Counter(normal_goal(t["said"]) for t in turns if t.get("status") != "said")
    phrases.pop("", None)
    stuck = defaultdict(list)
    for turn in turns:
        if turn.get("status") in ("failed", "clarify") and not turn.get("tools") and turn.get("origin") != "voice":
            stuck[normal_goal(turn["said"])].append(turn["said"])
    return {
        "days": DAYS, "requests": sum(1 for t in turns if t.get("status") != "said"), "actions": len(actions),
        "failed_or_unverified_steps": steps,
        "slow": {"sessions_over_15s": len(slow), "slowest": sorted(slow, key=lambda s: -s["seconds"])[:5],
                 "voice_first_audio_over_15s": len(slow_voice), "voice_examples": slow_voice[:3]},
        "could_be_instant": could_be_instant[:10],
        "speech": {"heard": len(heard), "decisions": dict(decisions.most_common(8)), "spoken_lines": len(spoken),
                   "devanagari_lines": devanagari,
                   "unclear_voice_requests": [{"said": redact(k, 60), "times": n} for k, n in unclear.most_common(5)]},
        "always_same_answer_to_asks": always,
        "habits": {"busiest_hours": [h for h, _ in hours.most_common(3)], "apps": apps.most_common(5),
                   "phrases": [[redact(p, 60), n] for p, n in phrases.most_common(5)]},
        "repeatedly_stuck": [{"said": group[-1], "times": len(group)} for key, group in stuck.items()
                             if key and len(group) >= 2][:5],
    }


def refresh_profile(base, registry=None):
    """Y4: refresh what Chutku knows about the owner, locally: habits (mind.json), learned instant skills, know_me."""
    from chutku import learning
    out = {"habits": len(learning.refresh_habits(base))}
    if registry is not None:
        from chutku import reflex
        out["new_instant_skills"] = len(reflex.compile_all(base, registry)["added"])
    from chutku.core.paths import home
    if Path(base).resolve() != home().resolve():
        out["know_me"] = "skipped (not the real Chutku folder)"   # it scans the owner's PC, not the base folder
        return out
    from chutku import know_me
    age = time.time() - float(know_me.load(base).get("refreshed") or 0)
    if age > 20 * 3600:
        know_me.refresh(base)
        out["know_me"] = "refreshed"
    else:
        out["know_me"] = f"fresh ({age / 3600:.0f} h old)"
    return out


# -- proposals ----------------------------------------------------------------------------------------------------

def _id(kind, key):
    return hashlib.sha256(f"{kind}\0{key}".encode("utf-8")).hexdigest()[:6]


def plan_hash(proposal):
    """What the owner approves: every plan field. A proposal edited after approval is not applied."""
    plan = {key: proposal.get(key) for key in PLAN_KEYS}
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_all(base):
    out = []
    for path in sorted(proposals_dir(base).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and ID.fullmatch(str(data.get("id"))) and path.stem == data["id"]:
            out.append(data)
    return sorted(out, key=lambda p: p.get("created", ""), reverse=True)


def load_proposal(base, pid):
    if not ID.fullmatch(str(pid)):
        return None
    try:
        data = json.loads((proposals_dir(base) / f"{pid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") == pid else None


def save_proposal(base, proposal):
    from chutku.core.jsonstore import write_json
    proposals_dir(base).mkdir(parents=True, exist_ok=True)
    write_json(proposals_dir(base) / f"{proposal['id']}.json", proposal)


def record(base, proposal, result, **extra):
    """One line per finished apply in data/evolve/history.jsonl."""
    row = {"at": datetime.now().isoformat(timespec="seconds"), "id": proposal["id"], "kind": proposal["kind"],
           "title": proposal["title"], "result": result, **extra}
    root(base).mkdir(parents=True, exist_ok=True)
    with (root(base) / "history.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _proposal(kind, key, title, evidence, change, steps, tests, risk, undo, payload):
    return {"id": _id(kind, key), "kind": kind, "key": key, "title": title[:120], "evidence": evidence,
            "change": change, "steps": steps, "tests": tests, "risk": risk, "undo": undo, "payload": payload,
            "status": "proposed", "created": datetime.now().isoformat(timespec="seconds"), "drafted_by": "template"}


def _phrase_candidates(base, found, registry):
    from chutku import experience, reflex
    from chutku.quick_intents import quick_proposal
    rows = experience.load(base)
    enabled = [s for s in reflex.load(base) if s.get("enabled")]
    out = []
    for item in found["could_be_instant"]:
        example = next((r for r in reversed(rows) if r.get("rating") != "bad"
                        and experience.normal_goal(r.get("goal", "")) == item["key"]
                        and [s["tool"] for s in r.get("steps") or []] == item["tools"]), None)
        if example is None:
            continue   # no stored plan with its arguments: nothing to make instant
        phrase = reflex.normalize(item["said"])
        if quick_proposal(phrase) is not None or any(re.match(s["regex"], phrase, re.I) for s in enabled):
            continue   # already instant
        if registry is not None:
            try:
                if not all(reflex._eligible_tool(registry.get(s["tool"])) for s in example["steps"]):
                    continue   # messages, deletes, code, file changes: never an instant phrase
            except KeyError:
                continue
        steps = [{"tool": s["tool"], "arguments": dict(s.get("arguments") or {}),
                  "purpose": s.get("purpose") or s["tool"]} for s in example["steps"]]
        tools = " + ".join(item["tools"])
        out.append((item["times"], _proposal(
            "phrase", item["key"], f"Instant phrase: '{redact(phrase, 50)}' -> {tools}",
            {"summary": f"The model planned this same request {item['times']} times this week, with the same "
                        f"tools ({tools}) and every step verified.", "count": item["times"],
             "examples": [redact(item["said"])]},
            {"lane": "data", "areas": ["data/reflexes.json"], "detail": "one learned instant phrase; no code"},
            ["Build a fixed reflex phrase from the stored verified plan.",
             "Refuse it if a step is not instant-safe or the phrase would also catch a request done with other tools "
             "(reflex collision check).", "Save it to data/reflexes.json (enabled)."],
            {"unit": ["reflex eligibility + collision checks run at apply time"],
             "real_check": f"say '{redact(phrase, 50)}' and see it answered without the model (planner: reflex)"},
            "low: only this exact wording changes, to steps that already worked; it switches itself off after one "
            "failed run", "say 'galat kiya' after it runs (switches the phrase off), or remove it from reflex.list",
            {"phrase": phrase, "steps": steps})))
    return out


def _routine_candidates(base):
    from chutku.mind import Mind
    from chutku.quick_intents import _single
    habits = Mind(base).load().get("habits") or {}
    names = [("subah", range(5, 12)), ("dopahar", range(12, 17)), ("shaam", range(17, 21))]
    groups = defaultdict(list)
    for habit in habits.values():
        name = next((n for n, hours in names if habit.get("hour") in hours), "raat")
        proposal = _single(str(habit.get("said") or ""))
        steps = (proposal or {}).get("next_steps") or []
        if steps and not steps[0]["tool"].startswith("routine."):   # only commands the instant rules understand
            groups[name].append(habit)
    out = []
    for name, group in groups.items():
        if len(group) < 2:
            continue   # one habit is not a routine
        group = sorted(group, key=lambda h: -h.get("count", 0))[:4]
        commands = [" ".join(h["said"].split())[:200] for h in group]
        days = min(h.get("days", 0) for h in group)
        out.append((days, _proposal(
            "routine", f"{name}:{'|'.join(sorted(c.casefold() for c in commands))}",
            f"Routine '{name}': {len(commands)} things you do every day around the same time",
            {"summary": f"These requests came on {days}+ different days at a similar hour.", "count": days,
             "examples": [redact(c) for c in commands]},
            {"lane": "data", "areas": ["data/routines.json"], "detail": f"one named routine '{name}'; no code"},
            [f"Save routine '{name}' with: " + "; ".join(redact(c, 60) for c in commands),
             "Each command must be one the instant rules understand (checked when it is saved)."],
            {"unit": ["routine.save validation"], "real_check": f"say 'start {name} mode'"},
            "low: nothing runs until you say the routine's name", f"say 'forget routine {name}'",
            {"name": name, "commands": commands})))
    return out


def _preference_candidates(base, found):
    from chutku.core.preferences import Preferences
    speech = found["speech"]
    out = []
    if speech["devanagari_lines"] >= 5 and speech["devanagari_lines"] >= 0.3 * max(speech["spoken_lines"], 1) \
            and Preferences(base).load()["stt_language"] == "en":
        n = speech["devanagari_lines"]
        out.append((n, _proposal(
            "preference", "stt_language:en|hi", "Listen for Hindi as well as English",
            {"summary": f"{n} of {speech['spoken_lines']} spoken lines this week were heard in Hindi script while "
                        "speech-to-text is set to English only.", "count": n, "examples": []},
            {"lane": "data", "areas": ["data/preferences.json"], "detail": "stt_language: en -> en|hi; no code"},
            ["Set the stt_language preference to en|hi (Whisper picks English or Hindi for each command)."],
            {"unit": ["Preferences.update validation"], "real_check": "say a Hindi command and check the heard log"},
            "low: a setting; commands may take a little longer to transcribe",
            "say 'hindi listening off' (or 'sirf english suno')", {"changes": {"stt_language": "en|hi"}})))
    return out


def _skill_candidates(found):
    from chutku.quick_intents import quick_proposal
    out = []
    for item in found["repeatedly_stuck"]:
        request = " ".join(item["said"].split())
        if quick_proposal(request) is not None or not 5 <= len(request) <= 300:
            continue
        out.append((item["times"], _proposal(
            "skill", request.casefold(), f"New skill for: '{redact(request, 60)}'",
            {"summary": f"You asked this {item['times']} times this week and I could not do it.",
             "count": item["times"], "examples": [redact(request)]},
            {"lane": "data", "areas": ["data/skills/_pending/<name>/"], "detail": "a pending self-written skill"},
            ["Ask the coder for a skill (skill.json, SKILL.md, tool.py, test_tool.py) that does this.",
             "Run its tests, repairing at most 3 times.", "Leave it pending: it still needs 'skill approve <name>'."],
            {"unit": ["the skill's own test_tool.py"], "real_check": "after 'skill approve', ask it once"},
            "medium: model-written code; it stays pending, and every run asks for your click",
            "say 'skill remove <name>' (Recycle Bin)", {"request": request})))
    return out


def _area(registry, tool_name):
    """The file a tool lives in, relative to the project (atlas apps: their JSON)."""
    import inspect
    if tool_name.startswith("app."):
        path = PROJECT_ROOT / "chutku" / "apps" / "atlas" / f"{tool_name.split('.')[1]}.json"
        return path.relative_to(PROJECT_ROOT).as_posix() if path.is_file() else None
    try:
        source = Path(inspect.getsourcefile(registry.get(tool_name).execute)).resolve()
        return source.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except (KeyError, TypeError, ValueError, OSError):
        return None


PLAN_SYSTEM = """You plan one small, surgical fix to Chutku, a Python Windows assistant. You get a short redacted
summary of a weekly failure count and the file involved. Answer ONLY with lines, nothing else:
STEP: <one concrete step>        (2 to 6 lines)
TEST: <one unit test to add, in a NEW test file>   (1 to 3 lines)
Never plan changes to policy, permissions, risk levels, approvals, tests that already exist, or other files."""


def _cloud_drafter(base):
    """Gemini drafts a code plan's steps when the owner enabled it and the internet is up; otherwise None."""
    from chutku.online import reachable
    from chutku.tools import builder
    key = builder.gemini_allowed(base)
    if not key or not reachable():
        return None
    from chutku.coder import GeminiCoder
    coder = GeminiCoder(key)
    return lambda summary: coder._ask(PLAN_SYSTEM, summary)


def _code_candidates(found, registry, drafter):
    from chutku.evolve_apply import protected
    out = []
    for tool, counts in found["failed_or_unverified_steps"].items():
        total = counts["failed"] + counts["unverified"]
        if total < MIN_FAILS or registry is None:
            continue
        area = _area(registry, tool)
        if area is None or protected(area):
            continue   # Evolve never edits its own brakes (or a file it cannot find)
        examples = [_cloud_safe(m) for m in counts["examples"]]
        steps = [f"Reproduce why {tool} failed or could not be checked {total} times this week"
                 + (f" (errors: {'; '.join(examples)})" if examples else "") + ".",
                 f"Find the cause in {area} and fix it with the smallest change.",
                 "Add a unit test for the fixed case in a NEW test file tests/test_improve_<id>.py."]
        tests = {"unit": ["the new test file", "the full unit test suite", "scripts/check_phrases.py"],
                 "real_check": f"run the same request that used {tool} again and check it verifies"}
        drafted = "template"
        if drafter is not None:
            try:
                text = drafter(f"Tool {tool} failed {counts['failed']} times and could not be verified "
                               f"{counts['unverified']} times in 7 days. Redacted error texts: {examples}. "
                               f"File: {area}.")
                cloud_steps = [line[5:].strip()[:200] for line in text.splitlines() if line.startswith("STEP:")][:6]
                cloud_tests = [line[5:].strip()[:200] for line in text.splitlines() if line.startswith("TEST:")][:3]
                if len(cloud_steps) >= 2:
                    steps, drafted = cloud_steps, "gemini"
                    tests["unit"] = cloud_tests + tests["unit"][1:]
            except Exception:   # the cloud is a help; the template stands without it
                pass
        out.append((total, _proposal(
            "code", f"fix:{tool}",
            f"Fix {tool}: {counts['failed']} failed, {counts['unverified']} unverified this week",
            {"summary": f"{tool} failed {counts['failed']} times and could not be verified {counts['unverified']} "
                        "times in the last 7 days.", "count": total, "examples": counts["examples"]},
            {"lane": "code", "areas": [area], "detail": "a code change, tested in a git worktree before any merge"},
            steps, tests,
            "medium: a code change; it merges only if the whole suite still passes, and it can never touch the "
            "protected files (policy, runtime, core, guard, registry, skills, Evolve itself, safety tests)",
            "git revert <commit> (the commit is named 'Evolve <id>: ...'); main is untouched if the tests fail",
            {"request": f"{tool} keeps failing: " + " ".join(steps)})))
        out[-1][1]["drafted_by"] = drafted
    return out


def propose(base, found, registry=None, *, drafter=None, now=None):
    """Up to MAX_PER_DAY new proposals from the evidence; ones seen before (any status) are not made again."""
    known = {p.get("id") for p in load_all(base)}
    today = datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")
    made_today = sum(1 for p in load_all(base) if str(p.get("created", "")).startswith(today))
    candidates = (_phrase_candidates(base, found, registry) + _routine_candidates(base)
                  + _preference_candidates(base, found) + _skill_candidates(found)
                  + _code_candidates(found, registry, drafter))
    order = {"phrase": 0, "routine": 1, "preference": 2, "skill": 3, "code": 4}
    candidates.sort(key=lambda c: (-c[0], order[c[1]["kind"]]))
    new = []
    for _count, proposal in candidates:
        if made_today + len(new) >= MAX_PER_DAY:
            break
        if proposal["id"] in known:
            continue
        known.add(proposal["id"])
        save_proposal(base, proposal)
        new.append(proposal)
    return new


def review(base, registry=None, *, compile_skills=True, drafter="auto", now=None):
    """The evolve_review job: evidence -> profile refresh -> at most 3 proposals. Never changes code."""
    base = Path(base)
    found = evidence(base, now)
    profile = refresh_profile(base, registry if compile_skills else None)
    if drafter == "auto":
        try:
            drafter = _cloud_drafter(base)
        except Exception:   # no grant store, no network module: offline templates
            drafter = None
    new = propose(base, found, registry, drafter=drafter, now=now)
    root(base).mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now or time.time()).strftime("%Y%m%d")
    (root(base) / f"review-{stamp}.json").write_text(json.dumps({"evidence": found, "profile": profile,
                                                                "new": [p["id"] for p in new]}, indent=1,
                                                               ensure_ascii=False), encoding="utf-8")
    return {"evidence": found, "profile": profile, "new_proposals": [p["id"] for p in new],
            "drafted_by": sorted({p["drafted_by"] for p in new}), "open": len(open_proposals(base))}


def open_proposals(base):
    return [p for p in load_all(base) if p.get("status") == "proposed"]


# -- showing ------------------------------------------------------------------------------------------------------

def describe(proposal):
    """The full plan in plain words."""
    p = proposal
    lines = [f"[{p['id']}] {p['title']} ({p['kind']}, {p['status']})",
             f"Why: {p['evidence']['summary']}"]
    if p["evidence"].get("examples"):
        lines.append("Examples (redacted): " + "; ".join(redact(e) for e in p["evidence"]["examples"][:3]))
    lines.append(f"Changes: {', '.join(p['change']['areas'])} ({p['change']['detail']})")
    lines += [f"Step {n}: {step}" for n, step in enumerate(p["steps"], 1)]
    lines.append(f"Tests: {'; '.join(p['tests']['unit'])}. Real check: {p['tests']['real_check']}")
    lines.append(f"Risk: {p['risk']}. Undo: {p['undo']}")
    if p.get("result"):
        lines.append(f"Result: {p['result']}")
    if p["status"] in APPROVABLE:
        lines.append(f"Approve: type 'evolve approve {p['id']}' (then click). Reject: 'evolve reject {p['id']}'.")
    return "\n".join(lines)


def listing(base):
    proposals = load_all(base)
    waiting = [p for p in proposals if p.get("status") == "proposed"]
    done = [p for p in proposals if p.get("status") not in ("proposed",)][:5]
    if not proposals:
        reply = "No improvement ideas yet. Say 'khud ko improve karo' and I will study the last 7 days."
    else:
        reply = (f"{len(waiting)} improvement idea(s) waiting for you." if waiting else "Nothing waiting for you.")
        if waiting:
            reply += "\n\n" + "\n\n".join(describe(p) for p in waiting)
        if done:
            reply += "\n\nEarlier: " + "; ".join(f"[{p['id']}] {p['title'][:60]}: {p['status']}" for p in done)
        reply += "\n\nPushing merged changes to GitHub: " + ("on" if _push_on(base) else "off (type 'evolve push on')")
    return {"waiting": [p["id"] for p in waiting], "proposals": [{k: p.get(k) for k in ("id", "kind", "title",
                                                                                         "status")} for p in proposals],
            "skill_reply": reply}


def _push_on(base):
    from chutku.core.preferences import Preferences
    return Preferences(base).load().get("evolve_push") is True


# -- owner decision -----------------------------------------------------------------------------------------------

def apply_data(base, registry, proposal):
    """phrase / routine / preference: through the existing data paths. Returns the result text; raises ValueError."""
    kind, payload = proposal["kind"], proposal["payload"]
    if kind == "phrase":
        from chutku import experience, reflex
        from chutku.core.jsonstore import lock_for, write_json
        from chutku.tools.registry import check_schema
        template = reflex.normalize(payload["phrase"])
        item = {"template": template, "slots": {}, "steps": payload["steps"], "regex": reflex.regex_for(template, {}),
                "example_values": {}}
        for step in item["steps"]:
            try:
                tool = registry.get(step["tool"])
            except KeyError:
                raise ValueError(f"{step['tool']} is not a tool any more") from None
            if not reflex._eligible_tool(tool):
                raise ValueError(f"{step['tool']} is not an instant-safe tool")
            check_schema(step["arguments"], tool.argument_schema)
            tool.validate_arguments(step["arguments"])
        clash = reflex._collision(item, base, experience.load(base))
        if clash:
            raise ValueError(f"the phrase {clash}")
        item["id"] = reflex._id(item)
        with lock_for(reflex._path(base)):
            skills = reflex.load(base)
            if any(s.get("id") == item["id"] for s in skills):
                return "it was already an instant phrase"
            item.update({"examples": [payload["phrase"][:120]], "created": time.time(), "hits": 0, "passes": 0,
                         "fails": 0, "enabled": True, "source": f"evolve {proposal['id']}"})
            write_json(reflex._path(base), skills + [item])
        return f"'{template}' is now instant (learned skill {item['id']})"
    if kind == "routine":
        from chutku import routines
        done = routines._save({"name": payload["name"], "commands": payload["commands"]}, None)
        if done.verification != Verification.PASS:
            raise ValueError(done.output.get("error", "the routine was not saved"))
        return f"routine '{payload['name']}' saved: say 'start {payload['name']} mode'"
    if kind == "preference":
        from chutku.core.preferences import Preferences
        changes = payload["changes"]
        if not isinstance(changes, dict) or not changes or set(changes) - PREFERENCE_KEYS:
            raise ValueError("Evolve may only change " + ", ".join(sorted(PREFERENCE_KEYS)))
        before = {k: Preferences(base).load()[k] for k in changes}
        now = Preferences(base).update(changes)
        if any(now[k] != v for k, v in changes.items()):
            raise ValueError("the preference did not change")
        return f"changed {changes} (was {before})"
    raise ValueError(f"{kind} is not applied here")


def start_background(base, pid):
    """skill / code: apply in a separate process, so a code change never runs inside the live assistant."""
    python = Path(sys.executable)
    console = python.with_name("python.exe")
    log = root(base) / f"apply-{pid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        subprocess.Popen([str(console if console.is_file() else python), "-m", "chutku.evolve_apply", str(base), pid],
                         cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                         creationflags=_NO_WINDOW)
    return log


def approve(base, registry, pid, *, start=None):
    proposal = load_proposal(base, pid)
    if proposal is None:
        return {"error": f"There is no improvement idea {pid} (see 'improvement ideas')."}
    if proposal.get("status") not in APPROVABLE:
        return {"error": f"Idea {pid} is {proposal.get('status')}; it cannot be approved now."}
    proposal["status"], proposal["approval"] = "approved", {"sha256": plan_hash(proposal),
                                                            "at": datetime.now().isoformat(timespec="seconds")}
    save_proposal(base, proposal)
    if proposal["kind"] in DATA_LANE:
        try:
            result = apply_data(base, registry, proposal)
            proposal["status"], proposal["result"] = "applied", result
        except (ValueError, OSError) as error:
            proposal["status"], proposal["result"] = "failed", str(error)[:300]
        save_proposal(base, proposal)
        record(base, proposal, proposal["status"], detail=proposal["result"])
        out = {"id": pid, "status": proposal["status"], "result": proposal["result"]}
        out["skill_reply" if proposal["status"] == "applied" else "error"] = (
            f"Applied [{pid}] {proposal['title']}: {proposal['result']}. Undo: {proposal['undo']}."
            if proposal["status"] == "applied" else f"[{pid}] was not applied: {proposal['result']}")
        return out
    log = (start or start_background)(base, pid)
    push = "on" if _push_on(base) else "off, so nothing is pushed to GitHub (type 'evolve push on' to change that)"
    where = ("written and tested in a separate git worktree; main changes only if the full test suite and the "
             "phrase check pass, otherwise it is thrown away") if proposal["kind"] == "code" else \
        "written by the coder as a pending skill; it still needs 'skill approve <name>'"
    return {"id": pid, "status": "approved", "log": str(log),
            "skill_reply": f"Approved [{pid}] {proposal['title']}. It is being {where}. 'improvement ideas' shows "
                           f"the result. GitHub push: {push}."}


def reject(base, pid):
    proposal = load_proposal(base, pid)
    if proposal is None:
        return {"error": f"There is no improvement idea {pid}."}
    if proposal.get("status") not in APPROVABLE:
        return {"error": f"Idea {pid} is {proposal.get('status')}; nothing to reject."}
    proposal["status"] = "rejected"
    save_proposal(base, proposal)
    record(base, proposal, "rejected")
    return {"id": pid, "status": "rejected",
            "skill_reply": f"Rejected [{pid}] {proposal['title']}. I will not suggest it again."}


# -- tools --------------------------------------------------------------------------------------------------------

def _validate_none(arguments):
    if arguments:
        raise ValueError("This takes no arguments.")


def _validate_id(arguments):
    if set(arguments) != {"id"} or not isinstance(arguments["id"], str) or not ID.fullmatch(arguments["id"]):
        raise ValueError("Give the idea's id (6 letters/digits, see 'improvement ideas').")


def _validate_switch(arguments):
    if set(arguments) != {"on"} or type(arguments["on"]) is not bool:
        raise ValueError("Give on: true or false.")


def _result(output):
    return ToolResult(output, Verification.FAIL if "error" in output else Verification.PASS)


_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
_ID = {"type": "object", "properties": {"id": {"type": "string", "pattern": ID.pattern}}, "required": ["id"],
       "additionalProperties": False}


def register_evolve_tools(registry, base):
    base = Path(base)

    def reviewing(_arguments, _context):
        out = review(base, registry)
        shown = listing(base)
        new = len(out["new_proposals"])
        shown["skill_reply"] = (f"I studied the last {DAYS} days: {out['evidence']['requests']} requests, "
                                f"{out['evidence']['actions']} actions. {new} new idea(s). " + shown["skill_reply"])
        return ToolResult(out | shown, Verification.PASS)

    def approving(arguments, context):
        if getattr(context, "provenance", None) != "user_stated":   # an on-screen-reviewed voice plan is not typing
            return ToolResult({"error": "Approve an improvement idea by typing 'evolve approve <id>', not by voice."},
                              Verification.FAIL)
        return _result(approve(base, registry, arguments["id"]))

    def switching(arguments, _context):
        from chutku.core.preferences import Preferences
        on = Preferences(base).update({"evolve_push": arguments["on"]})["evolve_push"]
        return ToolResult({"evolve_push": on, "skill_reply": "Evolve will push merged changes to GitHub." if on else
                           "Evolve will not push to GitHub (merges stay on this PC)."},
                          Verification.PASS if on == arguments["on"] else Verification.FAIL)

    registry.register(Tool("evolve.review", "Study the last 7 days of Chutku's own logs (failures, slow or model-planned "
        "requests, misheard speech, asks, habits), refresh the owner profile, and write at most 3 improvement ideas "
        "as full plans for the owner to approve. Changes no code.", Risk.REVERSIBLE, reviewing, _validate_none,
        argument_schema=_NONE, reversibility="creates_proposal_files_only", success_predicate="review_written"))
    registry.register(Tool("evolve.list", "Show Chutku's improvement ideas (full plans: evidence, change, steps, tests, "
        "risk, undo) and what happened to earlier ones.", Risk.OBSERVATION,
        lambda _arguments, _context: ToolResult(listing(base), Verification.PASS), _validate_none,
        argument_schema=_NONE, reversibility="not_applicable", success_predicate="proposals_listed"))
    registry.register(Tool("evolve.approve", "Owner only (typed 'evolve approve <id>', then a click): apply one "
        "improvement idea. Data ideas apply at once; code is written and tested in a separate git worktree and merged "
        "only if every test passes.", Risk.EXTERNAL_SIDE_EFFECT,
        approving, _validate_id, required_capability="process.launch", argument_schema=_ID, reversibility="none",
        success_predicate="approved_idea_applied_or_started", user_only=True, runs_code=True))
    registry.register(Tool("evolve.reject", "Reject one improvement idea; it is not suggested again.", Risk.REVERSIBLE,
        lambda arguments, _context: _result(reject(base, arguments["id"])), _validate_id, argument_schema=_ID,
        reversibility="none", success_predicate="proposal_marked_rejected"))
    registry.register(Tool("settings.evolve_push", "Owner only (typed 'evolve push on/off'): push changes Evolve merged "
        "to GitHub (off by default).", Risk.REVERSIBLE, switching, _validate_switch,
        argument_schema={"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"],
                         "additionalProperties": False},
        reversibility="compensatable", success_predicate="preference_written", user_only=True))
