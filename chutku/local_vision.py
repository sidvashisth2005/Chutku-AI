"""Local eyes: a vision model on this PC (Qwen3-VL-4B through the pinned llama.cpp runtime), so seeing the screen
and pictures works offline and nothing leaves the PC. Gemini vision stays as the backup (owner, 2026-10-04:
"replace Gemini, keep it as a backup").

- One loopback llama-server with the vision model + its image projector, started on first use.
- 4 GB of graphics memory cannot hold the planner model and this one together, so the planner is unloaded first
  (it restarts by itself on its next request). If the GPU start fails, the CPU runtime is used.
- Unloaded after IDLE_SECONDS without use, which hands the GPU back to the planner.
- Model files are checked against the hashes pinned in models/manifest.json ("vision") before the first start.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time

from chutku.app import PROJECT_ROOT

IDLE_SECONDS = 90
STARTUP_SECONDS = 90
CONTEXT_TOKENS = 8192
_ENV_KEYS = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "PATHEXT", "TEMP", "TMP",
             "COMSPEC", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}
_verified = {}


class VisionUnavailable(OSError):
    pass


def _sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(base=PROJECT_ROOT):
    """(model, projector) paths after checking them against the pinned hashes (cached per file state)."""
    base = Path(base)
    try:
        entry = json.loads((base / "models/manifest.json").read_text(encoding="utf-8"))["vision"]
    except (OSError, ValueError, KeyError) as error:
        raise VisionUnavailable("No local vision model is set up.") from error
    paths = []
    root = (base / "models").resolve()
    for key in ("model", "mmproj"):
        item = entry.get(key) or {}
        path = (base / str(item.get("path", ""))).resolve()
        if path.parent != root or not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256"))):
            raise VisionUnavailable("The local vision model files are missing.")
        state = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
        if _verified.get(state) != item["sha256"]:
            if _sha256(path) != item["sha256"]:
                raise VisionUnavailable(f"{path.name} does not match its pinned hash; not loading it.")
            _verified[state] = item["sha256"]
        paths.append(str(path))
    return paths[0], paths[1]


def available(base=PROJECT_ROOT):
    try:
        files(base)
        return True
    except VisionUnavailable:
        return False


def _request(port, key, path, payload=None, timeout=10):
    import http.client
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        connection.request("GET" if payload is None else "POST", path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        if response.status != 200:
            raise VisionUnavailable(f"Local vision server answered {response.status}.")
        return json.loads(data)
    finally:
        connection.close()


class LocalVision:
    def __init__(self, base=PROJECT_ROOT):
        self.base = Path(base)
        self._lock = threading.RLock()
        self.process = None
        self.port = 0
        self.key = ""
        self.backend = None
        self.last_used = 0.0
        self._reaper = None

    def _runtimes(self):
        vendor = self.base / "vendor"
        found = []
        # Vulkan: llama.cpp fits as many layers as the free graphics memory allows ("auto"); forcing all of them
        # failed on this PC (Brave and other apps keep ~0.7 GB of the 4 GB).
        for name, backend, layers in (("llama-b11181-vulkan", "Vulkan", "auto"), ("llama-b11181", "CPU", 0)):
            exe = vendor / name / "llama-server.exe"
            if exe.is_file():
                found.append((str(exe), backend, layers))
        return found

    def _spawn(self, exe, backend, layers, model, mmproj):
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        key = secrets.token_urlsafe(32)
        args = [exe, "--model", model, "--mmproj", mmproj, "--host", "127.0.0.1", "--port", str(port),
                "--api-key", key, "--offline", "--no-webui", "--log-disable", "--ctx-size", str(CONTEXT_TOKENS),
                "--parallel", "1", "--threads", "6", "--threads-batch", "6"]
        if layers != "auto":
            args += ["--n-gpu-layers", str(layers)]
        if layers:
            from chutku.gpu import discrete_device
            device = discrete_device(exe)
            if device:
                args += ["--device", device]
        if layers:
            args += ["--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]
        else:
            args += ["--no-mmproj-offload"]
        env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEYS}
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + STARTUP_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise VisionUnavailable(f"{backend} vision runtime exited during startup.")
            try:
                if _request(port, key, "/health").get("status") == "ok":
                    return process, port, key
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        process.kill()
        raise VisionUnavailable(f"{backend} vision runtime did not start in {STARTUP_SECONDS} s.")

    def ensure_started(self):
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return
            model, mmproj = files(self.base)
            from chutku.brain_service import claim_gpu
            claim_gpu(self)   # free the GPU: the planner restarts on its own next request
            errors = []
            for exe, backend, layers in self._runtimes():
                try:
                    self.process, self.port, self.key = self._spawn(exe, backend, layers, model, mmproj)
                    self.backend = backend
                    self.last_used = time.monotonic()
                    self._start_reaper()
                    return
                except (OSError, subprocess.SubprocessError) as error:
                    errors.append(str(error))
            raise VisionUnavailable("Local vision could not start: " + " | ".join(errors or ["no runtime"]))

    def _start_reaper(self):
        if self._reaper is not None and self._reaper.is_alive():
            return

        def reap():
            while True:
                time.sleep(5)
                with self._lock:
                    if self.process is None:
                        return
                    if time.monotonic() - self.last_used > IDLE_SECONDS:
                        self.close()
                        return
        self._reaper = threading.Thread(target=reap, name="chutku-vision-reaper", daemon=True)
        self._reaper.start()

    def close(self):
        with self._lock:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.kill()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self.process = None
                self.backend = None

    def look(self, images, system, prompt, *, schema=None, max_tokens=1024, timeout=180):
        """Ask about one or more images [(mime, bytes)]. Returns (text, info)."""
        started = time.monotonic()
        with self._lock:
            self.ensure_started()
            port, key = self.port, self.key
            self.last_used = time.monotonic()
        parts = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,"
                                                           + base64.b64encode(data).decode("ascii")}}
                 for mime, data in images]
        parts.append({"type": "text", "text": prompt})
        payload = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": parts}],
                   "temperature": 0, "seed": 42, "max_tokens": max_tokens, "stream": False}
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "seen", "schema": schema}}
        try:
            response = _request(port, key, "/v1/chat/completions", payload, timeout=timeout)
        except (OSError, ValueError) as error:
            self.close()
            raise VisionUnavailable(f"Local vision request failed: {error}") from error
        finally:
            self.last_used = time.monotonic()
        choice = response["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise VisionUnavailable("Local vision answer was cut off.")
        return choice["message"]["content"], {"model": "local:Qwen3-VL-4B", "backend": self.backend,
                                              "seconds": round(time.monotonic() - started, 1)}


_shared = None
_shared_lock = threading.Lock()


def shared(base=PROJECT_ROOT):
    global _shared
    with _shared_lock:
        if _shared is None or _shared.base != Path(base):
            _shared = LocalVision(base)
        return _shared
