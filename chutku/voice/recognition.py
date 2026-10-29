"""Offline free-form speech input. Transcripts never dispatch actions."""
from __future__ import annotations

import base64
from array import array
import io
import time
import json
import math
import subprocess
import sys
import wave

from chutku.core.action_control import ActionControl
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification
from chutku.voice.session import voice_session

COMMANDS = ("what time is it", "system status", "gpu status", "audio devices",
            "list files", "list windows", "capabilities", "open notepad",
            "open calculator", "focus notepad", "focus calculator",
            "check notepad", "check calculator", "list voices")

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$installed = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers())
if ($request.action -eq 'status') {
    $items = @($installed | ForEach-Object { [pscustomobject]@{id=$_.Id; culture=$_.Culture.Name} })
    [pscustomobject]@{recognizers=$items} | ConvertTo-Json -Depth 4 -Compress
    exit
}
$selected = $installed | Where-Object { $_.Culture.Name -eq 'en-US' } | Select-Object -First 1
if (-not $selected) { throw 'No local en-US recognizer installed.' }
$engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new([System.Speech.Recognition.RecognizerInfo]$selected)
$stream = New-Object System.IO.MemoryStream
$synth = $null
try {
    if ($request.action -eq 'fixture') {
        # Developer-only empirical test retains a closed grammar so expected
        # transcripts are deterministic. Production recognition uses dictation.
        $choices = New-Object System.Speech.Recognition.Choices
        $choices.Add([string[]]$request.commands)
        $builder = New-Object System.Speech.Recognition.GrammarBuilder
        $builder.Culture = $selected.Culture
        $builder.Append($choices)
        $engine.LoadGrammar([System.Speech.Recognition.Grammar]::new($builder))
        $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
        $synth.SetOutputToWaveStream($stream)
        $synth.Speak([string]$request.text)
        $synth.SetOutputToNull()
    } elseif ($request.action -eq 'recognize') {
        $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
        $bytes = [Convert]::FromBase64String([string]$request.wav)
        $stream.Write($bytes, 0, $bytes.Length)
    } else { throw 'Unsupported recognition action.' }
    $stream.Position = 0
    $engine.SetInputToWaveStream($stream)
    $result = $engine.Recognize([TimeSpan]::FromSeconds(5))
    if ($null -eq $result) {
        [pscustomobject]@{text=''; confidence=0; culture=$selected.Culture.Name} | ConvertTo-Json -Compress
    } else {
        [pscustomobject]@{text=$result.Text; confidence=$result.Confidence; culture=$selected.Culture.Name} | ConvertTo-Json -Compress
    }
} finally {
    $engine.Dispose()
    if ($null -ne $synth) { $synth.Dispose() }
    $stream.Dispose()
}
'''


def recognize(request):
    if sys.platform != "win32":
        raise OSError("Offline command recognition requires Windows.")
    from chutku.tools.windows_apps import WindowsDesktop
    executable = WindowsDesktop().system_dir / "WindowsPowerShell/v1.0/powershell.exe"
    script = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", script],
        input=json.dumps(request), capture_output=True, text=True, encoding="utf-8", timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        raise OSError("Local speech recognition failed. Check the installed en-US recognizer; no cloud fallback was used.")
    return json.loads(result.stdout.lstrip("\ufeff"))


def _default_input_identity(backend):
    index = int(backend.default.device[0])
    if index < 0:
        raise OSError("No default microphone is selected.")
    device = backend.query_devices(index, "input")
    return index, str(device.get("name", "")), int(device.get("hostapi", -1)), float(device.get("default_samplerate", 0))


def analyze_pcm(chunks, *, sample_rate=16000, frame_seconds=0.02, threshold=0.01):
    """Return bounded energy VAD metadata; PCM itself is never retained."""
    samples = array("h", b"".join(chunks))
    if sys.byteorder != "little":
        samples.byteswap()
    frame_size = int(sample_rate * frame_seconds)
    active = 0
    levels = []
    for offset in range(0, len(samples) - frame_size + 1, frame_size):
        frame = samples[offset:offset + frame_size]
        rms = math.sqrt(sum(value * value for value in frame) / frame_size) / 32768
        levels.append(rms)
        active += rms >= threshold
    return {
        "frame_milliseconds": int(frame_seconds * 1000), "threshold_rms": threshold,
        "active_frames": active, "total_frames": len(levels),
        "peak_frame_rms": round(max(levels, default=0), 6),
        # At least 0.24 s of voiced energy: brief clicks or bumps never reach a recognizer
        # (Whisper invents text such as "Thank you." from short noise).
        "speech_detected": active >= 12,
    }


MAX_CAPTURE_SECONDS = 12
WAIT_FOR_SPEECH_SECONDS = 5
END_SILENCE_SECONDS = 0.9
VAD_END_SILENCE_SECONDS = 0.6   # W3: with Silero deciding what is speech, the pause that ends a sentence is shorter
_CHUNK = 1600  # 100 ms at 16 kHz
LAST_END = {"at": None}         # when the last capture heard the speaker stop (monotonic): voice latency is from here


class SpeechProbability:
    """Silero VAD (shipped with faster-whisper, CPU, ~1 ms per call): is there speech in the last half second?
    It tells a voice from a fan, a keyboard or music far better than loudness alone (W3, 2026-10-29)."""

    WINDOW = 7680    # 0.48 s = 15 frames of 512 samples

    def __init__(self):
        from faster_whisper.vad import get_vad_model
        self.model = get_vad_model()
        self.recent = b""

    def __call__(self, chunk):
        import numpy as np
        self.recent = (self.recent + chunk)[-self.WINDOW * 2:]
        audio = np.frombuffer(self.recent, dtype=np.int16).astype(np.float32) / 32768.0
        usable = len(audio) // 512 * 512
        if usable == 0:
            return 0.0
        probabilities = np.asarray(self.model(audio[-usable:])).reshape(-1)
        return float(probabilities[-3:].max())


_vad = {"model": None, "failed": False}


def speech_probability():
    """A fresh SpeechProbability, or None when Silero cannot load (then loudness decides, as before)."""
    if _vad["failed"]:
        return None
    try:
        detector = SpeechProbability()
        return detector
    except Exception:
        _vad["failed"] = True
        return None


def _rms(chunk):
    samples = array("h", chunk)
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(v * v for v in samples) / max(len(samples), 1)) / 32768


LEVEL = {"rms": 0.0, "at": 0.0}  # latest microphone level while capturing (read by the HUD)


def capture(control, *, threshold=0.01, wait_seconds=WAIT_FOR_SPEECH_SECONDS, vad=True):
    """Record until the speaker pauses (end-of-speech endpointing), in memory only.

    Waits up to `wait_seconds` for speech (5 s; a follow-up window passes its own), stops 0.6 s after speech ends
    when Silero VAD is available (0.9 s by loudness otherwise), never exceeds 12 s.
    """
    import sounddevice as sd
    frames = []
    identity = _default_input_identity(sd)
    heard_speech, silent_chunks, active_run = False, 0, 0
    detector = speech_probability() if vad else None
    end_silence = VAD_END_SILENCE_SECONDS if detector is not None else END_SILENCE_SECONDS
    with sd.RawInputStream(device=identity[0], samplerate=16000, channels=1, dtype="int16") as stream:
        for index in range(int(MAX_CAPTURE_SECONDS * 10)):
            if index % 10 == 0:
                control.check()
                voice_session.check_capture()
                if _default_input_identity(sd) != identity:
                    raise OSError("The default microphone changed during capture; no transcript was produced.")
            chunk, overflowed = stream.read(_CHUNK)
            if overflowed:
                raise OSError("Microphone input overflowed; retry the voice request.")
            chunk = bytes(chunk)
            frames.append(chunk)
            level = _rms(chunk)
            LEVEL["rms"], LEVEL["at"] = level, time.monotonic()  # the HUD's reactor follows the voice
            loud = level >= threshold
            if detector is not None:
                loud = loud and detector(chunk) >= 0.5   # loud AND voice-like: a fan or a click does not count
            active_run = active_run + 1 if loud else 0
            if active_run >= 2:
                heard_speech = True
            if heard_speech:
                silent_chunks = 0 if loud else silent_chunks + 1
                if silent_chunks >= end_silence * 10:
                    LAST_END["at"] = time.monotonic() - end_silence
                    break
            elif index >= wait_seconds * 10:
                break
    control.check()
    voice_session.check_capture()
    pcm = b"".join(frames)
    from chutku.voice import speaker
    speaker.note_utterance(pcm)   # Owner Voice Lock (S19): memory only, scored when a voice task starts
    activity = analyze_pcm(frames)
    activity["captured_seconds"] = round(len(pcm) / 32000, 2)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return {"wav": base64.b64encode(buffer.getvalue()).decode("ascii"), "pcm": pcm, "activity": activity}


def command_language(base=None):
    """"en" (English only: Hinglish comes out translated) or "en|hi" (Whisper picks English or Hindi per clip)."""
    from chutku.app import PROJECT_ROOT
    from chutku.core.preferences import Preferences
    try:
        return Preferences(base or PROJECT_ROOT).load()["stt_language"]
    except (OSError, ValueError, KeyError):
        return "en"


def transcribe(captured):
    """Apply VAD before general local dictation; accept legacy string fixtures."""
    if isinstance(captured, dict):
        activity = captured.get("activity", {})
        if activity.get("speech_detected") is not True:
            return {"text": "", "confidence": 0, "culture": "en-US", "activity": activity}
        wav = captured.get("wav")
        if isinstance(captured.get("pcm"), (bytes, bytearray)):
            try:
                from chutku.voice.whisper_stt import WhisperUnavailable, transcribe_pcm
                heard = transcribe_pcm(bytes(captured["pcm"]), language=command_language())
                heard["activity"] = activity
                return heard
            except WhisperUnavailable:
                pass  # fall back to Windows offline dictation below
    else:
        activity, wav = None, captured
    heard = recognize({"action": "recognize", "wav": wav})
    if activity is not None:
        heard["activity"] = activity
    return heard


def _status(arguments, context):
    result = recognize({"action": "status"})
    result["mode"] = "free_form_dictation"
    from chutku.voice.whisper_stt import configured_model
    whisper = configured_model()
    result["engine"] = ("whisper:" + whisper["name"]) if whisper else "windows-dictation"
    result["language"] = ("Offline Whisper: English, Hindi and Hinglish (Romanized output); synthetic benchmark "
                          "only, human-voice accuracy not yet measured." if whisper else
                          "Installed en-US offline dictation; Hindi/Hinglish is not supported.")
    result["audio_session"] = voice_session.snapshot().state
    return ToolResult(result, Verification.PASS)


def _listen(arguments, context):
    control = ActionControl(context.granted_root.parent)
    with voice_session.active("listening"):
        audio = capture(control, wait_seconds=float(arguments.get("wait_seconds", WAIT_FOR_SPEECH_SECONDS)))
        control.check()
        voice_session.check_capture()
        heard = transcribe(audio)
    text, confidence = heard.get("text", ""), heard.get("confidence", 0)
    if not isinstance(text, str) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("Local recognizer returned an invalid result.")
    # Whisper's per-token probability runs lower than SAPI's confidence scale.
    accepted = bool(text.strip()) and confidence >= (0.35 if str(heard.get("engine", "")).startswith("whisper") else 0.55)
    if text.strip():
        from chutku.voice.heard import log_heard
        log_heard("hotkey", text, "command" if accepted else "ignored: unclear", confidence=confidence)
    output = {"transcript": text if accepted else None, "confidence": round(confidence, 3),
              "review_required": True, "executed": False, "provenance": "microphone_untrusted",
              "audio_saved": False,
              "capture_seconds": (heard.get("activity") or {}).get("captured_seconds"),
              "engine": heard.get("engine", "windows-dictation"), "language": heard.get("language"),
              "voice_activity": heard.get("activity"),
              "audio_session": "idle", "tts_self_trigger_suppressed": True,
              "message": "Chutku will analyze this transcript locally and show a tool plan for review." if accepted else "No confident speech was heard. Try again or type your request."}
    audit = {**output, "transcript": "[REDACTED]" if accepted else None}
    return ToolResult(output, Verification.PASS, audit)


LISTEN_SCHEMA = {"type": "object", "properties": {"wait_seconds": {"type": "number", "minimum": 1, "maximum": 15}},
                 "additionalProperties": False}


def _validate_listen(arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"wait_seconds"}:
        raise ValueError("Only wait_seconds (1-15) may be given.")
    wait = arguments.get("wait_seconds", WAIT_FOR_SPEECH_SECONDS)
    if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 1 <= wait <= 15:
        raise ValueError("wait_seconds must be between 1 and 15.")


def register_recognition(registry):
    from chutku.tools.assistant import _none
    registry.register(Tool("voice.recognition_status", "Inspect installed offline free-form speech recognition.",
                           Risk.OBSERVATION, _status, _none, argument_schema=EMPTY_ARGUMENT_SCHEMA,
                           prerequisites=("Windows offline speech recognizer",), reversibility="not_applicable",
                           success_predicate="recognizer_and_dictation_mode_status_returned"))
    registry.register(Tool("voice.listen_command", "Listen until the speaker pauses (max 12 s) and return a local offline transcript; never executes it by itself.",
                           Risk.REVERSIBLE, _listen, _validate_listen, argument_schema=LISTEN_SCHEMA,
                           prerequisites=("microphone and Windows offline speech recognizer",),
                           reversibility="transient", success_predicate="capture_completed_without_action_execution"))


def normalise_phrase(text):
    """Compare spoken commands by their words: case, punctuation and spacing are not speech errors
    ("Open Notepad." == "open notepad"); word order and wrong words still are."""
    import re
    return " ".join(re.sub(r"[^\w\s']", " ", (text or "").casefold()).split())
