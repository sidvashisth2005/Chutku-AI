"""Process-local audio session state, independent from task lifecycle state."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time


class VoiceSessionBusy(RuntimeError):
    pass


class VoiceCaptureCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceSessionSnapshot:
    state: str
    capture_cancelled: bool


class VoiceSession:
    """Own the single microphone/speaker lane and cooperative capture cancel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._cancel = threading.Event()
        self.idle_since = time.monotonic()

    def quiet_for(self) -> float:
        """Seconds since the microphone/speaker lane became idle (0 while busy)."""
        with self._lock:
            return 0.0 if self._state != "idle" else time.monotonic() - self.idle_since

    def snapshot(self) -> VoiceSessionSnapshot:
        with self._lock:
            return VoiceSessionSnapshot(self._state, self._cancel.is_set())

    @contextmanager
    def active(self, state: str):
        if state not in {"listening", "speaking"}:
            raise ValueError("Voice session state must be listening or speaking.")
        with self._lock:
            if self._state != "idle":
                raise VoiceSessionBusy(f"Voice is already {self._state}; wait or cancel capture first.")
            self._state = state
            self._cancel.clear()
        try:
            yield
        finally:
            with self._lock:
                self._state = "idle"
                self._cancel.clear()
                self.idle_since = time.monotonic()

    def cancel_capture(self) -> bool:
        with self._lock:
            if self._state != "listening":
                return False
            self._cancel.set()
            return True

    def check_capture(self) -> None:
        if self._cancel.is_set():
            raise VoiceCaptureCancelled("Voice capture was cancelled; no transcript or action was produced.")


voice_session = VoiceSession()
