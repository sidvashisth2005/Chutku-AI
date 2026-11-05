"""What Chutku knows about how the owner uses this PC (owner, 2026-11-01: "she must learn from what I do and play
regularly... an assistant makes my work easy, not a child I have to teach everything").

Built locally, refreshed at start-up and every night, kept in data/ only. It is never put in what the cloud brain
sees (browsing history above all).
- media: every video in the owner's media folders, grouped into series with episode numbers
  (D:\\SID\\Tele\\Baki\\26 The Centennial Tournament.mkv -> Baki, episode 26), plus VLC's own watch history
  (which episode was last played and where it stopped), so "baki ka next episode chalao" just works;
- apps: how often each program is launched (Windows' own UserAssist counts, no admin needed);
- sites: the domains visited most in Brave over the last 30 days (local copy of its History database), so
  "open <site>" finds the owner's usual site.
"""
from __future__ import annotations

import codecs
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIDEO = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".m4v", ".wmv", ".flv", ".ts"}
SKIP_DIRS = {"windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin",
             "system volume information", "node_modules", ".git", ".venv", "site-packages"}
_lock = threading.Lock()


def _file(base):
    return Path(base or PROJECT_ROOT) / "data" / "know_me.json"


def load(base=None):
    try:
        return json.loads(_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# -- media --------------------------------------------------------------------------------------------------------

def media_roots(base=None, extra=()):
    from chutku.core.preferences import Preferences
    home = Path(os.environ.get("USERPROFILE", "C:/Users/Public"))
    own = Preferences(Path(base or PROJECT_ROOT)).load()["media_folders"]   # e.g. the owner's D:\SID
    roots = [home / "Videos", home / "Downloads", home / "Downloads" / "Telegram Desktop", *map(Path, own),
             Path("D:/Videos"), Path("D:/Movies"), Path("D:/Anime"), *map(Path, extra)]
    for path in vlc_recent_paths():            # wherever the owner actually plays things from
        roots.append(path.parent.parent if path.parent.parent != path.parent else path.parent)
    seen, out = set(), []
    for root in roots:
        key = str(root).casefold()
        if key not in seen and root.is_dir():
            seen.add(key)
            out.append(root)
    return out


_EPISODE = [re.compile(r"\b[sS](\d{1,2})\s*[eE](\d{1,3})\b"),                 # S01E05
            re.compile(r"\b(?:ep|episode|e)\s*\.?\s*(\d{1,3})\b", re.I),     # Ep 5 / Episode 05
            re.compile(r"^\s*(\d{1,3})(?=[\s._\-\])])"),                     # "26 The Centennial ..."
            re.compile(r"[\s_\-\[(]+(\d{1,3})(?=[\s._\-\])\]]|$)")]          # "Baki - 26" / "Baki [26]"


def episode_of(name):
    stem = Path(name).stem
    for index, pattern in enumerate(_EPISODE):
        found = pattern.search(stem)
        if found:
            number = int(found.group(2) if index == 0 else found.group(1))
            if 0 < number < 2000 and not re.search(r"\b(?:480|720|1080|2160)p?\b", found.group(0)):
                return number
    return None


def series_of(path, root):
    """The show's name: the folder under a media root (D:\\SID\\Tele\\Baki -> Baki), else the file's own title."""
    parent = path.parent
    if parent != root and parent.name.casefold() not in {"telegram desktop", "downloads", "videos", "tele"}:
        return parent.name
    stem = re.sub(r"\[[^\]]*\]|\([^)]*\)|@\w+", " ", path.stem)              # [@Anime_RTX] [1080p] (2026) tags
    stem = re.sub(r"\b(?:ep|episode)\s*\.?\s*\d{1,3}\b", " ", stem, flags=re.I)   # "Ep 8 Bleach" -> "Bleach"
    title = re.split(r"\b[sS]\d{1,2}[eE]\d|\s-\s\d|[._ ](?:19|20)\d\d[._ ]|[._ ]\d{3,4}p\b", stem)[0]
    return re.sub(r"[._]+", " ", title).strip(" -") or path.stem


def scan_media(roots, *, max_depth=4, max_files=20000):
    library = {}
    count = 0
    for root in roots:
        for folder, dirs, files in os.walk(root):
            depth = len(Path(folder).relative_to(root).parts)
            dirs[:] = [d for d in dirs if d.casefold() not in SKIP_DIRS and depth < max_depth]
            for name in files:
                if Path(name).suffix.casefold() not in VIDEO:
                    continue
                path = Path(folder) / name
                show = series_of(path, root)
                entry = library.setdefault(show, {"folder": str(path.parent), "episodes": {}, "extras": []})
                number = episode_of(name)
                if number is None:
                    entry["extras"].append(str(path))
                else:
                    entry["episodes"].setdefault(str(number), str(path))
                count += 1
                if count >= max_files:
                    return library
    return library


def vlc_ini():
    return Path(os.environ.get("APPDATA", "")) / "vlc" / "vlc-qt-interface.ini"


def vlc_history():
    """[(path, stopped_at_ms)] newest first, from VLC's own recent-media list (0 = played to the end or new)."""
    try:
        text = vlc_ini().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    section = text.split("[RecentsMRL]", 1)[-1] if "[RecentsMRL]" in text else ""
    items = re.search(r"^list=(.*)$", section, re.M)
    times = re.search(r"^times=(.*)$", section, re.M)
    paths = [unquote(p.strip().removeprefix("file:///")).replace("/", "\\") for p in (items.group(1) if items else "").split(", ")
             if p.strip().startswith("file:///")]
    stops = [int(t) if t.strip().lstrip("-").isdigit() else 0 for t in (times.group(1) if times else "").split(",")]
    return [(Path(p), stops[i] if i < len(stops) else 0) for i, p in enumerate(paths)]


def vlc_recent_paths():
    return [path for path, _ in vlc_history()]


def progress(library, history):
    """{series: {"last": n, "stopped_ms": t, "file": path}} from VLC's history (newest first wins)."""
    where = {}
    for show, entry in library.items():
        for number, path in entry["episodes"].items():
            where[str(Path(path)).casefold()] = (show, int(number))
    out = {}
    for path, stopped in history:
        hit = where.get(str(path).casefold())
        if hit and hit[0] not in out:
            out[hit[0]] = {"last": hit[1], "stopped_ms": max(0, stopped), "file": str(path)}
    return out


# -- apps (Windows UserAssist) ------------------------------------------------------------------------------------

def frequent_apps(limit=25):
    try:
        import winreg
    except ImportError:
        return []
    counts = {}
    root = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as guids:
            for index in range(winreg.QueryInfoKey(guids)[0]):
                guid = winreg.EnumKey(guids, index)
                try:
                    with winreg.OpenKey(guids, guid + r"\Count") as key:
                        for value in range(winreg.QueryInfoKey(key)[1]):
                            name, data, _kind = winreg.EnumValue(key, value)
                            if not isinstance(data, bytes) or len(data) < 8:
                                continue
                            program = codecs.decode(name, "rot13")
                            runs = int.from_bytes(data[4:8], "little")
                            label = Path(program.replace("/", "\\")).stem if ("\\" in program or "/" in program) \
                                else program.rsplit("!", 1)[-1]
                            if runs > 0 and label and not label.startswith(("{", "UEME_")) and label != "App":
                                counts[label] = counts.get(label, 0) + runs
                except OSError:
                    continue
    except OSError:
        return []
    return [{"app": name, "launches": runs} for name, runs in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


# -- sites (Brave history, local copy) ----------------------------------------------------------------------------

def brave_history_db():
    return Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "History"


def frequent_sites(days=30, limit=40, db=None):
    source = Path(db) if db else brave_history_db()
    if not source.is_file():
        return []
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / "History"
        try:
            shutil.copy2(source, copy)        # Brave keeps the live file locked
        except OSError:
            return []
        cutoff = int(((datetime.utcnow() - timedelta(days=days)) - datetime(1601, 1, 1)).total_seconds() * 1_000_000)
        connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT url, title, visit_count, last_visit_time FROM urls "
                                      "WHERE last_visit_time > ? ORDER BY visit_count DESC LIMIT 5000", (cutoff,)).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            connection.close()
    sites = {}
    for url, title, visits, _last in rows:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        host = parts.hostname.removeprefix("www.")
        site = sites.setdefault(host, {"site": host, "visits": 0, "url": f"{parts.scheme}://{parts.hostname}/",
                                       "title": ""})
        site["visits"] += int(visits or 0)
        if not site["title"] and title:
            site["title"] = str(title)[:80]
    return sorted(sites.values(), key=lambda s: -s["visits"])[:limit]


# -- recently opened files (Windows' own Recent items) ------------------------------------------------------------

KINDS = {"pdf": {".pdf"}, "word": {".doc", ".docx", ".rtf", ".odt"}, "excel": {".xls", ".xlsx", ".csv", ".ods"},
         "ppt": {".ppt", ".pptx", ".odp"}, "text": {".txt", ".md"}, "image": {".jpg", ".jpeg", ".png", ".webp", ".heic"},
         "video": VIDEO}


def recent_files(limit=60):
    """[{"path", "kind", "at"}] newest first: targets of the shortcuts Windows keeps in Recent (no admin)."""
    import subprocess
    folder = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
    if not folder.is_dir():
        return []
    links = sorted(folder.glob("*.lnk"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    if not links:
        return []
    script = ("[Console]::InputEncoding = [Text.Encoding]::UTF8; [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
              "$s = New-Object -ComObject WScript.Shell; $input | ForEach-Object { "
              "try { $s.CreateShortcut($_).TargetPath } catch { '' } }")
    try:   # names can hold emoji and Devanagari: UTF-8 both ways
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              input="\n".join(str(p) for p in links), capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        targets = done.stdout.splitlines()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return []
    out = []
    for link, target in zip(links, targets):
        target = target.strip()
        suffix = Path(target).suffix.casefold()
        kind = next((name for name, suffixes in KINDS.items() if suffix in suffixes), None)
        if target and kind and Path(target).is_file():
            out.append({"path": target, "kind": kind, "at": link.stat().st_mtime})
    return out


def latest_file(kind, data):
    return next((f for f in data.get("recent_files", []) if kind in ("any", f["kind"])), None)


# -- refresh and use ----------------------------------------------------------------------------------------------

def refresh(base=None, *, roots=None):
    library = scan_media(roots if roots is not None else media_roots(base))
    data = {"refreshed": time.time(), "media": library, "progress": progress(library, vlc_history()),
            "apps": frequent_apps(), "sites": frequent_sites(), "recent_files": recent_files()}
    with _lock:
        path = _file(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))


def find_series(name, data):
    wanted = norm(name)
    shows = data.get("media", {})
    exact = [s for s in shows if norm(s) == wanted]
    if exact:
        return exact[0]
    starts = [s for s in shows if norm(s).startswith(wanted) or wanted.startswith(norm(s))]
    if starts:
        return min(starts, key=len)
    words = set(wanted.split())
    scored = sorted(((len(words & set(norm(s).split())), s) for s in shows), reverse=True)
    return scored[0][1] if scored and scored[0][0] else None


def choose_episode(show, data, episode=None, which="continue"):
    """(path, episode number, start seconds) for what to play."""
    entry = data["media"][show]
    numbers = sorted(int(n) for n in entry["episodes"])
    if not numbers:
        if entry["extras"]:
            return entry["extras"][0], None, 0
        raise LookupError(f"No episodes of {show} were found.")
    if episode is not None:
        if str(episode) not in entry["episodes"]:
            raise LookupError(f"Episode {episode} of {show} is not on this PC (I have {numbers[0]}–{numbers[-1]}).")
        return entry["episodes"][str(episode)], episode, 0
    seen = data.get("progress", {}).get(show)
    if which == "first" or not seen:
        number = numbers[0]
        return entry["episodes"][str(number)], number, 0
    if which == "next":
        later = [n for n in numbers if n > seen["last"]]
        if not later:
            raise LookupError(f"You have watched all {show} episodes on this PC (last: {seen['last']}).")
        return entry["episodes"][str(later[0])], later[0], 0
    if which == "latest":
        return entry["episodes"][str(numbers[-1])], numbers[-1], 0
    last, stopped = seen["last"], seen.get("stopped_ms", 0)
    if which == "again" or (which == "continue" and stopped > 60_000):
        return entry["episodes"][str(last)], last, (stopped // 1000 if which == "continue" else 0)
    later = [n for n in numbers if n > last]
    if not later:
        extra = f" There is also {Path(entry['extras'][0]).name}." if entry["extras"] else ""
        raise LookupError(f"You have watched all {show} episodes on this PC (last: {last}).{extra}")
    return entry["episodes"][str(later[0])], later[0], 0


def summary(data):
    shows = {s: {"episodes": len(e["episodes"]), "last_watched": data.get("progress", {}).get(s, {}).get("last")}
             for s, e in data.get("media", {}).items()}
    return {"series": dict(sorted(shows.items(), key=lambda kv: -(kv[1]["last_watched"] or 0))[:15]),
            "top_apps": [a["app"] for a in data.get("apps", [])[:10]],
            "top_sites": [s["site"] for s in data.get("sites", [])[:10]],
            "refreshed": data.get("refreshed")}


def watch(base, stop, every=6 * 3600):
    """Background refresh: at start-up and every 6 hours."""
    while True:
        try:
            refresh(base)
        except Exception:
            import logging
            logging.getLogger("chutku.know_me").warning("refreshing what I know failed", exc_info=True)
        if stop.wait(every):
            return
