"""Detect whether Chutku runs with an elevated (administrator) token.

Chutku must never act while elevated: running with normal rights keeps Windows' own
permissions on C:\\Windows and Program Files as a second layer behind the protected zones.
Any failure to read the token counts as elevated (fail closed).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import sys

ELEVATED_REASON = ("Chutku is running as administrator. It refuses to act while elevated, so Windows keeps "
                   "protecting system and program files. Restart Chutku normally (not 'Run as administrator').")
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS.TokenElevation


def _query_token() -> bool:
    if sys.platform != "win32":
        raise OSError("Elevation check requires Windows.")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.OpenProcessToken.restype = w.BOOL
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD,
                                           ctypes.POINTER(w.DWORD)]
    advapi.GetTokenInformation.restype = w.BOOL
    token = w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        elevated = w.DWORD()
        size = w.DWORD()
        if not advapi.GetTokenInformation(token, _TOKEN_ELEVATION, ctypes.byref(elevated),
                                          ctypes.sizeof(elevated), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(elevated.value)
    finally:
        kernel.CloseHandle(token)


def is_elevated() -> bool:
    try:
        return _query_token()
    except (OSError, AttributeError, ValueError):
        return True
