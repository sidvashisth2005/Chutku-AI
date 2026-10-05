from __future__ import annotations

from typing import Any, Protocol


class AudioBackend(Protocol):
    def query_devices(self) -> Any: ...


def inspect_input_devices(backend: AudioBackend) -> list[dict[str, int | float | str]]:
    """Extract only microphone-capable device facts; this function never records audio."""
    devices: list[dict[str, int | float | str]] = []
    for raw in backend.query_devices():
        input_channels = int(raw.get("max_input_channels", 0))
        if input_channels < 1:
            continue
        name = " ".join(str(raw.get("name", "Unnamed input device")).split())
        sample_rate = float(raw.get("default_samplerate", 0))
        devices.append({"name": name, "input_channels": input_channels, "default_sample_rate_hz": sample_rate})
    return devices


def local_input_devices() -> list[dict[str, int | float | str]]:
    import sounddevice

    return inspect_input_devices(sounddevice)


def measure_default_input_level(backend: Any, numerical: Any, seconds: float = 1.0) -> dict[str, float | str]:
    """Measure one bounded in-memory input sample and immediately discard raw audio."""
    if seconds != 1.0:
        raise ValueError("Only the fixed one-second microphone check is allowed.")
    device = backend.query_devices(kind="input")
    sample_rate = float(device["default_samplerate"])
    frames = int(sample_rate * seconds)
    samples = backend.rec(frames, samplerate=sample_rate, channels=1, dtype="float32", blocking=True)
    peak = float(numerical.max(numerical.abs(samples)))
    rms = float(numerical.sqrt(numerical.mean(numerical.square(samples))))
    del samples
    return {"duration_seconds": seconds, "sample_rate_hz": sample_rate, "peak": round(peak, 6), "rms": round(rms, 6)}


def measure_input_activity(backend: Any, numerical: Any, seconds: float = 3.0, frame_seconds: float = 0.02, threshold: float = 0.01) -> dict[str, float | int]:
    """Perform one bounded energy-based activity check and discard all raw samples."""
    if seconds != 3.0 or frame_seconds != 0.02 or threshold != 0.01:
        raise ValueError("Only the fixed three-second, 20 ms, threshold-0.01 activity check is allowed.")
    device = backend.query_devices(kind="input")
    sample_rate = float(device["default_samplerate"])
    frames = int(sample_rate * seconds)
    samples = backend.rec(frames, samplerate=sample_rate, channels=1, dtype="float32", blocking=True)
    frame_size = int(sample_rate * frame_seconds)
    usable_frames = (len(samples) // frame_size) * frame_size
    chunks = samples[:usable_frames].reshape(-1, frame_size)
    rms_levels = numerical.sqrt(numerical.mean(numerical.square(chunks), axis=1))
    active_frames = int(numerical.sum(rms_levels >= threshold))
    total_frames = int(len(rms_levels))
    del samples, chunks, rms_levels
    return {
        "duration_seconds": seconds,
        "sample_rate_hz": sample_rate,
        "frame_milliseconds": int(frame_seconds * 1000),
        "threshold_rms": threshold,
        "active_frames": active_frames,
        "total_frames": total_frames,
        "active_duration_seconds": round(active_frames * frame_seconds, 2),
    }
