"""Episodic timeline (master plan S21): "wo PDF jo kal shaam khola tha". Opt-in, metadata only.

While the owner has switched it on ("timeline on", typed), the running dashboard notes every 5 seconds which app and
window title is in front, when it changes, in data/timeline.sqlite. Nothing else: no screenshots, no window contents,
no keystrokes. Rows older than 14 days are deleted. Titles of private windows (InPrivate / Incognito / private
browsing, password managers, and any app the owner names in the ``timeline_private`` preference) are stored as
"[private]".

``search`` answers "which PDF did I open yesterday evening" from these rows plus the files Chutku itself opened
(action log). Window titles are outside text: the tool's output taints the session like any other read content.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import threading
import time

KEEP_DAYS = 14
TICK_SECONDS = 5
PRIVATE_TITLE = re.compile(r"\b(?:inprivate|incognito|private browsing|private window)\b", re.I)
PRIVATE_APPS = {"1password.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe", "dashlane.exe", "lastpass.exe",
                "credentialuibroker.exe", "lockapp.exe", "logonui.exe"}
_IGNORED = {"", "program manager", "task switching", "windows input experience", "start", "search"}
_STOP = {"the", "a", "an", "of", "in", "on", "my", "me", "i", "ko", "ka", "ki", "ke", "jo", "tha", "thi", "wo", "woh",
         "vo", "which", "what", "was", "did", "open", "opened", "khola", "kholi", "dekha", "dekhi", "kaunsa", "kaun",
         "si", "sa", "file", "that", "is", "abhi", "kal", "aaj", "shaam", "subah", "raat", "yesterday", "today",
         "evening", "morning", "night", "last", "week", "just", "now", "look", "looked", "at", "had", "have"}
_lock = threading.Lock()


def path(base):
    return Path(base) / "data" / "timeline.sqlite"


def _connect(base):
    file = path(base)
    file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(file, timeout=5)
    connection.execute("CREATE TABLE IF NOT EXISTS moments (at REAL NOT NULL, app TEXT NOT NULL, title TEXT NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS moments_at ON moments(at)")
    return connection


def enabled(base):
    from chutku.core.preferences import Preferences
    return Preferences(base).load().get("timeline") is True


def private_apps(base):
    from chutku.core.preferences import Preferences
    named = Preferences(base).load().get("timeline_private") or []
    return PRIVATE_APPS | {str(n).casefold() for n in named}


def clean(app, title, private):
    """(app, title) as stored: the exe name only, and "[private]" for private windows."""
    name = PureWindowsPath(app or "").name.casefold()
    title = " ".join(str(title or "").split())[:300]
    if name in private or PRIVATE_TITLE.search(title):
        title = "[private]"
    return name, title


def record(base, app, title, at=None):
    """Store one moment (the caller checks that the timeline is on). Returns False for ignored windows."""
    name, title = clean(app, title, private_apps(base))
    if title.casefold() in _IGNORED or not name:
        return False
    with _lock:
        connection = _connect(base)
        try:
            connection.execute("INSERT INTO moments (at, app, title) VALUES (?, ?, ?)", (at or time.time(), name, title))
            connection.commit()
        finally:
            connection.close()
    return True


def expire(base, now=None):
    cutoff = (now or time.time()) - KEEP_DAYS * 86400
    with _lock:
        connection = _connect(base)
        try:
            removed = connection.execute("DELETE FROM moments WHERE at < ?", (cutoff,)).rowcount
            connection.commit()
            return removed
        finally:
            connection.close()


def clear(base):
    """"timeline off" keeps nothing: the stored moments are deleted with it."""
    with _lock:
        path(base).unlink(missing_ok=True)


def watch(base, stop, tick=TICK_SECONDS):
    """Dashboard thread: note the foreground window whenever it changes, only while the timeline is on."""
    from chutku.core.log import get_logger
    from chutku.tools.everyday import Desktop
    log = get_logger("timeline")
    desktop, last, last_expiry = Desktop(), None, 0.0
    while not stop.wait(tick):
        try:
            if not enabled(base):
                last = None
                continue
            hwnd = desktop.foreground()
            if not hwnd:
                continue
            info = desktop.describe(hwnd)
            current = (info.get("executable") or "", info.get("title") or "")
            if current != last:
                record(base, *current)
                last = current
            if time.time() - last_expiry > 3600:
                expire(base)
                last_expiry = time.time()
        except Exception:
            log.exception("timeline tick failed")


# -- asking -----------------------------------------------------------------------------------------------------------

def window(when, now=None):
    """(start, end) datetimes for "kal shaam", "yesterday evening", "today", "abhi", "last week", ... (None: 14 days)."""
    now = now or datetime.now()
    text = (when or "").casefold()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\b(?:abhi|just now|right now|recently|thodi der pehle)\b", text):
        return now - timedelta(minutes=30), now
    if re.search(r"\b(?:last week|pichh?le hafte|this week|is hafte)\b", text):
        return day - timedelta(days=7), now
    if re.search(r"\b(?:kal|yesterday)\b", text):
        start, end = day - timedelta(days=1), day
    elif re.search(r"\b(?:parso|day before yesterday)\b", text):
        start, end = day - timedelta(days=2), day - timedelta(days=1)
    elif re.search(r"\b(?:aaj|today|this)\b", text):
        start, end = day, now
    else:
        start, end = now - timedelta(days=KEEP_DAYS), now
    for words, (h1, h2) in ((r"subah|morning", (5, 12)), (r"dopahar|dophar|afternoon", (12, 17)),
                            (r"shaam|sham|evening", (16, 21)), (r"raat|night", (20, 24))):
        if re.search(rf"\b(?:{words})\b", text):
            base = start.replace(hour=0)
            return base + timedelta(hours=h1), min(base + timedelta(hours=h2), now)
    return start, end


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", str(text).casefold()) if w not in _STOP and len(w) > 1}


_KINDS = {"pdf": (".pdf", "acrobat", "pdf"), "word": (".docx", ".doc", "word"), "excel": (".xlsx", ".xls", "excel"),
          "powerpoint": (".pptx", ".ppt", "powerpoint"), "ppt": (".pptx", ".ppt", "powerpoint"),
          "video": (".mp4", ".mkv", "vlc", "youtube"), "photo": (".jpg", ".jpeg", ".png", "photos")}


def search(base, query="", when=None, limit=8, runtime=None, now=None):
    """Moments in the time window whose app/title fit the query, best first (newest first on ties)."""
    start, end = window(when, now)
    wanted = _words(query)
    kinds = [hint for word in wanted for hint in _KINDS.get(word, ())]
    rows = []
    if path(base).exists():
        with _lock:
            connection = _connect(base)
            try:
                rows = connection.execute("SELECT at, app, title FROM moments WHERE at >= ? AND at <= ? ORDER BY at",
                                          (start.timestamp(), end.timestamp())).fetchall()
            finally:
                connection.close()
    if runtime is not None:   # files Chutku opened for the owner are part of the story too
        stamp = start.astimezone().isoformat(timespec="seconds")
        for entry in runtime.action_log.recent(500):
            if entry.get("tool") == "files.open" and entry.get("state") == "COMPLETED" and entry.get("paths"):
                at = datetime.fromisoformat(entry["time"]).timestamp()
                if start.timestamp() <= at <= end.timestamp():
                    rows.append((at, "chutku:files.open", entry["paths"][0]))
    scored = {}
    for at, app, title in rows:
        if title == "[private]":
            continue
        haystack = f"{app} {title}".casefold()
        score = len(wanted & _words(haystack)) + (2 if kinds and any(k in haystack for k in kinds) else 0)
        if wanted and score == 0:
            continue
        key = (app, title)
        if key not in scored or (score, at) > (scored[key][0], scored[key][1]):
            scored[key] = (score, at)
    best = sorted(scored.items(), key=lambda item: (-item[1][0], -item[1][1]))[:limit]
    return {"window": [start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")],
            "matches": [{"title": title, "app": app, "at": datetime.fromtimestamp(at).strftime("%a %d %b, %I:%M %p")}
                        for (app, title), (_score, at) in best],
            "recording": enabled(base)}
