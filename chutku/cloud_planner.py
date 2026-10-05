"""Gemini as a secondary agent planner (owner decision 2026-09-30).

Used only when the local planner fails or cannot decide, the `cloud.gemini`
capability is granted, and an API key is available (environment variable or
Windows Credential Manager). Only the goal, the tool catalog and redacted step
summaries leave the machine: never observed data, file contents, screenshots,
clipboard or memories. Its proposal passes the same validation and policy as a
local one, so it cannot authorize anything by itself.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import json
import os

from chutku.agent_loop import AGENT_SYSTEM, MAX_STEPS_PER_ROUND, planner_catalog, validate_proposal
from chutku.app import PROJECT_ROOT

CREDENTIAL_TARGET = "Chutku/Gemini"


class _Credential(ctypes.Structure):
    _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR), ("Comment", w.LPWSTR),
                ("LastWritten", w.FILETIME), ("CredentialBlobSize", w.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", w.DWORD),
                ("AttributeCount", w.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", w.LPWSTR),
                ("UserName", w.LPWSTR)]


def _advapi():
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
    advapi.CredReadW.restype = w.BOOL
    advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), w.DWORD]
    advapi.CredWriteW.restype = w.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    advapi.CredFree.restype = None
    return advapi


def stored_key():
    """Read the key from Windows Credential Manager (DPAPI-protected), if present."""
    try:
        advapi = _advapi()
    except (OSError, AttributeError):
        return None
    pointer = ctypes.POINTER(_Credential)()
    if not advapi.CredReadW(CREDENTIAL_TARGET, 1, 0, ctypes.byref(pointer)):
        return None
    try:
        blob = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
        return blob.decode("utf-16-le") or None
    finally:
        advapi.CredFree(pointer)


def store_key(key: str):
    if not isinstance(key, str) or not 20 <= len(key.strip()) <= 200:
        raise ValueError("That does not look like an API key.")
    advapi = _advapi()
    blob = key.strip().encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _Credential(Type=1, TargetName=CREDENTIAL_TARGET, CredentialBlobSize=len(blob),
                             CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)), Persist=2,
                             UserName="chutku")
    if not advapi.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def api_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or stored_key()


# Results Gemini may see so it can plan long tasks: public web data, system status and file
# *names*. Private content (file text, clipboard, screen text, memory, messages) stays local.
SHAREABLE_PREFIXES = ("web.", "youtube.", "system.get_time", "system.environment", "system.performance",
                      "apps.installed", "windows.list", "media.status", "audio.volume", "display.brightness",
                      "games.", "reminder.list", "filesystem.search", "filesystem.list", "filesystem.inspect",
                      "filesystem.largest", "code.build_project", "screen.understand", "screen.click",
                      "screen.scroll", "keyboard.", "apps.")
SHARED_STEPS = 15
SHARED_CHARS = 2500


def cloud_view(session, runtime):
    """What Gemini may see: goal, roots, redacted step summaries and shareable results only."""
    steps = []
    for index, step in enumerate(session.steps):
        try:
            sensitive = runtime.registry.get(step["tool"]).sensitive_argument_names
        except KeyError:
            sensitive = frozenset(step["arguments"])
        item = {"tool": step["tool"], "state": step["state"],
                "arguments": {k: "[REDACTED]" if k in sensitive else v for k, v in step["arguments"].items()}}
        if step.get("message"):
            item["message"] = str(step["message"])[:300]
        recent = index >= len(session.steps) - SHARED_STEPS
        if recent and step["tool"].startswith(SHAREABLE_PREFIXES) and step.get("observation"):
            item["observed_data"] = str(step["observation"])[:SHARED_CHARS]
        steps.append(item)
    context = {key: session.context.get(key) for key in ("accessible_roots", "user_folders", "projects_folder")}
    if session.context.get("past_successes"):  # approach only: tool names and purposes, no argument values
        context["past_successes"] = [{"goal": e["goal"], "steps": [{"tool": s["tool"], "purpose": s["purpose"]}
                                                                   for s in e["steps"]]}
                                     for e in session.context["past_successes"]]
    if session.context.get("about_you"):   # owner decision 2026-10-04: topic-related memory only, small
        from chutku.recall import _fit
        context["about_you"] = _fit(json.loads(json.dumps(session.context["about_you"])), 800)
    context["note"] = "Private results (file contents, clipboard, screen text) are withheld."
    view = {"GOAL": session.goal, "CONTEXT": context, "STEPS": steps}
    if session.feedback:
        view["FEEDBACK"] = session.feedback
    return json.dumps(view, ensure_ascii=False, separators=(",", ":"))


def cloud_schema(tool_names):
    """Gemini-friendly schema; arguments travel as a JSON string and are checked locally."""
    return {"type": "object", "properties": {
        "status": {"type": "string", "enum": ["continue", "done", "clarify"]},
        "reply": {"type": "string"},
        "declared_plan": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "maxItems": MAX_STEPS_PER_ROUND, "items": {
            "type": "object", "properties": {
                "tool": {"type": "string", "enum": sorted(tool_names)},
                "arguments_json": {"type": "string"},
                "purpose": {"type": "string"}},
            "required": ["tool", "arguments_json", "purpose"]}},
        "finish": {"type": "boolean"},
    }, "required": ["status", "reply", "declared_plan", "next_steps", "finish"]}


class GeminiAgentPlanner:
    name = "gemini"

    def __init__(self, key, model=None, transport=None):
        self.key = key
        self.model = model  # None: the newest Flash model this key can use, chosen on first call
        self.transport = transport  # tests inject a fake network call

    def propose(self, session, runtime, check=None):
        from chutku.gemini import GeminiUnavailable
        schemas, catalog = planner_catalog(runtime)
        system = AGENT_SYSTEM.replace(" /no_think", "") + "TOOL_CATALOG=" + catalog
        try:
            envelope = (self.transport or self._call)(system, cloud_view(session, runtime), cloud_schema(schemas))
        except GeminiUnavailable as error:
            raise OSError(str(error)) from error
        raw = envelope["plan"]
        try:
            steps = [{"tool": s["tool"], "arguments": json.loads(s.get("arguments_json") or "{}"),
                      "purpose": str(s.get("purpose", ""))[:160]} for s in raw.get("next_steps", [])]
            proposal = {"status": raw.get("status"), "reply": str(raw.get("reply", ""))[:600],
                        "declared_plan": [str(x)[:160] for x in raw.get("declared_plan", [])][:10],
                        "next_steps": steps, "finish": raw.get("finish") is True}
        except (TypeError, AttributeError, json.JSONDecodeError) as error:
            raise ValueError("Gemini returned malformed step arguments.") from error
        return validate_proposal(proposal, runtime, set(schemas)), {
            "planner": self.name, "backend": envelope.get("model"), "seconds": None}

    def _call(self, system, user, schema):
        from chutku.gemini import GeminiUnavailable, generate, generate_best
        if self.model is None:  # best available Flash, with a short retry / next-model fallback
            text, version = generate_best(self.key, "plan", system, user, schema=schema, max_tokens=8192,
                                          timeout=60, temperature=0, retries=1, backoff=(3,))
        else:
            text, version = generate(self.key, self.model, system, user, schema=schema, max_tokens=8192,
                                     timeout=60, temperature=0)
        try:
            plan = json.loads(text)
        except ValueError as error:
            raise GeminiUnavailable("Gemini returned an invalid structured response.") from error
        return {"plan": plan, "model": version}


class BackupPlanner:
    """The second planner (owner, 2026-10-04: work offline too, Gemini as the backup): Gemini when it is enabled
    and the internet is reachable, otherwise the local 8B model; if Gemini fails mid-request, the 8B finishes."""

    def __init__(self, gemini=None, strong=None, *, online=None):
        self.gemini, self.strong = gemini, strong
        self.online = online
        self.name = "gemini" if gemini is not None else "local-8b"

    def _reachable(self):
        if self.online is not None:
            return self.online()
        from chutku.online import reachable
        return reachable()

    def cheap_second_opinion(self):
        return self.gemini is not None and self._reachable()

    def _strong(self):
        from chutku.agent_loop import LocalAgentPlanner
        planner = LocalAgentPlanner(self.strong)
        planner.name = "local-8b"
        return planner

    def propose(self, session, runtime, check=None):
        if self.gemini is not None and self._reachable():
            try:
                self.name = "gemini"
                return self.gemini.propose(session, runtime, check)
            except (OSError, TimeoutError):
                if self.strong is None:
                    raise
        if self.strong is None:
            raise OSError("Gemini is not reachable and the local 8B model is not installed.")
        self.name = "local-8b"
        return self._strong().propose(session, runtime, check)

    def answer(self, session, runtime, check=None):
        if self.gemini is not None and hasattr(self.gemini, "answer") and self._reachable():
            try:
                return self.gemini.answer(session, runtime, check)
            except (OSError, TimeoutError):
                pass
        if self.strong is not None:
            return self._strong().answer(session, runtime, check)
        return None


def fallback_planner(base=PROJECT_ROOT):
    """Gemini (when the owner enabled it and a key exists) backed by the local 8B; None when neither exists."""
    from chutku.app import create_runtime
    from chutku.brain_service import strong_service
    gemini = None
    try:
        with create_runtime(base) as runtime:
            runtime.current_capability("cloud.gemini")
        key = api_key()
        gemini = GeminiAgentPlanner(key) if key else None
    except Exception:
        gemini = None
    strong = strong_service(base)
    if gemini is None and strong is None:
        return None
    return BackupPlanner(gemini, strong)
