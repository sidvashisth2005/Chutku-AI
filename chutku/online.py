"""Is the internet (Google's Gemini endpoint) reachable right now? A quick, cached check so offline Chutku goes
straight to its local models instead of waiting for network timeouts."""
from __future__ import annotations

import socket
import threading
import time

GEMINI_HOST = "generativelanguage.googleapis.com"
TTL_SECONDS = 30
_cache = {}
_lock = threading.Lock()


def offline_mode(base=None):
    """The owner's switch ("offline mode on"): local models only, even with internet. CHUTKU_OFFLINE=1 does the same."""
    import os
    if os.environ.get("CHUTKU_OFFLINE") == "1":
        return True
    from pathlib import Path
    from chutku.core.preferences import Preferences
    try:
        return bool(Preferences(Path(base) if base else Path(__file__).resolve().parents[1]).load()
                    .get("offline_mode", False))
    except (OSError, ValueError):
        return False


def reachable(host=GEMINI_HOST, *, port=443, timeout=2.0, now=None):
    if host == GEMINI_HOST and offline_mode():
        return False
    now = now or time.monotonic()
    with _lock:
        hit = _cache.get(host)
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ok = True
    except OSError:
        ok = False
    with _lock:
        _cache[host] = (now, ok)
    return ok


def forget():
    with _lock:
        _cache.clear()
