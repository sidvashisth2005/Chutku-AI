"""WA1 ask-once memory (owner 2026-11-08: "once a step worked for the same exact request, it no longer asks").

An entry is the exact step: the tool plus its normalised arguments. It is written only when the owner pressed
"Yes, always" AT THE LAPTOP and the step then verified (PASS). It is used only when nothing outside tainted the
request, never for deletes, never for power/kill/network (R4) other than the owner's own exact PowerShell or script,
and never for laptop-only steps asked from the phone or Telegram. An entry unused for 90 days expires; Settings lists
them with a Forget button (data/approval_memory.json).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

EXPIRE_SECONDS = 90 * 24 * 3600
REMOTE_ORIGINS = frozenset({"phone", "telegram", "relay"})
OWN_CODE = frozenset({"system.powershell", "code.run_python"})   # R4/code the owner's exact text may be remembered
NEVER = ("elevate.", "apps.uninstall", "services.set")           # elevated or removing: asks every time


def _file(base):
    return Path(base) / "data" / "approval_memory.json"


def _norm(value):
    if isinstance(value, str):
        return " ".join(value.replace("/", "\\").strip().split()).casefold()
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def key(step):
    text = json.dumps([step["tool"], _norm(step.get("arguments") or {})], sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def eligible(tool, *, tainted, origin):
    """May an approval of this tool be remembered or used at all?"""
    if tainted or tool.deletes or tool.name.startswith(NEVER):
        return False
    laptop_only = int(tool.base_risk) >= 4 or tool.runs_code
    if laptop_only and tool.name not in OWN_CODE:
        return False
    return not (laptop_only and origin in REMOTE_ORIGINS)


def load(base, now=None):
    now = now or time.time()
    try:
        data = json.loads(_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and now - v.get("used", 0) < EXPIRE_SECONDS}


def _save(base, data):
    from chutku.core.jsonstore import write_json
    write_json(_file(base), data)


def remember(base, step, tool, *, tainted, origin, now=None):
    """After the owner's "Yes, always" at the laptop and a verified run. False when this step may not be remembered."""
    if base is None or not eligible(tool, tainted=tainted, origin=origin) or origin in REMOTE_ORIGINS:
        return False
    now = now or time.time()
    data = load(base, now)
    summary = json.dumps(step.get("arguments") or {}, ensure_ascii=False, default=str)
    data[key(step)] = {"tool": step["tool"], "what": (step.get("purpose") or step["tool"])[:120],
                       "arguments": summary[:200], "granted": now, "used": now}
    _save(base, data)
    return True


def allows(base, step, tool, *, tainted, origin, now=None):
    """True when this exact step was remembered and may run without asking now (the use is recorded)."""
    if base is None or not eligible(tool, tainted=tainted, origin=origin):
        return False
    now = now or time.time()
    data = load(base, now)
    entry = data.get(key(step))
    if entry is None or entry.get("tool") != step["tool"]:
        return False
    entry["used"] = now
    _save(base, data)
    return True


def entries(base):
    return [{"id": k, **{f: v.get(f) for f in ("tool", "what", "arguments", "granted", "used")}}
            for k, v in sorted(load(base).items(), key=lambda item: -item[1].get("used", 0))]


def forget(base, entry_id):
    data = load(base)
    if data.pop(str(entry_id), None) is None:
        raise ValueError("That remembered step is already gone.")
    _save(base, data)
    return entries(base)
