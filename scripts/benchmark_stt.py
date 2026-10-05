"""Synthetic STT benchmark: Windows OneCore voices (en-US, en-IN, hi-IN) -> Whisper.

This measures model latency and keyword accuracy on synthetic speech only. It is
NOT a human-voice accuracy claim; consented own-voice trials remain separate.
"""
from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    ("en-US", "Zira", "Open Spotify.", [["spotify"]]),
    ("en-US", "Zira", "Search YouTube for lofi hip hop music.", [["youtube"], ["lofi", "lo-fi", "lo fi"]]),
    ("en-IN", "Heera", "Find the newest PDF in my downloads folder and open it.", [["pdf"], ["download"]]),
    ("en-IN", "Ravi", "What time is it?", [["time"]]),
    ("en-IN", "Heera", "Pause the music.", [["pause"]]),
    ("en-IN", "Ravi", "Create a folder called notes on the D drive.", [["folder"], ["notes"]]),
    ("hi-IN", "Kalpana", "स्पॉटिफाई खोलो", [["spotify", "स्पॉटिफाई", "स्पोटिफाई"], ["kholo", "खोलो", "kolo"]]),
    ("hi-IN", "Hemant", "कैलकुलेटर खोलो", [["calculator", "कैलकुलेटर", "केलकुलेटर"], ["kholo", "खोलो"]]),
    ("hi-IN", "Kalpana", "गाना रोको", [["gaana", "gana", "गाना"], ["roko", "रोको"]]),
    ("hi-IN", "Hemant", "यूट्यूब पे अरिजीत सिंह के गाने चलाओ", [["youtube", "यूट्यूब", "यू ट्यूब"], ["arijit", "अरिजीत", "अरिजित"]]),
    ("hi-IN", "Kalpana", "डाउनलोड्स फोल्डर में नई पीडीएफ खोलो", [["download", "डाउनलोड"], ["pdf", "पीडीएफ", "पी डी एफ"]]),
    ("hi-IN", "Hemant", "अभी कितने बजे हैं", [["बजे", "baje", "time"]]),
]

_SYNTH = r'''
$ErrorActionPreference = 'Stop'
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.Language -eq $request.culture -and $_.DisplayName -like ('*' + $request.voice + '*') } | Select-Object -First 1
if ($null -eq $voice) { throw 'voice missing' }
$synth.Voice = $voice
$stream = Await ($synth.SynthesizeTextToStreamAsync([string]$request.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
$memory = New-Object System.IO.MemoryStream
$net.CopyTo($memory)
[Convert]::ToBase64String($memory.ToArray())
'''


def synthesize(culture, voice, text):
    encoded = base64.b64encode(_SYNTH.encode("utf-16-le")).decode("ascii")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          input=json.dumps({"culture": culture, "voice": voice, "text": text}),
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    with wave.open(io.BytesIO(base64.b64decode(done.stdout.strip()))) as wav:
        return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels()


def score(text, keyword_groups):
    lowered = text.casefold()
    return all(any(k.casefold() in lowered for k in group) for group in keyword_groups)


def main():
    import numpy as np
    from faster_whisper import WhisperModel
    from chutku.voice import whisper_stt

    clips = []
    for culture, voice, text, keys in CASES:
        pcm, rate, channels = synthesize(culture, voice, text)
        audio = np.frombuffer(pcm, dtype=np.int16)
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
        clips.append((culture, voice, text, keys, audio.tobytes(), rate))
    results = {}
    names = sys.argv[1:] or ["faster-whisper-small", "faster-whisper-large-v3-turbo"]
    for name in names:
        load_started = time.monotonic()
        model = WhisperModel(str(ROOT / "models" / name), device="cpu", compute_type="int8", cpu_threads=6,
                             local_files_only=True)
        load_seconds = round(time.monotonic() - load_started, 2)
        rows = []
        for language in (None, "en"):
            for culture, voice, text, keys, pcm, rate in clips:
                whisper_stt._loaded.update(key=("bench", name), model=model)
                original = whisper_stt._load
                whisper_stt._load = lambda base=None: (model, {"name": name})
                try:
                    heard = whisper_stt.transcribe_pcm(pcm, sample_rate=rate, language=language)
                finally:
                    whisper_stt._load = original
                rows.append({"language_mode": language or "auto", "culture": culture, "voice": voice, "said": text,
                             "heard": heard["text"], "detected": heard["language"], "correct": score(heard["text"], keys),
                             "seconds": heard["seconds"], "audio_seconds": round(len(pcm) / 2 / rate, 2)})
        summary = {}
        for mode in ("auto", "en"):
            subset = [r for r in rows if r["language_mode"] == mode]
            summary[mode] = {"correct": sum(r["correct"] for r in subset), "total": len(subset),
                             "median_seconds": sorted(r["seconds"] for r in subset)[len(subset) // 2],
                             "max_seconds": max(r["seconds"] for r in subset)}
        results[name] = {"load_seconds": load_seconds, "summary": summary, "rows": rows}
        print(name, "load", load_seconds, "s", json.dumps(summary), flush=True)
        for r in rows:
            print(f"  [{r['language_mode']:4}] {'OK ' if r['correct'] else 'BAD'} {r['seconds']:5.2f}s "
                  f"{r['culture']} {r['said']!r} -> {r['heard']!r}", flush=True)
        del model
    report = {"generated_at": datetime.now(UTC).isoformat(), "device": "CPU int8, 6 threads (i5-12540H)",
              "scope": "Synthetic Windows OneCore voices only; not a human-speech accuracy claim.", "results": results}
    target = ROOT / "verification/stt-benchmark.json"
    if target.exists():  # keep earlier model results when re-running one model
        previous = json.loads(target.read_text(encoding="utf-8")).get("results", {})
        report["results"] = previous | results
    target.write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                                         encoding="utf-8")


if __name__ == "__main__":
    main()
