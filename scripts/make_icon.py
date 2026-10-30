"""Draw Chutku's icon (W4): the presence orb on a dark rounded tile. Writes chutku/web/icon.png (256 px, PWA and
presence page) and chutku/web/chutku.ico (16-256 px, browser tab and tray). Pure Python + numpy, no image library.

    python scripts/make_icon.py
"""
from pathlib import Path
import struct
import zlib

import numpy as np

WEB = Path(__file__).resolve().parents[1] / "chutku" / "web"


def orb(size):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) + 0.5
    c = size / 2
    nx, ny = (x - c) / c, (y - c) / c
    r = np.sqrt(nx ** 2 + ny ** 2)
    # rounded dark tile
    corner = 0.38
    qx, qy = np.maximum(np.abs(nx) - (1 - corner), 0), np.maximum(np.abs(ny) - (1 - corner), 0)
    inside = np.sqrt(qx ** 2 + qy ** 2) <= corner
    rgb = np.zeros((size, size, 3), np.float32)
    rgb[...] = np.array([7, 11, 18], np.float32)
    # glow and rings
    accent = np.array([34, 211, 238], np.float32)
    glow = np.clip(1 - r / 0.95, 0, 1) ** 2 * 0.55
    ring1 = np.exp(-((r - 0.62) / 0.035) ** 2) * 0.9
    ring2 = np.exp(-((r - 0.80) / 0.025) ** 2) * 0.45
    core = np.clip(1 - r / 0.36, 0, 1)
    white = np.clip(1 - np.sqrt((nx + 0.09) ** 2 + (ny + 0.11) ** 2) / 0.16, 0, 1)
    light = np.clip(glow + ring1 + ring2 + core * 1.2, 0, 1.4)[..., None]
    rgb = rgb + accent * light
    rgb = rgb * (1 - white[..., None]) + 255 * white[..., None]
    alpha = np.where(inside, 255, 0).astype(np.float32)
    image = np.concatenate([np.clip(rgb, 0, 255), alpha[..., None]], axis=2).astype(np.uint8)
    return image


def png(image):
    height, width, _ = image.shape
    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(sizes=(16, 24, 32, 48, 64, 128, 256)):
    images = [png(orb(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, blob in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    return header + entries + data


def main():
    (WEB / "icon.png").write_bytes(png(orb(256)))
    (WEB / "chutku.ico").write_bytes(ico())
    print("wrote", WEB / "icon.png", (WEB / "icon.png").stat().st_size, "bytes and", WEB / "chutku.ico",
          (WEB / "chutku.ico").stat().st_size, "bytes")


if __name__ == "__main__":
    main()
