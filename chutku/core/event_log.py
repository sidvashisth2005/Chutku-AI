from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                task_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    def append(self, task_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO events (task_id, timestamp, event_type, payload_json) VALUES (?, ?, ?, ?)",
            (task_id, datetime.now(UTC).isoformat(), event_type, json.dumps(payload, sort_keys=True)),
        )
        self._connection.commit()

    def events_for(self, task_id: str) -> list[tuple[str, dict[str, Any]]]:
        rows = self._connection.execute(
            "SELECT event_type, payload_json FROM events WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        return [(event_type, json.loads(payload)) for event_type, payload in rows]

    def recent_tasks(self, limit: int = 10) -> list[dict[str, str]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        received = self._connection.execute(
            """SELECT task_id, timestamp, payload_json FROM events
            WHERE event_type = 'task_received' ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        tasks: list[dict[str, str]] = []
        for task_id, timestamp, payload_json in received:
            command = json.loads(payload_json)["tool"]
            state_row = self._connection.execute(
                """SELECT payload_json FROM events WHERE task_id = ? AND event_type = 'task_state'
                ORDER BY id DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
            state = json.loads(state_row[0])["to"] if state_row else "RECEIVED"
            tasks.append({"task_id": task_id, "timestamp": timestamp, "tool": command, "state": state})
        return tasks

    def safe_trace(self, task_id: str) -> list[dict[str, Any]]:
        """Return only durable, already-redacted audit data for one task."""
        allowed = {"task_received", "validated_command", "task_state", "authorization", "tool_result", "runtime_error", "workflow_step", "workflow_result", "verification_result"}
        rows = self._connection.execute(
            "SELECT timestamp, event_type, payload_json FROM events WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        return [
            {"timestamp": timestamp, "event_type": event_type, "details": json.loads(payload_json)}
            for timestamp, event_type, payload_json in rows
            if event_type in allowed
        ]

    def close(self) -> None:
        self._connection.close()

    def mark_interrupted(self) -> int:
        """Called with the execution lock held, only after the owned core stopped."""
        rows = self._connection.execute("""SELECT task_id FROM events
            WHERE event_type = 'task_received' GROUP BY task_id""").fetchall()
        count = 0
        for (task_id,) in rows:
            states = [payload["to"] for event, payload in self.events_for(task_id) if event == "task_state"]
            previous = states[-1] if states else "RECEIVED"
            if previous in {"COMPLETED", "FAILED", "DENIED", "WAITING_CONFIRMATION", "CLARIFYING"}:
                continue
            self.append(task_id, "runtime_error", {"type": "GuardInterrupted",
                        "message": "Execution stopped. Effects may remain; inspect the operation journal before retrying."})
            self.append(task_id, "task_state", {"from": previous, "to": "FAILED"})
            count += 1
        return count
