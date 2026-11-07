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
        text = (base / "requirements.lock").read_text(encoding="utf-8")
        for line in re.sub(r"\\\r?\n\s*", " ", text).splitlines():   # a pin and its --hash lines are one line
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", parts[0])
            if not match or any(not part.startswith("--hash=sha256:") for part in parts[1:]):
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


# -- H26: a doctor that can repair ("khud ko theek karo", `chutku.cli doctor --fix`) --------------------------------
# Each fix is harmless or reversible and logged in the report: a damaged file is moved aside (never deleted) and its
# index is rebuilt from the source of truth. Everything else is reported, not fixed. The execution and guard locks
# are OS locks that Windows releases when their process dies, so there is never a stale lock file to remove.

def _sqlite_ok(path):
    from contextlib import closing
    try:   # closed explicitly: on Windows an open connection stops the damaged file from being moved aside
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            return db.execute("PRAGMA quick_check").fetchone() == ("ok",)
    except sqlite3.Error:
        return False


def _move_aside(path):
    """Keep a damaged file next to the original as <name>.broken-<time> (with its -wal/-shm). Returns the new name."""
    import time
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.broken-{stamp}")
    path.replace(target)
    for suffix in ("-wal", "-shm"):
        extra = path.with_name(path.name + suffix)
        if extra.exists():
            extra.replace(target.with_name(target.name + suffix))
    return target.name


def repair(base, *, fix=False, brain=None):
    """The H26 report: [{"name", "state": ok|fixed|broken|report, "detail"}]. With fix=False nothing is changed.
    `brain` is the running dashboard's local model service (None from the CLI: the dashboard owns that process)."""
    base = Path(base).resolve()
    data = base / "data"
    rows = []

    def row(name, state, detail):
        rows.append({"name": name, "state": state, "detail": detail})

    # 1. A pause the watchdog made by itself (never the owner's pause).
    from chutku.core.action_control import ActionControl, SELF_HEALING
    control = ActionControl(base)
    info = control.info()
    if not info:
        row("Pause", "ok", "Not paused")
    elif info.get("source") in SELF_HEALING:
        if fix:
            try:
                lifted = control.heal()
                row("Pause", "fixed" if lifted else "ok", "Lifted the watchdog's own pause" if lifted
                    else "Already lifted")
            except Exception as error:   # ExecutionBusy: an action is running right now
                row("Pause", "broken", f"Could not lift it yet: {error}")
        else:
            row("Pause", "broken", "The watchdog paused Chutku after a hang; --fix lifts it")
    else:
        row("Pause", "report", "Paused by the owner: only the owner resumes (Resume button or 'resume')")

    # 2. The chat-history search index (rebuilt from data/conversations.jsonl, which stays untouched).
    from chutku import history_index
    path = history_index.db_path(base)
    if not path.exists() or _sqlite_ok(path):
        row("History index", "ok", "Healthy" if path.exists() else "Not built yet; built on first search")
    elif fix:
        try:
            kept = _move_aside(path)
            history_index.sync(base)
            row("History index", "fixed", f"Rebuilt from the conversation log; the damaged copy is data/{kept}")
        except (OSError, sqlite3.Error) as error:
            row("History index", "broken", f"Rebuild failed: {error}")
    else:
        row("History index", "broken", "SQLite check failed; --fix rebuilds it from the conversation log")

    # 3. The embeddings cache (only a cache: vectors are computed again when needed).
    cache = data / "embeddings.sqlite"
    if not cache.exists() or _sqlite_ok(cache):
        row("Embeddings cache", "ok", "Healthy" if cache.exists() else "Empty; filled on use")
    elif fix:
        try:
            row("Embeddings cache", "fixed", f"Moved aside to data/{_move_aside(cache)}; it refills on use")
        except OSError as error:
            row("Embeddings cache", "broken", f"Could not move it: {error}")
    else:
        row("Embeddings cache", "broken", "SQLite check failed; --fix moves it aside (it is only a cache)")

    # 4. The local model server (only inside the running dashboard).
    if brain is None:
        row("Local model", "report", "Checked only inside the running Chutku (say 'khud ko theek karo')")
    elif brain.status().get("running"):
        row("Local model", "ok", f"Running ({brain.status().get('backend')})")
    elif fix:
        try:
            brain.ensure_started()
            row("Local model", "fixed", f"Started again ({brain.status().get('backend')})")
        except OSError as error:
            row("Local model", "broken", f"Could not start: {str(error)[:200]}")
    else:
        row("Local model", "report", "Not running (it starts on the next request, or --fix starts it now)")

    # 5. Model files: presence against the manifest; hashes are checked by scripts/setup_all.py (never re-downloaded).
    try:
        manifest = json.loads((base / "models/manifest.json").read_text(encoding="utf-8"))
        missing = [key for key, entry in manifest.items() if isinstance(entry, dict) and entry.get("path")
                   and not (base / str(entry["path"]).replace("\\", "/")).exists()]
        row("Model files", "report" if missing else "ok",
            ("Missing: " + ", ".join(missing) + " (run scripts/setup_all.py)") if missing else "All listed files present")
    except (OSError, ValueError, AttributeError):
        row("Model files", "report", "models/manifest.json is missing or unreadable")

    # 6. Telegram long poll (H16): reported, re-paired by the owner only.
    from chutku.gateway import telegram
    if telegram.paired(base) is not None:
        row("Telegram", "report", "Paired; the long poll reconnects by itself (with backoff) while Chutku runs")
    return {"fix": fix, "checks": rows, "fixed": sum(r["state"] == "fixed" for r in rows),
            "broken": sum(r["state"] == "broken" for r in rows)}


def summary(report):
    """One spoken line for the report."""
    broken = [r["name"] for r in report["checks"] if r["state"] == "broken"]
    fixed = [r["name"] for r in report["checks"] if r["state"] == "fixed"]
    noted = [f"{r['name']} ({r['detail']})" for r in report["checks"]
             if r["state"] == "report" and r["name"] != "Local model"]   # things only the owner can change
    parts = [] if broken or fixed else ["Kuch theek karne ki zaroorat nahi thi."]
    if fixed:
        parts.append("Theek kar diya: " + ", ".join(fixed) + ".")
    if broken:
        parts.append("Abhi bhi kharab: " + ", ".join(broken) + " (details dashboard pe).")
    if noted:
        parts.append("Dhyan do: " + "; ".join(noted) + ".")
    return " ".join(parts)


def register_doctor_tools(registry, base):
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification

    def run(arguments, _context):
        brain = None
        try:   # the local model server of THIS process (the dashboard); it never loads a model just to look
            from chutku.brain_service import shared_service
            brain = shared_service(base)
        except Exception:
            brain = None
        report = repair(base, fix=bool(arguments.get("fix")), brain=brain)
        report["summary"] = summary(report)
        return ToolResult(report, Verification.PASS)   # the check itself ran; "broken" rows are its findings

    registry.register(Tool(
        "system.self_repair", "Check Chutku's own health and, with fix=true, repair what is safe: lift the watchdog's "
        "own pause (never the owner's), rebuild a damaged history index or embeddings cache (the damaged copy is "
        "kept), start the local model. Everything else is only reported. 'khud ko theek karo', 'fix yourself'.",
        Risk.REVERSIBLE, run, argument_schema={"type": "object", "properties": {"fix": {"type": "boolean"}},
                                               "additionalProperties": False}))
