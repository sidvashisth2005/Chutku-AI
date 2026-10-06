"""Owner Voice Lock calibration (master plan S19): how well the speaker model tells voices apart.

Usage:
  .venv\\Scripts\\python.exe scripts\\calibrate_voice_lock.py [--owner DIR] [--impostors DIR]

- Always renders the same Hinglish/English lines with every installed Windows voice (SAPI) into
  D:\\ChutkuScratch\\voicelock\\sapi\\, so the pipeline is checked on real speech.
- --owner DIR: the owner's own 16 kHz mono WAV clips (e.g. recorded with `chutku.cli voice record`).
- --impostors DIR: other people / TV / YouTube clips (16 kHz mono WAV).

With owner clips it reports the owner-vs-impostor equal error rate (EER) and the threshold that keeps false accepts at
or below 1%, and writes verification/voice-lock.json. Without them it reports how far apart the Windows voices are
(each voice in turn plays "owner"), which proves the model works but is not the owner's calibration.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import subprocess
import sys
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.voice import speaker  # noqa: E402

OUT = Path(r"D:\ChutkuScratch\voicelock")
LINES = ["Oye Chutku, aaj ka weather batao aur Spotify par lofi chalao.",
         "Please send a message to mammi that I will be late today.",
         "Mere Downloads folder mein sabse badi file kaun si hai?",
         "Set the volume to thirty and open my calendar for tomorrow.",
         "Kal subah aath baje mujhe exam ke liye yaad dilana.",
         "What is on my screen right now, can you read it for me?"]

_RENDER = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$names = @()
foreach ($v in $s.GetInstalledVoices()) { if ($v.Enabled) { $names += $v.VoiceInfo.Name } }
foreach ($name in $names) {
  $s.SelectVoice($name)
  for ($i = 0; $i -lt $r.lines.Count; $i++) {
    $file = Join-Path $r.out (($name -replace '[^A-Za-z0-9]', '_') + "-" + $i + ".wav")
    $s.SetOutputToWaveFile($file, $fmt); $s.Speak($r.lines[$i]); $s.SetOutputToNull()
  }
}
$names | ConvertTo-Json -Compress
'''


def render_sapi():
    folder = OUT / "sapi"
    folder.mkdir(parents=True, exist_ok=True)
    shell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    done = subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command", _RENDER],
                          input=json.dumps({"out": str(folder), "lines": LINES}), capture_output=True, text=True,
                          timeout=300)
    names = json.loads(done.stdout or "[]")
    return folder, [names] if isinstance(names, str) else names


def read_wav(path):
    with wave.open(str(path), "rb") as stream:
        if stream.getframerate() != 16000 or stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError(f"{path.name}: needs 16 kHz mono 16-bit")
        return stream.readframes(stream.getnframes())


def embeddings(files):
    out = []
    for path in files:
        try:
            out.append(speaker.embed(read_wav(path)))
        except ValueError as error:
            print("skip", path.name, error)
    return out


def eer(genuine, impostor):
    """(equal error rate, threshold where false accepts and false rejects are closest)."""
    genuine, impostor = np.array(genuine), np.array(impostor)
    best_gap, best = None, None
    for threshold in np.linspace(-0.2, 1.0, 601):
        far, frr = float(np.mean(impostor >= threshold)), float(np.mean(genuine < threshold))
        if best_gap is None or abs(far - frr) < best_gap:
            best_gap, best = abs(far - frr), ((far + frr) / 2, threshold)
    return round(best[0], 4), round(float(best[1]), 3)


def far_threshold(impostor, target=0.01):
    ranked = sorted(impostor)
    index = min(len(ranked) - 1, int(np.ceil((1 - target) * len(ranked))))
    return round(float(ranked[index]) + 1e-3, 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner")
    parser.add_argument("--impostors")
    args = parser.parse_args()
    started = time.perf_counter()
    folder, voices = render_sapi()
    by_voice = {}
    for name in voices:
        key = "".join(c if c.isalnum() else "_" for c in name)
        by_voice[name] = embeddings(sorted(folder.glob(f"{key}-*.wav")))
    report = {"model": speaker.MODEL.name, "voices": {k: len(v) for k, v in by_voice.items()}}
    same, cross = [], []
    for name, vectors in by_voice.items():
        same += [speaker.cosine(a, b) for a, b in itertools.combinations(vectors, 2)]
        for other, others in by_voice.items():
            if other > name:
                cross += [speaker.cosine(a, b) for a in vectors for b in others]
    report["windows_voices"] = {"same_voice_mean": round(float(np.mean(same)), 3) if same else None,
                                "same_voice_min": round(float(np.min(same)), 3) if same else None,
                                "different_voice_mean": round(float(np.mean(cross)), 3) if cross else None,
                                "different_voice_max": round(float(np.max(cross)), 3) if cross else None}
    if same and cross:
        report["windows_voices"]["eer"], report["windows_voices"]["eer_threshold"] = eer(same, cross)
    if args.owner:
        owner = embeddings(sorted(Path(args.owner).glob("*.wav")))
        others = embeddings(sorted(Path(args.impostors).glob("*.wav"))) if args.impostors else []
        others += [v for vectors in by_voice.values() for v in vectors]
        mean = np.mean(owner[: max(1, len(owner) // 2)], axis=0)
        genuine = [speaker.cosine(v, mean) for v in owner[len(owner) // 2:]]
        impostor = [speaker.cosine(v, mean) for v in others]
        report["owner"] = {"clips": len(owner), "impostor_clips": len(others), "eer": eer(genuine, impostor)[0],
                           "threshold_far_1pct": far_threshold(impostor),
                           "genuine_min": round(min(genuine), 3), "impostor_max": round(max(impostor), 3)}
        (ROOT / "verification" / "voice-lock.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["seconds"] = round(time.perf_counter() - started, 1)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
