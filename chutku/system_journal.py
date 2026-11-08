"""WA2 hardening 2: every system change journals what it replaced (data/system_journal.jsonl), so "undo last change"
/ "wo wapas karo" can put it back. Installs are undone by uninstalling."""
from __future__ import annotations

import json
from pathlib import Path
import time


def _file(base):
    return Path(base) / "data" / "system_journal.jsonl"


def record(base, kind, target, before, after, **extra):
    """kind: setting | registry | startup | service | install."""
    path = _file(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": time.time(), "kind": kind, "target": target, "before": before, "after": after, "undone": False,
             **extra}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return entry


def entries(base):
    try:
        lines = _file(base).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def last(base):
    """The newest change that is not undone yet, or None."""
    return next((e for e in reversed(entries(base)) if not e.get("undone")), None)


def mark_undone(base, entry):
    rows = entries(base)
    for row in reversed(rows):
        if row == entry:
            row["undone"] = True
            break
    _file(base).write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
                           encoding="utf-8")
