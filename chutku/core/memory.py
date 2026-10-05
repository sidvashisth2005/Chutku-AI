from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3


class MemoryStore:
    """Explicit user notes. Stored text is data, never executable policy."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS memories (
            key TEXT PRIMARY KEY, value TEXT NOT NULL,
            provenance TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.connection.commit()

    @staticmethod
    def validate_key(key: str) -> None:
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", key):
            raise ValueError("Memory key must start with a letter and use up to 64 letters, digits, underscores or hyphens.")

    def save(self, key: str, value: str) -> dict:
        self.validate_key(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError("Memory value must contain 1 to 2000 characters.")
        key = key.casefold()
        exists = self.connection.execute("SELECT 1 FROM memories WHERE key=?", (key,)).fetchone()
        if not exists and self.connection.execute("SELECT count(*) FROM memories").fetchone()[0] >= 500:
            raise ValueError("Memory is full (500 notes). Forget an old note first.")
        with self.connection:
            self.connection.execute("""INSERT INTO memories VALUES (?, ?, 'user_stated', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, datetime.now(UTC).isoformat()))
        return self.get(key)

    def get(self, key: str) -> dict | None:
        row = self.connection.execute("SELECT key,value,provenance,updated_at FROM memories WHERE key=?", (key.casefold(),)).fetchone()
        return dict(zip(("key", "value", "provenance", "updated_at"), row)) if row else None

    def search(self, query: str = "") -> list[dict]:
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("Memory query must be at most 200 characters.")
        terms = query.casefold().split()
        rows = self.connection.execute("SELECT key,value,provenance,updated_at FROM memories ORDER BY key").fetchall()
        return [dict(zip(("key", "value", "provenance", "updated_at"), row)) for row in rows
                if all(term in (row[0] + " " + row[1]).casefold() for term in terms)]

    def forget(self, key: str) -> bool:
        self.validate_key(key)
        with self.connection:
            cursor = self.connection.execute("DELETE FROM memories WHERE key=?", (key.casefold(),))
        return cursor.rowcount == 1 and self.get(key) is None

    def close(self) -> None:
        self.connection.close()
