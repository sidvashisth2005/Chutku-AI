"""WA2 elevation broker (owner 2026-11-08: admin tasks through Windows' own UAC prompt; Chutku itself never elevated).

run(argv) runs ONE program with fixed arguments, built by a structured tool (never free text), through
Start-Process -Verb RunAs: the damage check runs first, the user sees Windows' prompt (and can say No), and the
output comes back through a temp file. Raw system.powershell never comes here: it always runs non-admin.
"""
from __future__ import annotations

import base64
from pathlib import Path
import subprocess
import tempfile

from chutku.core.paths import damage_in_text

TIMEOUT = 300


class ElevationRefused(PermissionError):
    pass


def _quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def command(argv, out_path):
    """The outer (non-admin) PowerShell argv: it asks Windows to run the inner script elevated and waits."""
    inner = (f"& {_quote(argv[0])} " + " ".join(_quote(a) for a in argv[1:])
             + f" *> {_quote(out_path)}; exit $LASTEXITCODE")
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    outer = ("$p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "
             f"'-NoProfile','-NonInteractive','-EncodedCommand','{encoded}'; exit $p.ExitCode")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", outer]


def run(argv, *, launch=subprocess.run, timeout=TIMEOUT):
    """(exit code, output). ElevationRefused for damage, or when the user said No to Windows' prompt."""
    if not argv or any(not isinstance(a, str) or "\n" in a or "\r" in a for a in argv):
        raise ValueError("An elevated step takes one program and plain arguments.")
    reason = damage_in_text(" ".join(argv))
    if reason:
        raise ElevationRefused(reason)
    out = Path(tempfile.mkstemp(prefix="chutku-elevated-", suffix=".txt")[1])
    try:
        try:
            done = launch(command(argv, str(out)), capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return 1, "The administrator step took too long and was stopped waiting."
        if done.returncode != 0 and "canceled by the user" in (done.stderr or "").casefold():
            raise ElevationRefused("You said No to Windows' administrator prompt, so nothing was changed.")
        try:
            output = out.read_text(encoding="utf-8", errors="replace")
        except OSError:
            output = ""
        return done.returncode, output[-4000:]
    finally:
        out.unlink(missing_ok=True)
