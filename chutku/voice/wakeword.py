"""Chutku's own "Oye Chutku" detector (2026-10-11): listens to every 80 ms of sound, ~1% CPU, no transcription.

Before, every sound went through Whisper (CPU) and the text was matched; Whisper was forced to English, so "Oye
Chutku" became "Why should it go?", songs and videos kept it busy, and far-away calls were lost. The detector is
trained by scripts/train_wake.py on openWakeWord's speech embedding (local ONNX models) and stored as plain numpy
weights in models/wake/oye_chutku.npz (np.load with allow_pickle=False: loading runs no code).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parents[2] / "models" / "wake" / "oye_chutku.npz"
REFRACTORY_FRAMES = 25          # 2 s after a wake, no second wake from the same words
CONTEXT_SAMPLES = 16000 * 5 // 2   # the last 2.5 s of sound, handed to Whisper to confirm a wake (two-stage, F3)


class Detector:
    def __init__(self, path: Path = MODEL, threshold: float | None = None):
        with np.load(path, allow_pickle=False) as data:   # closed here: an open .npz stays locked on Windows
            self.w1, self.b1, self.w2, self.b2 = data["w1"], data["b1"], data["w2"], data["b2"]
            self.mean, self.std = data["mean"], data["std"]
            self.threshold = float(threshold if threshold is not None else data["threshold"])
            self.meta = json.loads(str(data["meta"]))
        from openwakeword.utils import AudioFeatures
        self.features = AudioFeatures(inference_framework="onnx")
        self._pending = np.zeros(0, dtype=np.int16)
        self._recent = np.zeros(0, dtype=np.int16)
        # Two-stage (F3, 2026-10-29): the detector alone missed 5 of 9 owner clips at every threshold, so it now
        # runs at a low threshold as a cheap first stage and Whisper must hear the name in the same 2.5 s.
        self.two_stage = bool(self.meta.get("two_stage", False))
        self.cooldown = 0
        self.last_score = 0.0
        self.best_score = 0.0           # highest score since the last wake (shown in /api/state)

    def score(self) -> float:
        x = (self.features.get_features(16).reshape(1, -1) - self.mean) / self.std
        hidden = np.maximum(0, x @ self.w1 + self.b1)
        return float(1 / (1 + np.exp(-(hidden @ self.w2 + self.b2)[0, 0])))

    def feed(self, chunk: bytes) -> bool:
        """Feed raw 16 kHz int16 audio; True once when "Oye Chutku" has just been said."""
        incoming = np.frombuffer(chunk, dtype=np.int16)
        self._recent = np.concatenate([self._recent, incoming])[-CONTEXT_SAMPLES:]
        audio = np.concatenate([self._pending, incoming])
        woke = False
        while len(audio) >= 1280:
            self.features(audio[:1280])
            audio = audio[1280:]
            if self.cooldown:
                self.cooldown -= 1
                continue
            self.last_score = self.score()
            self.best_score = max(self.best_score, self.last_score)
            if self.last_score >= self.threshold:
                woke, self.cooldown = True, REFRACTORY_FRAMES
        self._pending = audio
        return woke

    def recent_audio(self) -> bytes:
        """The last 2.5 s of raw 16 kHz int16 sound (memory only), for the second stage."""
        return self._recent.tobytes()

    def reset(self):
        self.features.reset()
        self._pending = np.zeros(0, dtype=np.int16)
        self._recent = np.zeros(0, dtype=np.int16)


def available(path: Path = MODEL) -> bool:
    if not path.is_file():
        return False
    try:
        import openwakeword.utils  # noqa: F401
    except ImportError:
        return False
    return True
