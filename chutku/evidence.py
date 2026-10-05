"""Bounded local evidence reader; does not execute benchmarks during page loads."""
import hashlib
import json
from pathlib import Path


CRITICAL_FILES = (
    "pyproject.toml", "requirements.lock", "models/manifest.json", "AGENTS.md",
    "docs/DESIGN.md", "docs/ARCHITECTURE.md", "docs/ROADMAP.md", "docs/SECURITY.md",
    "THIRD_PARTY_LICENSES.md", "Start-Chutku.cmd", "Stop-Chutku.cmd",
)


def source_digest(base):
    base = Path(base)
    digest = hashlib.sha256()
    for directory in ("chutku", "tests", "scripts", "benchmarks"):
        for path in sorted((base / directory).rglob("*")):
            if path.suffix in {".py", ".js", ".css", ".html"} and path.is_file():
                digest.update(path.relative_to(base).as_posix().encode())
                digest.update(path.read_bytes())
    for relative in CRITICAL_FILES:
        path = base / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"[MISSING]")
    return digest.hexdigest()


_cache = {}


def _listing_key(base):
    """Names, sizes and modified times of every hashed file: cheap to read, changes whenever a file changes."""
    base = Path(base)
    entries = []
    for directory in ("chutku", "tests", "scripts", "benchmarks"):
        for path in (base / directory).rglob("*"):
            if path.suffix in {".py", ".js", ".css", ".html"} and path.is_file():
                info = path.stat()
                entries.append((path.as_posix(), info.st_size, info.st_mtime_ns))
    for relative in CRITICAL_FILES:
        path = base / relative
        if path.is_file():
            info = path.stat()
            entries.append((relative, info.st_size, info.st_mtime_ns))
    return str(base.resolve()), tuple(sorted(entries))


def cached_source_digest(base):
    """source_digest, recomputed only when a file's size or modified time changed (the dashboard polls it)."""
    key = _listing_key(base)
    if _cache.get("key") != key:
        _cache.update(key=key, digest=source_digest(base))
    return _cache["digest"]


def read_evidence(base):
    path = Path(base) / "verification/release-report.json"
    try:
        if path.stat().st_size > 65536:
            return None
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("checks"), list):
            return None
        return {**report, "stale": report.get("source_sha256") != cached_source_digest(base)}
    except (OSError, ValueError):
        return None
