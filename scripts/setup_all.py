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


RUNTIME_DIRS = {"runtime": "vendor/llama-b11181"}   # the CPU runtime's folder (its manifest entry has no "directory")


def _safe_extract(archive, directory):
    import zipfile
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (directory / member.filename).resolve().is_relative_to(directory.resolve()):
                raise OSError(f"{archive.name}: unsafe path in the archive ({member.filename}).")
        package.extractall(directory)


def fetch_runtime(label, entry):
    """A llama.cpp release zip: archive hash, safe extraction, then the executable or folder digest."""
    import shutil
    from chutku.brain_service import directory_digest
    directory = ROOT / (entry.get("directory") or RUNTIME_DIRS[label])
    archive = ROOT / "vendor" / "downloads" / entry["source"].rsplit("/", 1)[-1]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not (archive.is_file() and sha256(archive) == entry["sha256"]):
        download(entry["source"], archive, entry["sha256"])
    directory.mkdir(parents=True, exist_ok=True)
    _safe_extract(archive, directory)
    ok = (directory_digest(directory) == entry["directory_sha256"] if entry.get("directory_sha256")
          else sha256(directory / "llama-server.exe") == entry.get("executable_sha256"))
    if not ok:
        shutil.rmtree(directory)
        raise OSError(f"{label}: the extracted runtime does not match its pinned digest (deleted).")


def fetch_snapshot(label, entry):
    """A Hugging Face model folder at its pinned revision, kept only if the whole-folder digest matches."""
    import shutil
    import tempfile
    from huggingface_hub import snapshot_download
    from chutku.brain_service import directory_digest
    directory = ROOT / entry["directory"]
    repo = entry["source"].split("huggingface.co/", 1)[1].strip("/")
    with tempfile.TemporaryDirectory(dir=ROOT / "models") as temp:
        snapshot_download(repo, revision=entry["revision"], local_dir=temp)
        shutil.rmtree(Path(temp) / ".cache", ignore_errors=True)   # hub bookkeeping, not part of the model
        if directory_digest(Path(temp)) != entry["directory_sha256"]:
            raise OSError(f"{label}: the downloaded folder does not match its pinned digest (deleted).")
        shutil.copytree(temp, directory, dirs_exist_ok=True)


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
