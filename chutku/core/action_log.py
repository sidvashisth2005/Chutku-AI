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


ROTATE_BYTES = 5_000_000


def _reverse_lines(path: Path, block: int = 65536):
    """The non-empty lines of a file, last first, reading backwards in blocks (never the whole file at once)."""
    with path.open("rb") as stream:
        stream.seek(0, 2)
        position, rest = stream.tell(), b""
        while position > 0:
            step = min(block, position)
            position -= step
            stream.seek(position)
            chunk = stream.read(step) + rest
            lines = chunk.split(b"\n")
            rest = lines.pop(0)
            for line in reversed(lines):
                if line.strip():
                    yield line.decode("utf-8")
        if rest.strip():
            yield rest.decode("utf-8")


class ActionLog:
    """Rotated at 5 MB into ``actions.log.0001.jsonl``, ``…0002…``; the chain (seq and prev) continues across files."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)  # created on first append, so read-only checks never create data

    def _rotated(self) -> list[Path]:
        stem = self.path.name[:-len(".jsonl")] if self.path.name.endswith(".jsonl") else self.path.name
        return sorted(self.path.parent.glob(stem + ".[0-9][0-9][0-9][0-9].jsonl"))

    def _files(self) -> list[Path]:
        """Oldest first: rotated files, then the current one."""
        return self._rotated() + ([self.path] if self.path.exists() else [])

    def _entries(self) -> list[dict[str, Any]]:
        entries = []
        for file in self._files():
            with file.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        entries.append(json.loads(line))
        return entries

    def _newest_first(self):
        for file in reversed(self._files()):
            for line in _reverse_lines(file):
                yield json.loads(line)

    def _last(self) -> dict[str, Any] | None:
        for file in reversed(self._files()):
            if file.stat().st_size == 0:
                continue
            with file.open("rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - 65536))
                tail = stream.read().decode("utf-8", errors="replace").strip().splitlines()
            try:
                return json.loads(tail[-1]) if tail else None
            except json.JSONDecodeError:
                return None
        return None

    def _broken_tail(self) -> bool:
        files = [f for f in self._files() if f.stat().st_size]
        return bool(files) and self._last() is None

    def ready(self) -> None:
        """Raise unless the next entry can be appended (checked before acting: an action is never unlogged)."""
        if self._broken_tail():
            raise ValueError("The action log ends with an unreadable line; run doctor before acting.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8"):
            pass

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        last = self._last()
        if last is None and self._broken_tail():
            raise ValueError("The action log ends with an unreadable line; run doctor before acting.")
        entry = {**record, "seq": (last["seq"] + 1) if last else 1,
                 "time": datetime.now(UTC).isoformat(timespec="seconds"),
                 "prev": last["hash"] if last else GENESIS}
        entry["hash"] = _digest(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > ROTATE_BYTES:
            stem = self.path.name[:-len(".jsonl")]
            self.path.replace(self.path.with_name(f"{stem}.{len(self._rotated()) + 1:04d}.jsonl"))
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
        """Newest first, read from the end of the log. ``since`` is an ISO date/time prefix bound."""
        found = []
        for entry in self._newest_first():
            if since is not None and entry.get("time", "") < since:
                break
            found.append(entry)
            if len(found) >= limit:
                break
        return found

    def get(self, seq: int) -> dict[str, Any] | None:
        return next((entry for entry in self._newest_first() if entry.get("seq") == seq), None)
