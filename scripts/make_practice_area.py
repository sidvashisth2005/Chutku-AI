"""Chutku 1.2 practice area (owner 2026-11-08: real practice on this PC at night, in a practice area only).

Builds D:\\ChutkuPractice: a fake user's folders with harmless dummy files (a messy Downloads, documents, photos,
music, projects, a Desktop) with varied names, sizes and dates. The live practice runtime (chutku/practice, built on
the web branch) may only touch this folder. `--reset` rebuilds it from scratch, so every practice night starts from
the same state.

Usage:  .venv\\Scripts\\python.exe scripts\\make_practice_area.py [--root D:\\ChutkuPractice] [--reset]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import struct
import zipfile
import zlib

ROOT = Path(r"D:\ChutkuPractice")
MARKER = ".chutku-practice"   # only a folder carrying this file is ever reset (never wipe a real folder)


def _png(width=8, height=8, colour=(255, 122, 26)):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _pdf(text):
    body = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _zip(names):
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name in names:
            bundle.writestr(name, f"practice file {name}\n")
    return buffer.getvalue()


def layout():
    """(relative path, bytes, days old). Deterministic: the same area every time."""
    note = lambda text: text.encode("utf-8")
    files = [
        # a messy Downloads: mixed types, duplicates, an old installer, a screenshot pile
        ("Downloads/DBMS Tutorial 12.pdf", _pdf("DBMS Tutorial 12"), 1),
        ("Downloads/DBMS Tutorial 12 (1).pdf", _pdf("DBMS Tutorial 12"), 1),
        ("Downloads/resume_final_v3.pdf", _pdf("Resume"), 20),
        ("Downloads/invoice-october.pdf", _pdf("Invoice October"), 9),
        ("Downloads/holiday photos.zip", _zip(["beach.png", "mountain.png"]), 40),
        ("Downloads/setup-old-app.exe.txt", note("not a real installer, a practice placeholder"), 90),
        ("Downloads/Screenshot 2026-11-01 101500.png", _png(), 7),
        ("Downloads/Screenshot 2026-11-02 093000.png", _png(colour=(59, 91, 255)), 6),
        ("Downloads/song.mp3.txt", note("placeholder for a song"), 15),
        ("Downloads/notes from class.txt", note("Normalization: 1NF, 2NF, 3NF, BCNF\nExam on Friday\n"), 3),
        ("Downloads/data.csv", note("name,marks\nAsha,82\nRavi,76\nMeera,91\n"), 2),
        # documents
        ("Documents/Shopping list.txt", note("milk\neggs\nbread\n"), 0),
        ("Documents/Ideas.md", note("# Ideas\n- learn guitar\n- weekend trek\n"), 5),
        ("Documents/College/Assignment 1.txt", note("Assignment 1: ER diagram for a library\n"), 12),
        ("Documents/College/Assignment 2.txt", note("Assignment 2: SQL joins\n"), 4),
        ("Documents/Budget 2026.csv", note("month,spent\nOct,12000\nNov,9500\n"), 8),
        ("Documents/Letter to landlord.txt", note("Dear Sir,\nThe tap in the kitchen leaks.\n"), 30),
        # photos and music
        ("Pictures/Trip/beach.png", _png(colour=(43, 224, 162)), 60),
        ("Pictures/Trip/sunset.png", _png(colour=(255, 79, 139)), 60),
        ("Pictures/profile.png", _png(), 100),
        ("Music/playlist.txt", note("Kesariya\nApna Bana Le\nTum Hi Ho\n"), 25),
        # projects
        ("Projects/website/index.html", note("<!doctype html><title>My site</title><h1>Hello</h1>\n"), 14),
        ("Projects/website/style.css", note("h1{color:orange}\n"), 14),
        ("Projects/python/hello.py", note("print('hello from the practice area')\n"), 10),
        ("Projects/todo.txt", note("fix navbar\nadd contact page\n"), 2),
        # a desktop that needs tidying
        ("Desktop/New Text Document.txt", b"", 1),
        ("Desktop/New Text Document (2).txt", b"", 1),
        ("Desktop/meeting notes.txt", note("Meeting with Rahul at 5 pm about the project\n"), 0),
        ("Desktop/photo.png", _png(colour=(177, 148, 255)), 3),
    ]
    return files


def build(root=ROOT, reset=False):
    root = Path(root)
    if root.exists() and reset:
        if not (root / MARKER).is_file():
            raise SystemExit(f"{root} exists but is not a practice area (no {MARKER}); refusing to reset it.")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text(json.dumps({"made": datetime.now().isoformat(timespec="seconds"),
                                           "by": "scripts/make_practice_area.py"}), encoding="utf-8")
    now = datetime.now()
    made = 0
    for relative, data, days in layout():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
            made += 1
        stamp = (now - timedelta(days=days, hours=made % 7)).timestamp()
        os.utime(path, (stamp, stamp))
    return made


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--reset", action="store_true", help="rebuild from scratch (only a marked practice area)")
    args = parser.parse_args(argv)
    made = build(args.root, args.reset)
    files = sum(1 for p in Path(args.root).rglob("*") if p.is_file())
    print(f"Practice area ready at {args.root}: {files} files ({made} new).")


if __name__ == "__main__":
    main()
