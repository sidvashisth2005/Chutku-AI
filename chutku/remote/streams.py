"""The phone's screen, H.264 video, audio, pointer and file streams (PhoneStreams, mixed into PhoneHandler)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

from chutku.remote.auth import RemoteDenied


MAX_UPLOAD = 200 * 1024 * 1024             # P8 phone -> laptop files


SCREEN_MAX = 30 * 60


SCREEN_BEAT = 45.0   # one slow round trip (relay, mobile data) must not end the view


CURSOR_TICK = 1 / 60    # the pointer stream checks the mouse 60 times a second and sends only moves


VIDEO_FRAME = 1 / 30   # H.264: up to 30 frames/s (capture ~20 ms runs while the last frame is encoded)


HOVER_EVERY = 0.08      # what is under the pointer: looked up at most ~12 times a second (2-5 ms each)


STREAM_FRAME = 1 / 20   # the stream's fastest pace (capture ~30 ms + scale/encode ~30 ms in practice)   # trackpad input reuses the monitor rectangle instead of a capture per move


STREAM_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mkv": "video/webm", ".webm": "video/webm",
                ".mov": "video/mp4", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
                ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}


def file_refusal(path, max_size=MAX_UPLOAD):
    """Why a laptop file may not go to the phone (None = allowed). max_size None: no cap (streamed, not loaded)."""
    from chutku.core.paths import protected_zones
    from chutku.references import secret_reason
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return "No such file."
    if not resolved.is_file():
        return "That is not a file."
    lowered = str(resolved).casefold()
    if any(lowered == zone or lowered.startswith(zone.rstrip("\\") + "\\") for zone in protected_zones()):
        return "That file is in a protected system area."
    reason = secret_reason(str(resolved))
    if reason:
        return reason
    if max_size is not None and resolved.stat().st_size > max_size:
        return "Files up to 200 MB."
    return None


def _jpeg(rgb, quality, width=None):
    """JPEG through PyAV's MJPEG encoder (already installed for speech), scaled to `width` by PyAV's scaler (9 ms for
    1080p, against 225 ms for vision.scaled), else PNG. quality: 2 (best) .. 31."""
    try:
        import av
        import numpy as np
        height, full = rgb.shape[0], rgb.shape[1]
        out_w = min(width or full, full)
        out_w, out_h = out_w - out_w % 2, round(height * out_w / full / 2) * 2
        codec = av.CodecContext.create("mjpeg", "w")
        codec.width, codec.height, codec.pix_fmt = out_w, out_h, "yuvj420p"
        codec.qmin = codec.qmax = quality
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
        frame = frame.reformat(width=out_w, height=out_h, format="yuvj420p", interpolation="AREA")
        return b"".join(bytes(packet) for packet in codec.encode(frame)), "image/jpeg"
    except Exception:   # no PyAV or no MJPEG encoder: the lossless frame still works
        from chutku import vision
        return _png(vision.scaled(rgb, width or rgb.shape[1]), level=1), "image/png"


def _clock_ms(monotonic):
    """The laptop clock both streams are stamped with (ms, wraps at 2^32): the phone lines sound and picture up by it."""
    return int(monotonic * 1000) & 0xFFFFFFFF


def _changed(pixels):
    """A checksum of every pixel (~5 ms for 1080p): a typed letter or a blinking caret is a change. The old sample of
    every 16th row and column missed them until the 2 s keep-alive."""
    import zlib
    import numpy as np
    return zlib.crc32(np.ascontiguousarray(pixels))   # the array itself: no 6-8 MB copy


class _Grabber(threading.Thread):
    """Captures the next screen while the last one is encoded and sent (owner 2026-11-08: capture ~34 ms and encode
    ~15 ms took turns, ~17 frames/s). take() gives the newest capture, never an old one twice."""

    def __init__(self):
        super().__init__(daemon=True, name="chutku-screen-grab")
        self.latest, self.fresh, self.stop = None, threading.Event(), threading.Event()

    def run(self):
        from chutku import vision
        capturer = vision.Capturer()   # BGRA, GDI objects kept: ~20 ms a frame instead of ~35
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                try:
                    shot = capturer.grab()
                except OSError:   # locked or a secure screen for a moment
                    time.sleep(1.0)
                    continue
                last = self.latest
                same = last is not None and shot is last[0]   # the GPU said nothing changed: no checksum needed
                if same:
                    self.latest = last
                else:   # a GPU frame is new only when the screen changed: no checksum (it held the GIL ~3 ms)
                    self.latest = (shot, id(shot) if shot.window.get("gpu") else _changed(shot.pixels))
                self.fresh.set()
                time.sleep(max(0.0, VIDEO_FRAME - (time.monotonic() - started)))
        finally:
            capturer.close()

    def take(self, timeout):
        if not self.fresh.wait(timeout):
            return None
        self.fresh.clear()
        return self.latest


H264_ENCODERS = (("h264_nvenc", {"preset": "p1", "tune": "ull", "zerolatency": "1", "delay": "0"}),   # the GPU
                 ("libx264", {"preset": "ultrafast", "tune": "zerolatency"}))   # in PyAV itself: every laptop


class H264:
    """The screen as H.264 (owner 2026-11-08, "no lag or jitter"): the way paid remote desktops are fast. Measured on
    this laptop at 1280x720: NVENC 15 ms, libx264 12 ms a frame, every frame out at once (no delay, no B-frames), ~4-7 KB
    a frame after the first, where a JPEG frame is ~100 KB: far less for the ~90 ms Tailscale relay to carry."""

    def __init__(self, width, height, *, names=H264_ENCODERS, bit_rate=3_000_000):
        import av
        from fractions import Fraction
        self.size, self.count, self.name = (width - width % 2, height - height % 2), 0, None
        for name, options in names:
            try:
                codec = av.CodecContext.create(name, "w")
                codec.width, codec.height = self.size
                codec.pix_fmt = "yuv420p" if name == "libx264" else "nv12"
                codec.time_base, codec.framerate = Fraction(1, 30), Fraction(30, 1)
                codec.bit_rate, codec.gop_size, codec.max_b_frames = bit_rate, 600, 0
                # a steady stream (owner 2026-11-08, "smoothness"): at most bit_rate, with a 250 ms buffer, so one big
                # frame never arrives as a burst that stalls the relay; NVENC in constant-bitrate mode
                codec.options = {**options, "maxrate": str(bit_rate), "bufsize": str(bit_rate // 4),
                                 **({"rc": "cbr"} if name == "h264_nvenc" else {})}
                codec.open()
            except Exception:   # this encoder is missing or the GPU is busy: the next one
                continue
            self.codec, self.name = codec, name
            return
        raise OSError("No H.264 encoder works on this laptop.")

    def encode(self, pixels, layout="rgb24"):
        """[(keyframe, Annex B bytes)] for one screen picture (the first is a keyframe). layout: "rgb24", or "bgra"
        straight from vision.Capturer (no RGB copy; scaling from BGRA measured 12.7 ms against 18.5 ms)."""
        import av
        import numpy as np
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(pixels), format=layout)
        frame = frame.reformat(width=self.size[0], height=self.size[1], format=self.codec.pix_fmt, interpolation="AREA")
        frame.pts, self.count = self.count, self.count + 1
        return [(bool(packet.is_keyframe), bytes(packet)) for packet in self.codec.encode(frame)]


def _png(rgb, level=1):
    import struct
    import zlib
    import numpy as np
    height, width, _ = rgb.shape
    raw = np.hstack([np.zeros((height, 1), np.uint8), rgb.reshape(height, width * 3)]).tobytes()

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b""))


def _log(base, kind, details):
    try:
        from chutku.core.action_log import ActionLog
        ActionLog(Path(base) / "data" / "actions.log.jsonl").append(
            {"tool": "remote." + kind, "state": "COMPLETED", "origin": "phone", **details})
    except (OSError, ValueError):
        pass


class PhoneStreams:
    """Methods of PhoneHandler, kept here to keep server.py short."""

    def _frame(self, record, last_hash):
        screen = self.server.screen
        now = time.monotonic()
        if not screen or screen["device"] != record["device"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        if now > screen["until"] or now - screen["beat"] > SCREEN_BEAT:
            self.server.screen = None
            raise RemoteDenied("Screen view ended (30 min max, or the phone went quiet). Start it again.", 403)
        screen["beat"] = now
        from chutku import vision
        from chutku.remote.control import cursor_pos
        shot = vision.capture()
        controlling = self.server.controlling()
        x, y = cursor_pos()
        cursor = json.dumps([round((x - shot.left) / max(shot.width, 1), 4), round((y - shot.top) / max(shot.height, 1), 4)])
        digest = hashlib.sha1(shot.pixels[::16, ::16].tobytes() + cursor.encode()).hexdigest()
        headers = {"X-Frame-Hash": digest, "X-Cursor": cursor}
        if digest == last_hash:
            self._reply(204, b"", "text/plain", headers=headers)
            return
        self.server.monitor_seen = (time.monotonic(), (shot.left, shot.top, shot.width, shot.height))
        body, mime = _jpeg(shot.pixels, 7 if controlling else 8, width=1280)   # lighter frames while the owner drives
        self._reply(200, body, mime,
                    headers={**headers, "X-Monitor": json.dumps([shot.left, shot.top, shot.width, shot.height])})

    def _file_stream(self, record, raw_path):
        """GET /api/files/stream?path=: a laptop video, audio file, photo or PDF played by the phone's own player, with
        seeking (HTTP Range). Owner 2026-11-07: "an anime episode on my laptop" plays smoothly with sound this way;
        copying the screen could never be smooth. Same refusals as a download; inside the PIN session; read-only."""
        self._pin(record, None)
        path = Path(str(raw_path or "")).expanduser()
        reason = file_refusal(path, max_size=None)
        if reason:
            raise RemoteDenied(reason)
        size = path.stat().st_size
        start, end = 0, size - 1
        ranged = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        if ranged and (ranged[1] or ranged[2]):
            if ranged[1]:
                start, end = int(ranged[1]), int(ranged[2]) if ranged[2] else size - 1
            else:   # the last N bytes
                start = max(0, size - int(ranged[2]))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if ranged else 200)
        self.send_header("Content-Type", STREAM_TYPES.get(path.suffix.casefold(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if ranged:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if start == 0:
            _log(self.server.core.base, "file_streamed_to_phone", {"path": str(path), "bytes": size})
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError):
            pass   # the player seeks by closing this request and asking for another range

    def _stream(self, record, query):
        """GET /api/screen/stream: the screen as one continuous MJPEG stream (multipart/x-mixed-replace), shown by a
        plain <img>. No round trip per frame (owner 2026-11-07: "frames are still laggy"). The pointer is not in the
        picture: the phone draws it from /api/cursor/stream and moves it at once under your finger.
        Ends when the phone goes away, the view is stopped or replaced, or after SCREEN_MAX."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        from chutku import vision
        width = max(640, min(1920, int((query.get("w") or ["1280"])[0])))
        screen["stream"] = token = secrets.token_hex(4)   # a newer stream from this phone replaces this one
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=chutkuframe")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, sent_at = None, 0.0
        try:
            while self.server.screen is screen and screen.get("stream") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                started = time.monotonic()
                screen["beat"] = started
                try:
                    shot = vision.capture()
                    pixels = shot.pixels
                except OSError:   # locked or a secure desktop: try again shortly, keep the stream open
                    time.sleep(1.0)
                    continue
                digest = _changed(pixels)
                if digest != last or started - sent_at > 2.0:   # unchanged screens cost nothing (a keep-alive every 2 s)
                    self.server.monitor_seen = (started, (shot.left, shot.top, shot.width, shot.height))
                    body, mime = _jpeg(pixels, 8 if self.server.controlling() else 9, width=width)
                    self.wfile.write(b"--chutkuframe\r\nContent-Type: " + mime.encode() + b"\r\nContent-Length: "
                                     + str(len(body)).encode() + b"\r\n\r\n" + body + b"\r\n")
                    self.wfile.flush()
                    last, sent_at = digest, started
                time.sleep(max(0.0, STREAM_FRAME - (time.monotonic() - started)))
        except (BrokenPipeError, ConnectionError, OSError):
            pass   # the phone closed the stream

    def _h264(self, record, query):
        """GET /api/screen/h264: the screen as H.264 (owner 2026-11-08: "no lag or jitter"), decoded on the phone by
        WebCodecs. Each packet is [4-byte length][1 byte: 1 = keyframe][4-byte capture ms, _clock_ms][Annex B bytes]; the first is a keyframe. 409
        when no encoder works here: the phone falls back to /api/screen/stream. A still screen is sent 3 more times so
        it sharpens, then nothing until it changes. A different screen size ends the stream (the phone reconnects)."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        import struct
        width = max(640, min(1920, int((query.get("w") or ["1280"])[0])))
        grab = _Grabber()
        grab.start()
        first = grab.take(3.0)
        if first is None:
            grab.stop.set()
            raise RemoteDenied("The laptop is locked or showing a secure screen.", 503)
        size = (first[0].width, first[0].height)
        out_w = min(width, size[0])
        try:
            kbps = max(500, min(8000, int((query.get("kbps") or ["3000"])[0])))   # Watch mode asks for more
            encoder = H264(out_w, round(size[1] * out_w / size[0]), bit_rate=kbps * 1000)
        except (OSError, ImportError):
            grab.stop.set()
            raise RemoteDenied("No H.264 encoder on this laptop.", 409)
        grab.latest = first
        grab.fresh.set()   # the first capture is the first frame
        screen["stream"] = token = secrets.token_hex(4)   # a newer stream from this phone replaces this one
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Encoder", encoder.name)
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, settle = None, 0
        try:
            while self.server.screen is screen and screen.get("stream") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                taken = grab.take(1.0)
                screen["beat"] = time.monotonic()
                if taken is None:   # locked for a moment: keep the stream open
                    continue
                shot, digest = taken
                if (shot.width, shot.height) != size:
                    break
                settle = 3 if digest != last else settle - 1
                if settle >= 0:
                    self.server.monitor_seen = (time.monotonic(), (shot.left, shot.top, shot.width, shot.height))
                    stamp = _clock_ms(shot.taken)
                    for key, data in encoder.encode(shot.pixels, "bgra"):
                        self.wfile.write(struct.pack(">IBI", len(data), key, stamp) + data)
                    self.wfile.flush()
                    last = digest
        except (BrokenPipeError, ConnectionError, OSError):
            pass   # the phone closed the stream
        finally:
            grab.stop.set()

    # -- owner 2026-11-08: sound, speed test, window switcher, read aloud, voice click / voice typing -----------------
    def _audio(self, record):
        """GET /api/screen/audio: what the laptop plays, as Opus packets [4-byte length][4-byte capture ms][Opus 20 ms] (chutku/remote/audio.py),
        while the screen view lasts. 409 when there is no sound device to record from. Silence sends nothing."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        import struct
        from chutku.remote import audio
        try:
            source = audio.Loopback()
            encoder = audio.Opus(source.rate)
        except Exception:
            raise RemoteDenied("No sound device to record from on this laptop.", 409)
        screen["audio"] = token = secrets.token_hex(4)   # a newer one from this phone replaces this one
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            while self.server.screen is screen and screen.get("audio") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                samples = source.read()
                if samples is not None:
                    packets, now = encoder.encode(samples), time.monotonic()
                    for index, packet in enumerate(packets):
                        stamp = _clock_ms(now - 0.02 * (len(packets) - 1 - index))
                        self.wfile.write(struct.pack(">II", len(packet), stamp) + packet)
                    self.wfile.flush()
                time.sleep(0.02)
        except (BrokenPipeError, ConnectionError, OSError):
            pass   # the phone closed it
        finally:
            source.close()

    def _speedtest(self, query):
        """GET /api/speedtest?mb=N: N MB (1-20) for the phone to time, laptop -> phone, over whatever path Tailscale
        uses right now (direct or a relay)."""
        size = max(1, min(20, int((query.get("mb") or ["5"])[0]))) * 1024 * 1024
        chunk = secrets.token_bytes(64 * 1024)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for start in range(0, size, len(chunk)):
                self.wfile.write(chunk[:min(len(chunk), size - start)])
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _cursor_stream(self, record):
        """GET /api/cursor/stream: where the mouse is (0..1 of the streamed monitor), as server-sent events, whenever it
        moves (owner 2026-11-07, "the cursor still lags"). Like Chrome Remote Desktop / RustDesk / Parsec, the phone
        draws the pointer itself; this only corrects it, and shows moves made at the laptop. A newer one replaces it."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        from chutku.remote.control import cursor_pos
        screen["cursor"] = token = secrets.token_hex(4)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, sent_at, hovered, looked_at, looked_pos = None, 0.0, None, 0.0, None
        try:
            while self.server.screen is screen and screen.get("cursor") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                monitor = self._monitor()
                left, top, width, height = monitor
                x, y = cursor_pos()
                at = [round((x - left) / max(width, 1), 4), round((y - top) / max(height, 1), 4)]
                now = time.monotonic()
                if at != last or now - sent_at > 10:   # a keep-alive every 10 s finds a phone that went away
                    self.wfile.write(b"data: " + json.dumps(at).encode() + b"\n\n")
                    self.wfile.flush()
                    last, sent_at = at, now
                # the magnetic pointer (owner 2026-11-08): what is under it, while the phone controls the laptop
                if at != looked_pos and now - looked_at > HOVER_EVERY and self.server.controlling():
                    from chutku.remote import targets
                    found = targets.hover(x, y, monitor)
                    found = targets.on_monitor(found, monitor) if found else None
                    looked_pos, looked_at = at, now
                    if found != hovered:
                        self.wfile.write(b"event: hover\ndata: " + json.dumps(found).encode() + b"\n\n")
                        self.wfile.flush()
                        hovered = found
                time.sleep(CURSOR_TICK)
        except (BrokenPipeError, ConnectionError, OSError):
            pass
