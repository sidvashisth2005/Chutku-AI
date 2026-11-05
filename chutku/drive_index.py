"""Deep drive index (Phase 6 X5, 2026-11-05): the names of the owner's files on every fixed drive, so "D drive mein
resume.pdf kahan hai" answers in milliseconds instead of a bounded 12 s folder walk.

Only names, folders, sizes and modified times are stored, in data/drive-index.sqlite (local, never uploaded).
Skipped: system areas and Chutku's own folders (core.paths.protected_zones), hidden and code/library folders
(files_plus._NOISE_DIRS), and links. Night Shift refreshes it; files.index rebuilds it on request.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sqlite3
import string
import time

from chutku.core.paths import protected_zones

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_ENTRIES = 2_000_000          # shortcut: one build stops here, about 300 MB of names; raise if a PC has more files
MAX_SECONDS = 15 * 60


def _db(base=None):
    path = Path(base or PROJECT_ROOT) / "data" / "drive-index.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS files USING fts5(name, folder UNINDEXED, "
                       "size UNINDEXED, modified UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    connection.execute("CREATE TABLE IF NOT EXISTS info (key TEXT PRIMARY KEY, value TEXT)")
    return connection


def fixed_drives():
    """Fixed local drives only (DRIVE_FIXED = 3): no USB sticks, network shares or DVDs."""
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{letter}:\\" for i, letter in enumerate(string.ascii_uppercase)
            if mask >> i & 1 and ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") == 3]


def _skipped(path, zones):
    from chutku.tools.files_plus import _NOISE_DIRS
    name = path.name
    lowered = os.path.normcase(os.path.abspath(path))
    return (name.startswith((".", "$")) or name.casefold() in _NOISE_DIRS or name.casefold() == "system volume information"
            or any(lowered == zone or lowered.startswith(zone + os.sep) for zone in zones))


def _walk(roots, zones, deadline):
    from chutku.tools.files_plus import _is_link
    stack = [Path(r) for r in roots]
    while stack and time.monotonic() < deadline:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not _skipped(path, zones) and not _is_link(path):
                        stack.append(path)
                elif entry.is_file(follow_symlinks=False) and not entry.name.startswith("~$"):
                    info = entry.stat(follow_symlinks=False)
                    yield entry.name, str(folder), info.st_size, int(info.st_mtime)
            except OSError:
                continue


def build(base=None, roots=None, *, max_entries=MAX_ENTRIES, max_seconds=MAX_SECONDS):
    """Rebuild the index; returns {"files", "seconds", "drives", "complete"}."""
    started = time.monotonic()
    roots = list(roots) if roots is not None else fixed_drives()
    zones = [os.path.normcase(z) for z in protected_zones()]
    rows, complete = [], True
    for row in _walk(roots, zones, started + max_seconds):
        rows.append(row)
        if len(rows) >= max_entries:
            complete = False
            break
    if time.monotonic() >= started + max_seconds:
        complete = False
    with _db(base) as connection:
        connection.execute("DELETE FROM files")
        connection.executemany("INSERT INTO files VALUES (?, ?, ?, ?)", rows)
        for key, value in (("built", str(int(time.time()))), ("drives", ",".join(roots)),
                           ("complete", "1" if complete else "0"), ("count", str(len(rows)))):
            connection.execute("INSERT OR REPLACE INTO info VALUES (?, ?)", (key, value))
    connection.close()
    return {"files": len(rows), "seconds": round(time.monotonic() - started, 1), "drives": roots, "complete": complete}


def status(base=None):
    path = Path(base or PROJECT_ROOT) / "data" / "drive-index.sqlite"
    if not path.is_file():
        return {"built": None}
    with _db(base) as connection:
        info = dict(connection.execute("SELECT key, value FROM info"))
    connection.close()
    built = int(info["built"]) if info.get("built") else None
    return {"built": time.strftime("%Y-%m-%d %H:%M", time.localtime(built)) if built else None,
            "age_hours": round((time.time() - built) / 3600, 1) if built else None,
            "files": int(info.get("count", 0)), "drives": info.get("drives", ""), "complete": info.get("complete") == "1"}


def search(query, base=None, *, drive=None, limit=10):
    """Files whose name has every word of the query (prefix match), newest first."""
    words = [w for w in "".join(c if c.isalnum() else " " for c in query.casefold()).split()
             if w not in {"my", "the", "a", "file", "files", "document", "documents"}]
    if not words:
        return []
    match = " ".join(f'"{w}"*' for w in words)
    sql = "SELECT name, folder, size, modified FROM files WHERE files MATCH ?"
    args = [f"name : ({match})"]
    if drive:
        sql += " AND folder LIKE ?"
        args.append(drive.rstrip(":\\/").upper() + ":%")
    sql += " ORDER BY CAST(modified AS INTEGER) DESC LIMIT ?"
    args.append(int(limit))
    with _db(base) as connection:
        rows = connection.execute(sql, args).fetchall()
    connection.close()
    return [{"name": name, "path": str(Path(folder) / name), "folder": Path(folder).name or folder,
             "size_mb": round(int(size) / 1e6, 2), "modified": time.strftime("%Y-%m-%d %H:%M",
                                                                             time.localtime(int(modified)))}
            for name, folder, size, modified in rows]
