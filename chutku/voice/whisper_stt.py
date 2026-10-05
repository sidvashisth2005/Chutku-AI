"""Offline Whisper speech-to-text (faster-whisper, CPU int8) for English/Hindi/Hinglish.

The model directory is integrity-checked against models/manifest.json before
loading. Audio stays in memory; nothing is uploaded. The model is loaded once
per process and reused.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import time

from chutku.app import PROJECT_ROOT

# Biases decoding toward Romanized Hinglish and the names users say to Chutku.
# Mixed on purpose: Hinglish (verb last) and plain English questions. With only Hinglish examples, Whisper
# rewrote the owner's "what time is it" as "what time it is" (live trials, 2026-10-01).
HINGLISH_PROMPT = ("Chutku, what time is it? Spotify kholo. Open Notepad. YouTube pe search karo. Calculator open "
                   "karo. System status. Downloads folder mein newest PDF kholo. Pause the music. Gaana roko. Next song. "
                   "List windows. Volume kam karo.")

# Phrases Whisper is known to produce from non-speech (noise, music, silence).
HALLUCINATIONS = frozenset({"thank you", "thank you very much", "thanks for watching", "thank you for watching",
                            "you", "bye", "bye bye", "subscribe", "please subscribe", "okay", "so", "hmm",
                            "the end", "music", "applause", "silence"})

_lock = threading.Lock()
_loaded = {"key": None, "model": None}


class WhisperUnavailable(OSError):
    pass


def configured_model(base: Path = PROJECT_ROOT):
    """Return the verified model entry from the manifest, or None if not configured."""
    from chutku.brain_service import directory_digest
    base = Path(base)
    try:
        manifest = json.loads((base / "models/manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = manifest.get("stt")
    if not isinstance(entry, dict):
        return None
    directory = (base / str(entry.get("directory", ""))).resolve()
    if directory.parent != (base / "models").resolve() or not directory.is_dir():
        return None
    return {**entry, "path": directory}


def _load(base: Path = PROJECT_ROOT):
    entry = configured_model(base)
    if entry is None:
        raise WhisperUnavailable("No Whisper model is configured.")
    key = (str(entry["path"]), entry.get("directory_sha256"))
    with _lock:
        if _loaded["key"] == key:
            return _loaded["model"], entry
        from chutku.brain_service import directory_digest
        if directory_digest(entry["path"]) != entry.get("directory_sha256"):
            raise WhisperUnavailable("Whisper model integrity check failed; it was not loaded.")
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise WhisperUnavailable("faster-whisper is not installed.") from error
        model = WhisperModel(str(entry["path"]), device="cpu", compute_type="int8", cpu_threads=6,
                             local_files_only=True)
        _loaded.update(key=key, model=model)
        return model, entry


def transcribe_pcm(pcm: bytes, *, sample_rate=16000, base: Path = PROJECT_ROOT, language=None, prompt=HINGLISH_PROMPT):
    """Transcribe mono int16 PCM. Returns text, language and a 0..1 confidence."""
    import numpy as np
    model, entry = _load(base)
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate != 16000:
        positions = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sample_rate))
        audio = np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)
    started = time.monotonic()
    # vad_filter: Whisper's own speech detector cuts non-speech before decoding; temperature 0: no random retries,
    # which made text out of noise (owner report 2026-10-04).
    segments, info = model.transcribe(
        audio, language=language, task="transcribe", beam_size=1, vad_filter=True, temperature=0.0,
        initial_prompt=prompt, condition_on_previous_text=False, without_timestamps=True)
    pieces, logprobs = [], []
    for segment in segments:
        if segment.no_speech_prob > 0.5 and segment.avg_logprob < -0.8:
            continue  # this piece is probably noise; keep the rest
        pieces.append(segment.text.strip())
        logprobs.append(segment.avg_logprob)
    text = " ".join(p for p in pieces if p).strip()
    confidence = math.exp(sum(logprobs) / len(logprobs)) if logprobs else 0.0
    # Whisper can echo the biasing prompt on near-silence. Short phrases are legitimate
    # commands ("Spotify kholo"), so only a long verbatim echo is discarded.
    if prompt and len(text.split()) >= 2 and text.casefold().replace(" ", "").strip(".!?,") in \
            prompt.casefold().replace(" ", ""):
        text, confidence = "", 0.0     # an echo of the biasing prompt, not speech
    from chutku.voice.heard import meaningful
    if text.casefold().strip(" .!?,") in HALLUCINATIONS or (text and not meaningful(text, short_answers_ok=True)):
        text, confidence = "", 0.0
    return {"text": text, "confidence": round(confidence, 3), "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "seconds": round(time.monotonic() - started, 3), "engine": "whisper:" + entry.get("name", "?")}
