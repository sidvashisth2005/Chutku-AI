"""Download pinned public runtime/model artifacts; never send user data.

This is a development setup action, not an agent tool or startup behavior.
Artifacts are verified before extraction/use. Inference has no network dependency.
"""
from pathlib import Path
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11181/llama-b11181-bin-win-cpu-x64.zip"
RUNTIME_SHA = "d0d65ea389d16bf1cf29116589056f97b913102e6845c65664bf04e012e0bada"
REVISION = "bc640142c66e1fdd12af0bd68f40445458f3869b"
MODEL_URL = f"https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/{REVISION}/Qwen3-4B-Q4_K_M.gguf"
MODEL_SHA = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, sha=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha and digest(path) == sha:
        print(f"Already verified: {path.name}", flush=True)
        return
    pending = path.with_suffix(path.suffix + ".download")
    with urllib.request.urlopen(url, timeout=30) as response, pending.open("wb") as stream:
        count, reported = 0, 0
        while chunk := response.read(4 * 1024 * 1024):
            stream.write(chunk)
            count += len(chunk)
            if count - reported >= 128 * 1024 * 1024:
                print(f"{path.name}: {count // (1024 * 1024)} MiB downloaded", flush=True)
                reported = count
    if sha and digest(pending) != sha:
        raise ValueError(f"Checksum mismatch: {path.name}; not installed.")
    pending.replace(path)
    print(f"Downloaded{' and verified' if sha else ''}: {path.name}", flush=True)


def main():
    archive = ROOT / "vendor/downloads/llama-b11181-bin-win-cpu-x64.zip"
    runtime = ROOT / "vendor/llama-b11181"
    model = ROOT / "models/Qwen3-4B-Q4_K_M.gguf"
    download(RUNTIME_URL, archive, RUNTIME_SHA)
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (runtime / member.filename).resolve()
            if not target.is_relative_to(runtime.resolve()):
                raise ValueError("Unsafe runtime archive member.")
        package.extractall(runtime)
    download("https://raw.githubusercontent.com/ggml-org/llama.cpp/b11181/LICENSE", runtime / "LICENSE-llama.cpp.txt")
    download(MODEL_URL, model, MODEL_SHA)
    download(f"https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/{REVISION}/LICENSE", ROOT / "models/Qwen3-LICENSE.txt")
    manifest = {"runtime": {"source": RUNTIME_URL, "sha256": RUNTIME_SHA,
                            "executable_sha256": digest(runtime / "llama-server.exe"),
                            "license": "MIT", "version": "b11181", "backend": "CPU"},
                "model": {"source": MODEL_URL, "sha256": MODEL_SHA, "license": "Apache-2.0", "revision": REVISION,
                          "name": "Qwen3-4B-Q4_K_M", "path": str(model.relative_to(ROOT))},
                "status": "Downloaded and hash-verified; empirical evaluation required.", "cloud_fallback": False}
    (ROOT / "models/manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
