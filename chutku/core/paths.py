"""Data/model folders, protected zones, system_damage (paths that are always refused)."""
from __future__ import annotations

import functools
import os
import re
from pathlib import Path, PureWindowsPath
import tempfile


MAX_TEXT_BYTES = 64 * 1024
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


PATH_ARGUMENTS = ("path", "source", "destination")
_PATH_NAME = re.compile(r"(^|_)(path|paths|folder|directory|dir|file|source|destination|target|output|location)$")
CODE_ROOT = Path(__file__).resolve().parents[2]   # the code folder: chutku/, vendor/, bundled models, web, docs


# -- W2: where Chutku keeps its state ----------------------------------------------------------------------------
# The owner's PC runs from a git checkout with data/ inside it, and keeps doing so unchanged. An installed package
# keeps the user's data in %LOCALAPPDATA%/Chutku, so the app folder is never written to and an upgrade can replace it.

def is_checkout() -> bool:
    """Running from a git checkout (a developer or the owner's PC), not from an installed package."""
    return (CODE_ROOT / ".git").exists()


def home() -> Path:
    """Chutku's state root: CHUTKU_HOME if set; else the repo root in a git checkout; else %LOCALAPPDATA%/Chutku."""
    configured = os.environ.get("CHUTKU_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if is_checkout():
        return CODE_ROOT
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return Path(local) / "Chutku"


def data_dir() -> Path:
    return home() / "data"


def models_dir() -> Path:
    return home() / "models"


def resource(base, relative) -> Path:
    """A file Chutku reads that may be bundled with the app (models/manifest.json, vendor/, the essential models).

    For the real home, a file missing there is taken from the code folder. A test's own base never falls back, so
    tests see exactly the files they made. In a git checkout home and code are the same folder."""
    path = Path(base) / relative
    if path.exists() or Path(base).resolve() != home().resolve():
        return path
    return CODE_ROOT / relative


def model_file(base, relative, *, nested=False):
    """The resolved path of a model named in models/manifest.json, or None when it leaves the models folders.

    Allowed: <base>/models (downloads) and the bundled <code>/models. nested=False wants a file or folder directly
    inside models/; nested=True allows sub-folders (e.g. models/embed/model.onnx)."""
    if not relative or Path(str(relative)).is_absolute():
        return None
    path = resource(base, str(relative)).resolve()
    roots = {(Path(base) / "models").resolve(), (CODE_ROOT / "models").resolve()}
    inside = any(path.is_relative_to(root) and path != root for root in roots) if nested else path.parent in roots
    return path if inside else None

_DRIVE_ROOT_DIRS = {"windows", "program files", "program files (x86)", "programdata", "system volume information",
                    "$recycle.bin", "recovery", "boot", "efi", "config.msi", "$windows.~bt", "$windows.~ws",
                    "$winreagent", "msocache", "perflogs", "documents and settings"}
_DRIVE_ROOT_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "bootmgr", "bootnxt", "dumpstack.log",
                     "dumpstack.log.tmp"}


def path_argument_names(tool) -> set[str]:
    """Arguments of a tool that name filesystem locations, found from its schema rather than a fixed list."""
    properties = (tool.argument_schema or {}).get("properties", {})
    names = {key for key in PATH_ARGUMENTS if key in properties or tool.argument_schema is None}
    for key, spec in properties.items():
        kinds = spec.get("type") if isinstance(spec, dict) else None
        kinds = set(kinds) if isinstance(kinds, list) else {kinds}   # "type": ["integer", "string"] (registry.set_user)
        if not isinstance(spec, dict) or not kinds & {"string", None}:   # crashed the action log on Windows (2026-11-08)
            continue
        if spec.get("format") == "path" or _PATH_NAME.search(key.casefold()):
            names.add(key)
    return names


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _within(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)


_ROAMING_APPDATA = "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}"   # FOLDERID_RoamingAppData


@functools.lru_cache(maxsize=4)
def _known_folder(guid: str) -> str | None:
    """A Windows known folder from the shell (not from environment variables, which a process can change)."""
    if os.name != "nt":
        return None
    import ctypes
    import uuid
    try:
        raw = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
        found = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        if shell32.SHGetKnownFolderPath(ctypes.byref(raw), 0, None, ctypes.byref(found)) != 0:
            return None
        try:
            return found.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(found)
    except (OSError, ValueError, AttributeError):
        return None


def appdata_root() -> str | None:
    """The user's AppData folder: from the shell's known folder, else %USERPROFILE%; None if neither is known."""
    roaming = _known_folder(_ROAMING_APPDATA)
    if roaming:
        return str(Path(roaming).parent)
    profile = os.environ.get("USERPROFILE")
    return os.path.join(profile, "AppData") if profile else None


def protected_zones() -> list[str]:
    """Code-owned system areas Chutku may observe but never modify."""
    zones = []
    for name in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                 "ProgramData", "CommonProgramFiles", "CommonProgramFiles(x86)"):
        value = os.environ.get(name)
        if value:
            zones.append(value)
    appdata = appdata_root()
    if appdata:
        zones.append(appdata)
    profile = os.environ.get("USERPROFILE")
    if profile and _norm(os.path.join(profile, "AppData")) != _norm(appdata or ""):
        zones.append(os.path.join(profile, "AppData"))
    zones.append(str(CODE_ROOT))
    zones.append(str(home()))   # W2: the user's data folder is Chutku's own runtime area too
    result = []
    for zone in zones:
        try:
            result.append(_norm(Path(zone).resolve()))
        except OSError:
            result.append(_norm(zone))
    return sorted(set(result))


def _env_zone(*names):
    return [_norm(Path(os.environ[name]).resolve()) for name in names if os.environ.get(name)]


def system_damage(target: Path, op: str = "write") -> str | None:
    """WA1 (owner 2026-11-08, "never refuse except system damage"): why changing `target` could damage Windows or
    Chutku itself, else None. Always refused, in every mode, with any approval.
    op: "write" (create or overwrite), "delete" or "move" (the source of a move or rename)."""
    resolved = _norm(Path(target).resolve())
    state, sandbox = _norm(home().resolve()), _norm((home() / "sandbox").resolve())
    if _within(resolved, sandbox):
        return None
    if not _within(resolved, state) and _within(resolved, _norm(Path(tempfile.gettempdir()).resolve())):
        return None   # TEMP, as before WA1 (a CHUTKU_HOME inside TEMP stays protected)
    if appdata_root() is None:   # fail closed first: without AppData, Chutku's own data cannot be located safely
        return "Chutku cannot tell where your AppData folder is, so it will not change files there or elsewhere."
    for zone in (_norm(CODE_ROOT.resolve()), state):   # Chutku's code, grants and rules: never by itself
        if _within(resolved, zone):
            return "This is Chutku's own program or settings folder; it cannot change itself."
    parts = PureWindowsPath(resolved).parts
    if len(parts) == 1:
        return "A drive root itself cannot be changed."
    if len(parts) == 2 and (parts[1].casefold() in _DRIVE_ROOT_FILES or parts[1].casefold().startswith("dumpstack")):
        return "Windows' own files at the drive root are never changed (it could stop Windows from starting)."
    top = parts[1].casefold() if len(parts) >= 2 else ""
    for zone in _env_zone("SystemRoot", "windir"):
        if _within(resolved, zone):
            return "Windows' own folder is never changed: it could stop Windows from working."
    if top in {"windows", "boot", "efi", "recovery", "system volume information", "$windows.~bt", "$windows.~ws",
               "$winreagent", "config.msi"}:
        return f"'{parts[1]}' belongs to Windows or its start-up; it is never changed."
    programs = _env_zone("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "CommonProgramFiles",
                         "CommonProgramFiles(x86)")
    if op in {"delete", "move"} and (top in {"program files", "program files (x86)", "programdata"}
                                     or any(_within(resolved, zone) for zone in programs)):
        return "Installed programs are not deleted or moved file by file; say \"uninstall <app>\" instead."
    profile = os.environ.get("USERPROFILE")
    if profile and _norm(Path(profile).resolve()) == _norm(Path(resolved).parent) and \
            PureWindowsPath(resolved).name.casefold().startswith("ntuser."):
        return "Your Windows profile's registry files are never changed."
    return None


def sensitive_reason(target: Path) -> str | None:
    """WA1: not damage, but an app's own files (Program Files, ProgramData, AppData): asks the first time."""
    resolved = _norm(Path(target).resolve())
    if _within(resolved, _norm((home() / "sandbox").resolve())):   # Chutku's own scratch folder (inside AppData
        return None                                                 # in an installed app)
    if _within(resolved, _norm(Path(tempfile.gettempdir()).resolve())) and not _within(resolved, _norm(home().resolve())):
        return None   # TEMP (inside AppData\\Local) was always free to use
    zones = _env_zone("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "CommonProgramFiles",
                      "CommonProgramFiles(x86)")
    appdata = appdata_root()
    if appdata:
        zones.append(_norm(Path(appdata).resolve()))
    parts = PureWindowsPath(resolved).parts
    if any(_within(resolved, zone) for zone in zones) or (len(parts) >= 2 and parts[1].casefold() in _DRIVE_ROOT_DIRS):
        return "This changes an installed app's own files or settings; confirm it the first time."
    return None


# PowerShell and scripts can hide damage: this text check is the first filter; raw PowerShell also runs non-admin
# (Windows itself then protects system files). WA1 hardening 1.
_SYSTEM_PATH = r"(?:%systemroot%|%windir%|\$env:(?:systemroot|windir)|[a-z]:\\+(?:windows|boot|efi|recovery)\b|system32|syswow64|winsxs)"
_DAMAGE_TEXT = [re.compile(p, re.I) for p in (
    r"\bformat(?:\.com)?\s+[a-z]:",
    r"\b(?:format-volume|clear-disk|initialize-disk|remove-partition|diskpart|bcdedit|bcdboot)\b",
    r"\b(?:remove-item|del|erase|rd|rmdir|rm|ri|move-item|mv|rename-item|ren)\b[^|;]*" + _SYSTEM_PATH,
    r"\b(?:takeown|icacls|cacls)\b[^|;]*" + _SYSTEM_PATH,
    r"\breg(?:\.exe)?\s+(?:delete|add|import)\s+(?:hklm|hkey_local_machine)",
    r"\b(?:remove-item(?:property)?|set-itemproperty|new-itemproperty)\b[^|;]*hklm:",
    r"\bset-mppreference\b[^|;]*-disable", r"\bnetsh\s+advfirewall\s+set\s+\S+\s+state\s+off",
    r"\bset-netfirewallprofile\b[^|;]*-enabled\s+(?:\$?false|0)", r"\bsecedit\b|\bauditpol\b[^|;]*/clear",
    r"\bshutil\.rmtree\s*\([^)]*(?:windows|system32|program files)", r"\bos\.(?:remove|unlink|rmdir)\s*\([^)]*(?:windows|system32)",
)]


def damage_in_text(text: str) -> str | None:
    """A PowerShell command or a script whose text would damage Windows (format, bcdedit, deleting system files,
    HKLM deletes, turning Defender or the firewall off); None otherwise."""
    for pattern in _DAMAGE_TEXT:
        if pattern.search(str(text or "")):
            return ("That command could damage Windows (system files, start-up, security or a whole drive), so I "
                    "won't run it. Tell me what you want to achieve and I'll find a safe way.")
    return None


def protection_reason(target: Path, op: str = "write") -> str | None:
    """Why `target` may never be changed (WA1: the system-damage list), else None."""
    return system_damage(target, op)


def sandbox_target(root: Path, raw: str) -> Path:
    """Reject ambiguous Windows names and existing aliases before accessing a file.

    Absolute paths are accepted only when they lie inside the granted root.
    This is a bounded application guard, not a hostile-process filesystem sandbox.
    A process with access to the root could still race path checks.
    """
    if not isinstance(raw, str):
        raise ValueError("path must be a string.")
    windows = PureWindowsPath(raw)
    if windows.drive or windows.root:
        if not windows.drive or not windows.root or windows.drive.startswith("\\\\") or ".." in windows.parts:
            raise ValueError("Path is outside the granted root or is not a plain local absolute path.")
        root_windows = PureWindowsPath(str(root))
        if not _within(_norm(str(windows)), _norm(str(root_windows))):
            raise ValueError("Path is outside the granted root.")
        relative = windows.relative_to(windows.anchor).parts[len(root_windows.relative_to(root_windows.anchor).parts):]
        windows = PureWindowsPath(*relative) if relative else PureWindowsPath(".")
    if ".." in windows.parts:
        raise ValueError("Path is outside the granted sandbox root or is not relative.")
    parts = windows.parts
    for part in parts:
        if (part.rstrip(" .") != part or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or part.split(".")[0].upper() in _RESERVED
                or part.split(".")[0].upper() in {"COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}):
            raise ValueError("Unsupported Windows filename (device name, alternate stream or ambiguous path).")
    current = root
    for part in (None, *parts):
        if part is not None:
            current = current / part
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Reparse points and symbolic links are not allowed in the sandbox path.")
        if current.is_file() and current.stat().st_nlink > 1:
            raise ValueError("Hard-linked files are not allowed in the sandbox.")
    target = current.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path is outside the granted sandbox root.")
    return target


def read_bounded_text(path: Path) -> str:
    with path.open("rb") as stream:
        data = stream.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError(f"File exceeds the {MAX_TEXT_BYTES}-byte safe read limit.")
    return data.decode("utf-8")


def atomic_write_text(path: Path, content: str) -> None:
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError(f"Text exceeds the {MAX_TEXT_BYTES}-byte write limit.")
    descriptor, name = tempfile.mkstemp(prefix=".chutku-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def user_folder(name: str) -> str:
    """Chutku's own working folder (projects, phone inbox, scratch): D:/<name> when that folder already exists
    (the original owner's setup, whose C: is nearly full), otherwise %USERPROFILE%/<name> for everyone else."""
    second_drive = Path("D:\\") / name
    if second_drive.is_dir():
        return str(second_drive)
    return str(Path(os.environ.get("USERPROFILE") or Path.home()) / name)
