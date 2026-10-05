"""Everyday file helpers: zip, unzip (safe), recent files, disk space."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile
import time
import zipfile

from chutku.core.paths import sandbox_target
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

MAX_FILES = 20_000
MAX_TOTAL_BYTES = 4 * 1024 ** 3
MAX_RATIO = 100  # a member that expands more than 100x is treated as a zip bomb
_RESERVED = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(1, 10)}


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _validate(allowed, required=("path",)):
    def check(arguments):
        if not isinstance(arguments, dict) or set(arguments) - set(allowed) or any(k not in arguments for k in required):
            raise ValueError(f"Provide {', '.join(allowed)}.")
        for key in ("path", "destination"):
            if key in arguments and (not isinstance(arguments[key], str) or not 1 <= len(arguments[key]) <= 1000):
                raise ValueError(f"{key} must be 1 to 1000 characters.")
        if "query" in arguments and (not isinstance(arguments["query"], str) or not 1 <= len(arguments["query"].strip()) <= 100):
            raise ValueError("query must be 1 to 100 characters.")
        if "days" in arguments and (type(arguments["days"]) is not int or not 1 <= arguments["days"] <= 90):
            raise ValueError("days must be between 1 and 90.")
    return check


def _zip(arguments, context):
    source = sandbox_target(context.granted_root, arguments["path"])
    if not source.exists() or source == context.granted_root:
        return ToolResult({"error": "Choose an existing file or folder to zip."}, Verification.FAIL)
    default = source.with_suffix(".zip") if source.is_file() else Path(str(source) + ".zip")  # like Windows "Send to"
    target = sandbox_target(context.granted_root, arguments.get("destination") or str(default))
    if target.suffix.casefold() != ".zip":
        return ToolResult({"error": "The archive name must end in .zip."}, Verification.FAIL)
    if target.exists():
        return ToolResult({"error": "An archive with that name already exists; nothing was overwritten."}, Verification.FAIL)
    if target == source or source in target.parents:
        return ToolResult({"error": "Save the archive outside the folder being zipped."}, Verification.FAIL)
    members = []
    if source.is_file():
        members.append((source, source.name))
    else:
        for folder, dirs, files in os.walk(source):
            dirs[:] = [d for d in dirs if not _is_link(Path(folder) / d)]
            for name in files:
                path = Path(folder) / name
                if not _is_link(path):
                    members.append((path, str(path.relative_to(source.parent))))
                if len(members) > MAX_FILES:
                    return ToolResult({"error": f"More than {MAX_FILES} files; zip a smaller folder."}, Verification.FAIL)
    descriptor, temporary = tempfile.mkstemp(prefix=".chutku-", suffix=".zip.tmp", dir=target.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, name in members:
                archive.write(path, name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None or len(archive.infolist()) != len(members):
                raise OSError("The new archive failed its integrity check.")
        os.rename(temporary, target)  # fails rather than overwriting if the name appeared meanwhile
    except (OSError, zipfile.BadZipFile) as error:
        Path(temporary).unlink(missing_ok=True)
        return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult({"archive": str(target), "files": len(members), "bytes": target.stat().st_size},
                      Verification.PASS)


def _safe_member(name: str) -> bool:
    pure = PureWindowsPath(name.replace("/", "\\"))
    if pure.drive or pure.root or not pure.parts:
        return False
    for part in pure.parts:
        if part in {"..", "."} or part.rstrip(" .") != part or ":" in part or \
                part.split(".")[0].casefold() in _RESERVED or any(ord(c) < 32 or c in '<>"|?*' for c in part):
            return False
    return True


def _unzip(arguments, context):
    archive_path = sandbox_target(context.granted_root, arguments["path"])
    if not archive_path.is_file() or not zipfile.is_zipfile(archive_path):
        return ToolResult({"error": "Choose an existing .zip file."}, Verification.FAIL)
    destination = sandbox_target(context.granted_root,
                                 arguments.get("destination") or str(archive_path.with_suffix("")))
    if destination.exists():
        return ToolResult({"error": "The destination folder already exists; choose a new folder name."},
                          Verification.FAIL)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_FILES:
            return ToolResult({"error": f"The archive has more than {MAX_FILES} entries."}, Verification.FAIL)
        unsafe = [m.filename for m in members if not _safe_member(m.filename)]
        if unsafe:
            return ToolResult({"error": f"The archive contains unsafe paths (for example {unsafe[0]!r}); "
                                        "nothing was extracted."}, Verification.FAIL)
        total = sum(m.file_size for m in members)
        bomb = any(m.compress_size and m.file_size / m.compress_size > MAX_RATIO for m in members)
        if total > MAX_TOTAL_BYTES or bomb:
            return ToolResult({"error": "The archive's compression ratio or size is suspicious (possible zip bomb); "
                                        "nothing was extracted."}, Verification.FAIL)
        staging = Path(tempfile.mkdtemp(prefix=".chutku-unzip-", dir=destination.parent))
        try:
            for member in members:
                target = (staging / member.filename.replace("\\", "/")).resolve()
                if staging.resolve() not in target.parents and target != staging.resolve():
                    raise OSError("unsafe member path")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            os.rename(staging, destination)
        except (OSError, zipfile.BadZipFile) as error:
            shutil.rmtree(staging, ignore_errors=True)
            return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult({"folder": str(destination), "files": sum(not m.is_dir() for m in members)}, Verification.PASS)


def scan_recent(folders, days=7, limit=20):
    """Files changed in the last ``days`` under ``folders`` (bounded: depth 4, 20k entries, 10 s), newest first."""
    cutoff = time.time() - days * 86400
    found, scanned, deadline = [], 0, time.monotonic() + 10
    for start in folders:
        for folder, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.casefold() not in {"node_modules", "__pycache__"}
                       and not _is_link(Path(folder) / d)]
            if len(Path(folder).relative_to(start).parts) >= 4:
                dirs[:] = []
            for name in files:
                scanned += 1
                if scanned > 20_000 or time.monotonic() > deadline:
                    break
                path = Path(folder) / name
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if modified >= cutoff and not name.startswith((".", "~$")) and name.casefold() != "desktop.ini":
                    found.append((modified, path))
    found.sort(reverse=True)
    return [{"name": p.name, "path": str(p), "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(m))}
            for m, p in found[:limit]]


_NOISE_DIRS = {"node_modules", "__pycache__", "site-packages", "library", "packagecache", "obj", "bin", "build",
               "dist", ".git", ".venv", "venv", "appdata", "$recycle.bin"}
PERSONAL = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive")


def find_personal(folders, query, limit=10):
    """Files whose name contains every word of ``query``, newest first (bounded: 60k entries, 12 s)."""
    words = [w for w in query.casefold().replace("_", " ").replace("-", " ").split()
             if w not in {"my", "the", "a", "file", "files", "document", "documents"}]
    if not words:
        return []
    found, scanned, deadline = [], 0, time.monotonic() + 12
    for start in folders:
        for folder, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.casefold() not in _NOISE_DIRS
                       and not _is_link(Path(folder) / d)]
            for name in files:
                scanned += 1
                if scanned > 60_000 or time.monotonic() > deadline:
                    break
                plain = name.casefold().replace("_", " ").replace("-", " ")
                if all(word in plain for word in words) and not name.startswith("~$"):
                    path = Path(folder) / name
                    try:
                        found.append((path.stat().st_mtime, path))
                    except OSError:
                        continue
    found.sort(reverse=True)
    return [{"name": p.name, "path": str(p), "folder": p.parent.name,
             "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(m))} for m, p in found[:limit]]


def _find(arguments, context):
    home = Path(os.environ.get("USERPROFILE", "")).resolve()
    start = sandbox_target(context.granted_root, arguments.get("path", str(home)))
    folders = [home / name for name in PERSONAL if (home / name).is_dir()] if start == home else [start]
    if not folders or not all(f.is_dir() for f in folders):
        return ToolResult({"error": "That folder does not exist."}, Verification.FAIL)
    matches = find_personal(folders, arguments["query"])
    return ToolResult({"query": arguments["query"], "matches": matches, "count": len(matches)}, Verification.PASS,
                      {"count": len(matches), "matches": "[REDACTED]"})


def user_folders():
    home = Path(os.environ.get("USERPROFILE", ""))
    return [home / name for name in ("Desktop", "Documents", "Downloads")]


def _recent(arguments, context):
    folders = []
    home = Path(os.environ.get("USERPROFILE", "")).resolve()
    if "path" in arguments and sandbox_target(context.granted_root, arguments["path"]) != home:
        folders.append(sandbox_target(context.granted_root, arguments["path"]))
    else:
        for folder in user_folders():
            try:
                folders.append(sandbox_target(context.granted_root, str(folder)))
            except ValueError:
                continue  # outside the selected grant
    folders = [folder for folder in folders if folder.is_dir()]
    if not folders:
        return ToolResult({"error": "None of those folders is inside the drive Chutku has access to right now; "
                                    "name a folder to check."}, Verification.FAIL)
    files = scan_recent(folders, arguments.get("days", 7))
    output = {"files": files, "count": len(files), "days": arguments.get("days", 7),
              "searched": [str(folder) for folder in folders]}
    return ToolResult(output, Verification.PASS, {"count": len(files), "files": "[REDACTED]", "searched": "[REDACTED]"})


_INSTALLERS = {".exe", ".msi", ".msix", ".appx", ".iso"}


def _folder_size(folder, deadline, limit=60_000):
    total, seen = 0, 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not _is_link(Path(root) / d)]
        for name in files:
            seen += 1
            if seen > limit or time.monotonic() > deadline:
                return total, False
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total, True


def _recycle_bin_size(drive):
    import ctypes
    from ctypes import wintypes as w

    class Info(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("bytes", ctypes.c_longlong), ("items", ctypes.c_longlong)]
    info = Info()
    info.size = ctypes.sizeof(Info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(drive, ctypes.byref(info)) != 0:
        return None
    return {"bytes": info.bytes, "items": info.items}


def cleanup_report(home: Path):
    """Read-only: where space can be recovered. Nothing is deleted here."""
    deadline = time.monotonic() + 20
    gb = lambda n: round(n / 1024 ** 3, 2)
    temp_bytes, temp_complete = _folder_size(Path(tempfile.gettempdir()), deadline)
    downloads = home / "Downloads"
    old_installers, downloads_bytes = [], 0
    cutoff = time.time() - 14 * 86400
    if downloads.is_dir():
        for child in downloads.iterdir():
            try:
                if _is_link(child):
                    continue
                if child.is_file():
                    stat = child.stat()
                    downloads_bytes += stat.st_size
                    if child.suffix.casefold() in _INSTALLERS and stat.st_mtime < cutoff:
                        old_installers.append((stat.st_size, child))
                elif child.is_dir():
                    downloads_bytes += _folder_size(child, deadline, 20_000)[0]
            except OSError:
                continue
    old_installers.sort(reverse=True)
    biggest = []
    for root, dirs, files in os.walk(home):
        dirs[:] = [d for d in dirs if d.casefold() not in {"appdata", "node_modules", ".git", ".venv", "$recycle.bin"}
                   and not d.startswith(".") and not _is_link(Path(root) / d)]
        if time.monotonic() > deadline:
            break
        for name in files:
            path = Path(root) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 200 * 1024 ** 2:
                biggest.append((size, path))
    biggest.sort(reverse=True)
    recycle = _recycle_bin_size(home.anchor)
    suggestions = []
    if recycle and recycle["bytes"] > 100 * 1024 ** 2:
        suggestions.append(f"Empty the Recycle Bin on {home.anchor[0]}: ({gb(recycle['bytes'])} GB, {recycle['items']} items)")
    if temp_bytes > 500 * 1024 ** 2:
        suggestions.append(f"Clear temporary files ({gb(temp_bytes)} GB) with Windows Disk Cleanup or Storage Sense")
    if sum(s for s, _ in old_installers) > 50 * 1024 ** 2:
        suggestions.append(f"Recycle {len(old_installers)} old installer(s) in Downloads "
                           f"({gb(sum(s for s, _ in old_installers))} GB)")
    if biggest:
        suggestions.append(f"Move big files to D: (largest: {biggest[0][1].name}, {gb(biggest[0][0])} GB)")
    personal = temp_bytes + downloads_bytes + sum(size for size, _ in biggest)
    if personal < 5 * 1024 ** 3:
        suggestions.append("Your own files are small here: most of the drive is Windows, your programs and app "
                           "caches. Windows Settings > System > Storage shows that breakdown, and uninstalling unused "
                           "apps there frees the most")
    return {"drive": home.anchor, "recycle_bin_gb": gb(recycle["bytes"]) if recycle else None,
            "temp_gb": gb(temp_bytes), "temp_complete": temp_complete, "downloads_gb": gb(downloads_bytes),
            "old_installers": [{"name": p.name, "path": str(p), "gb": gb(s)} for s, p in old_installers[:6]],
            "biggest_files": [{"name": p.name, "path": str(p), "gb": gb(s)} for s, p in biggest[:6]],
            "suggestions": suggestions, "deleted_anything": False}


def _cleanup(arguments, context):
    home = Path(os.environ.get("USERPROFILE", "")).resolve()
    target = sandbox_target(context.granted_root, arguments.get("path", str(home)))
    if target != home:
        return ToolResult({"error": "The space report covers your user folder; ask without a path."}, Verification.FAIL)
    report = cleanup_report(home)
    return ToolResult(report, Verification.PASS, {"suggestions": len(report["suggestions"]), "files": "[REDACTED]"})


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This takes no arguments.")


def disk_report():
    import ctypes
    kernel = ctypes.WinDLL("kernel32")
    drives = []
    mask = kernel.GetLogicalDrives()
    for index in range(26):
        if mask & (1 << index):
            anchor = f"{chr(65 + index)}:\\"
            if kernel.GetDriveTypeW(anchor) != 3:  # fixed drives only
                continue
            try:
                usage = shutil.disk_usage(anchor)
            except OSError:
                continue
            percent = round(usage.free * 100 / usage.total, 1)
            drives.append({"drive": anchor, "free_gb": round(usage.free / 1024 ** 3, 1),
                           "total_gb": round(usage.total / 1024 ** 3, 1), "free_percent": percent,
                           "low": percent < 10})
    warning = [d["drive"] for d in drives if d["low"]]
    return {"drives": drives, "low_space": warning,
            "advice": ("Low space on " + ", ".join(warning) + ". Ask me for the biggest files there, "
                       "or empty the Recycle Bin.") if warning else None}


def _disk_space(arguments, context):
    return ToolResult(disk_report(), Verification.PASS)


def register_files_plus_tools(registry):
    registry.register(Tool("files.zip", "Compress a file or folder into a NEW .zip (default: next to it, same name). "
        "Never overwrites.", Risk.DATA_MODIFICATION, _zip, _validate(("path", "destination")),
        resource_access="modify", argument_schema={"type": "object", "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000},
            "destination": {"type": "string", "minLength": 1, "maxLength": 1000}},
            "required": ["path"], "additionalProperties": False},
        reversibility="creates_new_file_only", success_predicate="archive_integrity_checked"))
    registry.register(Tool("files.unzip", "Extract a .zip into a NEW folder (default: next to it, same name). Refuses "
        "unsafe paths and zip bombs; never overwrites.", Risk.DATA_MODIFICATION, _unzip,
        _validate(("path", "destination")), resource_access="modify", argument_schema={"type": "object", "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000},
            "destination": {"type": "string", "minLength": 1, "maxLength": 1000}},
            "required": ["path"], "additionalProperties": False},
        reversibility="creates_new_folder_only", success_predicate="all_members_extracted_into_new_folder"))
    registry.register(Tool("files.recent", "List files changed recently (default: Desktop, Documents and Downloads, "
        "last 7 days), newest first. Answers 'what was I working on?'.", Risk.OBSERVATION, _recent,
        _validate(("path", "days"), required=()), resource_access="observe",
        argument_schema={"type": "object", "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000},
            "days": {"type": "integer", "minimum": 1, "maximum": 90}}, "additionalProperties": False},
        reversibility="not_applicable", success_predicate="bounded_recent_scan_completed"))
    registry.register(Tool("files.find", "Find the user's own files by name words (e.g. 'resume', 'electricity bill') "
        "in Desktop, Documents, Downloads, Pictures, Videos, Music and OneDrive, skipping code/library folders; "
        "newest first. Give path to search one folder instead.", Risk.OBSERVATION, _find,
        _validate(("path", "query"), required=("query",)), resource_access="observe",
        argument_schema={"type": "object", "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000},
            "query": {"type": "string", "minLength": 1, "maxLength": 100}}, "required": ["query"],
            "additionalProperties": False},
        reversibility="not_applicable", success_predicate="bounded_personal_search_completed"))
    registry.register(Tool("storage.cleanup_report", "Find where disk space can be recovered on the user's drive "
        "(Recycle Bin, temp files, old installers in Downloads, biggest personal files). Read-only: deletes nothing.",
        Risk.OBSERVATION, _cleanup, _validate(("path",), required=()), resource_access="observe",
        argument_schema={"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}},
                         "additionalProperties": False},
        reversibility="not_applicable", success_predicate="bounded_space_report_completed"))
    registry.register(Tool("system.disk_space", "Free and total space on every fixed drive, with a low-space warning "
        "below 10%.", Risk.OBSERVATION, _disk_space, _no_arguments,
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="fixed_drive_usage_read"))
