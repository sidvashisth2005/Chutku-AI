from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OperationJournal:
    """Durable before/after journal for reversible R2+ filesystem operations."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS operations (
                operation_id INTEGER PRIMARY KEY,
                task_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                target TEXT NOT NULL,
                before_json TEXT NOT NULL,
                after_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )"""
        )
        self._connection.commit()

    def begin(self, task_id: str, operation: str, target: Path, before: dict[str, Any]) -> int:
        cursor = self._connection.execute(
            """INSERT INTO operations (task_id, operation, target, before_json, status, created_at)
            VALUES (?, ?, ?, ?, 'STARTED', ?)""",
            (task_id, operation, str(target), json.dumps(before, sort_keys=True), datetime.now(UTC).isoformat()),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def complete(self, operation_id: int, after: dict[str, Any]) -> None:
        self._connection.execute(
            """UPDATE operations SET after_json = ?, status = 'COMPLETED', completed_at = ?
            WHERE operation_id = ? AND status = 'STARTED'""",
            (json.dumps(after, sort_keys=True), datetime.now(UTC).isoformat(), operation_id),
        )
        self._connection.commit()

    def latest_completed(self, operation: str, root: Path | None = None) -> dict[str, Any] | None:
        rows = self._connection.execute(
            """SELECT operation_id, task_id, target, before_json, after_json FROM operations
            WHERE operation = ? AND status = 'COMPLETED' ORDER BY operation_id DESC""",
            (operation,),
        ).fetchall()
        for row in rows:
            target = Path(row[2]).resolve()
            if root is not None and target != root and root not in target.parents:
                continue
            return {"operation_id": row[0], "task_id": row[1], "target": target,
                    "before": json.loads(row[3]), "after": json.loads(row[4])}
        return None

    def records(self, operation: str) -> list[dict[str, Any]]:
        """Every finished record of one operation, oldest first (status included)."""
        rows = self._connection.execute(
            """SELECT operation_id, task_id, target, before_json, after_json, status FROM operations
            WHERE operation = ? AND after_json IS NOT NULL ORDER BY operation_id""",
            (operation,),
        ).fetchall()
        return [{"operation_id": row[0], "task_id": row[1], "target": Path(row[2]), "before": json.loads(row[3]),
                 "after": json.loads(row[4]), "status": row[5]} for row in rows]

    def incomplete(self, operation: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """SELECT operation_id, task_id, target, before_json FROM operations
            WHERE operation = ? AND status = 'STARTED' ORDER BY operation_id""",
            (operation,),
        ).fetchall()
        return [
            {"operation_id": row[0], "task_id": row[1], "target": Path(row[2]), "before": json.loads(row[3])}
            for row in rows
        ]

    def mark_undone(self, operation_id: int) -> None:
        self._connection.execute(
            "UPDATE operations SET status = 'UNDONE', completed_at = ? WHERE operation_id = ? AND status = 'COMPLETED'",
            (datetime.now(UTC).isoformat(), operation_id),
        )
        self._connection.commit()

    def mark_recovered(self, operation_id: int) -> None:
        self._connection.execute(
            "UPDATE operations SET status = 'RECOVERED', completed_at = ? WHERE operation_id = ? AND status = 'STARTED'",
            (datetime.now(UTC).isoformat(), operation_id),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
