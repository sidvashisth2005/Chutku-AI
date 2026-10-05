"""Verified file inventory, search, copy and move inside one explicit grant."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
import tempfile
import uuid

from chutku.core import recycle_bin
from chutku.core.paths import sandbox_target
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


MAX_TRANSFER_BYTES = 64 * 1024 * 1024
MAX_SEARCH_ENTRIES = 50000
MAX_SEARCH_SECONDS = 8
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_DEPTH = 20
TRASH_DIRECTORY = ".chutku-trash"

_PATH_REQUIRED = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}},
    "required": ["path"],
    "additionalProperties": False,
}
_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "maxLength": 1000},
        "query": {"type": "string", "minLength": 1, "maxLength": 200},
        "recursive": {"type": "boolean"},
        "sort": {"type": "string", "enum": ["name", "newest"]},
    },
    "required": ["query"],
    "additionalProperties": False,
}
_TRANSFER_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "minLength": 1, "maxLength": 1000},
        "destination": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
    "required": ["source", "destination"],
    "additionalProperties": False,
}
_UNDO_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def _validate_path(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"path"}:
        raise ValueError("Provide only path.")
    if not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 1000:
        raise ValueError("path must contain 1 to 1000 characters.")


def _validate_search(arguments):
    if (not isinstance(arguments, dict) or set(arguments) - {"path", "query", "recursive", "sort"}
            or "query" not in arguments):
        raise ValueError("Provide query with optional path, recursive and sort only.")
    if arguments.get("sort", "name") not in {"name", "newest"}:
        raise ValueError("sort must be name or newest.")
    if not isinstance(arguments.get("path", "."), str) or len(arguments.get("path", ".")) > 1000:
        raise ValueError("path must be a string of at most 1000 characters.")
    if not isinstance(arguments["query"], str) or not 1 <= len(arguments["query"]) <= 200:
        raise ValueError("query must contain 1 to 200 characters.")
    if "recursive" in arguments and type(arguments["recursive"]) is not bool:
        raise ValueError("recursive must be a boolean.")


def _validate_transfer(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"source", "destination"}:
        raise ValueError("Provide only source and destination.")
    for key in ("source", "destination"):
        if not isinstance(arguments[key], str) or not 1 <= len(arguments[key]) <= 1000:
            raise ValueError(f"{key} must contain 1 to 1000 characters.")
    if arguments["source"].casefold() == arguments["destination"].casefold():
        raise ValueError("source and destination must be different.")


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("This undo operation takes no arguments.")


def _hash_file(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_TRANSFER_BYTES:
        raise ValueError(f"File exceeds the {MAX_TRANSFER_BYTES}-byte transfer limit.")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_TRANSFER_BYTES:
                raise ValueError(f"File exceeds the {MAX_TRANSFER_BYTES}-byte transfer limit.")
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict:
    stat = path.stat()
    if path.is_file():
        return {"kind": "file", "size": stat.st_size, "sha256": _hash_file(path)}
    if path.is_dir():
        return {"kind": "directory", "identity": stat.st_ino}
    raise ValueError("Target is not a regular file or directory.")


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() or "."


def _inspect(arguments, context):
    target = sandbox_target(context.granted_root, arguments["path"])
    if not target.exists():
        # "It is not there" is a verified answer (e.g. checking a destination before copying).
        output = {"path": _relative(context.granted_root, target), "exists": False}
        return ToolResult(output, Verification.PASS, output | {"path": "[REDACTED]"})
    identity = _identity(target)
    output = {"path": _relative(context.granted_root, target), "exists": True, **identity}
    return ToolResult(output, Verification.PASS, output | {"path": "[REDACTED]"})


_SKIP_RECURSION = {"windows", "program files", "program files (x86)", "programdata", "appdata",
                   "$recycle.bin", "system volume information", "node_modules", ".git", ".venv",
                   TRASH_DIRECTORY}


def _search(arguments, context):
    """Bounded name search. Junctions, unreadable and system folders are skipped, not
    followed; limits return honest partial results instead of failing."""
    import time
    from datetime import datetime, UTC
    root = context.granted_root
    start = sandbox_target(root, arguments.get("path", "."))
    if not start.is_dir():
        return ToolResult({"error": "Search path is not an existing directory."}, Verification.FAIL)
    query = arguments["query"].casefold()
    recursive = arguments.get("recursive", True)
    deadline = time.monotonic() + MAX_SEARCH_SECONDS
    pending = [(start, 0)]
    scanned = skipped = 0
    stopped = None
    results = []
    while pending and stopped is None:
        directory, depth = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            skipped += 1
            continue
        for child in children:
            scanned += 1
            if scanned > MAX_SEARCH_ENTRIES:
                stopped = f"entry limit ({MAX_SEARCH_ENTRIES})"
                break
            if time.monotonic() > deadline:
                stopped = f"time limit ({MAX_SEARCH_SECONDS} s)"
                break
            try:
                attributes = getattr(child.lstat(), "st_file_attributes", 0)
                if child.is_symlink() or attributes & 0x400:
                    skipped += 1
                    continue
                is_dir = child.is_dir()
                if query in child.name.casefold():
                    info = child.stat()
                    results.append({"path": _relative(root, child), "full_path": str(child),
                                    "kind": "directory" if is_dir else "file",
                                    "size": None if is_dir else info.st_size,
                                    "modified": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(timespec="seconds")})
                if recursive and is_dir and depth < MAX_SEARCH_DEPTH and child.name.casefold() not in _SKIP_RECURSION:
                    pending.append((child, depth + 1))
            except OSError:
                skipped += 1
    if arguments.get("sort") == "newest":
        results.sort(key=lambda item: item["modified"], reverse=True)
    truncated = len(results) > MAX_SEARCH_RESULTS
    results = results[:MAX_SEARCH_RESULTS]
    output = {"matches": results, "count": len(results), "scanned": scanned, "skipped": skipped,
              "limit": MAX_SEARCH_RESULTS, "truncated": truncated, "complete": stopped is None,
              "stopped_by": stopped}
    return ToolResult(output, Verification.PASS, output | {"matches": "[REDACTED]"})


def _transfer_targets(arguments, context):
    root = context.granted_root
    source = sandbox_target(root, arguments["source"])
    destination = sandbox_target(root, arguments["destination"])
    if not source.is_file():
        raise ValueError("Source must be an existing regular file.")
    if destination.exists():
        raise ValueError("Destination already exists; overwrite is refused.")
    if not destination.parent.is_dir():
        raise ValueError("Destination parent must be an existing directory.")
    if source == destination:
        raise ValueError("Source and destination must be different.")
    return root, source, destination


def _copy(arguments, context):
    root, source, destination = _transfer_targets(arguments, context)
    before = {"source": _relative(root, source), "source_identity": _identity(source),
              "destination": _relative(root, destination), "destination_existed": False}
    operation_id = context.journal.begin(context.task_id, "filesystem.copy", destination, before)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".chutku-copy-", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    installed = False
    try:
        with source.open("rb") as incoming, os.fdopen(descriptor, "wb") as outgoing:
            while chunk := incoming.read(1024 * 1024):
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if _identity(source) != before["source_identity"]:
            raise OSError("Source changed during copy; no destination was installed.")
        os.rename(temporary, destination)
        installed = True
        copied = _identity(destination)
        if copied != before["source_identity"]:
            raise OSError("Copied file failed exact hash verification.")
        context.journal.complete(operation_id, {"destination_identity": copied})
        return ToolResult({"source": before["source"], "destination": before["destination"],
                           "operation_id": operation_id, "bytes_copied": copied["size"]}, Verification.PASS)
    except (OSError, ValueError) as error:
        temporary.unlink(missing_ok=True)
        if installed and destination.is_file():
            try:
                if _identity(destination) == before["source_identity"]:
                    destination.unlink()
                    context.journal.mark_recovered(operation_id)
            except (OSError, ValueError):
                pass
        return ToolResult({"operation_id": operation_id, "error": str(error)}, Verification.FAIL)


def _move(arguments, context):
    root, source, destination = _transfer_targets(arguments, context)
    source_identity = _identity(source)
    before = {"source": _relative(root, source), "source_identity": source_identity,
              "destination": _relative(root, destination), "destination_existed": False}
    operation_id = context.journal.begin(context.task_id, "filesystem.move", source, before)
    try:
        os.rename(source, destination)
        moved = _identity(destination)
        verified = not source.exists() and moved == source_identity
        if not verified:
            raise OSError("Moved file failed exact source/destination verification.")
        context.journal.complete(operation_id, {"destination_identity": moved})
        return ToolResult({"source": before["source"], "destination": before["destination"],
                           "operation_id": operation_id, "moved": True}, Verification.PASS)
    except (OSError, ValueError) as error:
        if destination.is_file() and not source.exists():
            try:
                if _identity(destination) == source_identity:
                    os.rename(destination, source)
                    context.journal.mark_recovered(operation_id)
            except (OSError, ValueError):
                pass
        return ToolResult({"operation_id": operation_id, "error": str(error)}, Verification.FAIL)


def _undo_copy(arguments, context):
    record = context.journal.latest_completed("filesystem.copy", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed copy is available to undo."}, Verification.FAIL)
    destination = sandbox_target(context.granted_root, record["before"]["destination"])
    expected = record["after"]["destination_identity"]
    if not destination.is_file() or _identity(destination) != expected:
        return ToolResult({"error": "Undo conflict: copied destination changed or disappeared."}, Verification.FAIL)
    destination.unlink()
    verified = not destination.exists()
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"operation_id": record["operation_id"], "undone": verified},
                      Verification.PASS if verified else Verification.FAIL)


def _undo_move(arguments, context):
    record = context.journal.latest_completed("filesystem.move", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed move is available to undo."}, Verification.FAIL)
    source = sandbox_target(context.granted_root, record["before"]["source"])
    destination = sandbox_target(context.granted_root, record["before"]["destination"])
    expected = record["after"]["destination_identity"]
    if source.exists() or not destination.is_file() or _identity(destination) != expected:
        return ToolResult({"error": "Undo conflict: source was recreated or moved file changed."}, Verification.FAIL)
    os.rename(destination, source)
    verified = source.is_file() and not destination.exists() and _identity(source) == expected
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"operation_id": record["operation_id"], "undone": verified},
                      Verification.PASS if verified else Verification.FAIL)


def _recycle(arguments, context):
    """Send one file or folder to the real Windows Recycle Bin (restorable from Explorer too)."""
    root = context.granted_root
    source = sandbox_target(root, arguments["path"])
    if source == root:
        return ToolResult({"error": "The granted folder itself cannot be recycled."}, Verification.FAIL)
    if not source.exists():
        return ToolResult({"error": "Choose an existing file or folder."}, Verification.FAIL)
    if source.name == TRASH_DIRECTORY or TRASH_DIRECTORY in source.relative_to(root).parts:
        return ToolResult({"error": "The internal recycle area cannot be recycled."}, Verification.FAIL)
    try:
        identity = _identity(source)
        before = {"source": _relative(root, source), "source_identity": identity, "via": "windows_recycle_bin"}
        operation_id = context.journal.begin(context.task_id, "filesystem.recycle", source, before)
        placed = recycle_bin.send(source)
        context.journal.complete(operation_id, {"recycled_identity": identity, "info": placed["info"],
                                                "data": placed["data"]})
        return ToolResult({"operation_id": operation_id, "recycled": True, "kind": identity["kind"],
                           "original_path": before["source"], "where": "Windows Recycle Bin"}, Verification.PASS)
    except (OSError, ValueError) as error:
        if "operation_id" in locals() and source.exists():
            context.journal.mark_recovered(operation_id)
        return ToolResult({"error": str(error)}, Verification.FAIL)


def _restore_recycled(arguments, context):
    record = context.journal.latest_completed("filesystem.recycle", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed recycled file is available to restore."}, Verification.FAIL)
    root = context.granted_root
    if "info" in record["after"]:
        original = sandbox_target(root, record["before"]["source"])
        try:
            recycle_bin.restore(record["after"]["info"], record["after"]["data"], original)
            verified = original.exists() and _identity(original) == record["after"]["recycled_identity"]
        except (OSError, ValueError) as error:
            return ToolResult({"operation_id": record["operation_id"], "error": str(error)}, Verification.FAIL)
        if verified:
            context.journal.mark_undone(record["operation_id"])
        return ToolResult({"operation_id": record["operation_id"], "restored": verified,
                           "path": record["before"]["source"]}, Verification.PASS if verified else Verification.FAIL)
    # Records from before 2026-10-01 used Chutku's internal .chutku-trash folder.
    original = sandbox_target(root, record["before"]["source"])
    recycled = sandbox_target(root, record["after"]["recycled"])
    expected = record["after"]["recycled_identity"]
    if original.exists() or not recycled.is_file() or _identity(recycled) != expected:
        return ToolResult({"error": "Restore conflict: original path exists or recycled content changed."},
                          Verification.FAIL)
    try:
        os.rename(recycled, original)
        verified = original.is_file() and not recycled.exists() and _identity(original) == expected
        if verified:
            context.journal.mark_undone(record["operation_id"])
            trash_root = root / TRASH_DIRECTORY
            if trash_root.is_dir() and not any(trash_root.iterdir()):
                trash_root.rmdir()
        return ToolResult({"operation_id": record["operation_id"], "restored": verified,
                           "path": record["before"]["source"]},
                          Verification.PASS if verified else Verification.FAIL)
    except (OSError, ValueError) as error:
        return ToolResult({"operation_id": record["operation_id"], "error": str(error)}, Verification.FAIL)


def _delete_permanent(arguments, context):
    """Irreversibly delete one file or folder. Links inside a folder are removed, never followed."""
    root = context.granted_root
    target = sandbox_target(root, arguments["path"])
    if target == root:
        return ToolResult({"error": "The granted folder itself cannot be deleted."}, Verification.FAIL)
    if not target.exists():
        return ToolResult({"error": "Choose an existing file or folder."}, Verification.FAIL)
    try:
        identity = _identity(target)
        operation_id = context.journal.begin(context.task_id, "filesystem.delete_permanent", target,
                                             {"path": _relative(root, target), "identity": identity})
        if target.is_dir():
            shutil.rmtree(target)  # Python 3.12+ unlinks junctions and symlinks instead of descending into them
        else:
            target.unlink()
        if target.exists():
            raise OSError("The item is still present after deletion.")
        context.journal.complete(operation_id, {"deleted": True})
        return ToolResult({"operation_id": operation_id, "deleted_permanently": True, "kind": identity["kind"],
                           "path": _relative(root, target)}, Verification.PASS)
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)


def register_extended_filesystem_tools(registry):
    registry.register(Tool("filesystem.inspect", "Check whether one file or folder exists and return its kind, size and hash.",
        Risk.OBSERVATION, _inspect, _validate_path, resource_access="observe", argument_schema=_PATH_REQUIRED,
        reversibility="not_applicable", success_predicate="exact_target_identity_returned"))
    registry.register(Tool("filesystem.search", "Find files/folders whose name contains query (case-insensitive, e.g. '.pdf' or 'invoice') under path; sort='newest' lists most recently modified first. Returns full_path, size, modified.",
        Risk.OBSERVATION, _search, _validate_search, frozenset({"query"}), resource_access="observe",
        argument_schema=_SEARCH_SCHEMA, reversibility="not_applicable",
        success_predicate="bounded_name_search_completed_without_leaving_grant"))
    registry.register(Tool("filesystem.copy", "Copy one bounded regular file without overwrite and verify its SHA-256.",
        Risk.DATA_MODIFICATION, _copy, _validate_transfer, resource_access="modify", argument_schema=_TRANSFER_SCHEMA,
        prerequisites=("existing regular source and absent destination",), reversibility="journaled",
        success_predicate="source_and_destination_SHA256_match"))
    registry.register(Tool("filesystem.move", "Move or rename one regular file without overwrite and verify its identity.",
        Risk.DATA_MODIFICATION, _move, _validate_transfer, resource_access="modify", argument_schema=_TRANSFER_SCHEMA,
        prerequisites=("existing regular source and absent destination",), reversibility="journaled",
        success_predicate="source_absent_and_destination_identity_matches"))
    registry.register(Tool("filesystem.undo_last_copy", "Remove the latest unchanged copied file.",
        Risk.DATA_MODIFICATION, _undo_copy, _validate_none, resource_access="modify", argument_schema=_UNDO_SCHEMA,
        prerequisites=("unchanged completed copy",), reversibility="journaled",
        success_predicate="copied_destination_no_longer_exists"))
    registry.register(Tool("filesystem.undo_last_move", "Restore the latest unchanged moved file to its original path.",
        Risk.DATA_MODIFICATION, _undo_move, _validate_none, resource_access="modify", argument_schema=_UNDO_SCHEMA,
        prerequisites=("unchanged completed move and absent original path",), reversibility="journaled",
        success_predicate="original_identity_restored_and_destination_absent"))
    registry.register(Tool("filesystem.recycle", "Delete a file or folder by sending it to the Windows Recycle Bin (restorable).",
        Risk.DATA_MODIFICATION, _recycle, _validate_path, resource_access="modify", argument_schema=_PATH_REQUIRED, deletes=True,
        prerequisites=("existing file or folder on a fixed local drive",), reversibility="journaled",
        success_predicate="original_absent_and_found_in_windows_recycle_bin"))
    registry.register(Tool("filesystem.delete_permanent", "Permanently delete a file or folder (NOT recoverable). "
        "Only when the user explicitly says 'permanently delete'; otherwise use filesystem.recycle.",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _delete_permanent, _validate_path, resource_access="modify",
        argument_schema=_PATH_REQUIRED, deletes=True, user_only=True,
        prerequisites=("existing file or folder; explicit user request and confirmation",),
        reversibility="irreversible", success_predicate="item_no_longer_exists"))
    registry.register(Tool("filesystem.restore_last_recycled", "Restore the latest file or folder Chutku sent to the Recycle Bin, without overwriting.",
        Risk.DATA_MODIFICATION, _restore_recycled, _validate_none, resource_access="modify", argument_schema=_UNDO_SCHEMA,
        prerequisites=("unchanged recycled file and absent original path",), reversibility="journaled",
        success_predicate="original_identity_restored_and_recycled_path_absent"))
