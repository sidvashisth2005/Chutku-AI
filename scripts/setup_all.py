r"""Check (and optionally restore) every pinned artifact in models/manifest.json: a reproducible install.

    .venv\Scripts\python.exe scripts\setup_all.py              # report what is present, missing or altered
    .venv\Scripts\python.exe scripts\setup_all.py --download   # also fetch missing single-file models (hash-checked)

Single files (the 4B planner, the 8B, the vision model and its projector) are downloaded from their pinned source
into models/ and kept only when the SHA-256 matches. Directories (Whisper, the llama.cpp runtimes) are checked by
digest and, when missing, the script says which setup step restores them. Nothing outside models/ is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def file_entries(manifest):
    """(label, entry) for every single-file artifact with source, path and sha256."""
    items = []
    for key, value in manifest.items():
        if not isinstance(value, dict):
            continue
        if {"source", "path", "sha256"} <= set(value):
            items.append((key, value))
        for sub_key, sub in value.items():
            if isinstance(sub, dict) and {"source", "path", "sha256"} <= set(sub):
                items.append((f"{key}.{sub_key}", sub))
    return items


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, target, expected):
    partial = target.with_suffix(target.suffix + ".download")
    done = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("ab" if done else "wb") as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    if sha256(partial) != expected:
        partial.unlink()
        raise OSError(f"{target.name}: downloaded file does not match its pinned hash (deleted).")
    partial.replace(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="fetch missing single-file models")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
    problems = 0
    for label, entry in file_entries(manifest):
        path = (ROOT / str(entry["path"]).replace("\\", "/")).resolve()
        if not path.is_relative_to((ROOT / "models").resolve()):
            print(f"SKIP     {label}: path is outside models/")
            problems += 1
            continue
        if path.is_file():
            from chutku.core import hashcache
            state = "OK      " if hashcache.matches(path, entry["sha256"]) else "ALTERED "
            problems += state != "OK      "
            print(f"{state} {label}: {path.name}")
            continue
        if args.download:
            print(f"DOWNLOAD {label}: {path.name} ...", flush=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            download(entry["source"], path, entry["sha256"])
            print(f"OK       {label}: {path.name} (downloaded and hash-checked)")
        else:
            print(f"MISSING  {label}: {path.name} (run with --download)")
            problems += 1
    from chutku.brain_service import directory_digest
    for label, hint in (("stt", "download Systran/faster-whisper-small into models/faster-whisper-small"),
                        ("gpu_runtime", "scripts/setup_local_brain.py fetches the llama.cpp runtime")):
        entry = manifest.get(label) or {}
        directory = ROOT / str(entry.get("directory", ""))
        if not entry:
            continue
        if not directory.is_dir():
            print(f"MISSING  {label}: {directory.name} ({hint})")
            problems += 1
        elif directory_digest(directory) != entry.get("directory_sha256"):
            print(f"ALTERED  {label}: {directory.name}")
            problems += 1
        else:
            print(f"OK       {label}: {directory.name}")
    print("All pinned artifacts are present and match." if not problems else f"{problems} artifact(s) need attention.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
