"""Small validated owner preferences (hands-free autonomy level, wake phrase opt-in, live conversation mode)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

# Phase 4 (2026-10-29): Gemini Live becomes opt-in ("conversation" False; it claimed things it had not done), the
# hotkey uses the local voice loop, the brain is free-cloud-first, ignored room speech is not stored unless a 24 h
# debug window is open (heard_ambient_until), and command speech-to-text may let Whisper pick English or Hindi.
DEFAULTS = {"handsfree_mode": "owner", "wake_word": False, "conversation": False, "browser": "brave", "heard_log": True,
            "offline_mode": False, "earned_autonomy_relax": False, "voice_lock": False, "voice_lock_threshold": 0.55,
            "timeline": False, "timeline_private": [], "voice_engine": "kokoro", "stt_language": "en",
            "heard_ambient_until": 0.0, "brain": "cloud_first", "follow_up_seconds": 8.0, "presence_overlay": True,
            "media_folders": [], "evolve_push": False, "reply_style": "normal"}
STT_LANGUAGES = {"en", "en|hi"}
BRAINS = {"cloud_first", "local"}
REPLY_STYLES = {"normal", "formal", "short", "masti"}   # H17


def _folders(value):
    """Extra folders Chutku looks in for the owner's videos ("baki chalao"): absolute paths, at most 20."""
    return isinstance(value, list) and len(value) <= 20 and all(
        isinstance(v, str) and 3 <= len(v) <= 260 and Path(v).is_absolute() for v in value)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)
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
            if type(raw.get("presence_overlay")) is bool:
                values["presence_overlay"] = raw["presence_overlay"]
            if type(raw.get("evolve_push")) is bool:
                values["evolve_push"] = raw["evolve_push"]
            if _folders(raw.get("media_folders")):
                values["media_folders"] = list(raw["media_folders"])
            if isinstance(raw.get("timeline_private"), list):
                values["timeline_private"] = [str(v)[:80] for v in raw["timeline_private"][:50]]
            if raw.get("voice_engine") in {"kokoro", "sapi"}:
                values["voice_engine"] = raw["voice_engine"]
            if raw.get("browser") in BROWSER_CHOICES:
                values["browser"] = raw["browser"]
            if raw.get("stt_language") in STT_LANGUAGES:
                values["stt_language"] = raw["stt_language"]
            if raw.get("reply_style") in REPLY_STYLES:
                values["reply_style"] = raw["reply_style"]
            if raw.get("brain") in BRAINS:
                values["brain"] = raw["brain"]
            if _number(raw.get("heard_ambient_until")) and raw["heard_ambient_until"] >= 0:
                values["heard_ambient_until"] = float(raw["heard_ambient_until"])
            if _number(raw.get("follow_up_seconds")) and 0 <= raw["follow_up_seconds"] <= 30:
                values["follow_up_seconds"] = float(raw["follow_up_seconds"])
            return values

    def update(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or not changes or set(changes) - set(DEFAULTS):
            raise ValueError("Only these can be changed: " + ", ".join(DEFAULTS) + ".")
        if "stt_language" in changes and changes["stt_language"] not in STT_LANGUAGES:
            raise ValueError("stt_language must be en or en|hi.")
        if "reply_style" in changes and changes["reply_style"] not in REPLY_STYLES:
            raise ValueError("reply_style must be normal, formal, short or masti.")
        if "brain" in changes and changes["brain"] not in BRAINS:
            raise ValueError("brain must be cloud_first or local.")
        if "heard_ambient_until" in changes and not (_number(changes["heard_ambient_until"])
                                                     and changes["heard_ambient_until"] >= 0):
            raise ValueError("heard_ambient_until must be a time (seconds since 1970) or 0.")
        if "follow_up_seconds" in changes and not (_number(changes["follow_up_seconds"])
                                                   and 0 <= changes["follow_up_seconds"] <= 30):
            raise ValueError("follow_up_seconds must be between 0 and 30.")
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
        if "media_folders" in changes and not _folders(changes["media_folders"]):
            raise ValueError("media_folders must be a list of up to 20 full folder paths (e.g. D:\\Videos).")
        if "timeline_private" in changes and not (isinstance(changes["timeline_private"], list) and all(
                isinstance(v, str) and 0 < len(v) <= 80 for v in changes["timeline_private"])
                                                  and len(changes["timeline_private"]) <= 50):
            raise ValueError("timeline_private must be a list of app names (e.g. mybank.exe).")
        for flag in ("wake_word", "conversation", "heard_log", "offline_mode", "earned_autonomy_relax", "voice_lock",
                     "timeline", "presence_overlay", "evolve_push"):
            if flag in changes and type(changes[flag]) is not bool:
                raise ValueError(f"{flag} must be true or false.")
        from chutku.core.jsonstore import lock_for, write_json
        with lock_for(self.path):   # one lock for every Preferences object: no lost updates between threads
            values = self.load() | changes
            write_json(self.path, values)
        return values
