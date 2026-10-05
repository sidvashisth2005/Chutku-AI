"""Chutku's small app icon (a green rounded square with a white "c"), drawn in code: no image libraries."""
from __future__ import annotations

from pathlib import Path
import struct

ICON_PATH = Path(__file__).resolve().parent / "web" / "chutku.ico"
GREEN = (0x23, 0x5F, 0x4D)


def _pixels(size: int):
    """BGRA rows, bottom-up (as ICO bitmaps are stored)."""
    radius, centre = size * 0.22, (size - 1) / 2
    ring_outer, ring_inner = size * 0.30, size * 0.18
    rows = []
    for y in range(size - 1, -1, -1):
        row = bytearray()
        for x in range(size):
            # rounded-square mask
            dx = max(radius - x, x - (size - 1 - radius), 0)
            dy = max(radius - y, y - (size - 1 - radius), 0)
            inside = dx * dx + dy * dy <= radius * radius
            if not inside:
                row += bytes((0, 0, 0, 0))
                continue
            # a "c": a ring with its right side cut away
            ox, oy = x - centre, y - centre
            distance = (ox * ox + oy * oy) ** 0.5
            letter = ring_inner <= distance <= ring_outer and not (ox > 0 and abs(oy) < size * 0.13)
            r, g, b = (255, 255, 255) if letter else GREEN
            row += bytes((b, g, r, 255))
        rows.append(bytes(row))
    return b"".join(rows)


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


def ensure_icon(path: Path = ICON_PATH) -> Path:
    data = icon_bytes()
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)
    return path
