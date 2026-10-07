"""Background pause (Phase 3b H2): hold every job Chutku starts by herself, while the owner's own requests still work.

"background kaam roko" writes data/background.paused; scheduled tasks and the Night Shift then wait. "pause
everything" (core/action_control.py) is different: it stops every action, the owner's too.

Fail safe, like hermes-agent's ESTOP sentinel (agent/estop.py, MIT, Nous Research): the file's presence is the pause,
whatever it contains (empty or damaged still counts), and an error while checking also counts as paused.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

_FILE = "data/background.paused"


def path(base) -> Path:
    return Path(base) / _FILE


def engaged(base) -> bool:
    """True while background work is paused. Uncached; any error other than "no file" counts as paused."""
    try:
        os.stat(path(base))
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def info(base) -> dict:
    if not engaged(base):
        return {"paused": False}
    try:
        import json
        data = json.loads(path(base).read_text(encoding="utf-8"))
        return {"paused": True, "since": data.get("at"), "reason": data.get("reason")}
    except (OSError, ValueError, AttributeError):
        return {"paused": True, "since": None, "reason": "pause file present"}


def engage(base, reason="owner asked", by="owner") -> dict:
    from chutku.core.jsonstore import write_json
    path(base).parent.mkdir(parents=True, exist_ok=True)
    write_json(path(base), {"at": datetime.now().isoformat(timespec="seconds"), "reason": str(reason)[:200],
                            "by": str(by)[:40]})
    return info(base)


def release(base) -> dict:
    path(base).unlink(missing_ok=True)
    return info(base)
