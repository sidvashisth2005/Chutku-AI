"""Small validated owner preferences (hands-free autonomy level, wake phrase opt-in, live conversation mode)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

DEFAULTS = {"handsfree_mode": "owner", "wake_word": False, "conversation": True, "browser": "brave", "heard_log": True,
            "offline_mode": False, "earned_autonomy_relax": False, "voice_lock": False, "voice_lock_threshold": 0.55,
            "timeline": False, "timeline_private": [], "voice_engine": "kokoro"}
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
            if type(raw.get("earned_autonomy_relax")) is bool:
                values["earned_autonomy_relax"] = raw["earned_autonomy_relax"]
            if type(raw.get("voice_lock")) is bool:
                values["voice_lock"] = raw["voice_lock"]
            if isinstance(raw.get("voice_lock_threshold"), (int, float)) and 0.2 <= raw["voice_lock_threshold"] <= 0.95:
                values["voice_lock_threshold"] = float(raw["voice_lock_threshold"])
            if type(raw.get("timeline")) is bool:
                values["timeline"] = raw["timeline"]
            if isinstance(raw.get("timeline_private"), list):
                values["timeline_private"] = [str(v)[:80] for v in raw["timeline_private"][:50]]
            if raw.get("voice_engine") in {"kokoro", "sapi"}:
                values["voice_engine"] = raw["voice_engine"]
            if raw.get("browser") in BROWSER_CHOICES:
                values["browser"] = raw["browser"]
            return values

    def update(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or not changes or set(changes) - set(DEFAULTS):
            raise ValueError("Only handsfree_mode, wake_word, conversation, browser, heard_log, offline_mode, "
                             "earned_autonomy_relax, voice_lock, voice_lock_threshold, timeline, "
                             "timeline_private and voice_engine can be changed.")
        if "browser" in changes and changes["browser"] not in BROWSER_CHOICES:
            raise ValueError("browser must be brave, edge, chrome, firefox or default.")
        if "handsfree_mode" in changes and changes["handsfree_mode"] not in _MODES:
            raise ValueError("handsfree_mode must be review, auto_safe, auto_edits or owner.")
        if "voice_lock_threshold" in changes and not (isinstance(changes["voice_lock_threshold"], (int, float))
                                                      and not isinstance(changes["voice_lock_threshold"], bool)
                                                      and 0.2 <= changes["voice_lock_threshold"] <= 0.95):
            raise ValueError("voice_lock_threshold must be between 0.2 and 0.95.")
        if "voice_engine" in changes and changes["voice_engine"] not in {"kokoro", "sapi"}:
            raise ValueError("voice_engine must be kokoro or sapi.")
        if "timeline_private" in changes and not (isinstance(changes["timeline_private"], list) and all(
                isinstance(v, str) and 0 < len(v) <= 80 for v in changes["timeline_private"])
                                                  and len(changes["timeline_private"]) <= 50):
            raise ValueError("timeline_private must be a list of app names (e.g. mybank.exe).")
        for flag in ("wake_word", "conversation", "heard_log", "offline_mode", "earned_autonomy_relax", "voice_lock",
                     "timeline"):
            if flag in changes and type(changes[flag]) is not bool:
                raise ValueError(f"{flag} must be true or false.")
        from chutku.core.jsonstore import lock_for, write_json
        with lock_for(self.path):   # one lock for every Preferences object: no lost updates between threads
            values = self.load() | changes
            write_json(self.path, values)
        return values
