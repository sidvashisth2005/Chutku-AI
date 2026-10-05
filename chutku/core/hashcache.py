"""Pinned-hash checks for multi-gigabyte model files, without re-reading them on every start.

A file is hashed in full the first time this process uses it. Later checks reuse the result while the file's
(path, size, modified time, file id) are unchanged, so swapping the GPU between the 4B planner, the 8B and the
vision model no longer re-reads up to 5 GB each time. A fresh process always hashes again, so the integrity
boundary at start-up is unchanged.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading

_lock = threading.Lock()
_files: dict[tuple, str] = {}
_directories: dict[tuple, str] = {}


def _state(path: Path) -> tuple:
    info = path.stat()
    return str(path.resolve()), info.st_size, info.st_mtime_ns, getattr(info, "st_ino", 0)


def file_sha256(path) -> str:
    path = Path(path)
    key = _state(path)
    with _lock:
        known = _files.get(key)
    if known is not None:
        return known
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with _lock:
        _files[key] = digest
    return digest


def matches(path, expected: str) -> bool:
    return file_sha256(path) == expected


def directory_digest(directory, compute) -> str:
    """`compute(directory)` once per unchanged directory listing (names, sizes, modified times)."""
    directory = Path(directory)
    listing = tuple(sorted((os.path.relpath(p, directory), p.stat().st_size, p.stat().st_mtime_ns)
                           for p in directory.rglob("*") if p.is_file()))
    key = (str(directory.resolve()), listing)
    with _lock:
        known = _directories.get(key)
    if known is not None:
        return known
    digest = compute(directory)
    with _lock:
        _directories[key] = digest
    return digest


def clear() -> None:
    with _lock:
        _files.clear()
        _directories.clear()
