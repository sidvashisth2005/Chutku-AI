"""Owner Voice Lock switches (master plan S19): "voice lock on/off" (typed by the owner only) and its status."""
from __future__ import annotations

from pathlib import Path

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
_SWITCH = {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"], "additionalProperties": False}


def _root():
    from chutku import mind
    return Path(mind.PROJECT_ROOT)


def _status(_arguments, _context):
    from chutku.voice import speaker
    enabled, threshold = speaker.settings(_root())
    return ToolResult({"voice_lock": enabled, "enrolled": speaker.load_voiceprint(_root()) is not None,
                       "model_ready": speaker.available(), "threshold": threshold,
                       "enroll_with": "python -m chutku.cli voice enroll (or the dashboard's Voice lock tab)"},
                      Verification.PASS)


def _switch(arguments, _context):
    from chutku.core.preferences import Preferences
    from chutku.voice import speaker
    if arguments["on"] and (speaker.load_voiceprint(_root()) is None or not speaker.available()):
        return ToolResult({"error": "Enroll your voice first (python -m chutku.cli voice enroll, or the dashboard's "
                                    "Voice lock tab); the lock stays off until then."}, Verification.FAIL)
    prefs = Preferences(_root())
    prefs.update({"voice_lock": bool(arguments["on"])})
    now = prefs.load()["voice_lock"]
    return ToolResult({"voice_lock": now}, Verification.PASS if now == bool(arguments["on"]) else Verification.FAIL)


def _validate_none(arguments):
    if arguments:
        raise ValueError("This takes no arguments.")


def _validate_switch(arguments):
    if set(arguments) != {"on"} or type(arguments["on"]) is not bool:
        raise ValueError("Give on: true or false.")


def register_voice_lock_tools(registry):
    registry.register(Tool("voice.lock_status", "Is the owner voice lock on, is a voice enrolled, and the threshold.",
        Risk.OBSERVATION, _status, _validate_none, argument_schema=_NONE, reversibility="not_applicable",
        success_predicate="voice_lock_read"))
    registry.register(Tool("settings.voice_lock", "Owner only: when on, a voice request that does not sound like the "
        "enrolled owner cannot change anything without a click on screen (off: no voice check).", Risk.REVERSIBLE,
        _switch, _validate_switch, argument_schema=_SWITCH, reversibility="compensatable",
        success_predicate="preference_written", user_only=True))
