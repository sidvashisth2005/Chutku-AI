"""Pick the real graphics card for the local models.

This laptop has Intel Iris Xe (listed first by llama.cpp as Vulkan0) and an RTX 3050 (Vulkan1). Left alone, the
models ran partly on the Intel chip; forcing the RTX made a planner round 25-30% faster (measured 2026-10-05).
"""
from __future__ import annotations

import re
import subprocess
import threading

_cache = {}
_lock = threading.Lock()
_DEVICE = re.compile(r"^\s*(Vulkan\d+):\s*(.+?)\s*\(", re.M)
_DISCRETE = re.compile(r"nvidia|geforce|rtx|gtx|quadro|radeon rx|radeon pro|arc a\d", re.I)


def pick(listing):
    """The first discrete GPU in `llama-server --list-devices` output, else None (let llama.cpp choose)."""
    for device, name in _DEVICE.findall(listing or ""):
        if _DISCRETE.search(name):
            return device
    return None


def discrete_device(executable):
    """Cached per runtime executable; None when listing fails or there is no discrete GPU."""
    with _lock:
        if executable in _cache:
            return _cache[executable]
    try:
        done = subprocess.run([executable, "--list-devices"], capture_output=True, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        device = pick(done.stdout + done.stderr)
    except (OSError, subprocess.SubprocessError):
        device = None
    with _lock:
        _cache[executable] = device
    return device
