"""Persistent, integrity-checked local model service for the agent loop.

One loopback llama-server per Chutku process is started lazily, reused across
requests and unloaded after an idle period. The GPU runtime is preferred; if it
fails to start, the pinned CPU runtime is used. Nothing is sent off-machine.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import threading
import time

from chutku.app import PROJECT_ROOT
from chutku.brain import MODEL_NAME, _request, verify_local_artifacts
from chutku.core import hashcache

IDLE_UNLOAD_SECONDS = 2700   # 45 min: a reload costs seconds of start-up plus the whole prompt again
STARTUP_SECONDS = 60
REQUEST_SECONDS = 110
CONTEXT_TOKENS = 16384
_ENV_KEYS = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "PATHEXT", "TEMP", "TMP",
             "COMSPEC", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}


def directory_digest(directory: Path) -> str:
    """Hash every file (name + content) so backend DLLs are pinned, not only the launcher."""
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(directory).rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


def runtime_candidates(base: Path = PROJECT_ROOT) -> list[dict]:
    """Return verified runtimes in preference order (GPU first, CPU fallback)."""
    base = Path(base)
    verified = verify_local_artifacts(base)  # model + pinned CPU runtime
    from chutku.core.paths import resource
    manifest = json.loads(resource(base, "models/manifest.json").read_text(encoding="utf-8"))
    candidates = []
    gpu = manifest.get("gpu_runtime")
    if isinstance(gpu, dict):
        directory = resource(base, str(gpu.get("directory", ""))).resolve()
        vendor = resource(base, "vendor").resolve()
        if (directory.parent == vendor and directory.is_dir()
                and isinstance(gpu.get("directory_sha256"), str)
                and hashcache.directory_digest(directory, directory_digest) == gpu["directory_sha256"]):
            candidates.append({"backend": gpu.get("backend", "GPU"),
                               "executable": str(directory / "llama-server.exe"),
                               "gpu_layers": 99})
    candidates.append({"backend": "CPU", "executable": verified["runtime"], "gpu_layers": 0})
    return [{**item, "model": verified["model"]} for item in candidates]


class BrainUnavailable(OSError):
    pass


def tool_confidence(tokens):
    """How much the model itself wanted the first tool name the grammar let through: the probability of the first
    token after "tool": " (None when there is no tool or no probabilities). Low means the model's own first choice
    was not an allowed tool: it is unsure (master plan S14)."""
    import math
    import re as _re
    if not tokens:
        return None
    text = ""
    for token in tokens:
        if _re.search(r'"tool"\s*:\s*"$', text):
            logprob = token.get("logprob")
            return round(math.exp(logprob), 4) if isinstance(logprob, (int, float)) else None
        text += str(token.get("token", ""))
    return None


def _describe(error):
    """Keep the server's own words (e.g. a context overflow), not only the exception's class name."""
    return f"{type(error).__name__}: {str(error)[:200]}" if str(error) else type(error).__name__


# -- one GPU, several local models ---------------------------------------------------------------------------
# 4 GB of graphics memory holds one model at a time: the planner (4B), the strong planner (8B, partly on the GPU)
# or the vision model. Whoever starts next unloads the current one; each restarts by itself when needed again.
_gpu_lock = threading.RLock()
_gpu_owner = None
GPU_HANDOVER_SECONDS = 30


def claim_gpu(owner):
    """Make `owner` the one model on the GPU. Call it WITHOUT holding the service's own lock (lock order: GPU first,
    then a service), and the previous model is closed only after its running request finished (or 30 s passed)."""
    global _gpu_owner
    with _gpu_lock:   # held across the hand-over: two models never start at once
        previous, _gpu_owner = _gpu_owner, owner
        if previous is not None and previous is not owner:
            deadline = time.monotonic() + GPU_HANDOVER_SECONDS
            while getattr(previous, "inflight", 0) > 0 and time.monotonic() < deadline:
                time.sleep(0.1)
            try:
                previous.close()
            except (OSError, subprocess.SubprocessError):
                pass


def pinned_model(base, key):
    """Path of an extra model listed in models/manifest.json under `key`, after checking its pinned sha256."""
    from chutku.core.paths import model_file, resource
    try:
        entry = json.loads(resource(base, "models/manifest.json").read_text(encoding="utf-8"))[key]
    except (OSError, ValueError, KeyError) as error:
        raise BrainUnavailable(f"No {key} model is set up.") from error
    path = model_file(base, entry.get("path"))
    if path is None or not path.is_file():
        raise BrainUnavailable(f"The {key} model file is missing.")
    from chutku.core import hashcache
    if not hashcache.matches(path, str(entry.get("sha256"))):
        raise BrainUnavailable(f"{path.name} does not match its pinned hash; not loading it.")
    return str(path), entry


class BrainService:
    """Thread-safe lazy model server with idle unload and crash restart."""

    def __init__(self, base: Path = PROJECT_ROOT, idle_seconds: float = IDLE_UNLOAD_SECONDS, *, variant=None):
        self.base = Path(base)
        self.variant = variant   # None = the everyday 4B planner; "strong" = the 8B offline backup
        self.idle_seconds = idle_seconds
        self._lock = threading.RLock()
        self.process = None
        self.port = 0
        self.key = ""
        self.backend = None
        self.last_used = 0.0
        self.started_seconds = None
        self._reaper = None
        self.inflight = 0    # requests running now: never reaped or handed over mid-request

    # -- lifecycle -------------------------------------------------------
    def _spawn(self, candidate):
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        key = secrets.token_urlsafe(32)
        args = [candidate["executable"], "--model", candidate["model"], "--host", "127.0.0.1",
                "--port", str(port), "--api-key", key, "--offline", "--no-webui", "--log-disable",
                "--ctx-size", str(CONTEXT_TOKENS), "--parallel", "1", "--threads", "4",
                "--threads-batch", "4", "--reasoning", "off"]
        if candidate["gpu_layers"] != "auto":
            args += ["--n-gpu-layers", str(candidate["gpu_layers"])]
        device = None
        if candidate["gpu_layers"]:
            from chutku.gpu import discrete_device
            device = discrete_device(candidate["executable"])
            if device:
                args += ["--device", device]   # the RTX, not the Intel chip llama.cpp lists first
        if candidate["gpu_layers"]:
            # Quantized KV + flash attention keep 16K context inside 4 GB VRAM.
            args += ["--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]
        if candidate.get("draft"):   # speculative decoding: a tiny model guesses, the planner checks in one pass
            args += ["--model-draft", candidate["draft"], "--gpu-layers-draft", "99", "--spec-draft-n-max", "16",
                     "--spec-draft-n-min", "1"] + (["--device-draft", device] if candidate["gpu_layers"] and device else [])
        env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEYS}
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + STARTUP_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrainUnavailable(f"{candidate['backend']} model runtime exited during startup.")
            try:
                if _request(port, key, "/health").get("status") == "ok":
                    return process, port, key
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        process.kill()
        process.wait(timeout=5)
        raise BrainUnavailable(f"{candidate['backend']} model startup exceeded {STARTUP_SECONDS} seconds.")

    def _running(self):
        return self.process is not None and self.process.poll() is None

    def ensure_started(self):
        with self._lock:
            if self._running():
                return
        claim_gpu(self)   # outside our own lock: another service may need it to close
        with self._lock:
            if self._running():
                return
            self.process = None
            started = time.monotonic()
            errors = []
            for candidate in self._candidates():
                try:
                    self.process, self.port, self.key = self._spawn(candidate)
                    self.backend = candidate["backend"]
                    self.started_seconds = round(time.monotonic() - started, 3)
                    self.last_used = time.monotonic()
                    self._start_reaper()
                    return
                except (OSError, subprocess.SubprocessError) as error:
                    errors.append(str(error))
            raise BrainUnavailable("No local model runtime could start: " + " | ".join(errors))

    def _candidates(self):
        candidates = runtime_candidates(self.base)
        if self.variant is None:
            # The everyday planner: models/manifest.json may select a different pinned planner model
            # ("active_planner") and a speculative-decoding draft ("draft" with "enabled": true). Each GPU candidate
            # is tried with the draft first and again without it (a draft that does not fit must not stop Chutku).
            try:
                from chutku.core.paths import resource
                manifest = json.loads(resource(self.base, "models/manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
            active = manifest.get("active_planner")
            if active and active != "model":
                model, _entry = pinned_model(self.base, active)
                candidates = [{**c, "model": model} for c in candidates]
            draft = None
            if (manifest.get("draft") or {}).get("enabled"):
                try:
                    draft, _entry = pinned_model(self.base, "draft")
                except BrainUnavailable:
                    draft = None
            if draft:
                candidates = [variant for c in candidates
                              for variant in ([{**c, "draft": draft}, c] if c["gpu_layers"] else [c])]
            return candidates
        model, entry = pinned_model(self.base, self.variant)
        layers = entry.get("gpu_layers", "auto")   # "auto": llama.cpp fits what the free graphics memory allows
        return [{**c, "model": model, "gpu_layers": layers if c["gpu_layers"] else 0} for c in candidates]

    def _start_reaper(self):
        if self._reaper is not None and self._reaper.is_alive():
            return
        def reap():
            while True:
                time.sleep(5)
                with self._lock:
                    if self.process is None:
                        return
                    if self.idle_expired():
                        self.close()
                        return
        self._reaper = threading.Thread(target=reap, name="chutku-brain-reaper", daemon=True)
        self._reaper.start()

    def idle_expired(self):
        """Unload only when nothing is running and the idle time has passed (a long generation is not idle)."""
        return self.inflight == 0 and time.monotonic() - self.last_used > self.idle_seconds

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

    def status(self):
        with self._lock:
            running = self.process is not None and self.process.poll() is None
            return {"running": running, "backend": self.backend if running else None,
                    "startup_seconds": self.started_seconds, "model": MODEL_NAME}

    # -- inference -------------------------------------------------------
    def complete_text(self, messages, *, max_tokens, check=None, timeout=600):
        """Free-text completion (e.g. source code), with a progress heartbeat while it runs."""
        from chutku.core.progress import beat
        self.ensure_started()
        with self._lock:
            port, key = self.port, self.key
            self.last_used = time.monotonic()
            self.inflight += 1
        try:
            return self._complete_text(port, key, messages, max_tokens, check, timeout)
        finally:
            with self._lock:
                self.inflight -= 1
                self.last_used = time.monotonic()

    def _complete_text(self, port, key, messages, max_tokens, check, timeout):
        from chutku.core.progress import beat
        payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.2, "seed": 42,
                   "max_tokens": max_tokens, "stream": False}
        results = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: results.put(self._safe_request(port, key, payload, timeout)),
                         daemon=True).start()
        started = time.monotonic()
        while time.monotonic() - started < timeout + 5:
            if check is not None:
                try:
                    check()
                except BaseException:
                    self.close()   # a stop ends the generation too (it would otherwise keep the server busy)
                    raise
            beat()
            self.last_used = time.monotonic()   # a long generation is not "idle"
            try:
                ok, response = results.get(timeout=1.0)
            except queue.Empty:
                continue
            self.last_used = time.monotonic()
            if not ok:
                raise BrainUnavailable(f"Local model request failed ({_describe(response)}).")
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("The local model ran out of room before finishing.")
            return choice["message"]["content"], {"seconds": round(time.monotonic() - started, 1),
                                                  "backend": self.backend}
        raise TimeoutError("Local model took too long.")

    @staticmethod
    def _safe_request(port, key, payload, timeout):
        try:
            return True, _request(port, key, "/v1/chat/completions", payload, timeout=timeout)
        except Exception as error:
            return False, error

    def stream_complete(self, messages, *, schema, schema_name, max_tokens, on_text, check=None):
        """Like complete(), but streamed: on_text(output_so_far) after every piece (to speak the first sentence early)."""
        self.ensure_started()
        with self._lock:
            port, key = self.port, self.key
            self.last_used = time.monotonic()
            self.inflight += 1
        payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0, "seed": 42, "max_tokens": max_tokens,
                   "stream": True, "response_format": {"type": "json_schema", "json_schema": {
                       "name": schema_name, "strict": True, "schema": schema}}}
        started = time.monotonic()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=REQUEST_SECONDS - 5)
        try:
            connection.request("POST", "/v1/chat/completions", body=json.dumps(payload),
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise BrainUnavailable(f"Local model request failed (HTTP {response.status}).")
            text, finish = [], None
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                choice = json.loads(data)["choices"][0]
                piece = (choice.get("delta") or {}).get("content") or ""
                finish = choice.get("finish_reason") or finish
                if piece:
                    text.append(piece)
                    self.last_used = time.monotonic()
                    if check is not None:
                        check()
                    on_text("".join(text))
            if finish not in (None, "stop"):
                raise ValueError("Local model response was truncated; nothing will execute.")
            content = "".join(text)
            return json.loads(content), {"seconds": round(time.monotonic() - started, 3), "backend": self.backend,
                                         "streamed": True}
        except BaseException as error:
            if not isinstance(error, (ValueError, json.JSONDecodeError)):
                self.close()   # a stop or a broken stream: the server must not keep generating
            raise
        finally:
            connection.close()
            with self._lock:
                self.inflight -= 1
                self.last_used = time.monotonic()

    def complete(self, messages, *, schema, schema_name, max_tokens, check=None):
        """One bounded structured completion. `check` is polled (e.g. pause/stop)."""
        self.ensure_started()
        with self._lock:
            port, key = self.port, self.key
            self.last_used = time.monotonic()
            self.inflight += 1
        try:
            return self._complete(port, key, messages, schema, schema_name, max_tokens, check)
        finally:
            with self._lock:
                self.inflight -= 1
                self.last_used = time.monotonic()

    def _complete(self, port, key, messages, schema, schema_name, max_tokens, check):
        payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0, "seed": 42,
                   "max_tokens": max_tokens, "stream": False, "logprobs": True, "top_logprobs": 1,
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": schema_name, "strict": True, "schema": schema}}}
        results = queue.Queue(maxsize=1)

        def request():
            try:
                results.put((True, _request(port, key, "/v1/chat/completions", payload,
                                            timeout=REQUEST_SECONDS - 5)))
            except Exception as error:  # surfaced below
                results.put((False, error))

        threading.Thread(target=request, daemon=True).start()
        started = time.monotonic()
        while time.monotonic() - started < REQUEST_SECONDS:
            if check is not None:
                try:
                    check()
                except BaseException:
                    self.close()
                    raise
            try:
                ok, response = results.get(timeout=0.1)
            except queue.Empty:
                continue
            self.last_used = time.monotonic()
            if not ok:
                self.close()
                raise BrainUnavailable(f"Local model request failed ({_describe(response)}).")
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("Local model response was truncated; nothing will execute.")
            content = json.loads(choice["message"]["content"])
            return content, {"seconds": round(time.monotonic() - started, 3),
                             "usage": response.get("usage", {}), "backend": self.backend,
                             "tool_confidence": tool_confidence((choice.get("logprobs") or {}).get("content"))}
        self.close()
        raise TimeoutError("Local model request exceeded its deadline.")


_shared = None
_strong = None
_shared_lock = threading.Lock()


def strong_service(base: Path = PROJECT_ROOT):
    """The 8B planner/coder used when the 4B is not enough and Gemini cannot be reached (None if not installed)."""
    global _strong
    # Presence only: the full SHA-256 of the 5 GB file happens when the 8B is actually started (_candidates ->
    # pinned_model). Hashing it here cost the first request after every restart 5-20 s (live check 2026-10-06).
    from chutku.core.paths import model_file, resource
    try:
        entry = json.loads(resource(base, "models/manifest.json").read_text(encoding="utf-8"))["strong"]
        path = model_file(base, entry.get("path"))
        if path is None or not path.is_file():
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    with _shared_lock:
        if _strong is None or _strong.base != Path(base):
            _strong = BrainService(base, idle_seconds=300, variant="strong")
        return _strong


def shared_service(base: Path = PROJECT_ROOT) -> BrainService:
    global _shared
    with _shared_lock:
        if _shared is None or _shared.base != Path(base):
            _shared = BrainService(base)
        return _shared
