"""Train Chutku's own "Oye Chutku" wake-word detector (local, no cloud, no account).

Why: the Whisper-based wake path transcribed every sound and forced English, so "Oye Chutku" came out as "Why should
it go?" and far-away calls were missed (owner, 2026-10-11: "chhe baar mein karti hai, door se toh hota hi nahi").

How:
- Features: openWakeWord's pretrained speech embedding (melspectrogram + embedding ONNX models, Apache-2.0), 16 frames
  of 96 numbers = the last 1.28 s of sound, computed every 80 ms.
- Positives: "Oye Chutku" / "ओए छुटकू" spoken by Kokoro voices (Hindi + English + blended voices, 3 speeds) and Windows
  voices, plus the owner's own recordings in data/wake/owner/*.wav when present (weighted higher). Every clip is
  augmented: distance (quiet), room echo, fan noise, a video or song playing behind.
- Negatives: ordinary Hindi/English/Hinglish speech, look-alikes ("Chotu", "chutki", "Why should I go"), noise, music.
- Model: a tiny 2-layer network, saved as plain numpy weights (models/wake/oye_chutku.npz): loading it runs no code.
- Test: voices never seen in training, near and far; false wakes per hour on a long non-wake stream.

Run: .venv\\Scripts\\python.exe scripts/train_wake.py   (about 10-20 minutes on CPU)
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RATE = 16000
WINDOW = int(2.0 * RATE)             # each training example: 2 s, the phrase ending ~0.25 s before the end
OUT = ROOT / "models" / "wake" / "oye_chutku.npz"            # the live model: only written by a passing run
CANDIDATE = ROOT / "models" / "wake" / "candidate.npz"
REPORT = ROOT / "verification" / "wake-detector.json"
OWNER_CLIPS = ROOT / "data" / "wake" / "owner"
OWNER_TALK = ROOT / "data" / "wake" / "owner_negative"
rng = np.random.default_rng(11)

POSITIVE_TEXTS = [("ओए छुटकू", "hi"), ("ओय छुटकू", "hi"), ("ओए छुटकू!", "hi"), ("Oye Chutku", "en-us"),
                  ("Oye Chhutku!", "en-us"), ("Oi Chutku", "en-us")]
NEGATIVE_TEXTS = [
    ("छोटू इधर आओ", "hi"), ("एक चुटकी नमक डालो", "hi"), ("कल ऑफिस जाना है", "hi"), ("ओए, सुन ना यार", "hi"),
    ("चुटकुला सुनाओ", "hi"), ("ओए होए क्या बात है", "hi"), ("मुझे भूख लगी है", "hi"), ("टाइम क्या हुआ है", "hi"),
    ("गाना चलाओ", "hi"), ("पापा घर आ गए", "hi"), ("ठीक है, कल मिलते हैं", "hi"), ("छुट्टी कब है", "hi"),
    ("Why should I go there?", "en-us"), ("I should go home now", "en-us"), ("Good morning to you", "en-us"),
    ("You're my sweetie pie", "en-us"), ("Hey Google, what's the weather?", "en-us"), ("Okay, open the file", "en-us"),
    ("Let's meet at four", "en-us"), ("Oye Chotu, come here", "en-us"), ("Chutney was delicious", "en-us"),
    ("What time is it?", "en-us"), ("Subscribe to my channel", "en-us"), ("Play the next video", "en-us"),
    ("Spotify kholo aur gaana chalao", "en-us"), ("Bhai ye code chal nahi raha", "en-us"),
    ("Oye, listen to me", "en-us"), ("Chuck, could you help", "en-us"), ("Hey Jarvis", "en-us"),
]
TRAIN_HI = ["hf_alpha", "hm_omega", "hm_psi"]
TEST_HI = ["hf_beta"]
TRAIN_EN = ["af_heart", "af_bella", "af_nicole", "af_sarah", "am_adam", "am_michael", "am_onyx", "bf_emma",
            "bm_george", "bm_lewis", "af_sky", "am_puck", "if_sara", "im_nicola"]
TEST_EN = ["af_nova", "am_echo", "bf_lily", "bm_daniel"]
WINDOWS_VOICES_TEST = [("hi-IN", "Kalpana"), ("hi-IN", "Hemant"), ("en-IN", "Heera"), ("en-IN", "Ravi")]


def kokoro():
    from kokoro_onnx import Kokoro
    return Kokoro(str(ROOT / "models/kokoro/kokoro-v1.0.onnx"), str(ROOT / "models/kokoro/voices-v1.0.bin"))


def to16k(samples, rate):
    samples = np.asarray(samples, dtype=np.float32)
    if rate != RATE:
        samples = np.interp(np.linspace(0, len(samples) - 1, int(len(samples) * RATE / rate)),
                            np.arange(len(samples)), samples)
    peak = np.abs(samples).max() or 1.0
    return (samples / peak * 0.7 * 32767).astype(np.float32)


def speak(engine, text, lang, voice, speed=1.0):
    style = voice if isinstance(voice, str) else voice
    samples, rate = engine.create(text, voice=style, lang=lang, speed=speed)
    return to16k(samples, rate)


def trim(audio):
    """Cut leading/trailing silence so the phrase can be placed exactly."""
    loud = np.where(np.abs(audio) > 0.02 * (np.abs(audio).max() or 1))[0]
    return audio[loud[0]:loud[-1] + 1] if len(loud) else audio


def place(phrase, end_gap=None):
    """Put the phrase into a 2 s window, ending 0.15-0.35 s before the end."""
    phrase = trim(phrase)[-WINDOW + 800:]
    gap = int((end_gap if end_gap is not None else rng.uniform(0.15, 0.35)) * RATE)
    window = np.zeros(WINDOW, dtype=np.float32)
    start = max(0, WINDOW - gap - len(phrase))
    window[start:start + len(phrase)] = phrase[: WINDOW - start]
    return window


def reverb(audio, seconds):
    n = int(seconds * RATE)
    tail = rng.normal(0, 1, n) * np.exp(-np.arange(n) / (seconds * RATE / 6))
    tail[0] = 0
    response = np.concatenate([[1.0], tail / (np.abs(tail).sum() or 1) * rng.uniform(0.6, 1.6)])
    return np.convolve(audio, response)[: len(audio)].astype(np.float32)


def augment(window, backgrounds, far=None):
    """Distance, room echo, fan noise and something playing behind; far=True forces a far-away version."""
    audio = window.copy()
    if far is None:
        far = rng.random() < 0.5
    if rng.random() < (0.85 if far else 0.4):
        audio = reverb(audio, rng.uniform(0.2, 0.7) if far else rng.uniform(0.1, 0.3))
    audio *= 10 ** (rng.uniform(-30, -14) / 20) if far else 10 ** (rng.uniform(-8, 0) / 20)
    audio += rng.normal(0, rng.uniform(5, 120), len(audio))                      # fan / hiss / mic noise
    if backgrounds and rng.random() < 0.5:
        back = backgrounds[rng.integers(len(backgrounds))]
        offset = rng.integers(max(1, len(back) - WINDOW))
        part = np.resize(back[offset:offset + WINDOW], WINDOW)
        audio += part * 10 ** (rng.uniform(-34, -18) / 20)                       # a video/song behind
    return np.clip(audio, -32768, 32767).astype(np.int16)


def music(seconds):
    t = np.arange(int(seconds * RATE)) / RATE
    out = np.zeros_like(t)
    for start in np.arange(0, seconds, 0.5):
        notes = rng.choice([220, 247, 262, 294, 330, 349, 392, 440, 494, 523], 3)
        mask = (t >= start) & (t < start + 0.5)
        for f in notes:
            out[mask] += np.sin(2 * np.pi * f * t[mask]) * np.exp(-(t[mask] - start) * 3)
    out += np.convolve(rng.normal(0, 0.3, len(t)), np.ones(40) / 40, "same") * (np.sin(2 * np.pi * 2 * t) > 0.9)
    return (out / (np.abs(out).max() or 1) * 0.5 * 32767).astype(np.float32)


def owner_clips(folder=OWNER_CLIPS, raw=False):
    clips = []
    for path in sorted(folder.glob("*.wav")) if folder.exists() else []:
        with wave.open(str(path)) as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32)
            clips.append(pcm if raw or folder == OWNER_TALK else to16k(pcm / 32767, wav.getframerate()))
    return clips


def features(windows):
    from openwakeword.utils import AudioFeatures
    extractor = AudioFeatures(inference_framework="onnx")
    out = []
    for start in range(0, len(windows), 64):
        batch = np.stack(windows[start:start + 64]).astype(np.int16)
        emb = extractor.embed_clips(batch, batch_size=64)          # (n, frames, 96)
        out.append(emb[:, -16:, :].reshape(len(batch), -1))
    return np.concatenate(out).astype(np.float32)


class Net:
    """Tiny MLP in numpy: 1536 -> 64 -> 1, trained with Adam on weighted log-loss."""

    def __init__(self, inputs, hidden=64):
        self.w1 = rng.normal(0, np.sqrt(2 / inputs), (inputs, hidden)).astype(np.float32)
        self.b1 = np.zeros(hidden, np.float32)
        self.w2 = rng.normal(0, np.sqrt(1 / hidden), (hidden, 1)).astype(np.float32)
        self.b2 = np.zeros(1, np.float32)

    def forward(self, x):
        h = np.maximum(0, x @ self.w1 + self.b1)
        return h, 1 / (1 + np.exp(-(h @ self.w2 + self.b2)[:, 0]))

    def fit(self, x, y, weight, epochs=60, lr=1e-3, l2=1e-4):
        params = [self.w1, self.b1, self.w2, self.b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        step = 0
        for _epoch in range(epochs):
            order = rng.permutation(len(x))
            for start in range(0, len(x), 128):
                idx = order[start:start + 128]
                xb, yb, wb = x[idx], y[idx], weight[idx]
                h, p = self.forward(xb)
                d = (p - yb) * wb / wb.sum()
                g2 = h.T @ d[:, None] + l2 * self.w2
                gb2 = d.sum(keepdims=True)
                dh = (d[:, None] @ self.w2.T) * (h > 0)
                g1 = xb.T @ dh + l2 * self.w1
                gb1 = dh.sum(0)
                step += 1
                for i, g in enumerate([g1, gb1, g2, gb2]):
                    m[i] = 0.9 * m[i] + 0.1 * g
                    v[i] = 0.999 * v[i] + 0.001 * g * g
                    params[i] -= lr * (m[i] / (1 - 0.9 ** step)) / (np.sqrt(v[i] / (1 - 0.999 ** step)) + 1e-8)

    def save(self, path, mean, std, threshold, meta):
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2, mean=mean, std=std,
                 threshold=np.float32(threshold), meta=np.array(json.dumps(meta)))


def stream_false_wakes(net, mean, std, threshold, audio):
    """Run the detector over a long stream the way the live listener does; count separate triggers."""
    from openwakeword.utils import AudioFeatures
    extractor = AudioFeatures(inference_framework="onnx")
    triggers, cooldown = 0, 0
    for start in range(0, len(audio) - 1280, 1280):
        extractor(audio[start:start + 1280].astype(np.int16))
        if cooldown:
            cooldown -= 1
            continue
        x = (extractor.get_features(16).reshape(1, -1) - mean) / std
        if net.forward(x)[1][0] >= threshold:
            triggers, cooldown = triggers + 1, 25          # 2 s refractory, as live
    return triggers


def main():
    started = time.monotonic()
    engine = kokoro()
    blends = []
    for _ in range(8):   # new speakers: blends of two Hindi/English training voices
        a, b = rng.choice(TRAIN_HI + TRAIN_EN[:6], 2, replace=False)
        mix = rng.uniform(0.3, 0.7)
        blends.append(engine.get_voice_style(a) * mix + engine.get_voice_style(b) * (1 - mix))

    def say_all(texts, voices, speeds):
        import hashlib
        key = hashlib.sha256(repr((texts, speeds)).encode() + b"".join(
            v.encode() if isinstance(v, str) else np.asarray(v).tobytes() for v in voices)).hexdigest()[:16]
        cache = ROOT / "data" / "wake" / "cache" / f"synth-{key}.npz"
        if cache.is_file():
            stored = np.load(cache, allow_pickle=False)
            return np.split(stored["audio"], np.cumsum(stored["lengths"])[:-1])
        out = []
        for text, lang in texts:
            for voice in voices:
                for speed in speeds:
                    try:
                        out.append(speak(engine, text, lang, voice, speed))
                    except Exception as error:   # one bad voice/text pair is skipped, not fatal
                        print("skip", text, getattr(voice, "shape", voice), error)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, audio=np.concatenate(out), lengths=np.array([len(a) for a in out]))
        return out

    print("synthesizing ...", flush=True)
    pos_train = say_all(POSITIVE_TEXTS, TRAIN_HI + TRAIN_EN + blends, [0.85, 1.0, 1.15])
    pos_test = say_all(POSITIVE_TEXTS, TEST_HI + TEST_EN, [1.0])
    neg_train = say_all(NEGATIVE_TEXTS, TRAIN_HI + TRAIN_EN[:8], [1.0])
    neg_test = say_all(NEGATIVE_TEXTS, TEST_HI + TEST_EN, [1.0])
    try:
        from scripts.benchmark_stt import synthesize
        from scripts.verify_voice_agent import to_16k_mono
        for culture, voice in WINDOWS_VOICES_TEST:
            for text, _lang in POSITIVE_TEXTS[:4]:
                pcm, rate, ch = synthesize(culture, voice, text)
                pos_test.append(to16k(np.frombuffer(to_16k_mono(pcm, rate, ch), np.int16) / 32767, RATE))
    except Exception as error:
        print("windows voices skipped:", error)
    owner_all = [c for c in owner_clips() if np.abs(c).max() > 0]
    owner = [c for i, c in enumerate(owner_all) if i % 4 != 3]          # training
    owner_test = [c for i, c in enumerate(owner_clips(raw=True)) if i % 4 == 3]   # held out, loudness as recorded
    owner_talk = owner_clips(OWNER_TALK)
    print(f"positives train {len(pos_train)} test {len(pos_test)} owner {len(owner)}; negatives {len(neg_train)}",
          flush=True)

    backgrounds = [np.concatenate(neg_train[i::7]) for i in range(7)] + [music(20) for _ in range(4)]
    talk_all = np.concatenate(owner_talk) if owner_talk else np.zeros(0, np.float32)
    talk_train, talk_test = talk_all[: int(len(talk_all) * 0.75)], talk_all[int(len(talk_all) * 0.75):]
    if len(talk_train) > WINDOW:
        backgrounds.append(talk_train)      # the owner's own voice talking in the background
    windows, labels, weights = [], [], []

    def add(window, label, weight):
        windows.append(window); labels.append(label); weights.append(weight)

    for clip in pos_train:
        for _ in range(4):
            add(augment(in_context(place(clip), backgrounds), backgrounds), 1, 1.0)
    for clip in owner:                       # the owner's real voice counts most
        for _ in range(30):
            add(augment(in_context(place(clip), backgrounds), backgrounds), 1, 4.0)
    for off in range(0, max(0, len(talk_train) - WINDOW), RATE // 4):     # the owner's ordinary talk: never a wake
        add(np.clip(talk_train[off:off + WINDOW] * rng.uniform(0.2, 2.0), -32768, 32767).astype(np.int16), 0, 3.0)
    for clip in pos_train[::2] + owner:      # only half the phrase, or the phrase long ago: not (yet) a wake
        cut = trim(clip)
        add(augment(place(cut[: len(cut) // 2]), backgrounds), 0, 1.0)
        add(augment(place(cut, end_gap=1.2), backgrounds), 0, 0.5)
    for clip in neg_train:
        for _ in range(5):
            add(augment(in_context(place(trim(clip)), backgrounds), backgrounds), 0, 1.0)
    long_neg = np.concatenate(neg_train + [music(30)] + ([talk_train] if len(talk_train) else []))
    for _ in range(1500):                    # random 2 s slices of speech, music and silence
        off = rng.integers(len(long_neg) - WINDOW)
        add(augment(long_neg[off:off + WINDOW] * rng.uniform(0, 1), backgrounds), 0, 1.0)
    print(f"examples {len(windows)} ({sum(labels)} positive); computing features ...", flush=True)
    x = features(windows)
    y, w = np.array(labels, np.float32), np.array(weights, np.float32)
    mean, std = x.mean(0), x.std(0) + 1e-3

    def train(x, y, w):
        w = w.copy()
        w[y == 0] *= (w[y == 1].sum() / w[y == 0].sum()) * 1.5     # balance, leaning towards fewer false wakes
        net = Net(x.shape[1])
        net.fit((x - mean) / std, y, w)
        return net

    print("training ...", flush=True)
    net = train(x, y, w)
    # Hard-negative mining: whatever still fires on long non-wake audio becomes a negative, then retrain.
    mining = np.concatenate([augment_stream(np.concatenate(neg_train[i::3] + [music(40)]), backgrounds)
                             for i in range(3)] + ([augment_stream(talk_train, backgrounds)] if len(talk_train) else []))
    for round_number in range(3):
        hard = mine(net, mean, std, mining, 0.3)
        print(f"round {round_number + 1}: {len(hard)} false triggers mined", flush=True)
        if not hard:
            break
        extra = features(hard)
        x = np.concatenate([x, extra]); y = np.concatenate([y, np.zeros(len(hard), np.float32)])
        w = np.concatenate([w, np.full(len(hard), 3.0, np.float32)])
        net = train(x, y, w)

    def scores(clips, far):
        feats = features([augment(place(c), backgrounds, far=far) for c in clips])
        return net.forward((feats - mean) / std)[1]

    near_pos, far_pos = scores(pos_test, False), scores(pos_test, True)
    owner_scores = None
    if owner_test:   # the owner's held-out clips exactly as recorded (near and far are already in them)
        feats = features([np.clip(place(c, end_gap=0.25) if np.abs(c).max() > 0 else np.resize(c, WINDOW), -32768, 32767)
                          .astype(np.int16) for c in owner_test])
        owner_scores = net.forward((feats - mean) / std)[1]
        print("owner held-out scores:", [round(float(v), 2) for v in owner_scores], flush=True)
    near_neg, far_neg = scores(neg_test, False), scores(neg_test, True)
    eval_stream = np.concatenate(neg_test * 3 + [music(120)] + [np.zeros(RATE * 30, np.float32)])
    eval_stream = augment_stream(eval_stream, backgrounds)
    if len(talk_test):            # the owner's own talk the model never saw
        eval_stream = np.concatenate([eval_stream, np.clip(talk_test, -32768, 32767).astype(np.int16)])
    hours = len(eval_stream) / RATE / 3600
    results = {}
    for threshold in (0.5, 0.6, 0.7, 0.8, 0.9):
        results[str(threshold)] = {
            "recall_near": round(float((near_pos >= threshold).mean()), 3),
            "recall_far": round(float((far_pos >= threshold).mean()), 3),
            "false_near_phrases": int((near_neg >= threshold).sum()), "false_far_phrases": int((far_neg >= threshold).sum()),
            "false_wakes_per_hour": round(stream_false_wakes(net, mean, std, threshold, eval_stream) / hours, 1),
            "owner_recall": (round(float((owner_scores >= threshold).mean()), 3)
                             if owner_scores is not None else None)}
        print(threshold, results[str(threshold)], flush=True)
    chosen = pick_threshold(results)
    meta = {"trained": time.strftime("%Y-%m-%d %H:%M"), "owner_clips": len(owner), "owner_test_clips": len(owner_test),
            "owner_talk_seconds": round(sum(len(t) for t in owner_talk) / RATE),
            "threshold": float(chosen) if chosen else None, "passed_gate": chosen is not None, "gate": GATE,
            "test_positives": len(pos_test), "test_negatives": len(neg_test), "stream_minutes": round(hours * 60, 1),
            "results": results, "seconds": round(time.monotonic() - started)}
    REPORT.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    # Only a model that passes the gate is installed (2026-10-12: one that did not was saved anyway, went live and
    # woke Chutku every minute). Otherwise it is kept as a candidate for study and the live listener is untouched.
    net.save(CANDIDATE, mean, std, float(chosen or 0.9), meta)
    if chosen is None:
        print("FAILED the gate", GATE, "- NOT installed; candidate kept at", CANDIDATE)
        sys.exit(2)
    CANDIDATE.replace(OUT)
    print("passed the gate at threshold", chosen, "- installed", OUT, f"({meta['seconds']} s)")


GATE = {"owner_recall_min": 0.9, "false_wakes_per_hour_max": 2.0, "false_near_phrases_max": 0}


def pick_threshold(results, gate=GATE):
    """The threshold that passes every gate with the best recall, or None (then nothing is installed)."""
    passing = [t for t, r in results.items()
               if r["false_wakes_per_hour"] <= gate["false_wakes_per_hour_max"]
               and r["false_near_phrases"] <= gate["false_near_phrases_max"]
               and (r["owner_recall"] is None or r["owner_recall"] >= gate["owner_recall_min"])]
    if not passing:
        return None
    return max(passing, key=lambda t: results[t]["recall_near"] + results[t]["recall_far"]
               + 2 * (results[t]["owner_recall"] or 0))


def in_context(window, backgrounds):
    """Half the time the phrase follows other sound (talk, music) instead of silence, as in a real room."""
    if rng.random() < 0.5:
        return window
    back = backgrounds[rng.integers(len(backgrounds))]
    offset = rng.integers(max(1, len(back) - WINDOW))
    part = np.resize(back[offset:offset + WINDOW], WINDOW).astype(np.float32) * rng.uniform(0.1, 0.6)
    lead = np.where(np.abs(window) > 0.02 * (np.abs(window).max() or 1))[0]
    cut = max(0, (lead[0] if len(lead) else WINDOW) - int(0.15 * RATE))
    part[cut:] = 0                       # the earlier sound stops shortly before the phrase starts
    return window + part


def mine(net, mean, std, audio, threshold):
    """2 s windows of a long non-wake stream where the detector fires (each counted once per 2 s)."""
    from openwakeword.utils import AudioFeatures
    extractor = AudioFeatures(inference_framework="onnx")
    found, cooldown = [], 0
    for start in range(0, len(audio) - 1280, 1280):
        extractor(audio[start:start + 1280].astype(np.int16))
        if cooldown:
            cooldown -= 1
            continue
        if start + 1280 < WINDOW:
            continue
        x = (extractor.get_features(16).reshape(1, -1) - mean) / std
        if net.forward(x)[1][0] >= threshold:
            found.append(audio[start + 1280 - WINDOW:start + 1280].astype(np.int16))
            cooldown = 6
    return found


def augment_stream(audio, backgrounds):
    out = audio * 10 ** (-12 / 20) + rng.normal(0, 40, len(audio))
    back = np.resize(backgrounds[7], len(audio)) * 10 ** (-26 / 20)      # [7] = the first synthetic music
    return np.clip(out + back, -32768, 32767).astype(np.int16)


if __name__ == "__main__":
    main()
