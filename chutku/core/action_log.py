"""Append-only, hash-chained log of everything Chutku did or was refused.

One JSON object per line in ``data/actions.log.jsonl``. Each entry carries ``seq``, ``time``,
``prev`` (the previous entry's hash) and ``hash`` = SHA-256 of the entry without ``hash``.
Editing, removing or reordering a line breaks the chain, which ``verify`` and ``doctor`` report.
The chain detects tampering; it does not prevent someone with file access from rewriting it.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _digest(entry: dict[str, Any]) -> str:
    body = {key: value for key, value in entry.items() if key != "hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ActionLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)  # created on first append, so read-only checks never create data

    def _entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def _last(self) -> dict[str, Any] | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        with self.path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 65536))
            tail = stream.read().decode("utf-8", errors="replace").strip().splitlines()
        try:
            return json.loads(tail[-1]) if tail else None
        except json.JSONDecodeError:
            return None

    def ready(self) -> None:
        """Raise unless the next entry can be appended (checked before acting: an action is never unlogged)."""
        last = self._last()
        if last is None and self.path.exists() and self.path.stat().st_size:
            raise ValueError("The action log ends with an unreadable line; run doctor before acting.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8"):
            pass

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        last = self._last()
        if last is None and self.path.exists() and self.path.stat().st_size:
            raise ValueError("The action log ends with an unreadable line; run doctor before acting.")
        entry = {**record, "seq": (last["seq"] + 1) if last else 1,
                 "time": datetime.now(UTC).isoformat(timespec="seconds"),
                 "prev": last["hash"] if last else GENESIS}
        entry["hash"] = _digest(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            stream.flush()
        return entry

    def verify(self) -> dict[str, Any]:
        previous, count = GENESIS, 0
        try:
            entries = self._entries()
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {"ok": False, "entries": count, "broken_at": None}
        for expected, entry in enumerate(entries, start=1):
            if (not isinstance(entry, dict) or entry.get("seq") != expected or entry.get("prev") != previous
                    or entry.get("hash") != _digest(entry)):
                return {"ok": False, "entries": len(entries), "broken_at": expected}
            previous, count = entry["hash"], count + 1
        return {"ok": True, "entries": count, "broken_at": None}

    def recent(self, limit: int = 20, since: str | None = None) -> list[dict[str, Any]]:
        """Newest first. ``since`` is an ISO date/time prefix bound (e.g. today's date)."""
        entries = [entry for entry in self._entries() if since is None or entry.get("time", "") >= since]
        return list(reversed(entries))[:limit]

    def get(self, seq: int) -> dict[str, Any] | None:
        return next((entry for entry in self._entries() if entry.get("seq") == seq), None)
