"""Small JSON files the owner's settings live in (preferences, reminders, routines).

Writes are atomic (temporary file + replace). A file that exists but cannot be read is never silently replaced by an
empty one: it is copied aside first (``name.unreadable-<time>``), so nothing the owner saved is lost.
Read-modify-write sequences hold one lock per file, shared by every caller in the process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import threading
import time

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def lock_for(path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(str(path)))
    with _guard:
        return _locks.setdefault(key, threading.RLock())


def write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock_for(path):
        if path.exists():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                shutil.copy2(path, path.with_name(f"{path.name}.unreadable-{int(time.time())}"))
            except OSError:
                pass
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
