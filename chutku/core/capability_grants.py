"""Durable, exact capability grants for non-filesystem PC authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import sqlite3


CAPABILITIES = frozenset({
    "screen.observe", "desktop.input", "clipboard.read", "clipboard.write",
    "process.observe", "process.launch", "process.terminate", "apps.launch", "internet.read", "reminders.manage",
    "browser.navigate", "browser.input", "browser.external",
    "cloud.gemini", "settings.observe", "settings.modify", "power.control",
    "audio.observe", "audio.modify", "network.observe", "network.modify",
    "email.send",   # X8: sending email from the owner's account; never granted by default
})


def validate_capability(value: str) -> str:
    if not isinstance(value, str) or value not in CAPABILITIES:
        raise ValueError("Unknown capability; wildcard or arbitrary authority is not allowed.")
    return value


@dataclass(frozen=True)
class CapabilityGrant:
    capability: str
    active: bool
    version: str

    def snapshot(self) -> dict:
        return {"capability": self.capability, "version": self.version}

    def public(self) -> dict:
        return self.snapshot() | {"active": self.active}


class CapabilityGrantStore:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS capability_grants (
            capability TEXT PRIMARY KEY, active INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.connection.commit()

    @staticmethod
    def _row(row):
        if row is None:
            return None
        return CapabilityGrant(row[0], bool(row[1]), row[3])

    def grant(self, capability: str) -> CapabilityGrant:
        capability = validate_capability(capability)
        now = datetime.now(UTC).isoformat()
        with self.connection:
            self.connection.execute("""INSERT INTO capability_grants VALUES (?, 1, ?, ?)
                ON CONFLICT(capability) DO UPDATE SET active=1,updated_at=excluded.updated_at""",
                (capability, now, now))
        return self.get(capability)

    def get(self, capability: str, *, active=True) -> CapabilityGrant:
        capability = validate_capability(capability)
        grant = self._row(self.connection.execute(
            "SELECT capability,active,created_at,updated_at FROM capability_grants WHERE capability=?",
            (capability,)).fetchone())
        if grant is None or active and not grant.active:
            raise ValueError("Capability has not been granted or has been revoked.")
        return grant

    def list(self):
        rows = self.connection.execute(
            "SELECT capability,active,created_at,updated_at FROM capability_grants ORDER BY capability").fetchall()
        return [self._row(row) for row in rows]

    def revoke(self, capability: str) -> CapabilityGrant:
        grant = self.get(capability)
        now = datetime.now(UTC).isoformat()
        with self.connection:
            self.connection.execute("UPDATE capability_grants SET active=0,updated_at=? WHERE capability=?",
                                    (now, grant.capability))
        return self.get(capability, active=False)

    def close(self):
        self.connection.close()
