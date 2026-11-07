"""The laptop's sound for the phone remote (owner 2026-11-08, "there is no audio, only video").

Windows WASAPI loopback records what the speakers play (the installed PortAudio has no loopback device), through
comtypes; PyAV's libopus makes 20 ms Opus packets (~96 kbit/s) that the phone decodes with WebCodecs. Only sound that
is already playing is sent; when the laptop is silent nothing is sent. Nothing here plays or changes any sound.
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, c_byte, c_int, c_longlong, c_uint32, c_uint64, c_void_p
from ctypes import wintypes as w

from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

RATE, CHANNELS, FRAME = 48000, 2, 960   # Opus: 48 kHz stereo, 20 ms
SILENT = 0x2                            # AUDCLNT_BUFFERFLAGS_SILENT


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", w.WORD), ("nChannels", w.WORD), ("nSamplesPerSec", w.DWORD),
                ("nAvgBytesPerSec", w.DWORD), ("nBlockAlign", w.WORD), ("wBitsPerSample", w.WORD), ("cbSize", w.WORD)]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(POINTER(c_byte)), "data"),
                  (["out"], POINTER(c_uint32), "frames"), (["out"], POINTER(c_uint32), "flags"),
                  (["out"], POINTER(c_uint64), "position"), (["out"], POINTER(c_uint64), "qpc")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "frames")),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize", (["in"], c_int, "mode"), (["in"], w.DWORD, "flags"),
                  (["in"], c_longlong, "duration"), (["in"], c_longlong, "period"),
                  (["in"], POINTER(WAVEFORMATEX), "format"), (["in"], POINTER(GUID), "session")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "frames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "latency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "frames")),
        COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_int, "mode"), (["in"], POINTER(WAVEFORMATEX), "format"),
                  (["out"], POINTER(POINTER(WAVEFORMATEX)), "closest")),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "format")),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(c_longlong), "default"),
                  (["out"], POINTER(c_longlong), "minimum")),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], w.HANDLE, "event")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"), (["out"], POINTER(POINTER(IUnknown)), "service")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], w.DWORD, "context"),
                  (["in"], c_void_p, "params"), (["out"], POINTER(POINTER(IUnknown)), "interface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore"),
        COMMETHOD([], HRESULT, "GetId"),
        COMMETHOD([], HRESULT, "GetState"),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints"),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int, "flow"), (["in"], c_int, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "device")),
    ]


class Loopback:
    """What the laptop's default speakers play, as float32 stereo-or-more frames at the mix rate."""

    def __init__(self):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        enumerator = comtypes.client.CreateObject(GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
                                                  interface=IMMDeviceEnumerator)
        device = enumerator.GetDefaultAudioEndpoint(0, 0)                  # eRender, eConsole
        self.client = device.Activate(IAudioClient._iid_, 23, None).QueryInterface(IAudioClient)   # CLSCTX_ALL
        mix = self.client.GetMixFormat()
        self.format = mix.contents
        self.rate, self.channels = self.format.nSamplesPerSec, self.format.nChannels
        self.block, self.bits = self.format.nBlockAlign, self.format.wBitsPerSample
        self.client.Initialize(0, 0x00020000, 2_000_000, 0, mix, None)      # shared, AUDCLNT_STREAMFLAGS_LOOPBACK, 200 ms
        self.capture = self.client.GetService(IAudioCaptureClient._iid_).QueryInterface(IAudioCaptureClient)
        self.client.Start()

    def read(self):
        """All sound captured since the last call: (numpy array (frames, channels) float32) or None."""
        import numpy as np
        parts = []
        while self.capture.GetNextPacketSize():
            data, frames, flags, _, _ = self.capture.GetBuffer()
            if frames:
                if flags & SILENT:
                    parts.append(np.zeros((frames, self.channels), np.float32))
                else:
                    raw = ctypes.string_at(data, frames * self.block)
                    kind = np.float32 if self.bits == 32 else np.int16
                    chunk = np.frombuffer(raw, kind).reshape(frames, self.channels)
                    parts.append(chunk if kind is np.float32 else chunk.astype(np.float32) / 32768)
            self.capture.ReleaseBuffer(frames)
        return np.concatenate(parts) if parts else None

    def close(self):
        try:
            self.client.Stop()
        except Exception:
            pass


class Opus:
    """float32 frames at any rate -> 20 ms Opus packets at 48 kHz stereo."""

    def __init__(self, rate, bit_rate=96_000):
        import av
        self.av, self.rate = av, rate
        self.codec = av.CodecContext.create("libopus", "w")
        self.codec.sample_rate, self.codec.layout, self.codec.format = RATE, "stereo", "flt"
        self.codec.bit_rate = bit_rate
        self.codec.open()
        self.resampler = av.AudioResampler(format="flt", layout="stereo", rate=RATE)
        self.fifo = av.AudioFifo()

    def encode(self, samples):
        """samples: (frames, channels) float32 -> [packet bytes]."""
        import numpy as np
        stereo = samples[:, :2] if samples.shape[1] >= 2 else np.repeat(samples, 2, axis=1)
        frame = self.av.AudioFrame.from_ndarray(np.ascontiguousarray(stereo).reshape(1, -1), format="flt", layout="stereo")
        frame.sample_rate = self.rate
        packets = []
        for resampled in self.resampler.resample(frame):
            self.fifo.write(resampled)
        while self.fifo.samples >= FRAME:
            for packet in self.codec.encode(self.fifo.read(FRAME)):
                packets.append(bytes(packet))
        return packets
