"""Weekly insights (Phase 3b H7, Hermes /insights): "is hafte kya kiya" / "weekly report".

Plain counts from Chutku's own logs for the last 7 days, compared with the 7 days before: requests (voice vs typed),
how many were answered instantly (rules, learned skills, exact replay) vs by a model (local or Gemini), the most used
actions, failures and refusals, how many approvals the owner clicked, and new learned skills. No model is used.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

INSTANT = {"quick", "reflex", "replay"}
MODEL = {"local", "gemini"}


def _jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _action_time(row):
    try:
        return datetime.fromisoformat(str(row.get("time"))).timestamp()
    except ValueError:
        return None


def _requests(rows):
    asked = [r for r in rows if r.get("status") != "said"]   # "said": a voice-conversation line, not a request
    planners = [set(r.get("planners") or []) for r in asked]
    instant = sum(1 for p in planners if p and p <= INSTANT)
    model = sum(1 for p in planners if p & MODEL)
    return {"requests": len(asked), "voice": sum(1 for r in asked if r.get("origin") == "voice"),
            "typed": sum(1 for r in asked if r.get("origin") == "text"), "instant": instant, "by_model": model,
            "gemini": sum(1 for p in planners if "gemini" in p),
            "instant_share": round(instant / len(asked), 2) if asked else None,
            "voice_chat_lines": len(rows) - len(asked),
            "not_done": sum(1 for r in asked if r.get("status") not in {"done", None})}


def week(base, now=None) -> dict:
    """This week (the last 7 days up to now) and the week before, from data/conversations.jsonl,
    data/actions.log.jsonl and data/reflexes.json."""
    base = Path(base)
    now = now or datetime.now()
    end, start, before = now.timestamp(), (now - timedelta(days=7)).timestamp(), (now - timedelta(days=14)).timestamp()
    conversations = _jsonl(base / "data" / "conversations.jsonl")
    this = [r for r in conversations if start <= float(r.get("at") or 0) <= end]
    last = [r for r in conversations if before <= float(r.get("at") or 0) < start]
    actions = [a for a in _jsonl(base / "data" / "actions.log.jsonl")
               if (t := _action_time(a)) is not None and start <= t <= end]
    tools = Counter(tool for r in this for tool in (r.get("tools") or []))
    failed = Counter(a.get("tool") for a in actions if a.get("state") == "FAILED")
    try:
        reflexes = json.loads((base / "data" / "reflexes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reflexes = []
    new_skills = []
    for skill in reflexes if isinstance(reflexes, list) else []:
        try:
            created = datetime.fromisoformat(str(skill.get("created"))).replace(tzinfo=None).timestamp()
        except ValueError:
            continue
        if start <= created <= end:
            new_skills.append(skill.get("template") or skill.get("id"))
    return {"from": datetime.fromtimestamp(start).strftime("%a %d %b"), "to": now.strftime("%a %d %b"),
            "this_week": _requests(this), "last_week": _requests(last),
            "top_actions": tools.most_common(5),
            "actions_logged": len(actions),
            "completed": sum(1 for a in actions if a.get("state") == "COMPLETED"),
            "failed": sum(failed.values()), "most_failed": failed.most_common(3),
            "refused": sum(1 for a in actions if a.get("state") == "DENIED"),
            "asked_you": sum(1 for a in actions if a.get("state") == "WAITING_CONFIRMATION"),
            "you_approved": sum(1 for a in actions if a.get("approved_on_screen")),
            "new_skills": new_skills}


def say(out) -> str:
    """The spoken/typed answer."""
    this, last = out["this_week"], out["last_week"]

    def share(value):
        return "–" if value is None else f"{round(value * 100)}%"
    text = (f"This week ({out['from']} – {out['to']}): {this['requests']} requests ({this['voice']} by voice, "
            f"{this['typed']} typed), last week {last['requests']}. Instant answers: {share(this['instant_share'])} "
            f"(last week {share(last['instant_share'])}); {this['by_model']} needed a model")
    gemini = this["gemini"]
    text += f", {gemini} of them Gemini." if gemini else "."
    if out["top_actions"]:
        text += " Most used: " + ", ".join(f"{tool} ×{count}" for tool, count in out["top_actions"][:3]) + "."
    text += (f" Actions: {out['completed']} done, {out['failed']} failed, {out['refused']} refused; "
             f"I asked you {out['asked_you']} times and you approved {out['you_approved']}.")
    if out["most_failed"]:
        text += " Failed most: " + ", ".join(f"{tool} ×{count}" for tool, count in out["most_failed"]) + "."
    text += f" New learned skills: {len(out['new_skills'])}."
    return text
