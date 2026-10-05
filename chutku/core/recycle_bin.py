"""Send files and folders to the real Windows Recycle Bin and restore exactly what Chutku sent.

Deleting goes through the shell (``SHFileOperationW`` with ``FOF_ALLOWUNDO``), the same path
Explorer uses. Restoring reads the item's ``$I`` record in the user's own
``<drive>\\$Recycle.Bin\\<SID>`` folder, checks the recorded original path, renames the ``$R``
data back and removes the ``$I`` record.

Safety: only fixed local drives are accepted (removable and network drives have no Recycle Bin,
so the shell would delete permanently), and ``FOF_WANTNUKEWARNING`` makes Windows ask rather than
silently destroy anything it cannot recycle.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import struct
import time

_FO_DELETE = 3
_FLAGS = 0x0004 | 0x0010 | 0x0040 | 0x0400 | 0x4000  # SILENT|NOCONFIRMATION|ALLOWUNDO|NOERRORUI|WANTNUKEWARNING
_DRIVE_FIXED = 3


class RecycleError(OSError):
    pass


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", w.HWND), ("wFunc", w.UINT), ("pFrom", w.LPCWSTR), ("pTo", w.LPCWSTR),
                ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", w.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", w.LPCWSTR)]


def _drive_type(anchor: str) -> int:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDriveTypeW.argtypes = [w.LPCWSTR]
    kernel.GetDriveTypeW.restype = w.UINT
    return int(kernel.GetDriveTypeW(anchor))


def user_sid() -> str:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    token = w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.c_void_p.from_buffer(buffer).value  # TOKEN_USER.User.Sid
        text = w.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def bin_folder(path: Path) -> Path:
    return Path(Path(path).anchor) / "$Recycle.Bin" / user_sid()


def parse_info(info: Path) -> dict:
    """Read a ``$I`` record: original path, size and deletion time (FILETIME)."""
    data = Path(info).read_bytes()
    if len(data) < 24:
        raise RecycleError("Recycle Bin record is truncated.")
    version, size, deleted = struct.unpack_from("<qqq", data, 0)
    if version == 2:
        (length,) = struct.unpack_from("<i", data, 24)
        original = data[28:28 + length * 2].decode("utf-16-le").rstrip("\x00")
    elif version == 1:
        original = data[24:24 + 520].decode("utf-16-le").split("\x00", 1)[0]
    else:
        raise RecycleError("Unknown Recycle Bin record version.")
    return {"original": original, "size": size, "deleted": deleted}


def _same(first: str, second: str) -> bool:
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(second))


def send(path: Path) -> dict:
    """Recycle one existing file or folder; return the exact ``$I``/``$R`` pair that now holds it."""
    path = Path(path)
    if not path.is_absolute() or not path.exists():
        raise RecycleError("Choose an existing file or folder.")
    if _drive_type(path.anchor) != _DRIVE_FIXED:
        raise RecycleError("This drive has no Windows Recycle Bin (removable or network); nothing was deleted.")
    folder = bin_folder(path)
    before = {item.name for item in folder.glob("$I*")} if folder.is_dir() else set()
    operation = _SHFILEOPSTRUCTW(None, _FO_DELETE, str(path) + "\x00", None, _FLAGS, False, None, None)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
    result = shell.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        raise RecycleError(f"Windows did not recycle the item (code {result}).")
    if path.exists():
        raise RecycleError("The item is still in place after recycling.")
    deadline = time.monotonic() + 5  # the shell may write a folder's $I record just after the move
    while True:
        found = _find(folder, before, path)
        if found is not None or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    if found is not None:
        return found
    raise RecycleError("The item left its folder but could not be found in the Recycle Bin.")


def _find(folder: Path, before: set[str], path: Path) -> dict | None:
    for info in folder.glob("$I*"):
        if info.name in before:
            continue
        try:
            record = parse_info(info)
        except (OSError, RecycleError):
            continue
        data = info.with_name("$R" + info.name[2:])
        if _same(record["original"], str(path)) and data.exists():
            return {"info": str(info), "data": str(data), "original": record["original"]}
    return None


def restore(info: str, data: str, original: Path) -> None:
    info, data, original = Path(info), Path(data), Path(original)
    if original.exists():
        raise RecycleError("Something already exists at the original location; nothing was overwritten.")
    if not info.is_file() or not data.exists():
        raise RecycleError("The item is no longer in the Recycle Bin (emptied or restored elsewhere).")
    if not _same(parse_info(info)["original"], str(original)):
        raise RecycleError("The Recycle Bin record does not match the original location.")
    original.parent.mkdir(parents=True, exist_ok=True)
    os.rename(data, original)
    info.unlink()


def purge(info: str, data: str) -> None:
    """Permanently remove one exact Recycle Bin item (used by tests for their own items only)."""
    import shutil
    data = Path(data)
    if data.is_dir():
        shutil.rmtree(data)
    elif data.exists():
        data.unlink()
    Path(info).unlink(missing_ok=True)
