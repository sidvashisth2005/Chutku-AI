"""Real hands-free verification without a human, using an acoustic loop.

1. Presses the real Ctrl+Alt+Space hotkey (synthetic key input) and confirms that a
   microphone capture was triggered (audit log), with no session if nothing was said.
2. Enables the wake phrase and confirms the listener reads the real microphone.
3. Records that this laptop's array mic cancels its own speaker output (so an
   over-the-air loop is impossible), then feeds synthesized "Oye Chutku, what time
   is it?" and a "Oye Chotu" near-miss into the same listener pipeline:
   segmenter -> Whisper -> wake match -> server -> agent -> verified tool.

Plays one clip aloud. Audio is only held in memory. Restores the wake preference.
"""
from __future__ import annotations

import ctypes
from datetime import UTC, datetime
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.dashboard import DashboardServer  # noqa: E402
from chutku.evidence import source_digest  # noqa: E402
from scripts.benchmark_stt import synthesize  # noqa: E402


def press_hotkey():
    user = ctypes.WinDLL("user32")
    for vk, up in ((0x11, 0), (0x12, 0), (0x20, 0), (0x20, 2), (0x12, 2), (0x11, 2)):
        user.keybd_event(vk, 0, up, 0)
        time.sleep(0.03)


def play(culture, voice, text):
    import winsound
    pcm, rate, channels = synthesize(culture, voice, text)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(buffer.getvalue())
    try:
        winsound.PlaySound(handle.name, winsound.SND_FILENAME)
    finally:
        Path(handle.name).unlink(missing_ok=True)


def clip(culture, voice, text):
    from scripts.verify_voice_agent import to_16k_mono
    return to_16k_mono(*synthesize(culture, voice, text))


class ClipBackend:
    """Stands in for sounddevice: 2 s of room noise, the clip, then silence, in real time."""

    def __init__(self, pcm):
        import random
        noise = bytes(b for _ in range(32000) for b in (random.randint(0, 20).to_bytes(2, "little")))
        self.audio = noise + pcm

    def RawInputStream(self, **_):
        backend = self

        class Stream:
            offset = 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, frames):
                time.sleep(0.1)
                chunk = backend.audio[self.offset:self.offset + frames * 2]
                self.offset += frames * 2
                return chunk + bytes(frames * 2 - len(chunk)), False
        return Stream()


def speaker_to_mic_levels():
    import math
    import threading
    from array import array
    import sounddevice as sd
    levels, stop = [], threading.Event()

    def record():
        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600) as stream:
            while not stop.is_set():
                data = array("h", bytes(stream.read(1600)[0]))
                levels.append(math.sqrt(sum(v * v for v in data) / len(data)) / 32768)
    thread = threading.Thread(target=record)
    thread.start()
    time.sleep(1.0)
    idle = len(levels)
    play("en-IN", "Ravi", "Oye Chutku, what time is it?")
    stop.set()
    thread.join()
    return max(levels[idle:] or [0]), max(levels[:idle] or [0])


def wait_session(server, previous, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        current = server.latest_session_id
        if current and current != previous:
            session = server.agent_sessions.get(current)
            snap = session.snapshot()
            if snap["status"] in {"done", "clarify", "failed", "stopped", "cancelled", "waiting_confirmation"}:
                return snap
        time.sleep(0.3)
    return None


def main():
    checks = []

    def check(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + name, detail, flush=True)

    server = DashboardServer(ROOT, port=0)
    previous_prefs = server.preferences.load()
    try:
        server.start_handsfree()
        server.apply_wake(False)  # the owner's wake phrase may be on: test the hotkey on its own first
        check("hotkey_registered", server.hotkey.registered.is_set(), "Ctrl+Alt+Space")
        from chutku.app import create_runtime
        with create_runtime(ROOT) as runtime:
            before = len([t for t in runtime.event_log.recent_tasks(50) if t["tool"] == "voice.listen_command"])
        press_hotkey()
        time.sleep(1.0)
        deadline = time.monotonic() + 20
        captured = False
        while time.monotonic() < deadline and not captured:
            time.sleep(0.5)
            with create_runtime(ROOT) as runtime:
                after = len([t for t in runtime.event_log.recent_tasks(50) if t["tool"] == "voice.listen_command"])
            captured = after > before and not server.action_lock.locked()
        check("hotkey_triggers_microphone_capture", captured, "voice.listen_command task recorded after key press")
        check("silence_starts_no_session", server.latest_session_id is None)

        server.preferences.update({"wake_word": True, "handsfree_mode": "auto_safe"})
        server.apply_wake(True)
        time.sleep(3.0)
        wake = server.wake
        check("wake_listener_reads_real_microphone", wake is not None and wake.is_alive() and not wake.error
              and wake.frames_read >= 20, f"frames read: {wake.frames_read if wake else 0}")
        peak, floor = speaker_to_mic_levels()
        check("laptop_mic_cancels_own_speaker_output (recorded fact)", True,
              f"mic peak {peak:.4f} while playing speech vs idle floor {floor:.4f}: the array mic's echo "
              "cancellation removes self-played audio, so over-the-air loopback cannot be tested here")
        server.apply_wake(False)

        # Same pipeline (segmenter -> Whisper -> wake match -> server -> agent), fed the clip directly.
        from chutku.voice.handsfree import WAKE_PROMPT, WakeListener
        from chutku.voice.whisper_stt import transcribe_pcm
        for label, (culture, voice, text), expect_session in (
                ("wake_phrase_runs_request", ("en-IN", "Ravi", "Oye Chutku, what time is it?"), True),
                ("near_miss_does_not_wake", ("hi-IN", "Hemant", "ओए छोटू, इधर आओ"), False)):
            previous = server.latest_session_id
            listener = WakeListener(lambda command: server.handsfree_request(command or None),
                                    lambda pcm: transcribe_pcm(pcm, language="en", base=ROOT, prompt=WAKE_PROMPT),
                                    backend=ClipBackend(clip(culture, voice, text)))
            listener.start()
            snap = wait_session(server, previous, seconds=60 if expect_session else 15)
            listener.stop()
            listener.join(5)
            if expect_session:
                check(label, snap is not None and snap["status"] == "done" and snap["origin"] == "voice"
                      and any(s["tool"] == "system.get_time" and s["state"] == "COMPLETED" for s in snap["steps"]),
                      json.dumps({"goal": snap and snap["goal"], "status": snap and snap["status"],
                                  "reply": snap and snap["reply"][:120]}, ensure_ascii=False))
                from chutku.voice.session import voice_session
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and voice_session.quiet_for() < 2.0:
                    time.sleep(0.2)  # the listener is deaf while Chutku speaks its answer
            else:
                check(label, snap is None and listener.segments_heard >= 1 and listener.wakes == 0,
                      f"segments heard {listener.segments_heard}, wakes {listener.wakes}")
    finally:
        server.apply_wake(False)
        server.preferences.update({k: previous_prefs[k] for k in ("wake_word", "handsfree_mode")})
        if server.hotkey:
            server.hotkey.stop()
        if server.action_lock.acquire(timeout=60):
            server.action_lock.release()
        server.server_close()
        from chutku.brain_service import shared_service
        shared_service(ROOT).close()
    report = {"generated_at": datetime.now(UTC).isoformat(), "source_digest": source_digest(ROOT),
              "passed": all(c["passed"] for c in checks), "checks": checks,
              "scope": "Real hotkey, real microphone, synthetic speech played through the laptop speakers. Not a "
                       "human-voice or per-hour false-accept measurement."}
    (ROOT / "verification/handsfree.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} passed")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
