"""Chutku's neural voice (master plan S10 service): Kokoro-82M, voice hf_alpha, chosen by the owner's blind listening
test on 2026-10-07 (10 of 10 preferred over Windows SAPI Zira).

Text is split into sentences (also at the Devanagari danda "।"). While one sentence plays, the next is being made, so
speech starts after the first sentence instead of after the whole answer. ``stop()`` ("ruko" / "stop", the dashboard's
stop-speaking button) ends playback within about 0.1 s. When the model files are missing or anything fails, the
caller falls back to Windows SAPI, so Chutku never goes silent.
"""
from __future__ import annotations

from pathlib import Path
import queue
import re
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models" / "kokoro" / "kokoro-v1.0.onnx"
VOICES = ROOT / "models" / "kokoro" / "voices-v1.0.bin"
VOICE = "hf_alpha"
MAX_CHARS = 1000
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")

_engine = None
_engine_lock = threading.Lock()
_play_lock = threading.Lock()      # one voice at a time
stop_event = threading.Event()
STOPS = {"count": 0}    # every stop() adds one: a speech queue drops sentences queued before an interruption (W3)


def available():
    from chutku.voice.heard import _under_test
    if _under_test():
        return False   # a test run never loads the real model or plays sound (tests fake this function instead)
    return MODEL.is_file() and VOICES.is_file()


def sentences(text):
    """Split into speakable sentences; very long ones are cut at commas so the first audio comes quickly."""
    parts = []
    for sentence in _SENTENCE_END.split(" ".join(str(text).split())):
        while len(sentence) > 220 and "," in sentence[:220]:
            cut = sentence[:220].rindex(",") + 1
            parts.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            parts.append(sentence)
    return parts


def _model():
    global _engine
    with _engine_lock:
        if _engine is None:
            from kokoro_onnx import Kokoro
            _engine = Kokoro(str(MODEL), str(VOICES))
        return _engine


def synthesize(sentence):
    lang = "hi" if _DEVANAGARI.search(sentence) else "en-us"
    samples, rate = _model().create(sentence, voice=VOICE, lang=lang)
    return samples, rate


SPEAKING = {"envelope": (), "started": 0.0, "step": 0.05}   # her voice's loudness while she talks (presence orb, W4)


def speaking_level(now=None):
    """0..1 loudness of what Chutku is saying right now (0 when silent)."""
    envelope = SPEAKING["envelope"]
    if not envelope:
        return 0.0
    index = int(((now or time.monotonic()) - SPEAKING["started"]) / SPEAKING["step"])
    return float(envelope[index]) if 0 <= index < len(envelope) else 0.0


def _envelope(samples, rate, step=0.05):
    try:
        import numpy as np
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        size = max(1, int(rate * step))
        blocks = audio[:len(audio) // size * size].reshape(-1, size)
        rms = np.sqrt((blocks ** 2).mean(axis=1)) if len(blocks) else np.zeros(0)
        peak = float(rms.max()) if len(rms) else 0.0
        return tuple(float(v) for v in (rms / peak if peak > 0 else rms))
    except Exception:
        return ()


def _play(samples, rate, backend=None):
    """Play one clip; returns False when stopped."""
    sd = backend
    if sd is None:
        import sounddevice as sd
    SPEAKING.update(envelope=_envelope(samples, rate), started=time.monotonic())
    sd.play(samples, rate)
    end = time.monotonic() + len(samples) / rate + 0.5
    while time.monotonic() < end:
        if stop_event.is_set():
            sd.stop()
            SPEAKING["envelope"] = ()
            return False
        time.sleep(0.05)
    sd.wait()
    SPEAKING["envelope"] = ()
    return True


def speak(text, *, make=synthesize, play=_play):
    """Speak ``text`` sentence by sentence; the next sentence is made while the current one plays.

    Returns {"sentences": n spoken, "stopped": bool, "first_audio_s": seconds until the first sound}."""
    parts = sentences(str(text)[:MAX_CHARS])
    started = time.perf_counter()
    with _play_lock:
        stop_event.clear()
        made = queue.Queue(maxsize=2)

        def producer():
            for part in parts:
                if stop_event.is_set():
                    break
                try:
                    made.put(("ok", make(part)))
                except Exception as error:   # the caller falls back to SAPI for what is left
                    made.put(("error", error))
                    return
            made.put(("end", None))
        threading.Thread(target=producer, name="chutku-tts", daemon=True).start()
        spoken, first_audio = 0, None
        while True:
            kind, value = made.get()
            if kind == "end":
                break
            if kind == "error":
                if spoken == 0:
                    raise value
                break
            if first_audio is None:
                first_audio = time.perf_counter() - started
            if not play(*value):
                return {"sentences": spoken, "stopped": True, "first_audio_s": first_audio}
            spoken += 1
        return {"sentences": spoken, "stopped": stop_event.is_set(), "first_audio_s": first_audio}


def stop():
    """Stop speaking now ("ruko" / "stop", the stop-speaking endpoint, a hotkey barge-in)."""
    STOPS["count"] += 1
    stop_event.set()


def warm_up():
    """Load the model in the background so the first answer is not delayed by loading."""
    if available():
        try:
            synthesize("Haan.")
        except Exception:
            pass
