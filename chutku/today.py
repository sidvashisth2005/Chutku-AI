"""The dashboard's "Today" panel: a fast, read-only snapshot of the owner's day.

Nothing here changes the PC. Weather is fetched in the background (30-minute cache) so the
panel never waits on the network; the other facts are local and bounded.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

WEATHER_TTL = 30 * 60
_weather_lock = threading.Lock()
_weather_fetching = False


def greeting(hour: int) -> str:
    if hour < 5 or hour >= 22:
        return "Working late"
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


def _weather_cache(base: Path) -> Path:
    return Path(base) / "data" / "today-weather.json"


def _refresh_weather(base: Path) -> None:
    global _weather_fetching
    try:
        from chutku.core.memory import MemoryStore
        from chutku.tools.internet import _weather
        memory = MemoryStore(Path(base) / "data" / "memory.db")
        try:
            result = _weather({}, SimpleNamespace(memory=memory))
        finally:
            memory.close()
        payload = {"fetched": time.time(), "ok": result.verification == "PASS", "data": result.output}
        _weather_cache(base).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:  # weather is decoration: never break the panel
        pass
    finally:
        with _weather_lock:
            _weather_fetching = False


def weather(base: Path, *, background: bool = True):
    """Cached weather; starts a background refresh when stale. Returns None until something is cached."""
    global _weather_fetching
    path = _weather_cache(base)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    stale = cached is None or time.time() - cached.get("fetched", 0) > WEATHER_TTL
    if stale:
        with _weather_lock:
            start = not _weather_fetching
            _weather_fetching = _weather_fetching or start
        if start:
            if background:
                threading.Thread(target=_refresh_weather, args=(base,), daemon=True).start()
            else:
                _refresh_weather(base)
                return weather(base, background=False) if path.exists() else None
    if not cached:
        return None
    data = cached.get("data") or {}
    if not cached.get("ok"):
        return {"error": data.get("error", "Weather unavailable.")}
    now = data.get("now", {})
    return {"place": data.get("place"), "temperature_c": now.get("temperature_c"), "sky": now.get("sky"),
            "feels_like_c": now.get("feels_like_c"), "today": (data.get("next_days") or [None])[0]}


def _readable(folder: Path, grants) -> bool:
    """Show recent files only from folders the owner granted Chutku to observe."""
    target = str(folder.resolve()).casefold()
    for grant in grants:
        root = str(grant.root).casefold().rstrip("\\") + "\\"
        if "observe" in grant.access and grant.active and (target + "\\").startswith(root):
            return True
    return False


def snapshot(base: Path, runtime) -> dict:
    from chutku.tools.files_plus import disk_report, scan_recent, user_folders
    from chutku.tools.reminders import load as load_reminders
    now = datetime.now().astimezone()
    try:
        grants = runtime.resource_grants.list() if runtime.resource_grants is not None else []
    except Exception:
        grants = []
    folders = [f for f in user_folders() if f.is_dir() and _readable(f, grants)]
    reminders = sorted(({"at": v["at"], "message": v["message"]} for v in load_reminders(base).values()
                        if isinstance(v, dict) and not v.get("fired") and v.get("at", "") >= now.strftime("%Y-%m-%dT%H:%M")),
                       key=lambda r: r["at"])[:5]
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat(timespec="seconds")
    actions = runtime.action_log.recent(200, midnight)
    chain = runtime.action_log.verify()
    return {
        "greeting": greeting(now.hour),
        "date": now.strftime("%A, %d %B %Y"),
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "weather": weather(base),
        "disk": disk_report(),
        "reminders": reminders,
        "recent_files": scan_recent(folders, days=3, limit=6) if folders else [],
        "recent_scope": [f.name for f in folders],
        "chutku_today": {"count": len(actions),
                         "done": sum(a.get("state") == "COMPLETED" for a in actions),
                         "refused": sum(a.get("state") == "DENIED" for a in actions),
                         "latest": [{"tool": a["tool"], "state": a["state"], "time": a["time"]} for a in actions[:4]],
                         "log_intact": chain["ok"]},
        "actions_paused": runtime.action_control.paused,
        "alerts": [{"title": title, "message": message} for _key, title, message, _band in _health_problems()],
        "routines": _routines(),
        "notes": _notes(),
    }


def _notes():
    from chutku.notes import visible
    open_items = [i for i in visible() if not i.get("done")]
    return {"open": len(open_items), "items": [{"id": i["id"], "text": i["text"]} for i in open_items[:5]]}


def _routines():
    from chutku.routines import load
    return [{"name": name, "commands": commands} for name, commands in sorted(load().items())]


def _health_problems():
    from chutku.health import problems, readings
    try:
        return problems(readings())
    except Exception:
        return []
