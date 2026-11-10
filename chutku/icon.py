"""Chutku's brand mark (2026-11-08 redesign): a warm orange rounded square with a white "c" and a dot in its
opening, like a speech mark. Drawn in code, anti-aliased by 4x4 supersampling: no image libraries. The same shape is
chutku/web/logo.svg; chutku/web/icon.png is written by `python -m chutku.icon` (png_bytes)."""
from __future__ import annotations

from pathlib import Path
import struct
import zlib

ICON_PATH = Path(__file__).resolve().parent / "web" / "chutku.ico"
BRAND = (0xE8, 0x59, 0x0C)


def _coverage(u, v):
    """What covers the point (u, v) in a 64x64 design (logo.svg): 0 outside, 1 brand, 2 white."""
    radius = 15.0
    dx = max(radius - u, u - (64 - radius), 0)
    dy = max(radius - v, v - (64 - radius), 0)
    if dx * dx + dy * dy > radius * radius:
        return 0
    ox, oy = u - 32, v - 32
    distance = (ox * ox + oy * oy) ** 0.5
    if 10.5 <= distance <= 17.5 and not (ox > 0 and abs(oy) < 9.5 * distance / 13.1):   # the "c", open to the right
        return 2
    if (u - 45.5) ** 2 + (v - 32) ** 2 <= 3.6 * 3.6:                                      # the dot
        return 2
    return 1


def _rgba(size: int):
    """RGBA rows, top-down."""
    rows, step = [], 64 / size
    for y in range(size):
        row = bytearray()
        for x in range(size):
            hits = [_coverage((x + (i + .5) / 4) * step, (y + (j + .5) / 4) * step) for i in range(4) for j in range(4)]
            inside = sum(1 for h in hits if h)
            if not inside:
                row += bytes(4)
                continue
            white = sum(1 for h in hits if h == 2) / inside
            colour = [round(c + (255 - c) * white) for c in BRAND]
            row += bytes((*colour, round(255 * inside / 16)))
        rows.append(bytes(row))
    return rows


def _pixels(size: int):
    """BGRA rows, bottom-up (as ICO bitmaps are stored)."""
    out = []
    for row in reversed(_rgba(size)):
        out.append(b"".join(bytes((row[i + 2], row[i + 1], row[i], row[i + 3])) for i in range(0, len(row), 4)))
    return b"".join(out)


def png_bytes(size: int = 256) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + row for row in _rgba(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def icon_bytes(sizes=(16, 32, 48)) -> bytes:
    images = []
    for size in sizes:
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
        mask = b"\x00" * (((size + 31) // 32) * 4 * size)  # alpha carries transparency
        images.append(header + _pixels(size) + mask)
    directory = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for size, image in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return directory + entries + b"".join(images)


def ensure_icon(path: Path | None = None) -> Path:
    """The icon file, written only when it is missing or stale. W2: an installed app never writes into its own
    folder; the bundled icon is used when it is current, else a copy goes to the user's data folder."""
    from chutku.core.paths import data_dir, is_checkout
    data = icon_bytes()
    if path is None:
        if ICON_PATH.is_file() and ICON_PATH.read_bytes() == data:
            return ICON_PATH
        path = ICON_PATH if is_checkout() else data_dir() / "chutku.ico"
    if not path.exists() or path.read_bytes() != data:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path
