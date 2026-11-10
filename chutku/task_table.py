"""The task table (owner 2026-11-10: "synthetic workflows of all possible tasks a user can give, all types of
personalities ... put into a hash table for lookup").

chutku/apps/tasks.jsonl holds requests written for different kinds of users (a curious Gen-Z kid, a busy office
worker, a parent, a student...) in English, Hinglish and Hindi script. A row with `steps` is a ready plan: its
normalised sentence is the key of a dict, so a known request costs one lookup, no regex scan and no model.

The steps still pass policy, approvals and each tool's own check like any other plan. A step of an app atlas
(`app.<app>.<action>`) is used only after the Action Lab verified it on this PC; a row with an unverified step is
skipped, so the request goes on to the other routes.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

FILE = Path(__file__).resolve().parent / "apps" / "tasks.jsonl"
_TABLE = {}


def key(goal):
    """How a request is looked up: Hindi script as Hinglish, polite lead-ins and fillers dropped, case, spaces and end
    punctuation ignored."""
    from chutku.reflex import normalize
    return re.sub(r"[\s.!?,]+$", "", normalize(goal).casefold())


def rows(path=FILE):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("//")]


def table(path=FILE):
    """{key: row} for every row with a plan (built once per file)."""
    if path not in _TABLE:
        _TABLE[path] = {key(row["say"]): row for row in rows(path) if row.get("steps")}
    return _TABLE[path]


def lookup(goal, *, verified=None, path=FILE):
    """A proposal for a request the table knows, else None."""
    row = table(path).get(key(goal))
    if row is None:
        return None
    apps = [s["tool"].split(".") for s in row["steps"] if s["tool"].startswith("app.")]
    if apps:
        if verified is None:
            from chutku.app import PROJECT_ROOT
            from chutku.apps.lab import verified_actions
            verified = verified_actions(PROJECT_ROOT)
        if any(action not in verified.get(app, ()) for _prefix, app, action in apps):
            return None   # not proven on this PC yet: the planner handles it
    steps = [{"tool": s["tool"], "arguments": dict(s.get("arguments") or {}),
              "purpose": s.get("purpose") or row.get("title") or "task table"} for s in row["steps"]]
    return {"status": "continue", "reply": row.get("reply") or "Kar rahi hoon.",
            "declared_plan": [row.get("title") or row["say"]], "next_steps": steps, "finish": True,
            "task_table": row.get("id")}
