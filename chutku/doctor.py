"""Read-only foundation health check. Never records audio or starts a model."""
from importlib import metadata
import json
from pathlib import Path
import re
import sqlite3
import sys
import tomllib


def inspect_foundation(base):
    base = Path(base).resolve()
    checks = []
    def add(name, ready, detail, required=True):
        checks.append({"name": name, "ready": bool(ready), "required": required, "detail": detail})
    add("Python", sys.version_info >= (3, 11), sys.version.split()[0])
    add("Windows", sys.platform == "win32", sys.platform)
    from chutku.core.elevation import ELEVATED_REASON, is_elevated
    elevated = is_elevated()
    add("Not elevated", not elevated, ELEVATED_REASON if elevated else "Normal user rights; Windows ACLs protect system folders")
    for name in ("pyproject.toml", "requirements.lock", "THIRD_PARTY_LICENSES.md", "models/manifest.json"):
        add("Project " + name, (base / name).is_file(), "Required reproducibility and licensing record")
    try:
        project = tomllib.loads((base / "pyproject.toml").read_text(encoding="utf-8"))
        direct = {}
        for dependency in project["project"]["dependencies"]:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", dependency)
            if not match:
                raise ValueError
            direct[match[1].casefold()] = match[2]
        locked = {}
        for line in (base / "requirements.lock").read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line.strip())
            if not match:
                raise ValueError
            locked[match[1].casefold()] = match[2]
        lock_aligned = bool(direct) and all(locked.get(name) == version for name, version in direct.items())
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        lock_aligned = False
    add("Dependency lock alignment", lock_aligned, "Every direct dependency is exact and matches requirements.lock")
    try:
        ledger = (base / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8").casefold()
        manifest = json.loads((base / "models/manifest.json").read_text(encoding="utf-8"))
        license_coverage = (all(name in ledger for name in ("numpy", "sounddevice", "llama.cpp", "qwen"))
                            and all(isinstance(manifest[section].get("license"), str)
                                    and manifest[section]["license"] for section in ("runtime", "model"))
                            and isinstance(manifest["model"].get("revision"), str)
                            and bool(manifest["model"]["revision"]))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        license_coverage = False
    add("License ledger coverage", license_coverage, "Runtime packages, local model/runtime licenses and model revision are recorded")
    root = base / "sandbox"
    reparse = root.exists() and getattr(root.lstat(), "st_file_attributes", 0) & 0x400
    add("Granted root", not root.is_symlink() and not reparse and (not root.exists() or root.is_dir()), str(root))
    for name in ("index.html", "style.css", "app.js"):
        add("Dashboard " + name, (base / "chutku/web" / name).is_file(), "Bundled local asset")
    for name in ("chutku.db", "operations.db", "memory.db", "resource_grants.db"):
        path = base / "data" / name
        if not path.exists():
            add(name, True, "Not initialized; created on first use")
            continue
        try:
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
                add(name, result == ("ok",), "SQLite quick_check " + ("passed" if result == ("ok",) else "failed"))
            finally:
                connection.close()
        except sqlite3.Error:
            add(name, False, "Cannot read a healthy SQLite database; preserve files and inspect before using")
    from chutku.core.action_log import ActionLog
    chain = ActionLog(base / "data" / "actions.log.jsonl").verify()
    add("Action log", chain["ok"], f"Hash chain intact ({chain['entries']} entries)" if chain["ok"] else
        f"Hash chain broken at entry {chain['broken_at']}: the log was edited, truncated or damaged; preserve it")
    optional = {"numpy": "audio", "sounddevice": "audio", "faster-whisper": "offline speech recognition",
                "websockets": "the live voice conversation", "playwright": "browser automation",
                "pypdf": "reading PDF files"}
    for package, purpose in optional.items():
        try:
            add(package, True, metadata.version(package), required=False)
        except metadata.PackageNotFoundError:
            add(package, False, f"Missing: {purpose} will not work; everything else still does", required=False)
    try:
        import tkinter  # noqa: F401  (the HUD)
        add("tkinter", True, "HUD available", required=False)
    except ImportError:
        add("tkinter", False, "Missing: the HUD will not show; the dashboard still works", required=False)
    model_ready = (base / "models/Qwen3-4B-Q4_K_M.gguf").is_file() and (base / "vendor/llama-b11181/llama-server.exe").is_file()
    add("Local model artifacts", model_ready, "Presence only; integrity/inference require separate verification", required=False)
    try:
        manifest = json.loads((base / "models/manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    extras = {"stt": ("Offline speech (Whisper)", "directory"), "strong": ("Offline backup planner (8B)", "path"),
              "vision": ("Local vision model", None), "gpu_runtime": ("GPU model runtime", "directory")}
    for key, (label, field) in extras.items():
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            add(label, False, "Not set up (optional); scripts/setup_all.py reports how to add it", required=False)
            continue
        if field is None:
            present = all((base / str((entry.get(part) or {}).get("path", "")).replace("\\", "/")).is_file()
                          for part in ("model", "mmproj"))
        else:
            present = (base / str(entry.get(field, "")).replace("\\", "/")).exists()
        add(label, present, "Present (presence only; scripts/setup_all.py checks the hashes)" if present else
            "Missing files; run scripts/setup_all.py", required=False)
    return {"project": str(base), "python": sys.executable,
            "ready": all(c["ready"] for c in checks if c["required"]), "checks": checks,
            "actions_paused": (base / "data/actions.paused").exists(),
            "scope": "Read-only prerequisite and storage check. Does not prove microphone, foreground focus or model correctness."}
