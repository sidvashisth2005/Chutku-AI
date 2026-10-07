"""Night Shift (master plan S20): Chutku improves while the PC idles.

``run_once`` runs these jobs in order, each time-boxed and logged, and writes data/nightshift/report-YYYYMMDD.json:

1. Learned skills: ``reflex.compile_all`` (S17).
2. Reliability: the earned-autonomy summary (S16), so the morning card can say what keeps failing.
3. Regression replay: every distinct real goal of the last 7 days is planned again (rules, learned skills, exact
   repeats and, when the model is allowed, one model round). Nothing is executed: the runtime is only asked for tool
   descriptions. The first tools are compared with what was verified last time: same, changed, or now failing.
4. Maintenance: events older than 90 days go to the archive database, the heard log is pruned, the action log's
   hash chain is checked.
5. Fine-tune readiness (approved plan, data-gated): with 300+ verified turns and no adapter in the last 7 days,
   data/nightshift/lora-ready.json is written. Training itself is S20b and needs the owner's go-ahead.

It runs from Task Scheduler (``chutku.cli nightshift install``): from 04:00 every day, on mains power, Chutku waits
until the PC has had no keyboard or mouse input for 30 minutes, then runs once that day. It refuses to work on
battery and keeps the PC awake only while the jobs run.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import time

REPORT_DIR = ("data", "nightshift")
REPLAY_DAYS = 7
MAX_GOALS = 1000   # every distinct goal of the week; the time box decides how many are checked (newest first)
LORA_TURNS = 300
IDLE_MINUTES = 30   # owner, 2026-10-06: after 04:00, once the PC has been unused for half an hour
_INSTANT = {"quick", "reflex", "replay"}


def on_ac_power():
    """True on mains power (or a desktop without a battery); False on battery; None when Windows will not say."""
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    status = Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return {1: True, 0: False}.get(status.ACLineStatus)


def report_dir(base):
    return Path(base).joinpath(*REPORT_DIR)


def latest_report(base):
    reports = sorted(report_dir(base).glob("report-*.json"))
    if not reports:
        return None
    try:
        return json.loads(reports[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _job(report, name, work):
    started = time.perf_counter()
    try:
        report["jobs"][name] = {"ok": True, **(work() or {})}
    except Exception as error:   # one failing job never stops the others
        report["jobs"][name] = {"ok": False, "error": f"{type(error).__name__}: {error}"[:300]}
    report["jobs"][name]["seconds"] = round(time.perf_counter() - started, 2)


# -- 3. regression replay -----------------------------------------------------------------------------------------------

def recent_goals(base, days=REPLAY_DAYS, now=None):
    """Distinct goals (by normalised wording) of the last ``days`` with the tools that were verified last time."""
    from chutku import recall
    from chutku.experience import normal_goal
    cutoff = (now or time.time()) - days * 86400
    latest = {}
    for turn in recall.turns(base, 5000):
        said = str(turn.get("said") or "").strip()
        if not said or float(turn.get("at") or 0) < cutoff:
            continue
        key = normal_goal(said)
        if not key:
            continue
        at = float(turn.get("at") or 0)
        entry = latest.setdefault(key, {"goal": said, "verified_tools": None, "times": 0, "at": 0.0, "verified_at": 0.0})
        entry["times"] += 1
        if at >= entry["at"]:   # the newest wording of the request
            entry["goal"], entry["at"] = said, at
        if turn.get("status") == "done" and turn.get("tools") and at >= entry["verified_at"]:
            entry["verified_tools"], entry["verified_at"] = list(turn["tools"]), at   # what worked most recently
    return sorted(latest.values(), key=lambda e: -e["at"])


def plan_only(base, goal, runtime, model=None):
    """(tools of the first planned round, planner) for a goal, without running anything."""
    from chutku.agent_loop import AgentSession
    from chutku.quick_intents import quick_proposal
    from chutku import experience, reflex
    proposal = quick_proposal(goal)
    if proposal is not None and proposal["next_steps"]:
        return [s["tool"] for s in proposal["next_steps"]], "quick"
    found = reflex.match(base, goal, runtime)
    if found is not None:
        return [s["tool"] for s in found[0]["next_steps"]], "reflex"
    key = experience.normal_goal(goal)
    for row in experience.load(base):
        if row.get("replayable") and row.get("rating") != "bad" and experience.normal_goal(row["goal"]) == key:
            return [s["tool"] for s in row["steps"]], "replay"
    if model is None:
        return None, "model not asked"
    session = AgentSession(goal, mode="review")   # review: even if something went wrong, nothing would run unasked
    proposal, _meta = model.propose(session, runtime)
    if proposal["status"] == "done":
        return [], "model: answers directly"
    if proposal["status"] != "continue":
        return [], f"model: {proposal['status']}"
    return [s["tool"] for s in proposal["next_steps"]], "model"


def regression_replay(base, runtime, model=None, deadline=None):
    goals = recent_goals(base)[:MAX_GOALS]
    rows = []
    for entry in goals:
        if deadline is not None and time.monotonic() > deadline:
            rows.append({"goal": entry["goal"][:120], "verdict": "not checked (time box)"})
            continue
        try:
            tools, planner = plan_only(base, entry["goal"], runtime, model)
        except Exception as error:   # the plan broke a tool's rules: live, the loop retries once with this reason
            rows.append({"goal": entry["goal"][:120], "verdict": "rejected plan", "error": str(error)[:200],
                         "verified_before": entry["verified_tools"]})
            continue
        before = entry["verified_tools"]
        if tools is None:
            verdict = "not checked (needs the model)"
        elif not tools and planner == "model: answers directly":
            verdict = "answers directly"          # no tool needed now (chat, maths, knowledge): never a failure
        elif before is None:
            verdict = "new plan" if tools else "chat (no tools)"
        elif not tools:
            verdict = "fails now"
        elif before[:len(tools)] == tools:
            verdict = "same"
        else:
            verdict = "changed"
        rows.append({"goal": entry["goal"][:120], "planner": planner, "now": tools, "verified_before": before,
                     "verdict": verdict})
    counts = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {"distinct_goals": len(goals), "counts": counts, "rows": rows}


# -- 4. maintenance / 5. fine-tune readiness ---------------------------------------------------------------------------

def maintenance(base, runtime):
    from chutku.voice import heard
    archived = runtime.event_log.archive_older_than(90)
    pruned = heard.prune(base)
    chain = runtime.action_log.verify()
    return {"events_archived": archived, "heard_lines_dropped": pruned, "action_log_chain_ok": chain["ok"]}


def lora_readiness(base, now=None):
    from chutku import recall
    verified = sum(1 for t in recall.turns(base, 100000)
                   if t.get("status") == "done" and t.get("tools") and not t.get("tainted"))
    adapters = sorted((Path(base) / "models").glob("planner-lora*.gguf"))
    newest = max((a.stat().st_mtime for a in adapters), default=0)
    fresh = (now or time.time()) - newest < 7 * 86400
    ready = verified >= LORA_TURNS and not fresh
    marker = report_dir(base) / "lora-ready.json"
    if ready:
        marker.write_text(json.dumps({"verified_turns": verified, "at": datetime.now().isoformat(timespec="seconds")}),
                          encoding="utf-8")
    return {"verified_turns": verified, "needed": LORA_TURNS, "ready": ready}


# -- the night -----------------------------------------------------------------------------------------------------------

def run_once(base, *, model=None, minutes=30, force=False):
    """Run every job once and write the report. Returns the report (``skipped`` on battery)."""
    from chutku.app import create_runtime
    base = Path(base)
    report_dir(base).mkdir(parents=True, exist_ok=True)
    report = {"date": datetime.now().strftime("%Y-%m-%d"), "started": datetime.now().isoformat(timespec="seconds"),
              "jobs": {}}
    if not force and on_ac_power() is False:
        report["skipped"] = "on battery"
        return report
    deadline = time.monotonic() + minutes * 60
    try:
        keep_awake(True)   # only for these minutes; Windows' own sleep timer applies again afterwards
    except (AttributeError, OSError):
        pass
    try:
        _run_jobs(base, report, model, deadline, create_runtime)
    finally:
        try:
            keep_awake(False)
        except (AttributeError, OSError):
            pass
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    path = report_dir(base) / f"report-{datetime.now():%Y%m%d}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["path"] = str(path)
    return report


def _run_jobs(base, report, model, deadline, create_runtime):
    with create_runtime(base) as runtime:
        from chutku import reflex
        _job(report, "learned_skills", lambda: _skills(base, runtime, reflex))
        _job(report, "reliability", lambda: _reliability(runtime))
        _job(report, "regression_replay", lambda: regression_replay(base, runtime, model, deadline))
        _job(report, "maintenance", lambda: maintenance(base, runtime))
        _job(report, "fine_tune_readiness", lambda: lora_readiness(base))


def _skills(base, runtime, reflex):
    before = len(reflex.load(base))
    result = reflex.compile_all(base, runtime.registry)
    return {"new_skills": len(result["added"]), "added": result["added"], "total": result["skills"],
            "turned_down": len(result["rejected"]), "before": before}


def _reliability(runtime):
    from chutku.core.ledger import MIN_TRIALS, Reliability, unreliable, wilson_lower
    rows = runtime.ledger.table(100)
    weak = [r for r in rows if unreliable(Reliability(r["trials"], r["passes"], wilson_lower(r["passes"], r["trials"])
                                                      if r["trials"] >= MIN_TRIALS else None, r["target"]))]
    return {"kinds_measured": len(rows), "keeps_failing": [f"{r['tool']} on {r['target']}" for r in weak[:10]]}


def morning_line(base):
    """The Today card line: "Raat ko: 2 naye skills, 1 badla hua plan, ..." from the newest report."""
    report = latest_report(base)
    if not report or report.get("skipped"):
        return None
    jobs = report.get("jobs", {})
    skills = (jobs.get("learned_skills") or {}).get("new_skills", 0)
    counts = (jobs.get("regression_replay") or {}).get("counts", {})
    weak = len((jobs.get("reliability") or {}).get("keeps_failing", []))
    parts = [f"{skills} naye skills", f"{counts.get('changed', 0)} badle hue plans",
             f"{counts.get('fails now', 0)} ab fail", f"{counts.get('rejected plan', 0)} galat plan",
             f"{counts.get('same', 0)} same"]
    if weak:
        parts.append(f"{weak} baar-baar fail hone wale kaam")
    return f"Raat ko ({report['date']}): " + ", ".join(parts) + "."


def report_summary(base):
    """Last night's report for the owner ("night report", "raat ko kya kiya"): what ran, when, and what it found.
    Only plain facts from the saved report; the goals listed are the owner's own past requests."""
    report = latest_report(base)
    if not report:
        return {"ran": False, "summary": "Night Shift has not run yet: it runs at 4 AM after 30 minutes without "
                                         "keyboard or mouse, on charger."}
    if report.get("skipped"):
        return {"ran": False, "date": report.get("date"), "summary": f"Night Shift skipped ({report['skipped']})."}
    jobs = report.get("jobs", {})
    replay = jobs.get("regression_replay") or {}
    rows = replay.get("rows") or []

    def goals(verdict):
        return [row["goal"][:80] for row in rows if row.get("verdict") == verdict][:5]
    failed_jobs = [name for name, job in jobs.items() if isinstance(job, dict) and not job.get("ok", True)]
    tune = jobs.get("fine_tune_readiness") or {}
    return {"ran": True, "date": report.get("date"), "started": report.get("started"),
            "finished": report.get("finished"), "summary": morning_line(base),
            "new_skills": (jobs.get("learned_skills") or {}).get("new_skills", 0),
            "requests_rechecked": replay.get("distinct_goals", 0), "counts": replay.get("counts", {}),
            "fails_now": goals("fails now"), "changed": goals("changed"),
            "keeps_failing": (jobs.get("reliability") or {}).get("keeps_failing", [])[:5],
            "fine_tune": f"{tune.get('verified_turns', 0)}/{tune.get('needed', 300)} verified turns",
            "jobs_failed": failed_jobs}


_INSTALL = r'''
$ErrorActionPreference = 'Stop'
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
$action = New-ScheduledTaskAction -Execute $r.python -Argument '-m chutku.cli nightshift run --when-idle' -WorkingDirectory $r.root
$trigger = New-ScheduledTaskTrigger -Daily -At 04:00
# Chutku itself waits for 30 minutes without keyboard or mouse (Windows' own idle condition is checked too coarsely).
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 23) -StartWhenAvailable -MultipleInstances IgnoreNew
$settings.DisallowStartIfOnBatteries = $true
$settings.StopIfGoingOnBatteries = $true
Register-ScheduledTask -TaskPath '\Chutku\' -TaskName 'NightShift' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
$t = Get-ScheduledTask -TaskPath '\Chutku\' -TaskName 'NightShift'
@{ state = [string]$t.State; at = ($t.Triggers | Select-Object -First 1).StartBoundary; ac_only = $t.Settings.DisallowStartIfOnBatteries; runs = $t.Actions[0].Arguments } | ConvertTo-Json -Compress
'''


def idle_seconds():
    """Seconds since the last keyboard or mouse input in this Windows session."""
    import ctypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)


def ran_today(base, now=None):
    report = latest_report(base)
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    return bool(report and report.get("date") == today and report.get("finished"))


def wait_for_idle(base, *, idle_needed=IDLE_MINUTES * 60, poll=60, until=None, now=time.time, idle=None,
                  sleep=time.sleep, power=None):
    """From 04:00 (the task's start), wait until the PC has had no input for ``idle_needed`` seconds while on mains
    power, at most until ``until`` (the next 04:00). True when it is time to run, False when the day passed."""
    idle, power = idle or idle_seconds, power or on_ac_power
    until = until or (now() + 24 * 3600 - 60)
    while now() < until:
        if ran_today(base):
            return False                          # once a day: a manual run today already counts
        if power() is not False and idle() >= idle_needed:
            return True
        sleep(poll)
    return False


def keep_awake(on):
    """Ask Windows not to sleep while the night's jobs run (only for those minutes)."""
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def install(root):
    """Task Scheduler \\Chutku\\NightShift: from 04:00 daily, on mains power; Chutku then waits for 30 minutes without
    keyboard or mouse before it starts (owner's choice, 2026-10-06; it was a fixed 02:30 before)."""
    import sys
    from chutku.tools.everyday import _powershell
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.is_file():
        python = Path(sys.executable)
    return _powershell(_INSTALL, {"python": str(python), "root": str(root)}, timeout=30)
