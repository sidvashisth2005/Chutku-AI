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


def read_evidence(base):
    path = Path(base) / "verification/release-report.json"
    try:
        if path.stat().st_size > 65536:
            return None
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("checks"), list):
            return None
        return {**report, "stale": report.get("source_sha256") != source_digest(base)}
    except (OSError, ValueError):
        return None
