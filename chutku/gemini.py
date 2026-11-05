"""Gemini client (off until the owner stores a key and grants cloud.gemini).

What may be sent (owner decisions 2026-09-30 / 2026-10-01): the request text, the tool catalog,
redacted step summaries and public results (planner, cloud_planner.cloud_view); project requests
and real error output (coder); and screenshots of the monitor in use (vision). File contents,
clipboard, memory and message text are never sent. Gemini never gets execution authority:
everything it proposes passes the same validation, policy and verification as local plans.
Free-tier limits are handled here: overloaded models are retried, used-up models are skipped
until the daily reset, and lite models carry most traffic.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request


DEFAULT_MODEL = "gemini-3.8-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_MODEL = re.compile(r"gemini-[a-z0-9][a-z0-9.-]{1,78}")


class GeminiUnavailable(RuntimeError):
    """Gemini is disabled, unavailable, or returned an unusable response."""

    def __init__(self, message="Gemini unavailable.", status=None):
        super().__init__(message)
        self.status = status  # HTTP status when there was one


def configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def selected_model() -> str:
    model = os.environ.get("CHUTKU_GEMINI_MODEL", DEFAULT_MODEL).strip()
    if not _MODEL.fullmatch(model):
        raise GeminiUnavailable("The configured Gemini model name is invalid.")
    return model


class GeminiAdvisor:
    """One bounded structured-output call to Google's fixed Gemini endpoint."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 timeout_seconds: float = 25.0):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model or selected_model()
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise GeminiUnavailable("Gemini is not configured.")
        if not _MODEL.fullmatch(self.model):
            raise GeminiUnavailable("The configured Gemini model name is invalid.")
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("Gemini timeout must be between 1 and 60 seconds.")

    def plan(self, message: str, *, system: str, schema: dict,
             cloud_consent: bool = False) -> dict:
        if cloud_consent is not True:
            raise PermissionError("Explicit cloud consent is required before sending request text to Gemini.")
        if not isinstance(message, str) or not message.strip() or len(message) > 1000:
            raise ValueError("Describe your request in 1 to 1000 characters.")
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": message}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 220,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        request = urllib.request.Request(
            ENDPOINT.format(model=self.model),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(65537)
        except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as error:
            raise GeminiUnavailable("Gemini could not be reached; local planning remains available.") from error
        if len(raw) > 65536:
            raise GeminiUnavailable("Gemini returned an oversized response.")
        try:
            envelope = json.loads(raw)
            candidate = envelope["candidates"][0]
            if candidate.get("finishReason") not in (None, "STOP"):
                raise ValueError("incomplete")
            text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
            plan = json.loads(text)
            if not isinstance(plan, dict):
                raise ValueError("not an object")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GeminiUnavailable("Gemini returned an invalid structured response.") from error
        return {"plan": plan, "model": envelope.get("modelVersion", self.model),
                "usage": envelope.get("usageMetadata", {})}


# -- model discovery and plain generation (used by long-task planning and the coder) ----

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
_chosen = {}


def _version(name):
    match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(match.group(1)) if match else 0.0


def available_models(api_key, timeout=15):
    request = urllib.request.Request(MODELS_URL, headers={"x-goog-api-key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            listing = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        raise GeminiUnavailable("The Gemini key was rejected." if error.code in (400, 401, 403)
                                else f"Gemini model list failed (HTTP {error.code}).") from error
    except (OSError, TimeoutError, ValueError) as error:
        raise GeminiUnavailable("Gemini could not be reached (offline?).") from error
    return [m["name"].removeprefix("models/") for m in listing.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


def ranked_models(api_key, purpose="plan"):
    """Usable text models, best first: newest Flash for planning; for code the newest capable model
    (Pro wins at the same version). An env override goes first."""
    cache_key = (api_key[-6:], purpose)
    if cache_key not in _chosen:
        names = [n for n in available_models(api_key) if n.startswith("gemini-") and not re.search(
            r"embedding|tts|image|audio|live|vision|aqa|learnlm|robotics|computer-use|native|thinking-exp|"
            r"transcribe|omni|customtools", n)]
        if not names:
            raise GeminiUnavailable("This key has no usable Gemini text models.")
        stable = [n for n in names if "preview" not in n and "exp" not in n] or names
        full = [n for n in stable if "lite" not in n and ("pro" in n or "flash" in n)] or stable
        # Lite models are 5-8 s on screenshots with accurate boxes (measured 2026-10-01) and are the
        # last resort when the big free models are overloaded.
        lite = sorted([n for n in stable if "flash-lite" in n], key=lambda n: (_version(n), "latest" not in n),
                      reverse=True)
        if purpose == "code":
            order = sorted(full, key=lambda n: (_version(n), "pro" in n, "latest" not in n, -len(n)), reverse=True)
        else:
            flash = [n for n in full if "flash" in n] or full
            order = sorted(flash, key=lambda n: (_version(n), "latest" not in n, -len(n)), reverse=True)
        # Free keys get ~20 requests/day on the big Flash models; lite models have more headroom and are
        # fast, so planning and vision use them first and the big models are kept for writing code.
        order = lite + [n for n in order if n not in lite] if purpose in {"vision", "plan"} else order + [
            n for n in lite if n not in order]
        _chosen[cache_key] = order
    override = os.environ.get("CHUTKU_GEMINI_MODEL" if purpose == "plan" else "CHUTKU_GEMINI_CODE_MODEL")
    if override and _MODEL.fullmatch(override.strip()):
        return [override.strip()] + [n for n in _chosen[cache_key] if n != override.strip()]
    return list(_chosen[cache_key])


def _quota_details(error):
    """(daily_quota_hit, retry_after_seconds) from a Gemini error body."""
    try:
        details = json.loads(error.read(65536)).get("error", {}).get("details", [])
    except (OSError, ValueError, AttributeError):
        return False, None
    daily, retry = False, None
    for detail in details:
        for violation in detail.get("violations", []) if isinstance(detail, dict) else []:
            daily = daily or "PerDay" in str(violation.get("quotaId", ""))
        if isinstance(detail, dict) and str(detail.get("retryDelay", "")).endswith("s"):
            try:
                retry = float(detail["retryDelay"][:-1])
            except ValueError:
                pass
    return daily, retry


# Models whose free daily quota is used up, kept until Google's daily reset (midnight Pacific, ~08:00 UTC).
_QUOTA_FILE = None
_exhausted = {}


def _quota_file():
    from chutku.app import PROJECT_ROOT
    return PROJECT_ROOT / "data" / "gemini-quota.json"


def _load_exhausted():
    global _exhausted
    try:
        stored = json.loads((_QUOTA_FILE or _quota_file()).read_text(encoding="utf-8"))
        _exhausted = {k: float(v) for k, v in stored.items() if float(v) > time.time()}
    except (OSError, ValueError, AttributeError):
        _exhausted = {k: v for k, v in _exhausted.items() if v > time.time()}
    return _exhausted


def _mark_exhausted(model):
    now = time.time()
    reset = (now // 86400) * 86400 + 8 * 3600  # next 08:00 UTC
    if reset <= now:
        reset += 86400
    _exhausted[model] = reset
    try:
        path = _QUOTA_FILE or _quota_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_exhausted), encoding="utf-8")
    except OSError:
        pass


RETRY_STATUSES = {500, 502, 503, 504}  # overload: worth one retry. 429 (quota) moves on to the next model.


def generate_best(api_key, purpose, system, user, *, models=6, retries=1, backoff=(5,), sleep=time.sleep, **kw):
    """generate() with the best available model: retry temporary overloads (5xx) with backoff,
    move on to the next model when one is overloaded, out of quota (429) or retired (404).
    Returns (text, model_version)."""
    last = None
    exhausted = _load_exhausted()
    ranked = ranked_models(api_key, purpose)
    usable = [m for m in ranked if m not in exhausted] or ranked[:1]
    for model in usable[:models]:
        for attempt in range(retries + 1):
            try:
                result = generate(api_key, model, system, user, **kw)
                if model != ranked[0]:  # remember what works right now
                    _chosen[(api_key[-6:], purpose)] = [model] + [n for n in ranked if n != model]
                return result
            except GeminiUnavailable as error:
                last = error
                if error.status == 429 and getattr(error, "daily", False):
                    _mark_exhausted(model)  # used up until tomorrow: don't ask it again today
                    break
                if error.status == 429 and (getattr(error, "retry_after", None) or 99) <= 20 and attempt < retries:
                    sleep(error.retry_after + 1)  # per-minute limit: wait it out
                    continue
                if error.status not in RETRY_STATUSES or attempt == retries:
                    break
                sleep(backoff[min(attempt, len(backoff) - 1)])
        if last is not None and last.status in (400, 401, 403):
            break  # the key itself is refused: other models won't help
        cache_key = (api_key[-6:], purpose)
        if last is not None and last.status in (404, 429) and cache_key in _chosen:
            rest = [n for n in _chosen[cache_key] if n != model]  # retired: drop; out of quota: try it last
            _chosen[cache_key] = rest if last.status == 404 else rest + [model]
    raise last or GeminiUnavailable("No Gemini model answered.")


def generate(api_key, model, system, user, *, schema=None, max_tokens=8192, timeout=180, temperature=0.2,
             images=()):
    """One Gemini call. `images` is a sequence of (mime_type, bytes). Returns (text, model_version).
    Raises GeminiUnavailable."""
    import base64
    from chutku.online import offline_mode
    if offline_mode():   # the owner's "offline mode": nothing is sent to Google, whichever path asked
        raise GeminiUnavailable("Offline mode is on: Gemini is not used.")
    config = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if schema is not None:
        config.update(responseMimeType="application/json", responseJsonSchema=schema)
    parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}}
             for mime, data in images] + [{"text": user}]
    payload = {"systemInstruction": {"parts": [{"text": system}]},
               "contents": [{"role": "user", "parts": parts}], "generationConfig": config}
    request = urllib.request.Request(ENDPOINT.format(model=model), data=json.dumps(payload).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "x-goog-api-key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4_000_001)
    except urllib.error.HTTPError as error:
        daily, retry_after = _quota_details(error)
        reason = ("daily free quota used up" if daily else "quota exhausted") if error.code == 429 else f"HTTP {error.code}"
        failure = GeminiUnavailable(f"Gemini unavailable ({reason}).", status=error.code)
        failure.daily, failure.retry_after = daily, retry_after
        raise failure from error
    except (OSError, TimeoutError) as error:
        raise GeminiUnavailable("Gemini could not be reached (offline?).") from error
    try:
        envelope = json.loads(body)
        candidate = envelope["candidates"][0]
        text = "".join(part.get("text", "") for part in candidate["content"]["parts"] if not part.get("thought"))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise GeminiUnavailable("Gemini returned an unusable response.") from error
    if candidate.get("finishReason") not in (None, "STOP"):
        raise GeminiUnavailable(f"Gemini stopped early ({candidate.get('finishReason')}).")
    return text, envelope.get("modelVersion", model)
