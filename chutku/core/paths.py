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
        if not isinstance(spec, dict) or spec.get("type") not in {"string", None}:
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


def protection_reason(target: Path) -> str | None:
    """Return why a resolved target is in a protected system zone, else None."""
    resolved = _norm(Path(target).resolve())
    exempt = [_norm((home() / "sandbox").resolve()), _norm(Path(tempfile.gettempdir()).resolve())]
    if any(_within(resolved, item) for item in exempt):
        return None
    parts = PureWindowsPath(resolved).parts
    if len(parts) >= 2 and parts[1].casefold() in _DRIVE_ROOT_DIRS:
        return f"'{parts[1]}' is a protected system area; Chutku will not modify it."
    if len(parts) == 2 and (parts[1].casefold() in _DRIVE_ROOT_FILES or parts[1].casefold().startswith("dumpstack")):
        return "Drive-root system files are protected; Chutku will not modify them."
    if len(parts) == 1:
        return "A drive root itself cannot be modified."
    if appdata_root() is None:
        # Without knowing where AppData is, its protection cannot be applied: refuse rather than guess.
        return "Chutku cannot tell where your AppData folder is, so it will not change files anywhere."
    profile = os.environ.get("USERPROFILE")
    if profile and _norm(Path(profile).resolve()) == _norm(Path(resolved).parent) and \
            PureWindowsPath(resolved).name.casefold().startswith("ntuser."):
        return "User registry hive files are protected; Chutku will not modify them."
    for zone in protected_zones():
        if _within(resolved, zone):
            return "This location is a protected system or Chutku runtime area; Chutku will not modify it."
    return None


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
