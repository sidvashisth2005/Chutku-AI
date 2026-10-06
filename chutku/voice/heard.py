"""Only real speech counts: a noise gate for the live conversation, a shared transcript filter, and a local
"what I heard" log (owner report 2026-10-04: "Chutku listens to random noises that aren't there").

- NoiseGate: learns the room's noise floor; a 40-100 ms chunk passes only when it is clearly louder than the floor
  (and much louder while Chutku itself is talking, so its own voice and echoes never count). A short hangover keeps
  word endings, and a little pre-roll keeps word beginnings.
- meaningful(text): False for what speech-to-text invents from noise ("Thank you.", "Thanks for watching!",
  subtitle credits, lone fillers, repeated words, bracketed [noise] tags); real short commands ("agla gaana",
  "haan", "ruko") pass.
- log_heard(): data/heard.jsonl, local only, last 7 days: what was heard, on which path, and what Chutku did with
  it, so false triggers can be seen on the dashboard and fixed.
"""
from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path
import re
import threading
import time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLOOR_MIN, OPEN_RATIO, SPEAKING_FLOOR, SPEAKING_RATIO = 0.008, 3.0, 0.03, 2.5
HANGOVER_SECONDS, PREROLL_SECONDS = 0.5, 0.2
KEEP_DAYS = 7
_pruned_day = None


def rms(chunk):
    from array import array
    samples = array("h", chunk)
    return math.sqrt(sum(v * v for v in samples) / max(len(samples), 1)) / 32768


class NoiseGate:
    """Decides, chunk by chunk, whether the microphone carries speech worth sending."""

    def __init__(self, chunk_seconds=0.04):
        self.chunk_seconds = chunk_seconds
        self.floor = 0.002
        self.recent = deque(maxlen=max(1, int(3.0 / chunk_seconds)))     # 3 s of levels
        self.hangover = 0
        self.preroll = deque(maxlen=max(1, int(PREROLL_SECONDS / chunk_seconds)))
        self.speech_seconds = 0.0          # loud, gated-open audio since the last reset

    def threshold(self, speaking=False):
        base = max(self.floor * OPEN_RATIO, FLOOR_MIN)
        return max(base * SPEAKING_RATIO, SPEAKING_FLOOR) if speaking else base

    def feed(self, chunk, speaking=False):
        """Returns the chunks to send as audio (pre-roll + this one) or [] when the chunk is noise."""
        level = rms(chunk)
        self.recent.append(level)
        # The floor follows quiet moments quickly and a sustained noise rise slowly (a fan switching on must not
        # leave the gate stuck open): the quietest level of the last 3 s pulls it up.
        if level < self.threshold():
            self.floor = 0.95 * self.floor + 0.05 * level
        if len(self.recent) == self.recent.maxlen:   # only with a full 3 s window: the first word is not "noise"
            self.floor = max(self.floor, min(self.recent) * 0.9)
        if level >= self.threshold(speaking):
            self.hangover = int(HANGOVER_SECONDS / self.chunk_seconds)
            self.speech_seconds += self.chunk_seconds
            out = list(self.preroll) + [chunk]
            self.preroll.clear()
            return out
        if self.hangover > 0:
            self.hangover -= 1
            return [chunk]
        self.preroll.append(chunk)
        return []

    def reset_speech(self):
        self.speech_seconds = 0.0


# -- what speech-to-text invents from noise --------------------------------------------------------------

_INVENTED = re.compile(
    r"^(?:thank(?:s| you)(?: (?:so|very) much)?(?: for (?:watching|listening))?|please subscribe|subscribe"
    r"|(?:like and )?subscribe(?: to (?:my|the) channel)?|subtitles? by .*|.*amara\.org.*|transcribed by .*"
    r"|you|bye(?: bye)?|the end|music|applause|silence|laughter|i'?m sorry|sorry|oh|uh|um|hmm+|mm+|ah+|huh"
    r"|okay|ok|so|yeah|yes|no|hey|hello|hi|ha+|he+|wow|see you(?: next time| later)?)$", re.I)
_TAG = re.compile(r"^[\[(（【♪*].*[\])）】♪*]$|^[♪\s.]+$")


def _clean(text):
    from chutku.translit import roman
    return " ".join(re.sub(r"[^\w\s']", " ", roman(text or "").casefold()).split())


def meaningful(text, *, short_answers_ok=False):
    """Could this transcript be something the owner really said to Chutku?

    short_answers_ok: in an approval moment "haan" / "ok" / "no" are real answers, so lone yes/no words pass."""
    raw = (text or "").strip()
    if not raw or _TAG.match(raw):
        return False
    words = _clean(raw).split()
    if not words or len("".join(words)) < 2:
        return False
    if len(words) >= 3 and len(set(words)) <= max(1, len(words) // 3):
        return False  # "you you you you" / "thank you thank you thank you"
    phrase = " ".join(words)
    if _INVENTED.match(phrase):
        if short_answers_ok and phrase in {"yes", "no", "okay", "ok", "hmm", "yeah"}:
            return True
        return False
    return True


# -- the local "what I heard" log ------------------------------------------------------------------------

_log_lock = threading.Lock()


def heard_path(base=None):
    return Path(base or PROJECT_ROOT) / "data" / "heard.jsonl"


def log_heard(path_name, text, decision, *, level=None, confidence=None, base=None):
    """Append one line (local only). Older than KEEP_DAYS is dropped when the file grows past 1 MB."""
    from chutku.core.preferences import Preferences
    if base is None and _under_test():
        return  # a test run must never write into the owner's real log
    try:
        if not Preferences(Path(base or PROJECT_ROOT)).load().get("heard_log", True):
            return
    except (OSError, ValueError):
        pass
    row = {"at": time.time(), "path": path_name, "text": str(text or "")[:300], "decision": decision}
    if level is not None:
        row["level"] = round(float(level), 4)
    if confidence is not None:
        row["confidence"] = round(float(confidence), 3)
    file = heard_path(base)
    with _log_lock:
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            global _pruned_day
            today = time.strftime("%Y-%m-%d")
            if file.stat().st_size > 1_000_000 or _pruned_day != today:   # by age at least once a day, not only by size
                _pruned_day = today
                _prune_file(file)
        except OSError:
            pass  # the log is a diagnostic aid, never a reason to fail


def _prune_file(file):
    """Keep the last KEEP_DAYS (at most 5000 lines). Returns how many lines were dropped."""
    cutoff = time.time() - KEEP_DAYS * 86400
    lines = file.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if _at(line) >= cutoff][-5000:]
    file.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return len(lines) - len(kept)


def prune(base=None):
    """Night Shift (S20): prune the heard log even on days nothing was heard."""
    file = heard_path(base)
    with _log_lock:
        try:
            return _prune_file(file) if file.exists() else 0
        except OSError:
            return 0


def _under_test():
    """True inside a test run, however it was started (python -m unittest, scripts/verify_release.py ...)."""
    import os
    import sys
    if os.environ.get("CHUTKU_HEARD_LOG") == "0" or "unittest" in str(sys.argv[0]):
        return True
    return "unittest" in sys.modules and any(name.startswith("test_") or name.startswith("tests.")
                                             for name in list(sys.modules))


def _at(line):
    try:
        return float(json.loads(line).get("at", 0))
    except (ValueError, AttributeError):
        return 0.0


def recent_heard(limit=50, base=None):
    try:
        lines = heard_path(base).read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    rows = []
    for line in reversed(lines):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows
