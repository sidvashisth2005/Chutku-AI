"""Owner Voice Lock (master plan S19): only the owner's voice gives tasks.

A WeSpeaker ResNet34 speaker model (ONNX, CPU, models/speaker/) turns a few seconds of speech into a 256-number
voice embedding. Enrollment averages the owner's clips into ``data/voiceprint.npy``; it never leaves this PC and is
never sent to Gemini. When the lock is on and a voice request does not sound like the owner, every step that changes
something waits for an on-screen click (questions and chat still work), and that request cannot be approved by voice.

Every place that records the microphone hands its latest utterance here (``note_utterance`` / ``feed``); the
dashboard scores it once when the voice request starts (``verify_recent``).

Honest limit: a recording of the owner's voice can pass. This is a convenience filter against other people and the
TV, not a security boundary.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import threading
import time

import numpy as np

MODEL = Path(__file__).resolve().parents[2] / "models" / "speaker" / "voxceleb_resnet34_LM.onnx"
SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = 0.55
MIN_SECONDS = 1.0           # shorter speech is too little to judge: "not sure", which counts as not the owner
RECENT_SECONDS = 20         # an utterance older than this is not the one that started the request
RING_SECONDS = 15           # live conversation: the last seconds of raw microphone sound
LIVE_WINDOW_SECONDS = 6

# What the owner reads during enrollment: Hinglish and English, like real requests (about 5 seconds each).
ENROLL_LINES = [
    "Oye Chutku, aaj ka weather batao aur meri reminders bhi dikhao.",
    "Please open Spotify and play some lofi music for studying.",
    "Mammi ko WhatsApp pe bolo ki main thodi der mein ghar aa raha hoon.",
    "What is the biggest file in my Downloads folder right now?",
    "Kal subah aath baje mujhe exam ke liye yaad dila dena, theek hai?",
    "Set the volume to thirty and turn the brightness down a little.",
    "Mere desktop pe kitni files hain aur sabse nayi kaun si hai?",
    "Search YouTube for Arijit Singh songs and open the first one.",
]

_session = None
_session_lock = threading.Lock()
_recent = {"pcm": None, "at": 0.0}
_ring = deque()
_ring_lock = threading.Lock()


# -- features (Kaldi-compatible log-mel filterbank, as WeSpeaker was trained) -------------------------------------------

def _mel(f):
    return 1127.0 * np.log(1.0 + f / 700.0)


def _mel_banks(bins=80, fft=512, rate=SAMPLE_RATE, low=20.0, high=None):
    high = high or rate / 2
    mel_low, mel_high = _mel(low), _mel(high)
    centers = np.linspace(mel_low, mel_high, bins + 2)
    freqs = _mel(np.arange(fft // 2) * rate / fft)
    banks = np.zeros((bins, fft // 2 + 1), dtype=np.float32)
    for m in range(bins):
        left, center, right = centers[m], centers[m + 1], centers[m + 2]
        up = (freqs - left) / (center - left)
        down = (right - freqs) / (right - center)
        banks[m, :fft // 2] = np.maximum(0.0, np.minimum(up, down))
    return banks


_BANKS = _mel_banks()
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 399)) ** 0.85   # Kaldi "povey" window


def fbank(samples):
    """(frames, 80) log-mel features of 16 kHz mono float samples in [-1, 1], mean-normalised over time."""
    wave = np.asarray(samples, dtype=np.float32) * 32768.0
    if wave.size < 400:
        raise ValueError("Too little audio.")
    count = 1 + (wave.size - 400) // 160
    index = np.arange(400)[None, :] + 160 * np.arange(count)[:, None]
    frames = wave[index].astype(np.float64)
    frames -= frames.mean(axis=1, keepdims=True)                          # remove DC offset
    frames[:, 1:] -= 0.97 * frames[:, :-1].copy()                         # pre-emphasis
    frames[:, 0] -= 0.97 * frames[:, 0]
    frames *= _WINDOW
    spectrum = np.abs(np.fft.rfft(frames, n=512)) ** 2
    energies = spectrum @ _BANKS.T
    features = np.log(np.maximum(energies, np.finfo(np.float32).eps)).astype(np.float32)
    return features - features.mean(axis=0, keepdims=True)


def to_samples(pcm):
    """16-bit little-endian mono bytes (or an int16/float array) as float samples in [-1, 1]."""
    if isinstance(pcm, (bytes, bytearray, memoryview)):
        return np.frombuffer(bytes(pcm), dtype=np.int16).astype(np.float32) / 32768.0
    array = np.asarray(pcm)
    return array.astype(np.float32) / 32768.0 if array.dtype == np.int16 else array.astype(np.float32)


def _voiced(samples, rate=SAMPLE_RATE):
    """Only the parts that carry speech (20 ms frames well above the clip's quiet floor)."""
    frame = rate // 50
    usable = samples[: len(samples) // frame * frame].reshape(-1, frame)
    if not len(usable):
        return samples
    energy = np.sqrt((usable ** 2).mean(axis=1))
    floor = np.percentile(energy, 20)
    keep = energy > max(floor * 3, 0.005)
    return usable[keep].reshape(-1) if keep.sum() >= 10 else samples


def voiced_seconds(pcm):
    return len(_voiced(to_samples(pcm))) / SAMPLE_RATE


# -- the model --------------------------------------------------------------------------------------------------------

def available():
    return MODEL.is_file()


def _model():
    global _session
    with _session_lock:
        if _session is None:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            _session = ort.InferenceSession(str(MODEL), options, providers=["CPUExecutionProvider"])
        return _session


def embed(pcm):
    """The L2-normalised 256-number voice embedding of an utterance."""
    samples = _voiced(to_samples(pcm))
    if len(samples) < MIN_SECONDS * SAMPLE_RATE:
        raise ValueError("Too little speech to recognise the voice.")
    features = fbank(samples)[None, :, :]
    vector = _model().run(None, {"feats": features})[0][0]
    return vector / (np.linalg.norm(vector) + 1e-9)


def cosine(a, b):
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


# -- the owner's voiceprint -------------------------------------------------------------------------------------------

def voiceprint_path(base):
    return Path(base) / "data" / "voiceprint.npy"


def enroll(base, clips):
    """Average the owner's clips (each at least 2 s of speech) into the voiceprint. Returns the number used."""
    good = [embed(c) for c in clips if voiced_seconds(c) >= 2.0]
    if len(good) < 6:
        raise ValueError(f"Only {len(good)} clear clips (6 needed, each at least 2 seconds of speech). Try again "
                         "somewhere quiet.")
    mean = np.mean(good, axis=0)
    path = voiceprint_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, (mean / np.linalg.norm(mean)).astype(np.float32))
    return len(good)


def load_voiceprint(base):
    try:
        vector = np.load(voiceprint_path(base))
        return vector if vector.shape == (256,) else None
    except (OSError, ValueError):
        return None


def settings(base):
    from chutku.core.preferences import Preferences
    values = Preferences(base).load()
    return bool(values.get("voice_lock")), float(values.get("voice_lock_threshold") or DEFAULT_THRESHOLD)


def score(base, pcm):
    print_ = load_voiceprint(base)
    if print_ is None:
        raise ValueError("No voice is enrolled.")
    return cosine(embed(pcm), print_)


def is_owner(base, pcm):
    """(True/False/None, score). None: the lock is off or nobody is enrolled (no change to anything)."""
    enabled, threshold = settings(base)
    if not enabled or load_voiceprint(base) is None or not available():
        return None, None
    try:
        value = score(base, pcm)
    except ValueError:
        return False, None   # too little speech to tell: not treated as the owner (fail closed)
    return value >= threshold, round(value, 3)


# -- hand-off from the microphone code ----------------------------------------------------------------------------------

def note_utterance(pcm):
    """The utterance a local voice request was transcribed from (Whisper paths)."""
    _recent["pcm"], _recent["at"] = bytes(pcm) if pcm is not None else None, time.monotonic()


def feed(chunk):
    """Raw live-conversation microphone sound; the last RING_SECONDS are kept in memory only."""
    data = bytes(chunk)
    with _ring_lock:
        _ring.append((time.monotonic(), data))
        while _ring and _ring[0][0] < time.monotonic() - RING_SECONDS:
            _ring.popleft()


def _live_window():
    with _ring_lock:
        cutoff = time.monotonic() - LIVE_WINDOW_SECONDS
        return b"".join(data for at, data in _ring if at >= cutoff)


def verify_recent(base):
    """Score the utterance that started this voice request: (True/False/None, score)."""
    enabled, _threshold = settings(base)
    if not enabled:
        return None, None
    if _recent["pcm"] and time.monotonic() - _recent["at"] <= RECENT_SECONDS:
        pcm = _recent["pcm"]
    else:
        pcm = _live_window()
    if not pcm:
        return (False, None) if load_voiceprint(base) is not None else (None, None)
    return is_owner(base, pcm)
