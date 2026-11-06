"""Backup and restore of Chutku's memory (H25, from Hermes `backup` / `import`).

`chutku.cli backup` (or "backup bana lo") writes ChutkuBackups/chutku-YYYYMMDD-HHMMSS.zip with data/ and a manifest.json
holding each file's SHA-256. SQLite databases are copied with SQLite's own backup API, so a copy taken while Chutku
runs is consistent. Not included: rebuildable indexes and caches, locks, logs, voice clips and the voiceprint (personal
audio; opt in with --voice). Keys and tokens live in Windows Credential Manager, never in data/, so they are never in a
backup; after a restore on another PC they are entered again. The newest 4 backups are kept; older ones go to the
Recycle Bin.

`chutku.cli backup restore <zip>` only runs while Chutku is stopped (its databases are open otherwise). It checks every
file against the manifest first (any mismatch: nothing changes), then backs up the current data, then replaces it.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

KEEP = 4
SKIP_NAMES = {"embeddings.sqlite", "history.db", "drive-index.sqlite", "execution.lock", "guard.lock", "guard.running",
              "dashboard-session.json", "voiceprint.npy"}
SKIP_DIRS = {"logs", "wake", "cache", "__pycache__", "evolve-work"}
SKIP_SUFFIXES = (".db-wal", ".db-shm", ".lock", ".tmp")
SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
MAX_FILE = 50 * 1024 * 1024


def backup_folder():
    from chutku.core.paths import user_folder
    return Path(user_folder("ChutkuBackups"))


def _included(relative: Path, size: int, voice: bool):
    if relative.name in SKIP_NAMES and not (voice and relative.name == "voiceprint.npy"):
        return False
    if any(part in SKIP_DIRS and not (voice and part == "wake") for part in relative.parts[:-1]):
        return False
    return not relative.name.endswith(SKIP_SUFFIXES) and size <= MAX_FILE


def _sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def create(base, *, folder=None, voice=False, now=None):
    """Write one backup zip; returns {"path", "files", "bytes", "removed"}."""
    data = Path(base) / "data"
    folder = Path(folder or backup_folder())
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = folder / f"chutku-{stamp}.zip"
    extra = 1
    while target.exists():   # two backups in one second (a restore's safety copy right after a backup)
        extra += 1
        target = folder / f"chutku-{stamp}-{extra}.zip"
    manifest = {"made": stamp, "files": {}}
    with tempfile.TemporaryDirectory() as temp, zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in data.rglob("*") if p.is_file()):
            relative = path.relative_to(data)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if not _included(relative, size, voice):
                continue
            source = path
            if path.suffix in SQLITE_SUFFIXES:
                source = Path(temp) / (relative.as_posix().replace("/", "__"))
                try:
                    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as live,                             closing(sqlite3.connect(source)) as copy:
                        live.backup(copy)   # consistent even while Chutku writes
                except sqlite3.Error:
                    source = path
            try:
                manifest["files"][relative.as_posix()] = _sha256(source)
                archive.write(source, "data/" + relative.as_posix())
            except OSError:
                manifest["files"].pop(relative.as_posix(), None)   # a file that vanished meanwhile
        archive.writestr("manifest.json", json.dumps(manifest, indent=1))
    removed = _prune(folder)
    return {"path": str(target), "files": len(manifest["files"]), "bytes": target.stat().st_size, "removed": removed}


def _prune(folder):
    """Keep the newest KEEP backups; older ones go to the Recycle Bin (never deleted for good)."""
    from chutku.core.recycle_bin import RecycleError, send
    removed = []
    for old in sorted(folder.glob("chutku-*.zip"))[:-KEEP]:
        try:
            send(old)
            removed.append(old.name)
        except (RecycleError, OSError):
            pass   # kept: an extra backup is harmless
    return removed


def listing(folder=None):
    folder = Path(folder or backup_folder())
    return [{"name": p.name, "bytes": p.stat().st_size} for p in sorted(folder.glob("chutku-*.zip"), reverse=True)]


def verify(zip_path):
    """{relative path: bytes} for a backup whose every file matches its manifest; ValueError otherwise."""
    with zipfile.ZipFile(zip_path) as archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, ValueError):
            raise ValueError("This is not a Chutku backup (no manifest).") from None
        files = {}
        for relative, digest in manifest.get("files", {}).items():
            if relative.startswith(("/", "\\")) or ".." in Path(relative).parts or ":" in relative:
                raise ValueError(f"Unsafe path in the backup: {relative}")
            try:
                content = archive.read("data/" + relative)
            except KeyError:
                raise ValueError(f"{relative} is missing from the backup.") from None
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"{relative} does not match the manifest (changed or damaged); nothing was restored.")
            files[relative] = content
    return files


def running(base):
    return (Path(base) / "data" / "guard.running").exists()


def restore(base, zip_path, *, folder=None):
    """Replace data/ files with the backup's (Chutku must be stopped). Returns {"restored", "safety_backup"}."""
    if running(base):
        raise RuntimeError("Stop Chutku first (Stop-Chutku.cmd); its databases are open while it runs.")
    files = verify(zip_path)                                    # any mismatch: nothing changes
    safety = create(base, folder=folder)                         # the current state, in case the restore was wrong
    data = Path(base) / "data"
    for relative, content in files.items():
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        for stale in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
            stale.unlink(missing_ok=True)                        # old WAL pages would be replayed onto the copy
        temporary = target.with_name(target.name + ".restoring")
        temporary.write_bytes(content)
        temporary.replace(target)
    return {"restored": len(files), "safety_backup": safety["path"]}



def register_backup_tools(registry, base):
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification
    from chutku.tools.everyday import EMPTY_ARGUMENT_SCHEMA, _validate_none

    def making(_arguments, _context):
        try:
            made = create(base)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            return ToolResult({"error": f"The backup could not be written: {error}"[:300]}, Verification.FAIL)
        ok = Path(made["path"]).is_file() and made["files"] > 0
        return ToolResult(made, Verification.PASS if ok else Verification.FAIL)

    def listing_tool(_arguments, _context):
        return ToolResult({"folder": str(backup_folder()), "backups": listing()}, Verification.PASS)

    registry.register(Tool("backup.create", "Back up Chutku's memory (mind, notes, conversations, skills, settings) to a "
        "zip in the ChutkuBackups folder, with a hash for every file; keeps the newest 4.", Risk.REVERSIBLE, making,
        _validate_none, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="creates_new_file_only",
        success_predicate="backup_zip_written"))
    registry.register(Tool("backup.list", "List Chutku's memory backups (newest first).", Risk.OBSERVATION,
        listing_tool, _validate_none, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="backups_listed"))
