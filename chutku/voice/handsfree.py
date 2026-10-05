"""Hands-free voice: a global push-to-talk hotkey and an opt-in "Oye Chutku" wake phrase.

The wake phrase is not authentication. Whatever starts a request, the chosen autonomy
level and the policy kernel still bound what runs, and R3+ steps still wait for an
on-screen click. Audio stays in memory; transcripts that do not start with the wake
phrase are discarded without logging. Listening pauses while Chutku itself speaks.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import math
import queue
import re
import sys
import threading
from array import array

from chutku.voice.session import voice_session

HOTKEY_LABEL = "Ctrl+Alt+Space"
# The command-biasing Hinglish prompt made Whisper hear "Chotu" as "Chutku"
# (verification/wake-benchmark.json); wake detection uses this neutral prompt.
WAKE_PROMPT = "Hinglish speech: kholo, chalao, roko, batao, open, search, time."
_MOD_ALT, _MOD_CONTROL, _MOD_NOREPEAT, _VK_SPACE, _WM_HOTKEY, _WM_QUIT = 0x1, 0x2, 0x4000, 0x20, 0x312, 0x12
# Mic-mute toggle: the first combination no other program holds. Owner (2026-10-05): one hand, three keys, so
# Ctrl+Alt+X first (Ctrl+Alt+M was taken on the owner's PC); the rest are fallbacks for other PCs.
MUTE_HOTKEYS = (("Ctrl+Alt+X", 0x2 | 0x1, 0x58), ("Ctrl+Alt+Z", 0x2 | 0x1, 0x5A), ("Ctrl+Alt+M", 0x2 | 0x1, 0x4D),
                ("Ctrl+Alt+Shift+Space", 0x2 | 0x1 | 0x4, 0x20))

# Her name is छुटकू, said "Chhutku" (owner, 2026-10-05); "chh" and Hindi script read as "chhutaku" both match.
# Whisper spells "Oye Chutku" many ways ("Owe Chutku", "Oichutku", "Owei chudku",
# "chutkoom"). Match the distinctive ch-vowel-t/d-k-u shape on the first 1-3 words.
# "Chotu" (no k) and "chutki" (a common Hindi word, ends in -i) deliberately fail.
_CORE = re.compile(r"(?:[oyewihbak]{0,5})c+h{0,2}[aeiou]{1,2}[td]{1,2}h?a?k+(?:u|uu|oo|o|ou)m?")
# Whisper sometimes drops the t ("Oe chuku"); accepted only after the "Oye" greeting, so a bare "chuku" never wakes.
_DROPPED_T = re.compile(r"o[yeiw]{0,3}c+h{0,2}u{1,2}k+(?:u|uu|oo)")
_WORD = re.compile(r"[A-Za-z']+")
_LISTEN_WORD = re.compile(r"^(?:sun+|suno+|sunna|suniye|suno na|sun na|soon|son|sunn|listen)\b[\s,.!?]*", re.I)


def split_wake(text):
    """Return (True, command) when text starts with the wake phrase, else (False, "")."""
    from chutku.translit import roman
    text = roman(text or "")
    words = list(_WORD.finditer(text))
    for count in (1, 2, 3):
        if len(words) < count:
            break
        joined = "".join(m.group(0) for m in words[:count]).lower().replace("'", "")
        if _CORE.fullmatch(joined) or (count > 1 and _DROPPED_T.fullmatch(joined)):
            rest = text[words[count - 1].end():].strip(" .,!?:;-")
            # "Chutku sun" / "Chutku suno" (Whisper often writes "soon"): the listen word is not the command.
            rest = _LISTEN_WORD.sub("", rest, count=1).strip(" .,!?:;-")
            return True, rest
    return False, ""


def chime(kind="listen"):
    """Short audible cue so the user knows the microphone is open."""
    try:
        import winsound
        if kind == "listen":
            winsound.Beep(880, 90)
            winsound.Beep(1320, 90)
        else:
            winsound.Beep(660, 120)
    except (ImportError, RuntimeError):
        pass


class HotkeyListener(threading.Thread):
    """Owns Ctrl+Alt+Space in a dedicated message-loop thread of the core process."""

    def __init__(self, on_press, on_mute=None):
        super().__init__(name="chutku-ptt-hotkey", daemon=True)
        self.on_press = on_press
        self.on_mute = on_mute     # Ctrl+Alt+M: mic mute toggle (optional; Ctrl+Alt+Space works without it)
        self.mute_registered = False
        self.mute_hotkey = None    # the combination actually registered
        self.registered = threading.Event()
        self.failed = threading.Event()
        self.thread_id = None

    def run(self):
        if sys.platform != "win32":
            self.failed.set()
            return
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32")
        user.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
        user.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        self.thread_id = kernel.GetCurrentThreadId()
        if not user.RegisterHotKey(None, 7, _MOD_CONTROL | _MOD_ALT | _MOD_NOREPEAT, _VK_SPACE):
            self.failed.set()
            return
        self.registered.set()
        if self.on_mute is not None:
            for name, modifiers, key in MUTE_HOTKEYS:
                if user.RegisterHotKey(None, 8, modifiers | _MOD_NOREPEAT, key):
                    self.mute_registered, self.mute_hotkey = True, name
                    break
        message = w.MSG()
        try:
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == _WM_HOTKEY and message.wParam == 7:
                    threading.Thread(target=self.on_press, name="chutku-ptt", daemon=True).start()
                elif message.message == _WM_HOTKEY and message.wParam == 8 and self.on_mute is not None:
                    threading.Thread(target=self.on_mute, name="chutku-mute", daemon=True).start()
        finally:
            user.UnregisterHotKey(None, 7)
            if self.mute_registered:
                user.UnregisterHotKey(None, 8)

    def stop(self):
        if self.thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self.thread_id, _WM_QUIT, 0, 0)


WAKE_MIN_CONFIDENCE = 0.35   # real wake phrases scored 0.40-0.71 in scripts/benchmark_noise.py; noise gave no text


class Segmenter:
    """Energy VAD that turns a 16 kHz int16 stream into short utterance segments."""

    def __init__(self, *, threshold=None, min_seconds=0.4, max_seconds=6.0, end_silence=0.6):
        # Fixed threshold for tests; otherwise adapt to the measured noise floor (this
        # laptop's array mic idles near 0.001 RMS, so a fixed 0.012 would miss soft speech).
        self.fixed_threshold, self.noise = threshold, 0.002
        self.min_chunks = int(min_seconds * 10)
        self.max_chunks, self.end_chunks = int(max_seconds * 10), int(end_silence * 10)
        self.reset()

    @property
    def threshold(self):
        if self.fixed_threshold is not None:
            return self.fixed_threshold
        return min(max(self.noise * 5, 0.008), 0.05)   # floor 0.008 (was 0.004: a keyboard or fan counted)

    def reset(self):
        self.chunks, self.silence, self.loud_run, self.active = [], 0, 0, False
        self.levels = getattr(self, "levels", [])

    def feed(self, chunk):
        """Feed one 100 ms chunk; return a finished segment (bytes) or None."""
        samples = array("h", chunk)
        rms = math.sqrt(sum(v * v for v in samples) / max(len(samples), 1)) / 32768
        self.levels = (self.levels + [rms])[-30:]
        if self.fixed_threshold is None and len(self.levels) == 30:
            # A sustained rise (fan, AC, music) lifts the floor: the quietest of the last 3 s can't be speech.
            # Before, the floor only learned from quiet chunks and could lock low, so noise was transcribed
            # back to back forever.
            self.noise = max(self.noise, min(self.levels) / 1.5)
        loud = rms >= self.threshold
        if not loud and not self.active:
            self.noise = 0.95 * self.noise + 0.05 * rms  # track the quiet-room floor
        if not self.active:
            self.loud_run = self.loud_run + 1 if loud else 0
            self.chunks = (self.chunks + [chunk])[-3:]  # keep 300 ms of pre-roll
            if self.loud_run >= 3:                       # 300 ms of loud sound (was 200 ms)
                self.active, self.silence = True, 0
            return None
        self.chunks.append(chunk)
        self.silence = 0 if loud else self.silence + 1
        if self.silence >= self.end_chunks or len(self.chunks) >= self.max_chunks:
            segment, speech_chunks = b"".join(self.chunks), len(self.chunks) - self.silence
            self.reset()
            return segment if speech_chunks >= self.min_chunks else None
        return None


class WakeListener(threading.Thread):
    """Opt-in background listener; only transcripts starting with the wake phrase act."""

    def __init__(self, on_wake, transcribe, *, backend=None):
        super().__init__(name="chutku-wake", daemon=True)
        self.on_wake, self.transcribe, self.backend = on_wake, transcribe, backend
        self.stop_event = threading.Event()
        self.busy = threading.Event()  # set while a request is being handled
        self.hold = threading.Event()  # set for a whole live conversation (outlives the request that started it)
        self.error = None
        self.handling = False
        self.segments_heard = 0
        self.frames_read = 0
        self.wakes = 0
        self.overflows = 0        # audio the sound card dropped because the loop was late (shown in /api/state)
        self.dropped = 0          # segments skipped because transcription was still busy
        self.restarts = 0
        self._segments = queue.Queue(maxsize=2)

    RESTARTS = 5

    def run(self):
        """Listen; after a crash (unplugged mic, driver error) start again with growing pauses, up to RESTARTS."""
        threading.Thread(target=self._transcriber, name="chutku-wake-stt", daemon=True).start()
        for attempt in range(self.RESTARTS + 1):
            try:
                self._listen()
                return
            except Exception as error:  # surfaced in /api/state; the rest of Chutku keeps working
                self.error = f"{type(error).__name__}: {error}"[:200]
                if attempt == self.RESTARTS or self.stop_event.wait(2 ** (attempt + 1)):
                    return
                self.restarts += 1

    def _listen(self):
        sd = self.backend
        if sd is None:
            import sounddevice as sd
        segmenter = Segmenter()
        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600) as stream:
            while not self.stop_event.is_set():
                chunk, overflowed = stream.read(1600)
                self.frames_read += 1
                if overflowed:
                    self.overflows += 1
                from chutku.voice import mic
                if self.busy.is_set() or self.hold.is_set() or mic.muted() or voice_session.quiet_for() < 1.0:
                    segmenter.reset()  # never listen to ourselves or during a request
                    continue
                segment = segmenter.feed(bytes(chunk))
                if segment is None:
                    continue
                self.segments_heard += 1
                from chutku.voice.recognition import analyze_pcm
                voiced = analyze_pcm([segment], threshold=segmenter.threshold)
                if voiced["active_frames"] < 25:   # under 0.5 s of voiced audio: a knock, a cough, a click
                    continue
                # Whisper runs on its own thread: the microphone is read on time while it transcribes.
                try:
                    self._segments.put_nowait((segment, voiced["peak_frame_rms"]))
                except queue.Full:
                    try:
                        self._segments.get_nowait()   # keep the newest speech, not the oldest
                        self.dropped += 1
                    except queue.Empty:
                        pass
                    self._segments.put_nowait((segment, voiced["peak_frame_rms"]))

    def _transcriber(self):
        from chutku.voice.heard import log_heard, meaningful
        while not self.stop_event.is_set():
            try:
                segment, level = self._segments.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.busy.is_set() or self.hold.is_set():
                continue   # a request started meanwhile
            try:
                heard = self.transcribe(segment)
            except Exception as error:
                self.error = f"{type(error).__name__}: {error}"[:200]
                continue
            text = heard.get("text", "")
            woke, command = split_wake(text)
            if woke and (heard.get("confidence", 1.0) < WAKE_MIN_CONFIDENCE or not meaningful(text)):
                woke = False                   # a garbled near-match is not the owner calling Chutku
            if text:
                log_heard("wake", text, "wake" if woke else "ignored", level=level, confidence=heard.get("confidence"))
            if woke and not self.busy.is_set():
                self.wakes += 1
                self.busy.set()
                threading.Thread(target=self._dispatch, args=(command,), daemon=True).start()

    def _dispatch(self, command):
        self.handling = True
        try:
            self.on_wake(command)
        finally:
            self.handling = False
            if not self.hold.is_set():  # a live conversation keeps the microphone until it ends
                self.busy.clear()

    def stop(self):
        self.stop_event.set()
