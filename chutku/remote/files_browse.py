"""Browse the laptop's files from the phone (owner 2026-11-07: "I won't remember paths; let me browse my PC's files,
with filters like photo, PDF"). Read-only: places, one folder's listing, recent files and search, each filtered by
kind. The rules of /api/files/get apply: protected system areas and secret files are never listed; hidden and
system entries are skipped. Search and recent use Chutku's drive index (chutku/drive_index.py), which knows every
fixed drive and answers in ~20 ms.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import time

KINDS = {
    "photo": {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "tif", "tiff"},
    "video": {"mp4", "mkv", "avi", "mov", "webm", "wmv", "m4v", "3gp"},
    "pdf": {"pdf"},
    "doc": {"doc", "docx", "txt", "rtf", "odt", "xls", "xlsx", "csv", "ppt", "pptx", "md", "odp", "ods"},
    "audio": {"mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "wma"},
    "archive": {"zip", "rar", "7z", "tar", "gz"},
}
PLACES = ("Desktop", "Downloads", "Documents", "Pictures", "Videos", "Music")
# Windows known-folder ids: Pictures or Desktop may live in OneDrive or on another drive, not under the home folder
_KNOWN = {"Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
          "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7", "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
          "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC", "Music": "4BD8D571-6D19-48D3-BE97-422220080E43"}
MAX_LIST = 400
_HIDDEN = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)


def kind_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    return next((kind for kind, exts in KINDS.items() if ext in exts), "other")


def _wanted(name: str, kind: str) -> bool:
    return kind in ("", "all") or kind_of(name) == kind


def _refused(path: Path) -> str | None:
    """Why this folder or file is never shown (the same zones and secret rules as a file fetch)."""
    from chutku.core.paths import protected_zones
    from chutku.references import secret_reason
    lowered = str(path).casefold()
    if any(lowered == zone or lowered.startswith(zone.rstrip("\\") + "\\") for zone in protected_zones()):
        return "That is a protected system area."
    return secret_reason(str(path))


def _entry(path: Path, info) -> dict:
    return {"name": path.name, "path": str(path), "size": info.st_size, "kind": kind_of(path.name),
            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime))}


def places() -> dict:
    """The owner's usual folders that exist, and the fixed drives."""
    from chutku.core.paths import _known_folder
    home = Path.home()
    found = []
    for name in PLACES:
        folder = Path(_known_folder(_KNOWN[name]) or home / name)
        if folder.is_dir():
            found.append({"name": name, "path": str(folder)})
    try:
        from chutku.drive_index import fixed_drives
        drives = [{"name": drive.rstrip("\\"), "path": drive} for drive in fixed_drives()]
    except (OSError, AttributeError):
        drives = []
    return {"places": found, "drives": drives}


def listing(raw_path: str, kind: str = "all") -> dict:
    if kind not in ("all", *KINDS):
        raise ValueError("Unknown kind.")
    path = Path(str(raw_path or "")).expanduser()
    try:
        folder = path.resolve(strict=True)
    except OSError:
        raise ValueError("No such folder.") from None
    if not folder.is_dir():
        raise ValueError("That is not a folder.")
    reason = _refused(folder)
    if reason:
        raise PermissionError(reason)
    folders, files = [], []
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.startswith((".", "$")) or entry.is_symlink():
                continue
            try:
                info = entry.stat()
            except OSError:
                continue
            if getattr(info, "st_file_attributes", 0) & _HIDDEN:
                continue
            child = Path(entry.path)
            if _refused(child):
                continue
            if entry.is_dir(follow_symlinks=False):
                folders.append({"name": entry.name, "path": entry.path})
            elif _wanted(entry.name, kind):
                files.append(_entry(child, info))
    folders.sort(key=lambda f: f["name"].casefold())
    files.sort(key=lambda f: f["modified"], reverse=True)
    parent = str(folder.parent) if folder.parent != folder else ""
    return {"path": str(folder), "parent": parent, "folders": folders[:MAX_LIST], "files": files[:MAX_LIST],
            "truncated": len(folders) > MAX_LIST or len(files) > MAX_LIST}


def _checked(paths, kind, limit):
    out = []
    for raw in paths:
        path = Path(raw)
        if path.name.startswith((".", "~$")) or kind_of(path.name) == "other" and kind == "all" \
                or not _wanted(path.name, kind) or _refused(path):
            continue
        try:
            info = path.stat()
        except OSError:
            continue   # the index is older than the disk: gone since
        out.append(_entry(path, info))
        if len(out) >= limit:
            break
    return out


def search(query: str, kind: str = "all", limit: int = 60) -> dict:
    if kind not in ("all", *KINDS):
        raise ValueError("Unknown kind.")
    query = str(query or "").strip()
    if not 1 <= len(query) <= 100:
        raise ValueError("Type a name to search for.")
    from chutku import drive_index
    rows = drive_index.search(query, limit=400)
    return {"query": query, "files": _checked([row["path"] for row in rows], kind, limit)}


def recent(kind: str = "all", limit: int = 60) -> dict:
    """The newest files of this kind anywhere on the fixed drives (from the drive index), else from the usual folders."""
    if kind not in ("all", *KINDS):
        raise ValueError("Unknown kind.")
    from chutku import drive_index
    paths = []
    try:
        with drive_index._db() as connection:
            # "all" means the owner's kinds of files, not logs and lock files (PC check 2026-11-07: .tick.lock came first)
            exts = sorted(set().union(*KINDS.values())) if kind == "all" else sorted(KINDS[kind])
            match = " OR ".join(f'"{ext}"' for ext in exts)
            rows = connection.execute("SELECT name, folder FROM files WHERE files MATCH ? ORDER BY "
                                      "CAST(modified AS INTEGER) DESC LIMIT 600", [f"name : ({match})"]).fetchall()
        connection.close()
        paths = [str(Path(folder) / name) for name, folder in rows]
    except Exception:   # no index yet: the usual folders, one level deep
        home = Path.home()
        for place in PLACES:
            try:
                paths += [str(p) for p in (home / place).iterdir() if p.is_file()]
            except OSError:
                pass
        paths.sort(key=lambda p: Path(p).stat().st_mtime if Path(p).exists() else 0, reverse=True)
    return {"files": _checked(paths, kind, limit)}
