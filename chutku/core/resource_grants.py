"""Durable, runtime-owned resource grants for filesystem capabilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
import os
from pathlib import Path
import secrets
import sqlite3


class ResourceAccess(StrEnum):
    OBSERVE = "observe"
    MODIFY = "modify"


@dataclass(frozen=True)
class ResourceGrant:
    grant_id: str
    root: Path
    access: frozenset[str]
    source: str
    revocable: bool
    active: bool
    version: str

    def snapshot(self) -> dict:
        return {"grant_id": self.grant_id, "root": str(self.root),
                "access": sorted(self.access), "version": self.version}

    def public(self) -> dict:
        return self.snapshot() | {"source": self.source, "revocable": self.revocable,
                                  "active": self.active}


def _validated_root(raw: Path | str) -> Path:
    if not isinstance(raw, (str, Path)):
        raise ValueError("Grant root must be a filesystem path.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("Grant root must be an absolute path selected by the user.")
    path = path.resolve()
    if path.drive.startswith("\\\\") or not path.drive:
        raise ValueError("Grant root must be on a local drive.")
    if not path.exists() or not path.is_dir():
        raise ValueError("Grant root must be an existing directory.")
    if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("A grant root cannot be a symbolic link or reparse point.")
    return path


def _validated_access(values) -> frozenset[str]:
    if not isinstance(values, (set, frozenset, list, tuple)):
        raise ValueError("Grant access must be an explicit list.")
    access = frozenset(values)
    allowed = {item.value for item in ResourceAccess}
    if not access or not all(isinstance(item, str) for item in access) or not access <= allowed:
        raise ValueError("Grant access must contain only observe and/or modify.")
    if ResourceAccess.MODIFY in access:
        access = access | {ResourceAccess.OBSERVE}
    return frozenset(str(item) for item in access)


class ResourceGrantStore:
    """At most 20 explicit roots. Revocation is checked again at execution time."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS resource_grants (
            grant_id TEXT PRIMARY KEY, canonical_root TEXT NOT NULL UNIQUE,
            display_root TEXT NOT NULL, access_json TEXT NOT NULL,
            source TEXT NOT NULL, revocable INTEGER NOT NULL, active INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.connection.commit()

    @staticmethod
    def _key(root: Path) -> str:
        return os.path.normcase(str(root))

    @staticmethod
    def _row(row) -> ResourceGrant | None:
        if row is None:
            return None
        return ResourceGrant(row[0], Path(row[2]), frozenset(json.loads(row[3])), row[4],
                             bool(row[5]), bool(row[6]), row[8])

    def ensure_sandbox(self, root: Path) -> ResourceGrant:
        root = _validated_root(root)
        now = datetime.now(UTC).isoformat()
        access = json.dumps([ResourceAccess.MODIFY, ResourceAccess.OBSERVE])
        with self.connection:
            existing = self.connection.execute(
                "SELECT grant_id,canonical_root,display_root,access_json,source,revocable,active,created_at,updated_at FROM resource_grants WHERE grant_id='sandbox'"
            ).fetchone()
            if existing and existing[1] != self._key(root):
                raise ValueError("The runtime sandbox grant cannot be retargeted.")
            if existing is None:
                self.connection.execute("""INSERT INTO resource_grants VALUES
                    ('sandbox', ?, ?, ?, 'runtime', 0, 1, ?, ?)""",
                    (self._key(root), str(root), access, now, now))
        return self.get("sandbox")

    def grant(self, root: Path | str, access) -> ResourceGrant:
        root = _validated_root(root)
        access = _validated_access(access)
        if ResourceAccess.MODIFY in access and root != Path(root.anchor):
            from chutku.core.paths import protection_reason
            reason = protection_reason(root)
            if reason is not None:
                raise ValueError("Modify access cannot be granted here: " + reason)
        if len(self.list(active_only=True)) >= 20:
            raise ValueError("At most 20 resource grants may be active.")
        now = datetime.now(UTC).isoformat()
        existing = self.connection.execute("SELECT grant_id,source FROM resource_grants WHERE canonical_root=?",
                                           (self._key(root),)).fetchone()
        if existing and existing[1] == "runtime":
            raise ValueError("The runtime sandbox grant is already active and cannot be replaced.")
        grant_id = existing[0] if existing else "grant-" + secrets.token_hex(8)
        with self.connection:
            self.connection.execute("""INSERT INTO resource_grants VALUES (?, ?, ?, ?, 'user', 1, 1, ?, ?)
                ON CONFLICT(canonical_root) DO UPDATE SET access_json=excluded.access_json,
                active=1, updated_at=excluded.updated_at""",
                (grant_id, self._key(root), str(root), json.dumps(sorted(access)), now, now))
        return self.get(grant_id)

    def get(self, grant_id: str, *, active=True) -> ResourceGrant:
        if not isinstance(grant_id, str) or len(grant_id) > 80:
            raise ValueError("Invalid resource grant ID.")
        row = self.connection.execute(
            "SELECT grant_id,canonical_root,display_root,access_json,source,revocable,active,created_at,updated_at FROM resource_grants WHERE grant_id=?",
            (grant_id,)).fetchone()
        grant = self._row(row)
        if grant is None or active and not grant.active:
            raise ValueError("Resource grant does not exist or has been revoked.")
        # Refuse silently moved/replaced roots on every use.
        if _validated_root(grant.root) != grant.root:
            raise ValueError("Resource grant root changed and must be granted again.")
        return grant

    def list(self, *, active_only=False) -> list[ResourceGrant]:
        suffix = " WHERE active=1" if active_only else ""
        rows = self.connection.execute(
            "SELECT grant_id,canonical_root,display_root,access_json,source,revocable,active,created_at,updated_at FROM resource_grants" + suffix + " ORDER BY source,display_root"
        ).fetchall()
        return [self._row(row) for row in rows]

    def revoke(self, grant_id: str) -> ResourceGrant:
        grant = self.get(grant_id)
        if not grant.revocable:
            raise ValueError("The runtime sandbox grant cannot be revoked.")
        now = datetime.now(UTC).isoformat()
        with self.connection:
            self.connection.execute("UPDATE resource_grants SET active=0,updated_at=? WHERE grant_id=? AND active=1",
                                    (now, grant_id))
        return self.get(grant_id, active=False)

    def close(self):
        self.connection.close()
