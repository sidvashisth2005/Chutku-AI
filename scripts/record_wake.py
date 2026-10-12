"""Guided recording of the owner's "Oye Chutku" (for scripts/train_wake.py). Hands-free: Chutku speaks each
instruction and beeps; nothing to press. Clips stay on this PC: data/wake/owner/*.wav (wake phrase) and
data/wake/owner_negative/*.wav (ordinary talk, so she learns what NOT to wake on). data/ is never committed.

Run: .venv\\Scripts\\python.exe scripts/record_wake.py [--near N --far N --soft N --talk SECONDS]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RATE = 16000
POS = ROOT / "data" / "wake" / "owner"
NEG = ROOT / "data" / "wake" / "owner_negative"


def say(text):
    import sounddevice as sd
    try:
        from chutku.voice import tts
        samples, rate = tts.synthesize(text)
        sd.play(samples, rate)
        sd.wait()
    except Exception:
        print("  (voice unavailable) " + text)
    print(text, flush=True)


def beep():
    import winsound
    winsound.Beep(1000, 150)


def save(folder, pcm):
    folder.mkdir(parents=True, exist_ok=True)
    number = len(list(folder.glob("*.wav"))) + 1
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{number:03d}.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())
    return path


def record(seconds):
    import sounddevice as sd
    audio = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="int16")
    sd.wait()
    return audio[:, 0]


def level(pcm):
    return float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)) / 32768)


def utterances(pcm):
    """Cut a continuous recording into separate utterances (100 ms energy, adaptive floor)."""
    frames = [level(pcm[i:i + 1600]) for i in range(0, len(pcm) - 1600, 1600)]
    floor = float(np.percentile(frames, 20)) if frames else 0.0
    loud = [f > max(floor * 4, 0.003) for f in frames]
    spans, start, quiet = [], None, 0
    for index, is_loud in enumerate(loud + [False] * 5):
        if is_loud:
            start = index if start is None else start
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet >= 4:                         # 0.4 s of quiet ends the utterance
                spans.append((start, index - quiet + 1))
                start, quiet = None, 0
    out = []
    for first, last in spans:
        if 4 <= last - first <= 25:                # 0.4-2.5 s: a wake phrase, not a cough or a long sentence
            out.append(pcm[max(0, (first - 3) * 1600):min(len(pcm), (last + 3) * 1600)])
    return out


def takes(seconds, instruction):
    """Record continuously; the owner says "Oye Chutku" at their own pace, every few seconds."""
    say(instruction)
    beep()
    pcm = record(seconds)
    beep()
    found = utterances(pcm)
    for clip in found:
        save(POS, clip)
    print(f"  {len(found)} utterances found in {seconds} s", flush=True)
    return len(found)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--near", type=int, default=30, help="seconds")
    parser.add_argument("--far", type=int, default=35, help="seconds")
    parser.add_argument("--soft", type=int, default=20, help="seconds")
    parser.add_argument("--talk", type=int, default=0)
    args = parser.parse_args()
    say("Wake word recording. Beep ke baad, apni speed se, har teen chaar second mein Oye Chutku boliye. "
        "Doosri beep pe ruk jaiye.")
    if args.near:
        takes(args.near, "Pehle paas se, normal awaaz mein.")
    if args.far:
        say("Ab do teen metre door chale jaiye, jaise kaam karte waqt bolte hain.")
        time.sleep(5)
        takes(args.far, "Door se. Beep ke baad shuru.")
    if args.soft:
        takes(args.soft, "Ab paas aake, thoda dheere aur casually.")
    if args.talk:
        say(f"Last step. Ab {args.talk} second tak kuch bhi normal baat kijiye, par Chutku mat boliye. Beep ke baad shuru.")
        beep()
        pcm = record(args.talk)
        save(NEG, pcm)
        beep()
    say("Ho gaya, shukriya! Ab main aapki awaaz se seekh rahi hoon.")


if __name__ == "__main__":
    main()
