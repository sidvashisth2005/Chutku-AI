from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification
from chutku.voice.session import voice_session


# Fixed script only. User text arrives as JSON stdin, never as PowerShell code.
_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$speaker = New-Object -ComObject SAPI.SpVoice
$tokens = $speaker.GetVoices()
$voices = @()
for ($i=0; $i -lt $tokens.Count; $i++) {
    $token = $tokens.Item($i)
    $voices += [pscustomobject]@{id=$token.Id; name=$token.GetDescription(); gender=$token.GetAttribute('Gender'); language=$token.GetAttribute('Language')}
}
if ($request.action -eq 'list') {
    [pscustomobject]@{voices=$voices} | ConvertTo-Json -Depth 4 -Compress
} elseif ($request.action -eq 'speak') {
    $selected = -1
    for ($i=0; $i -lt $tokens.Count; $i++) {
        if ($request.voice_id -and $tokens.Item($i).Id -eq $request.voice_id) { $selected=$i; break }
        if (-not $request.voice_id -and $tokens.Item($i).GetAttribute('Gender') -eq 'Female') { $selected=$i; break }
    }
    if ($selected -lt 0) { throw 'The requested voice or a local female voice is not installed. List voices first.' }
    $speaker.Voice = $tokens.Item($selected)
    $speaker.Rate = 0
    # Async + literal text (not XML). No file generation and no automatic mic use.
    $null = $speaker.Speak([string]$request.text, 17)
    $completed = $speaker.WaitUntilDone(12000)
    if (-not $completed) { $null = $speaker.Speak('', 2); throw 'Speech exceeded the 12-second playback limit.' }
    [pscustomobject]@{speech_completed=$true; voice=$speaker.Voice.GetDescription(); microphone_started=$false; audio_saved=$false} | ConvertTo-Json -Compress
} else { throw 'Unsupported speech action.' }
'''

_SPEAK_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1, "maxLength": 1000},
        "voice_id": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": ["text"],
    "additionalProperties": False,
}


def sapi(request):
    if sys.platform != "win32":
        raise OSError("Local speech requires Windows SAPI.")
    from chutku.tools.windows_apps import WindowsDesktop
    powershell = WindowsDesktop().system_dir / "WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        input=json.dumps(request, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8",
        timeout=18, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise OSError("Local speech was unavailable or exceeded its deadline. No cloud fallback was attempted.")
    return json.loads(result.stdout.lstrip("\ufeff"))


def validate_speech(arguments):
    if set(arguments) - {"text", "voice_id"} or "text" not in arguments:
        raise ValueError("Speech accepts text and an optional installed voice_id only.")
    if not isinstance(arguments["text"], str) or not arguments["text"].strip() or len(arguments["text"]) > 1000:
        raise ValueError("Speech text must contain 1 to 1000 characters.")
    if "voice_id" in arguments and (not isinstance(arguments["voice_id"], str) or not 1 <= len(arguments["voice_id"]) <= 500):
        raise ValueError("Choose an installed voice ID returned by voice.list_voices.")


def _list(arguments, _):
    return ToolResult(sapi({"action": "list"}), Verification.PASS)


def _engine():
    """The owner's choice of offline voice: "kokoro" (default since the 2026-10-07 listening test) or "sapi"."""
    try:
        from chutku import mind
        from chutku.core.preferences import Preferences
        return Preferences(Path(mind.PROJECT_ROOT)).load().get("voice_engine", "kokoro")
    except (OSError, ValueError):
        return "kokoro"


def _speak_sapi(arguments):
    """Windows SAPI, 200 characters per call (its 12-second limit): longer text is spoken sentence by sentence."""
    from chutku.voice.tts import sentences
    result = None
    for part in sentences(arguments["text"]) or [arguments["text"]]:
        for start in range(0, len(part), 200):
            result = sapi({"action": "speak", **arguments, "text": part[start:start + 200]})
    return result


def _speak(arguments, _):
    from chutku.voice import tts
    with voice_session.active("speaking"):
        result, engine, problem = None, "sapi", None
        if "voice_id" not in arguments and _engine() == "kokoro" and tts.available():
            try:
                spoken = tts.speak(arguments["text"])
                result = {"speech_completed": not spoken["stopped"], "stopped_by_owner": spoken["stopped"],
                          "voice": f"Kokoro {tts.VOICE}", "sentences": spoken["sentences"],
                          "first_audio_s": round(spoken["first_audio_s"] or 0, 2),
                          "microphone_started": False, "audio_saved": False}
                engine = "kokoro"
            except Exception as error:   # never silent: the Windows voice says it instead
                problem = f"{type(error).__name__}: {error}"[:160]
        if result is None:
            result = _speak_sapi(arguments)
            if problem:
                result["kokoro_failed"] = problem
    # This verifies the engine's completion, not what a human actually heard.
    result["engine"] = engine
    result["verification_scope"] = "Playback completed; audible output is not measured."
    result["audio_session"] = "idle"
    result["listening_suppressed_during_playback"] = True
    ok = result.get("speech_completed") is True or result.get("stopped_by_owner") is True
    return ToolResult(result, Verification.PASS if ok else Verification.FAIL)


def register_speech(registry):
    from chutku.tools.assistant import _none
    registry.register(Tool("voice.list_voices", "List installed local Windows speech voices; no download or playback.",
                           Risk.OBSERVATION, _list, _none, argument_schema=EMPTY_ARGUMENT_SCHEMA,
                           prerequisites=("Windows SAPI",), reversibility="not_applicable",
                           success_predicate="installed_voice_inventory_returned"))
    registry.register(Tool("voice.speak", "Speak up to 1000 characters with Chutku's local neural voice (Kokoro, falls back to Windows SAPI); sentence by sentence, can be stopped, no microphone.",
                           Risk.REVERSIBLE, _speak, validate_speech, frozenset({"text"}),
                           argument_schema=_SPEAK_SCHEMA, prerequisites=("Windows SAPI and installed voice",),
                           reversibility="transient", success_predicate="SAPI_reports_playback_completed"))
