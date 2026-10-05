"""Small validated owner preferences (hands-free autonomy level, wake phrase opt-in, live conversation mode)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

DEFAULTS = {"handsfree_mode": "owner", "wake_word": False, "conversation": True, "browser": "brave", "heard_log": True,
            "offline_mode": False}
_MODES = {"review", "auto_safe", "auto_edits", "owner"}
BROWSER_CHOICES = {"brave", "edge", "chrome", "firefox", "default"}  # owner's choice 2026-10-04: Brave


class Preferences:
    def __init__(self, base: Path):
        self.path = Path(base) / "data" / "preferences.json"
        self._lock = threading.Lock()

    def load(self) -> dict:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            values = dict(DEFAULTS)
            if raw.get("handsfree_mode") in _MODES:
                values["handsfree_mode"] = raw["handsfree_mode"]
            if type(raw.get("wake_word")) is bool:
                values["wake_word"] = raw["wake_word"]
            if type(raw.get("conversation")) is bool:
                values["conversation"] = raw["conversation"]
            if type(raw.get("heard_log")) is bool:
                values["heard_log"] = raw["heard_log"]
            if type(raw.get("offline_mode")) is bool:
                values["offline_mode"] = raw["offline_mode"]
            if raw.get("browser") in BROWSER_CHOICES:
                values["browser"] = raw["browser"]
            return values

    def update(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or not changes or set(changes) - set(DEFAULTS):
            raise ValueError("Only handsfree_mode, wake_word, conversation, browser, heard_log and offline_mode can be "
                             "changed.")
        if "browser" in changes and changes["browser"] not in BROWSER_CHOICES:
            raise ValueError("browser must be brave, edge, chrome, firefox or default.")
        if "handsfree_mode" in changes and changes["handsfree_mode"] not in _MODES:
            raise ValueError("handsfree_mode must be review, auto_safe, auto_edits or owner.")
        for flag in ("wake_word", "conversation", "heard_log", "offline_mode"):
            if flag in changes and type(changes[flag]) is not bool:
                raise ValueError(f"{flag} must be true or false.")
        values = self.load() | changes
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        return values
