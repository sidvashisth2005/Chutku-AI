"""W5: optional offline packs, downloaded with progress and resume, kept only when their pinned hash matches.

Moved here from scripts/setup_all.py (which stays as a thin CLI) so the first-run page can use it. Everything is
written under a base folder (home(): the repo in a git checkout, %LOCALAPPDATA%/Chutku in an installed package):
single model files into <base>/models, llama.cpp runtimes into <base>/vendor, Whisper into <base>/models. A file or
folder that does not match its pin is deleted, never used.

Packs (the essentials, i.e. wake word, speaker and embeddings, ship inside the app package):
  voice   offline speech in and out: Whisper small (stt) and the Kokoro voice (tts)      about 0.8 GB
  brain   the offline planner Qwen3-4B with the llama.cpp CPU and GPU runtimes            about 2.5 GB
  screen  offline screen understanding: Qwen3-VL-4B and its projector (vision)           about 2.8 GB
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import threading
import urllib.request

PACKS = {
    "voice": {"label": "Offline voice", "keys": ("stt", "tts"), "about_gb": 0.8},
    "brain": {"label": "Offline brain", "keys": ("model", "runtime", "gpu_runtime"), "about_gb": 2.5},
    "screen": {"label": "Offline screen understanding", "keys": ("vision",), "about_gb": 2.8},
}
RUNTIME_DIRS = {"runtime": "vendor/llama-b11181"}   # the CPU runtime's folder (its manifest entry has no "directory")
CHUNK = 1 << 20


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest():
    from chutku.core.paths import CODE_ROOT
    return json.loads((CODE_ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))


def file_entries(data):
    """(label, entry) for every single-file artifact with source, path and sha256."""
    items = []
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if {"source", "path", "sha256"} <= set(value):
            items.append((key, value))
        for sub_key, sub in value.items():
            if isinstance(sub, dict) and {"source", "path", "sha256"} <= set(sub):
                items.append((f"{key}.{sub_key}", sub))
    return items


def download(url, target, expected, progress=None, opener=urllib.request.urlopen):
    """Download with resume (a partial `<name>.download` continues with a Range request). The file is kept only if
    its SHA-256 is `expected`; otherwise it is deleted and OSError is raised. progress(done_bytes, total_or_None)."""
    target = Path(target)
    partial = target.with_suffix(target.suffix + ".download")
    done = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={done}-"} if done else {})
    with opener(request, timeout=60) as response:
        if done and getattr(response, "status", 206) != 206:
            done = 0   # the server ignored the Range header: start again
        length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
        total = done + int(length) if length and str(length).isdigit() else None
        with partial.open("ab" if done else "wb") as out:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if sha256(partial) != expected:
        partial.unlink()
        raise OSError(f"{target.name}: downloaded file does not match its pinned hash (deleted).")
    partial.replace(target)
    return target


def safe_extract(archive, directory):
    import zipfile
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (Path(directory) / member.filename).resolve().is_relative_to(Path(directory).resolve()):
                raise OSError(f"{Path(archive).name}: unsafe path in the archive ({member.filename}).")
        package.extractall(directory)


def fetch_runtime(base, label, entry, fetcher=download):
    """A llama.cpp release zip: archive hash, safe extraction, then the executable or folder digest."""
    from chutku.brain_service import directory_digest
    base = Path(base)
    directory = base / (entry.get("directory") or RUNTIME_DIRS[label])
    archive = base / "vendor" / "downloads" / entry["source"].rsplit("/", 1)[-1]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not (archive.is_file() and sha256(archive) == entry["sha256"]):
        fetcher(entry["source"], archive, entry["sha256"])
    directory.mkdir(parents=True, exist_ok=True)
    safe_extract(archive, directory)
    ok = (directory_digest(directory) == entry["directory_sha256"] if entry.get("directory_sha256")
          else sha256(directory / "llama-server.exe") == entry.get("executable_sha256"))
    if not ok:
        shutil.rmtree(directory)
        raise OSError(f"{label}: the extracted runtime does not match its pinned digest (deleted).")


def fetch_snapshot(base, label, entry):
    """A Hugging Face model folder at its pinned revision, kept only if the whole-folder digest matches."""
    import tempfile
    from huggingface_hub import snapshot_download
    from chutku.brain_service import directory_digest
    base = Path(base)
    directory = base / entry["directory"]
    (base / "models").mkdir(parents=True, exist_ok=True)
    repo = entry["source"].split("huggingface.co/", 1)[1].strip("/")
    with tempfile.TemporaryDirectory(dir=base / "models") as temp:
        snapshot_download(repo, revision=entry["revision"], local_dir=temp)
        shutil.rmtree(Path(temp) / ".cache", ignore_errors=True)   # hub bookkeeping, not part of the model
        if directory_digest(Path(temp)) != entry["directory_sha256"]:
            raise OSError(f"{label}: the downloaded folder does not match its pinned digest (deleted).")
        shutil.copytree(temp, directory, dirs_exist_ok=True)


def _model_path(base, entry):
    path = (Path(base) / str(entry["path"]).replace("\\", "/")).resolve()
    if not path.is_relative_to((Path(base) / "models").resolve()):
        raise OSError(f"{entry['path']} is outside models/; refused.")
    return path


def pack_installed(base, pack, data=None):
    """True when every artifact of the pack is present (presence only; the loaders check the hashes)."""
    data = data or manifest()
    for key in PACKS[pack]["keys"]:
        entry = data.get(key) or {}
        files = file_entries({key: entry})
        if files:
            if not all(_model_path(base, item).is_file() for _label, item in files):
                return False
        elif key in ("runtime", "gpu_runtime"):
            folder = Path(base) / str(entry.get("directory") or RUNTIME_DIRS.get(key, ""))
            if not (folder / "llama-server.exe").is_file():
                return False
        elif entry.get("directory") and not (Path(base) / entry["directory"]).is_dir():
            return False
    return True


def install_pack(base, pack, progress=None, data=None, fetcher=download, snapshot=fetch_snapshot):
    """Download every missing artifact of a pack (resumable, hash-checked). progress(label, done, total)."""
    if pack not in PACKS:
        raise ValueError(f"Unknown pack {pack}; choose one of {', '.join(PACKS)}.")
    data = data or manifest()
    for key in PACKS[pack]["keys"]:
        entry = data.get(key) or {}
        files = file_entries({key: entry})
        for label, item in files:
            path = _model_path(base, item)
            if path.is_file() and sha256(path) == item["sha256"]:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            fetcher(item["source"], path, item["sha256"],
                    (lambda done, total, label=label: progress(label, done, total)) if progress else None)
        if not files and key in ("runtime", "gpu_runtime") and entry:
            fetch_runtime(base, key, entry, fetcher)
        elif not files and entry.get("directory"):
            snapshot(base, key, entry)
    return pack_installed(base, pack, data)


class Downloads:
    """Background pack downloads for the first-run page: one thread per pack, polled with status()."""

    def __init__(self, base):
        self.base, self.lock, self.jobs = Path(base), threading.Lock(), {}

    def start(self, pack, installer=install_pack):
        if pack not in PACKS:
            raise ValueError(f"Unknown pack {pack}.")
        with self.lock:
            job = self.jobs.get(pack)
            if job and job["state"] == "downloading":
                return dict(job)
            self.jobs[pack] = {"state": "downloading", "file": None, "done": 0, "total": None, "error": None}

        def progress(label, done, total):
            with self.lock:
                self.jobs[pack].update(file=label, done=done, total=total)

        def run():
            try:
                ok = installer(self.base, pack, progress)
                state, error = ("installed", None) if ok else ("failed", "Some files are still missing.")
            except (OSError, ValueError, KeyError, ImportError) as failure:
                state, error = "failed", str(failure)[:300]
            with self.lock:
                self.jobs[pack].update(state=state, error=error)
        threading.Thread(target=run, name=f"chutku-pack-{pack}", daemon=True).start()
        return self.status()[pack]

    def status(self):
        with self.lock:
            jobs = {name: dict(job) for name, job in self.jobs.items()}
        data = manifest()
        return {name: {"label": spec["label"], "about_gb": spec["about_gb"],
                       **({"state": "installed"} if pack_installed(self.base, name, data) else {"state": "not_installed"}),
                       **jobs.get(name, {})} for name, spec in PACKS.items()}
