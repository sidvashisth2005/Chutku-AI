r"""Neural voice spike (master plan S10): Kokoro-82M vs Windows SAPI on Chutku's own real replies.

    .venv\Scripts\python.exe scripts\tts_ab.py            # render + measure speed (no sound)
    .venv\Scripts\python.exe scripts\tts_ab.py --listen   # the owner's blind A/B test (plays pairs, press 1 or 2)

Rendering writes WAV files to D:\ChutkuScratch\tts_ab\ and prints how fast each voice is. The listening test plays
the same sentence twice in random order (Kokoro and SAPI); the owner presses 1 or 2 for the voice they prefer, or s to
skip. Choices are saved to verification\tts-ab.json. Chutku switches voices only if the owner prefers Kokoro.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = Path(r"D:\ChutkuScratch\tts_ab")
KOKORO_VOICES = ("hf_alpha", "hf_beta", "af_heart")
SAMPLES = 20
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def real_replies(count=SAMPLES):
    """Chutku's own recent replies (Hinglish Roman, Hindi script and English), cleaned, 15-220 characters."""
    rows = [json.loads(line) for line in (ROOT / "data" / "conversations.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    seen, texts = set(), []
    for row in reversed(rows):
        text = re.sub(r"\s*\[Verified:.*\]\s*$", "", row.get("reply", "")).strip().split("\n")[0]
        if 15 <= len(text) <= 220 and text not in seen:
            seen.add(text)
            texts.append(text)
    return list(reversed(texts[:count]))


def write_wav(path, samples, rate):
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)


_SAPI = r'''
$m = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$female = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq 'Female' } | Select-Object -First 1
if ($female) { $s.SelectVoice($female.VoiceInfo.Name) }
$s.SetOutputToWaveFile([string]$m.path)
$s.Speak([string]$m.text)
$s.Dispose()
'''


def render_sapi(text, path):
    from chutku.health import powershell_exe
    encoded = base64.b64encode(_SAPI.encode("utf-16-le")).decode("ascii")
    started = time.perf_counter()
    subprocess.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                   input=json.dumps({"text": text, "path": str(path)}), text=True, encoding="utf-8",
                   capture_output=True, timeout=60, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return time.perf_counter() - started


def render():
    from kokoro_onnx import Kokoro
    OUT.mkdir(parents=True, exist_ok=True)
    kokoro = Kokoro(str(ROOT / "models/kokoro/kokoro-v1.0.onnx"), str(ROOT / "models/kokoro/voices-v1.0.bin"))
    kokoro.create("warm up", voice="hf_alpha", lang="en-us")
    texts = real_replies()
    stats = {voice: [] for voice in KOKORO_VOICES} | {"sapi": []}
    for index, text in enumerate(texts):
        lang = "hi" if _DEVANAGARI.search(text) else "en-us"
        first = re.split(r"(?<=[.!?।])\s+", text)[0]
        for voice in KOKORO_VOICES:
            started = time.perf_counter()
            samples, rate = kokoro.create(text, voice=voice, lang=lang)
            took = time.perf_counter() - started
            started = time.perf_counter()
            kokoro.create(first, voice=voice, lang=lang)
            first_audio = time.perf_counter() - started
            write_wav(OUT / f"{index:02d}_{voice}.wav", samples, rate)
            stats[voice].append({"rtf": took / (len(samples) / rate), "first_audio_s": first_audio})
        took = render_sapi(text, OUT / f"{index:02d}_sapi.wav")
        with wave.open(str(OUT / f"{index:02d}_sapi.wav")) as audio:
            seconds = audio.getnframes() / audio.getframerate()
        stats["sapi"].append({"rtf": took / max(seconds, 0.1), "first_audio_s": took})
    (OUT / "texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {}
    for voice, rows in stats.items():
        rtf = sorted(r["rtf"] for r in rows)
        first = sorted(r["first_audio_s"] for r in rows)
        summary[voice] = {"median_rtf": round(rtf[len(rtf) // 2], 2), "median_first_audio_s": round(first[len(first) // 2], 2)}
        print(f"{voice:9} median RTF {summary[voice]['median_rtf']:.2f}  median first audio "
              f"{summary[voice]['median_first_audio_s']:.2f}s")
    (OUT / "speed.json").write_text(json.dumps({"samples": len(texts), "summary": summary}, indent=1), encoding="utf-8")
    print(f"{len(texts)} real replies rendered to {OUT}")


def listen():
    import sounddevice as sd
    import numpy as np
    texts = json.loads((OUT / "texts.json").read_text(encoding="utf-8"))
    choices = []
    print("Blind test: each sentence plays twice (A then B). Press 1 if you prefer A, 2 for B, s to skip, q to stop.")
    for index, text in enumerate(texts):
        pair = [("kokoro", OUT / f"{index:02d}_hf_alpha.wav"), ("sapi", OUT / f"{index:02d}_sapi.wav")]
        random.shuffle(pair)
        for label, (_, path) in zip("AB", pair):
            with wave.open(str(path)) as audio:
                data = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
                print(f"  {label}...", flush=True)
                sd.play(data, audio.getframerate())
                sd.wait()
            time.sleep(0.4)
        answer = input(f"[{index + 1}/{len(texts)}] {text[:60]!r}  prefer 1 (A) or 2 (B)? ").strip().casefold()
        if answer == "q":
            break
        if answer in {"1", "2"}:
            choices.append({"text": text, "preferred": pair[int(answer) - 1][0]})
    kokoro = sum(1 for c in choices if c["preferred"] == "kokoro")
    result = {"at": time.strftime("%Y-%m-%d %H:%M"), "answers": len(choices), "kokoro_preferred": kokoro,
              "sapi_preferred": len(choices) - kokoro, "switch": len(choices) >= 5 and kokoro > len(choices) / 2,
              "choices": choices}
    (ROOT / "verification" / "tts-ab.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    print(f"Kokoro preferred {kokoro} of {len(choices)}. Switch: {result['switch']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", action="store_true")
    (listen if parser.parse_args().listen else render)()
