"""CommandCatalog, RoutedCommand: fixed typed commands."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# This closed vocabulary is the deterministic brain contract.  Language adapters
# may select an intent later, but only this catalog may turn user text into a tool
# proposal.  Keeping intent and tool names separate lets policy continue to reason
# about tools while tests measure understanding in stable product terms.
INTENT_BY_TOOL = {
    "apps.focus": "FOCUS_APP",
    "apps.close": "CLOSE_APP",
    "apps.open": "OPEN_APP",
    "apps.status": "CHECK_APP_STATUS",
    "assistant.capabilities": "SHOW_CAPABILITIES",
    "clipboard.read_text": "READ_CLIPBOARD",
    "clipboard.write_text": "WRITE_CLIPBOARD",
    "filesystem.create_directory": "CREATE_DIRECTORY",
    "filesystem.copy": "COPY_FILE",
    "filesystem.inspect": "INSPECT_FILE",
    "filesystem.list": "LIST_FILES",
    "filesystem.list_incomplete_writes": "LIST_INCOMPLETE_WRITES",
    "filesystem.move": "MOVE_FILE",
    "filesystem.read_text": "READ_TEXT_FILE",
    "filesystem.recycle": "RECYCLE_FILE",
    "filesystem.restore_last_recycled": "RESTORE_RECYCLED_FILE",
    "filesystem.search": "SEARCH_FILES",
    "filesystem.undo_last_copy": "UNDO_LAST_COPY",
    "filesystem.undo_last_move": "UNDO_LAST_MOVE",
    "filesystem.undo_last_write": "UNDO_LAST_WRITE",
    "filesystem.write_text": "WRITE_TEXT_FILE",
    "memory.forget": "FORGET_MEMORY",
    "memory.remember": "REMEMBER_MEMORY",
    "memory.search": "SEARCH_MEMORY",
    "screen.capture": "CAPTURE_DISPLAY",
    "screen.displays": "LIST_DISPLAYS",
    "screen.undo_last_capture": "UNDO_LAST_SCREEN_CAPTURE",
    "system.audio_devices": "CHECK_AUDIO_DEVICES",
    "system.environment": "CHECK_SYSTEM_STATUS",
    "system.get_time": "GET_TIME",
    "system.gpu_status": "CHECK_GPU_STATUS",
    "uia.inspect": "INSPECT_APP_CONTROLS",
    "voice.audio_input_status": "CHECK_AUDIO_INPUT",
    "voice.list_voices": "LIST_VOICES",
    "voice.listen_command": "LISTEN_FOR_COMMAND",
    "voice.microphone_activity_check": "CHECK_MICROPHONE_ACTIVITY",
    "voice.microphone_level_check": "CHECK_MICROPHONE_LEVEL",
    "voice.recognition_status": "CHECK_SPEECH_RECOGNITION",
    "voice.speak": "SPEAK_TEXT",
    "settings.earned_autonomy": "SET_EARNED_AUTONOMY",
    "settings.voice_lock": "SET_VOICE_LOCK",
    "settings.timeline": "SET_TIMELINE",
    "never.add": "ADD_NEVER_RULE",
    "never.list": "LIST_NEVER_RULES",
    "never.remove": "REMOVE_NEVER_RULE",
    "skill.approve": "APPROVE_SKILL",
    "evolve.approve": "APPROVE_IMPROVEMENT",
    "evolve.reject": "REJECT_IMPROVEMENT",
    "settings.evolve_push": "SET_EVOLVE_PUSH",
    "background.pause": "PAUSE_BACKGROUND",
    "background.resume": "RESUME_BACKGROUND",
    "background.status": "CHECK_BACKGROUND_PAUSE",
    "windows.list": "LIST_WINDOWS",
}


@dataclass(frozen=True)
class RoutedCommand:
    tool_name: str
    arguments: dict[str, Any]

    @property
    def intent(self) -> str:
        """Return the stable intent label or fail closed for an unlabeled route."""
        try:
            return INTENT_BY_TOOL[self.tool_name]
        except KeyError as error:
            raise ValueError("The matched command has no registered intent label.") from error


_PATH = r"(?P<path>(?:[a-zA-Z]:[\\/]|\\\\|~)[^\n]*?)"
_NEVER_PATH = [
    re.compile(r"^(?:never|don't ever|do not ever) (?:touch|change|edit|modify|delete|use|open)\s+" + _PATH + r"\s*$",
               re.IGNORECASE),
    re.compile(r"^" + _PATH + r"\s+(?:ko|mein|me|ke andar)?\s*(?:kabhi(?: bhi)?)\s+(?:mat|na|nahi)\s+"
               r"(?:chhoona|chhuna|chhona|chhedna|chedna|badalna|chhuo|chhedo|badlo|chhoo)\s*$", re.IGNORECASE),
    re.compile(r"^(?:kabhi(?: bhi)?)\s+" + _PATH + r"\s+(?:ko\s+)?(?:mat|na|nahi)\s+"
               r"(?:chhoona|chhuna|chhona|chhedna|chedna|badalna|chhuo|chhedo|badlo|chhoo)\s*$", re.IGNORECASE),
]
_NEVER_COMMAND = re.compile(r"^never (?:run|execute) (?:a |any )?(?:command|script|code) (?:with|containing) (?P<what>.+)$",
                            re.IGNORECASE)
_NEVER_TOOL = re.compile(r"^never use (?:the )?tool (?P<what>[a-z][a-z0-9_.*]{1,80})$", re.IGNORECASE)
_NEVER_LIST = re.compile(r"^(?:(?:show |list )?(?:my )?never[- ]rules|never rules dikhao|mere never rules(?: dikhao)?|"
                         r"kya kya kabhi nahi karna hai)$", re.IGNORECASE)
_NEVER_REMOVE = re.compile(r"^(?:remove never[- ]rule|never[- ]rule hatao|never rule (?P<id2>[0-9a-f]{6}) hatao)"
                           r"(?:\s+(?P<id>[0-9a-f]{6}))?$", re.IGNORECASE)


_BG = r"(?:background(?: ka| ke)?(?: kaam| work| jobs| tasks)?)"   # not "scheduled tasks roko": that cancels them
_BG_PAUSE = re.compile(rf"^(?:pause (?:the |my |all )?{_BG}|{_BG} (?:pause karo|pause kar do|roko|rok do|band karo|"
                       rf"band kar do|ruk jao)|stop {_BG})$", re.IGNORECASE)
_BG_RESUME = re.compile(rf"^(?:resume (?:the |my |all )?{_BG}|{_BG} (?:resume karo|resume kar do|shuru karo|"
                        rf"shuru kar do|chalu karo|chalu kar do|wapas chalao))$", re.IGNORECASE)
_BG_STATUS = re.compile(rf"^(?:is (?:the )?{_BG} paused\??|{_BG} (?:status|paused hai\??|ruka hai\??|ruka hua hai\??))$",
                        re.IGNORECASE)


def background_route(text):
    """Background pause phrases (Phase 3b H2); None when the text is not one."""
    text = text.strip().rstrip(".!")
    if _BG_PAUSE.fullmatch(text):
        return RoutedCommand("background.pause", {})
    if _BG_RESUME.fullmatch(text):
        return RoutedCommand("background.resume", {})
    if _BG_STATUS.fullmatch(text):
        return RoutedCommand("background.status", {})
    return None


def _never_rule(text):
    for pattern in _NEVER_PATH:
        if match := pattern.fullmatch(text):
            return RoutedCommand("never.add", {"kind": "path", "pattern": match["path"].strip().rstrip(".")})
    if match := _NEVER_COMMAND.fullmatch(text):
        return RoutedCommand("never.add", {"kind": "command", "pattern": match["what"].strip()})
    if match := _NEVER_TOOL.fullmatch(text):
        return RoutedCommand("never.add", {"kind": "tool", "pattern": match["what"]})
    if _NEVER_LIST.fullmatch(text):
        return RoutedCommand("never.list", {})
    if (match := _NEVER_REMOVE.fullmatch(text)) and (match["id"] or match["id2"]):
        return RoutedCommand("never.remove", {"id": (match["id"] or match["id2"]).casefold()})
    return None


class CommandCatalog:
    """Small explicit command grammar. Unknown language fails closed instead of guessing."""

    _CREATE_DIRECTORY = re.compile(r"^(?:create|make) (?:a )?(?:folder|directory) (?P<path>.+)$", re.IGNORECASE)
    _WRITE_TEXT = re.compile(r"^write (?P<content>.+) to (?P<path>.+)$", re.IGNORECASE)
    _READ_TEXT = re.compile(r"^read (?:file )?(?P<path>.+)$", re.IGNORECASE)
    _INSPECT = re.compile(r"^inspect (?:file )?(?P<path>.+)$", re.IGNORECASE)
    _SEARCH_FILES = re.compile(r"^(?:find|search for) (?P<query>.+) in (?P<path>.+)$", re.IGNORECASE)
    _COPY = re.compile(r"^copy (?P<source>.+) to (?P<destination>.+)$", re.IGNORECASE)
    _MOVE = re.compile(r"^(?:move|rename) (?P<source>.+) to (?P<destination>.+)$", re.IGNORECASE)
    _RECYCLE = re.compile(r"^recycle (?:file )?(?P<path>.+)$", re.IGNORECASE)

    def route(self, text: str) -> RoutedCommand:
        # Preserve user data (multiple spaces/newlines) in write and remember commands.
        normalized = text.strip()
        if normalized.casefold() in {"read clipboard", "show clipboard text"}:
            return RoutedCommand("clipboard.read_text", {})
        if match := re.fullmatch(r"(?:set clipboard to|copy to clipboard) (.*)", normalized,
                                 re.IGNORECASE | re.DOTALL):
            return RoutedCommand("clipboard.write_text", {"text": match[1]})
        if match := re.fullmatch(r"earned autonomy relax (on|off)", normalized, re.IGNORECASE):
            # Owner-only switch (master plan S16): typed by the owner, never chosen by the agent.
            return RoutedCommand("settings.earned_autonomy", {"on": match[1].casefold() == "on"})
        if match := re.fullmatch(r"voice lock (on|off)", normalized, re.IGNORECASE):
            # Owner-only switch (master plan S19): typed by the owner, never by voice or the agent.
            return RoutedCommand("settings.voice_lock", {"on": match[1].casefold() == "on"})
        if match := re.fullmatch(r"timeline (on|off)", normalized, re.IGNORECASE):
            # Owner-only switch (master plan S21): typed by the owner, never by voice or the agent.
            return RoutedCommand("settings.timeline", {"on": match[1].casefold() == "on"})
        if match := re.fullmatch(r"(?:skill approve|approve skill) ([a-z][a-z0-9_]{2,39})", normalized, re.IGNORECASE):
            # Owner-only (master plan X15): typed by the owner, then a click; never by voice or the agent.
            return RoutedCommand("skill.approve", {"name": match[1].casefold()})
        if match := re.fullmatch(r"evolve (approve|reject) ([0-9a-f]{6})", normalized, re.IGNORECASE):
            # Y2: approving an improvement idea is owner-only, typed, then a click; never by voice or the agent.
            return RoutedCommand(f"evolve.{match[1].casefold()}", {"id": match[2].casefold()})
        if match := re.fullmatch(r"evolve push (on|off)", normalized, re.IGNORECASE):
            return RoutedCommand("settings.evolve_push", {"on": match[1].casefold() == "on"})
        if routed := background_route(normalized):
            # Background pause (Phase 3b H2): resuming is typed by the owner only.
            return routed
        if routed := _never_rule(normalized):
            # The owner's never-rules (Phase 3b H1): typed by the owner; removing one always asks.
            return routed
        if normalized.casefold() == "listen for a command":
            return RoutedCommand("voice.listen_command", {})
        if normalized.casefold() == "speech recognition status":
            return RoutedCommand("voice.recognition_status", {})
        if normalized.casefold() in {"list voices", "show voices", "available voices"}:
            return RoutedCommand("voice.list_voices", {})
        if match := re.fullmatch(r"(?:say|speak) (.+)", normalized, re.IGNORECASE | re.DOTALL):
            return RoutedCommand("voice.speak", {"text": match[1]})
        if match := re.fullmatch(r"(?:open|launch|start) (notepad|calculator)", normalized, re.IGNORECASE):
            return RoutedCommand("apps.open", {"app": match[1].casefold()})
        if match := re.fullmatch(r"(?:focus|switch to) (notepad|calculator)", normalized, re.IGNORECASE):
            return RoutedCommand("apps.focus", {"app": match[1].casefold()})
        if match := re.fullmatch(r"close (notepad|calculator)", normalized, re.IGNORECASE):
            return RoutedCommand("apps.close", {"app": match[1].casefold()})
        if match := re.fullmatch(r"(?:status of|check) (notepad|calculator)", normalized, re.IGNORECASE):
            return RoutedCommand("apps.status", {"app": match[1].casefold()})
        if match := re.fullmatch(r"inspect (notepad|calculator) controls", normalized, re.IGNORECASE):
            return RoutedCommand("uia.inspect", {"app": match[1].casefold()})
        if match := re.fullmatch(r"remember ([a-zA-Z][a-zA-Z0-9_-]{0,63})\s*=\s*(.+)", normalized, re.IGNORECASE | re.DOTALL):
            return RoutedCommand("memory.remember", {"key": match[1], "value": match[2]})
        if normalized.casefold() in {"memories", "show memories", "what do you remember"}:
            return RoutedCommand("memory.search", {})
        if match := re.fullmatch(r"recall (.+)", normalized, re.IGNORECASE):
            return RoutedCommand("memory.search", {"query": match[1]})
        if match := re.fullmatch(r"forget ([a-zA-Z][a-zA-Z0-9_-]{0,63})", normalized, re.IGNORECASE):
            return RoutedCommand("memory.forget", {"key": match[1]})
        if normalized.casefold() in {"capabilities", "what can you do", "help capabilities"}:
            return RoutedCommand("assistant.capabilities", {})
        if normalized.casefold() in {"list windows", "show windows", "open windows"}:
            return RoutedCommand("windows.list", {})
        if normalized.casefold() in {"list displays", "show displays", "display inventory"}:
            return RoutedCommand("screen.displays", {})
        if normalized.casefold() in {"undo last screen capture", "undo the last screen capture"}:
            return RoutedCommand("screen.undo_last_capture", {})
        if match := re.fullmatch(r"capture display (?P<index>\d{1,2}) to (?P<path>.+)", normalized,
                                 re.IGNORECASE):
            return RoutedCommand("screen.capture", {
                "display_index": int(match.group("index")), "path": match.group("path")})
        if normalized.casefold() in {"unfinished writes", "list incomplete writes"}:
            return RoutedCommand("filesystem.list_incomplete_writes", {})
        if match := re.fullmatch(r"list files in (.+)", normalized, re.IGNORECASE):
            return RoutedCommand("filesystem.list", {"path": match[1]})
        if normalized.casefold() in {"what time is it", "what is the time", "time", "tell me the time"}:
            return RoutedCommand("system.get_time", {})
        if normalized.casefold() in {"system status", "environment status", "show environment", "diagnose environment"}:
            return RoutedCommand("system.environment", {})
        if normalized.casefold() in {"gpu status", "show gpu", "gpu information", "graphics status"}:
            return RoutedCommand("system.gpu_status", {})
        if normalized.casefold() in {"audio status", "audio devices", "show audio devices", "microphone status"}:
            return RoutedCommand("system.audio_devices", {})
        if normalized.casefold() in {"microphone input status", "input devices", "test microphone access"}:
            return RoutedCommand("voice.audio_input_status", {})
        if normalized.casefold() in {"check microphone level", "test microphone", "microphone check"}:
            return RoutedCommand("voice.microphone_level_check", {})
        if normalized.casefold() in {"check microphone activity", "test microphone activity", "audio activity check"}:
            return RoutedCommand("voice.microphone_activity_check", {})
        if normalized.casefold() in {"list files", "list folders", "show files", "show sandbox"}:
            return RoutedCommand("filesystem.list", {"path": "."})
        if normalized.casefold() in {"undo last write", "undo the last write"}:
            return RoutedCommand("filesystem.undo_last_write", {})
        if normalized.casefold() in {"undo last copy", "undo the last copy"}:
            return RoutedCommand("filesystem.undo_last_copy", {})
        if normalized.casefold() in {"undo last move", "undo the last move", "undo last rename"}:
            return RoutedCommand("filesystem.undo_last_move", {})
        if normalized.casefold() in {"restore last recycled file", "restore the last recycled file"}:
            return RoutedCommand("filesystem.restore_last_recycled", {})
        if match := self._RECYCLE.fullmatch(normalized):
            return RoutedCommand("filesystem.recycle", {"path": match.group("path")})
        if match := self._COPY.fullmatch(normalized):
            return RoutedCommand("filesystem.copy", {
                "source": match.group("source"), "destination": match.group("destination")})
        if match := self._MOVE.fullmatch(normalized):
            return RoutedCommand("filesystem.move", {
                "source": match.group("source"), "destination": match.group("destination")})
        if match := self._SEARCH_FILES.fullmatch(normalized):
            return RoutedCommand("filesystem.search", {
                "path": match.group("path"), "query": match.group("query"), "recursive": True})
        if match := self._INSPECT.fullmatch(normalized):
            return RoutedCommand("filesystem.inspect", {"path": match.group("path")})
        if match := self._READ_TEXT.fullmatch(normalized):
            return RoutedCommand("filesystem.read_text", {"path": match.group("path")})
        if match := self._CREATE_DIRECTORY.fullmatch(normalized):
            return RoutedCommand("filesystem.create_directory", {"path": match.group("path")})
        if match := self._WRITE_TEXT.fullmatch(normalized):
            content = match.group("content")
            if len(content) >= 2 and content.startswith('"') and content.endswith('"'):
                content = content[1:-1]
            return RoutedCommand("filesystem.write_text", {"path": match.group("path"), "content": content})
        raise ValueError(
            "I do not have a safe deterministic match for that request. Try: 'what time is it', "
            "'system status', 'list files', 'inspect file PATH', 'find NAME in PATH', "
            "'copy SOURCE to DESTINATION', 'move SOURCE to DESTINATION', 'read file PATH', "
            "'create folder NAME', 'write \"TEXT\" to PATH', 'list displays', "
            "'capture display INDEX to PATH', or an exact undo command."
        )
