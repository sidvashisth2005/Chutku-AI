"""Learning from experience: plans that fully succeeded are kept as worked examples, and the
most similar ones are shown to the planner for new requests.

Only sessions where every step was independently verified are stored. Sensitive argument
values (message text, typed text, file contents) are never stored. The planner sees tool names,
purposes and non-sensitive arguments; Gemini sees tool names and purposes only.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
import time

MAX_EXAMPLES = 500
_lock = threading.RLock()
_STOP = {"a", "an", "the", "to", "and", "of", "in", "on", "for", "my", "me", "it", "is", "please", "then", "into",
         "with", "at", "from", "this", "that", "karo", "kar", "do", "ko", "ka", "ki", "ke", "mein", "me", "aur", "se"}


def _path(base):
    return Path(base) / "data" / "experience.jsonl"


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in _STOP and len(w) > 1}


def record(base, session, runtime=None, *, replayable=None):
    """Store a fully verified session as an example (no-op otherwise).

    ``replayable=False`` keeps it as an example the planner may read but never re-run blindly."""
    snap = session.snapshot()
    steps = snap["steps"]
    if snap["status"] != "done" or not steps or any(s["state"] != "COMPLETED" for s in steps):
        return False
    if snap.get("tainted"):
        return False  # a plan steered by a web page or a message must never become a worked example
    if snap.get("origin") == "script":
        return False  # a test script's request is not an example of what the owner wants (F7)
    planners = [p.get("planner") for p in snap.get("planners", [])]
    if planners and all(name == "quick" for name in planners):
        return False  # rule-matched plans teach the model nothing, and a wrong match must never become an example
    kept, complete = [], True
    for step in steps:
        sensitive = set()
        if runtime is not None:
            try:
                sensitive = set(runtime.registry.get(step["tool"]).sensitive_argument_names)
            except KeyError:
                sensitive = set(step["arguments"])
        arguments = {k: v for k, v in step["arguments"].items()
                     if k not in sensitive and k not in {"text", "content", "message"}
                     and len(json.dumps(v, default=str)) <= 200}
        complete = complete and len(arguments) == len(step["arguments"])
        kept.append({"tool": step["tool"], "purpose": step.get("purpose", "")[:120], "arguments": arguments})
    row = {"goal": snap["goal"][:300], "steps": kept[:20], "at": time.time(),
           "planners": [p.get("planner") for p in snap.get("planners", [])][:6],
           # A plan made in ONE round never depended on observed results, so it can be replayed as it is.
           "replayable": complete and snap.get("rounds", 99) == 1 and len(steps) <= 4 and replayable is not False}
    path = _path(base)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = load(base)
        rows = [r for r in rows if r["goal"].casefold() != row["goal"].casefold()] + [row]
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-MAX_EXAMPLES:]),
                        encoding="utf-8")
    return True


def load(base):
    try:
        lines = _path(base).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def save_rows(base, rows):
    path = _path(base)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-MAX_EXAMPLES:]),
                        encoding="utf-8")


def update_rows(base, change):
    """Read, change and write the examples under one lock (no lost update against record())."""
    with _lock:
        rows = load(base)
        if change(rows):
            save_rows(base, rows)


def _practice_wins(base):
    """Night practice plans the model got right (verified by score, train split only): examples, never replayed."""
    import json
    rows = []
    for path in sorted((Path(base) / "data" / "finetune").glob("*.jsonl"))[-14:]:   # the last two weeks
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                steps = [{"tool": s["tool"], "arguments": s.get("arguments") or {}, "purpose": s.get("purpose", "")}
                         for s in item.get("plan") or [] if isinstance(s, dict) and s.get("tool")]
                if steps:
                    rows.append({"goal": item["prompt"], "steps": steps, "at": path.stat().st_mtime})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return rows


def similar(base, goal, k=3, minimum=0.28):
    """Up to k past successful plans whose goal shares enough meaningful words with this one (2026-11-08: also the
    night practice's verified plans, and a lower bar, so more wins are reused)."""
    words = _words(goal)
    if not words:
        return []
    scored = []
    for row in [*load(base), *_practice_wins(base)]:
        if row.get("rating") == "bad":
            continue  # the owner said this was wrong ("galat kiya"): never an example again
        other = _words(row["goal"])
        if not other:
            continue
        score = len(words & other) / len(words | other) + (0.1 if row.get("rating") == "good" else 0)
        if score >= minimum:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -item[1].get("at", 0)))
    return [{"goal": row["goal"], "steps": row["steps"], "similarity": round(score, 2),
             **({"replayable": True} if row.get("replayable") and row.get("rating") != "bad" else {})}
            for score, row in scored[:k]]


def normal_goal(text):
    """For exact repeats: Hindi script read as Hinglish, case, punctuation and polite fillers ignored."""
    from chutku.translit import roman
    text = re.sub(r"[^\w\s]", " ", roman(str(text)).casefold())
    return " ".join(w for w in text.split() if w not in {"please", "pls", "plz", "chutku", "oye", "zara", "na",
                                                          "yaar", "bhai", "hey"})
