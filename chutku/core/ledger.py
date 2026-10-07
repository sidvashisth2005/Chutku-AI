"""Earned Autonomy (master plan S16): every step's expected result vs what was observed, and a calibrated trust score.

Each completed, failed or unverified step of a tool that changes something (risk >= 1) is recorded with a target
key (which app, site, folder or contact it acted on). The Wilson lower bound of its recent success rate tells how
much to trust the next such step: a combination that keeps failing asks first, in every mode. By default this can
only ADD asks; removing one needs the owner's explicit "earned autonomy relax on" (a user-only setting).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit

WINDOW = 50          # recent rows that count
MIN_TRIALS = 5       # fewer than this: no opinion
ASK_BELOW = 0.7      # Wilson lower bound under this: ask first ...
MIN_FAILURES = 2     # ... and only after repeated failures: 5 perfect runs give a bound of 0.566, never a reason to ask
Z = 1.96


@dataclass(frozen=True)
class Reliability:
    n: int
    passes: int
    lcb: float | None
    key: str
    recent_failures: int = 0   # failures among the last 20 (for the relax rule)


def unreliable(reliability):
    """True when the record shows this kind of step keeps failing (enough trials, low bound, repeated failures)."""
    return (reliability is not None and reliability.lcb is not None and reliability.lcb < ASK_BELOW
            and reliability.n - reliability.passes >= MIN_FAILURES)


def wilson_lower(passes, n, z=Z):
    if n <= 0:
        return 0.0
    p = passes / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def target_key(tool, arguments):
    arguments = arguments if isinstance(arguments, dict) else {}
    if tool.startswith("apps."):
        return "app:" + " ".join(str(arguments.get("name") or arguments.get("app_id") or "").casefold().split())
    if tool.startswith(("web.", "youtube.")):
        url = str(arguments.get("url") or "")
        host = urlsplit(url).hostname if url.startswith(("http://", "https://")) else None
        if host:
            parts = host.casefold().split(".")
            return "site:" + ".".join(parts[-2:])
        return "site:" + str(arguments.get("site") or tool.split(".")[0]).casefold()
    if tool.startswith(("filesystem.", "files.")):
        # The exact file (not its folder tree): "earned autonomy relax" must only ever cover the very target that
        # earned it (code review 2026-10-06; the plan's two-part root would have covered all of C:\Users).
        raw = str(arguments.get("path") or arguments.get("source") or "")
        return "file:" + "\\".join(p for p in re.split(r"[\\/]+", raw) if p).casefold()
    if tool.startswith("message."):
        name = " ".join(str(arguments.get("to") or "").casefold().split())
        return "contact:" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return "tool"


class Ledger:
    """Opens the database for each use and closes it again: no file stays locked between steps."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY, at REAL NOT NULL, tool TEXT NOT NULL, target_key TEXT NOT NULL,
                expected TEXT, observed TEXT, verdict TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'UNKNOWN')),
                seconds REAL, autonomy TEXT, surprise INTEGER NOT NULL, session_id TEXT)""")
            connection.execute("CREATE INDEX IF NOT EXISTS outcomes_key ON outcomes(tool, target_key, id)")

    def _connect(self):
        import contextlib

        @contextlib.contextmanager
        def opened():
            connection = sqlite3.connect(self.path, timeout=5)
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()
        return opened()

    def record(self, tool, key, *, expected, observed, verdict, seconds=None, autonomy=None, session_id=None):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO outcomes (at, tool, target_key, expected, observed, verdict, seconds, autonomy, surprise, "
                "session_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), tool, key, str(expected or "")[:200], str(observed or "")[:200], verdict, seconds,
                 autonomy, int(verdict != "PASS"), session_id))

    def stats(self, tool, key):
        with self._connect() as connection:
            # Only checked outcomes count: a result that could not be verified (UNKNOWN) is neither a pass nor a
            # failure (owner, 2026-10-08: an unverifiable Spotify search made every later try ask).
            rows = [v for (v,) in connection.execute(
                "SELECT verdict FROM outcomes WHERE tool = ? AND target_key = ? AND verdict != 'UNKNOWN' "
                "ORDER BY id DESC LIMIT ?", (tool, key, WINDOW))]
        n, passes = len(rows), sum(1 for v in rows if v == "PASS")
        return Reliability(n, passes, wilson_lower(passes, n) if n >= MIN_TRIALS else None, key,
                           sum(1 for v in rows[:20] if v != "PASS"))

    def table(self, limit=200):
        """Per tool and target: trials, passes, success rate and lower bound, most used first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT tool, target_key, COUNT(*), SUM(verdict = 'PASS'), MAX(at) FROM outcomes "
                "GROUP BY tool, target_key ORDER BY COUNT(*) DESC LIMIT ?", (limit,)).fetchall()
        return [{"tool": tool, "target": key, "trials": n, "passes": passes, "rate": round(passes / n, 3),
                 "lower_bound": round(wilson_lower(passes, n), 3) if n >= MIN_TRIALS else None, "last": last}
                for tool, key, n, passes, last in rows]

    def close(self):
        pass   # nothing stays open
