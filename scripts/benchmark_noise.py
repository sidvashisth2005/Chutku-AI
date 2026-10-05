"""Noise benchmark for the wake path (owner report 2026-10-04: "Chutku hears random noises that aren't there").

Runs the real WakeListener loop (Segmenter -> voiced check -> faster-whisper -> filters -> split_wake) over
synthetic room sound: near-silence, fan hiss at three levels, mains hum, keyboard clicks, a door knock, music-like
chords, and a step from quiet to loud fan. Then the same with spoken wake phrases (OneCore voices) mixed in.
Reports false wakes per hour of noise and recall on the phrases. Real-room recordings are still needed for a
per-hour figure in the owner's room; this is the repeatable offline part.
"""
from __future__ import annotations

import json
import threading
import time
import types
from datetime import UTC, datetime
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.voice import heard  # noqa: E402
from chutku.voice.handsfree import WAKE_PROMPT, WakeListener  # noqa: E402
from chutku.voice.session import voice_session  # noqa: E402
from chutku.voice.whisper_stt import transcribe_pcm  # noqa: E402

RATE, CHUNK = 16000, 1600
rng = np.random.default_rng(7)


def seconds(n):
    return int(n * RATE)


def noise_scenes():
    t = lambda s: np.arange(seconds(s)) / RATE
    hiss = lambda level, s: rng.normal(0, level, seconds(s))
    clicks = np.zeros(seconds(30))
    for start in rng.integers(0, seconds(29.9), 120):             # typing: 4 keys a second
        clicks[start:start + 160] += rng.normal(0, 0.15, 160) * np.exp(-np.arange(160) / 30)
    knock = hiss(0.002, 20)
    for at in (3, 3.25, 3.5, 11, 11.3):
        i = seconds(at)
        knock[i:i + 800] += np.sin(2 * np.pi * 120 * np.arange(800) / RATE) * 0.4 * np.exp(-np.arange(800) / 200)
    chords = sum(0.03 * np.sin(2 * np.pi * f * t(40)) for f in (220, 277, 330, 440)) * \
        (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t(40))) + hiss(0.004, 40)
    step = np.concatenate([hiss(0.002, 10), hiss(0.02, 30)])
    return {
        "near_silence": hiss(0.0015, 40),
        "fan_soft": hiss(0.004, 40),
        "fan_medium": hiss(0.01, 40),
        "fan_loud": hiss(0.025, 40),
        "mains_hum": 0.02 * np.sin(2 * np.pi * 50 * t(30)) + hiss(0.003, 30),
        "keyboard": clicks + hiss(0.002, 30),
        "door_knock": knock,
        "music_chords": chords,
        "quiet_then_fan": step,
    }


def to_pcm(audio):
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()


class Stream:
    def __init__(self, pcm, done):
        self.pcm, self.at, self.done = pcm, 0, done

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _frames):
        if self.at >= len(self.pcm):
            self.done.set()
            time.sleep(0.01)
            return b"\0" * CHUNK * 2, False
        piece = self.pcm[self.at:self.at + CHUNK * 2]
        self.at += CHUNK * 2
        return piece.ljust(CHUNK * 2, b"\0"), False


def run(pcm):
    done, woke, log = threading.Event(), [], []
    backend = types.SimpleNamespace(RawInputStream=lambda **_: Stream(pcm, done))
    listener = WakeListener(lambda command: woke.append(command),
                            lambda segment: transcribe_pcm(segment, language="en", prompt=WAKE_PROMPT),
                            backend=backend)
    with patch.object(voice_session, "quiet_for", return_value=5.0), \
            patch.object(heard, "log_heard", lambda *a, **k: log.append((*a[1:3], k.get("confidence")))):
        listener.start()
        done.wait(600)
        deadline = time.time() + 30
        while listener.handling and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        listener.stop()
        listener.join(5)
    return woke, listener.segments_heard, log


def main():
    total_seconds, false_wakes, report = 0.0, 0, {"noise": {}, "speech": []}
    for name, audio in noise_scenes().items():
        woke, segments, log = run(to_pcm(audio))
        total_seconds += len(audio) / RATE
        false_wakes += len(woke)
        report["noise"][name] = {"seconds": len(audio) / RATE, "segments_to_whisper": segments, "wakes": woke,
                                 "heard": log}
        print(f"{name:15s} {len(audio) / RATE:5.0f}s  segments={segments:2d}  wakes={len(woke)}  heard={log}",
              flush=True)
    per_hour = false_wakes * 3600 / total_seconds
    print(f"noise total {total_seconds:.0f}s: {false_wakes} false wakes ({per_hour:.1f}/hour)")

    from scripts.benchmark_stt import synthesize
    from scripts.verify_voice_agent import to_16k_mono
    hits = 0
    phrases = [("en-IN", "Heera", "Oye Chutku, open Spotify."), ("en-IN", "Ravi", "Oye Chutku, gaana roko."),
               ("en-IN", "Ravi", "Chutku, what time is it?"), ("hi-IN", "Kalpana", "ओए छुटकू, टाइम बताओ")]
    for culture, voice, text in phrases:
        speech = np.frombuffer(to_16k_mono(*synthesize(culture, voice, text)), dtype=np.int16) / 32768
        audio = rng.normal(0, 0.004, seconds(2) * 2 + len(speech))     # over a soft fan
        audio[seconds(2):seconds(2) + len(speech)] += speech
        woke, _, log = run(to_pcm(audio))
        hits += bool(woke)
        report["speech"].append({"voice": voice, "said": text, "woke": woke, "heard": log})
        print(f"speech {voice:8s} {text!r:32s} woke={woke} heard={log}", flush=True)
    print(f"recall {hits}/{len(phrases)}")
    report |= {"generated_at": datetime.now(UTC).isoformat(), "noise_seconds": total_seconds,
               "false_wakes": false_wakes, "false_wakes_per_hour": round(per_hour, 2),
               "recall": f"{hits}/{len(phrases)}",
               "scope": "Synthetic noise and OneCore voices through the real wake loop and Whisper; not a real room."}
    (ROOT / "verification/noise-benchmark.json").write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                                           encoding="utf-8")


if __name__ == "__main__":
    main()
