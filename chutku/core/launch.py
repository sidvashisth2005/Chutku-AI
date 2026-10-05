"""Start the owner's apps so they outlive Chutku.

The guard runs Chutku inside a Windows kill-on-close job, so a stop or crash also ends every process Chutku started.
That is right for Chutku's own helpers (the local model server, the OCR worker), but not for the browser, VS Code or
an app the owner asked for: those are started here with CREATE_BREAKAWAY_FROM_JOB (the guard's job allows it).
"""
from __future__ import annotations

import subprocess

CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def popen_user_app(argv, **kwargs):
    """subprocess.Popen for an app the owner keeps using; falls back to a normal start if breakaway is refused."""
    flags = kwargs.pop("creationflags", 0)
    try:
        return subprocess.Popen(argv, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        return subprocess.Popen(argv, creationflags=flags, **kwargs)
