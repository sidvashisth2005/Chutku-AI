r"""Check (and optionally restore) every pinned artifact in models/manifest.json: a reproducible install.

    .venv\Scripts\python.exe scripts\setup_all.py              # report what is present, missing or altered
    .venv\Scripts\python.exe scripts\setup_all.py --download   # also fetch everything missing (hash-checked)

Single files (the 4B planner, the 8B, the vision model and its projector, the voice) are downloaded from their pinned
source into models/ and kept only when the SHA-256 matches. Directories are fetched too: the llama.cpp CPU and GPU
runtimes (release zip, archive SHA-256, then the server executable or whole-folder digest) into vendor/, and Whisper
(the pinned Hugging Face revision) into models/. Anything that does not match is deleted, never used. Nothing outside
models/ and vendor/ is written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# W5: the download and hash code lives in chutku/models.py (the first-run page uses it too); these names stay so the
# CLI and its tests keep working. ROOT and download are read at call time, so they can be patched.
from chutku import models as _models   # noqa: E402

file_entries = _models.file_entries
sha256 = _models.sha256
download = _models.download
_safe_extract = _models.safe_extract
RUNTIME_DIRS = _models.RUNTIME_DIRS


def fetch_runtime(label, entry):
    """A llama.cpp release zip: archive hash, safe extraction, then the executable or folder digest."""
    return _models.fetch_runtime(ROOT, label, entry, fetcher=lambda *args: download(*args))


def fetch_snapshot(label, entry):
    """A Hugging Face model folder at its pinned revision, kept only if the whole-folder digest matches."""
    return _models.fetch_snapshot(ROOT, label, entry)


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
    for label, fetch in (("runtime", fetch_runtime), ("gpu_runtime", fetch_runtime), ("stt", fetch_snapshot)):
        entry = manifest.get(label) or {}
        if not entry:
            continue
        directory = ROOT / str(entry.get("directory") or RUNTIME_DIRS.get(label, ""))
        present = (directory / "llama-server.exe").is_file() if label == "runtime" else directory.is_dir()
        if not present and args.download:
            print(f"DOWNLOAD {label}: {directory.name} ...", flush=True)
            fetch(label, entry)
            print(f"OK       {label}: {directory.name} (downloaded and digest-checked)")
            continue
        if not present:
            print(f"MISSING  {label}: {directory.name} (run with --download)")
            problems += 1
        elif label == "runtime":
            same = sha256(directory / "llama-server.exe") == entry.get("executable_sha256")
            print(f"{'OK      ' if same else 'ALTERED '} {label}: {directory.name}")
            problems += not same
        elif directory_digest(directory) != entry.get("directory_sha256"):
            print(f"ALTERED  {label}: {directory.name}")
            problems += 1
        else:
            print(f"OK       {label}: {directory.name}")
    print("All pinned artifacts are present and match." if not problems else f"{problems} artifact(s) need attention.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
