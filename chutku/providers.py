"""Free cloud model providers for the cloud-first brain (W2, owner decision 2026-10-29: "free cloud first").

Groq and Cerebras speak the OpenAI chat-completions protocol and are fast on their free tiers; Gemini (chutku.gemini)
is the third rung; the local Qwen models are the offline fallback. Keys live in Windows Credential Manager
("Chutku/Groq", "Chutku/Cerebras"; DPAPI-protected, never in files or logs) or in environment variables.

A provider that answers 429 (quota) or 5xx is put on a cooldown (data/provider-cooldown.json) and the next rung is
used; 401/403 marks the key as bad until it is stored again. Nothing here authorizes anything: proposals still pass
validate_proposal and the policy kernel.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)

PROVIDERS = {
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "env": "GROQ_API_KEY",
             "credential": "Chutku/Groq",
             "models": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]},   # as listed 2026-10-30
    "cerebras": {"url": "https://api.cerebras.ai/v1/chat/completions", "env": "CEREBRAS_API_KEY",
                 "credential": "Chutku/Cerebras", "models": ["llama-3.3-70b", "qwen-3-32b"]},
}
ORDER = ("groq", "cerebras")
QUOTA_COOLDOWN = 60           # a 429 without Retry-After: free tiers limit tokens per MINUTE (measured 2026-10-30)
ERROR_COOLDOWN = 60
_lock = threading.Lock()


class ProviderError(OSError):
    def __init__(self, message, *, kind="unavailable", retry_after=None):
        super().__init__(message)
        self.kind, self.retry_after = kind, retry_after


def api_key(provider):
    spec = PROVIDERS[provider]
    value = os.environ.get(spec["env"])
    if value:
        return value
    try:
        from chutku.cloud_planner import stored_key
        return stored_key(spec["credential"])
    except Exception:
        return None


def store_key(provider, key):
    from chutku.cloud_planner import store_key as store
    store(key, PROVIDERS[provider]["credential"])


def configured(base=None):
    """Providers with a key, in ladder order."""
    return [name for name in ORDER if api_key(name)]


# -- cooldowns ---------------------------------------------------------------------------------------------------

def _cooldown_file(base=None):
    return Path(base or PROJECT_ROOT) / "data" / "provider-cooldown.json"


def cooling(base=None, now=None):
    now = now or time.time()
    try:
        data = json.loads(_cooldown_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, (int, float)) and v > now} if isinstance(data, dict) else {}


def cool_down(key, seconds, base=None):
    with _lock:
        data = cooling(base)
        data[key] = time.time() + seconds
        path = _cooldown_file(base)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass


# -- the call ----------------------------------------------------------------------------------------------------

def chat_json(provider, model, system, user, *, key=None, timeout=25, max_tokens=2048, transport=None):
    """One JSON-mode chat completion. Returns (parsed JSON object, seconds). Raises ProviderError."""
    spec = PROVIDERS[provider]
    key = key or api_key(provider)
    if not key:
        raise ProviderError(f"No {provider} key is stored.", kind="no_key")
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    started = time.monotonic()
    if transport is not None:
        raw = transport(spec["url"], body)
    else:
        request = urllib.request.Request(spec["url"], data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json",
                                                  "User-Agent": "Chutku/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            retry = error.headers.get("Retry-After") if error.headers else None
            try:
                retry = float(retry) if retry else None
            except ValueError:
                retry = None
            if error.code == 429:
                raise ProviderError(f"{provider} quota reached.", kind="quota", retry_after=retry) from None
            if error.code in (401, 403):
                raise ProviderError(f"The {provider} key was rejected.", kind="auth") from None
            if error.code == 404:
                raise ProviderError(f"{provider} no longer offers {model}.", kind="retired") from None
            raise ProviderError(f"{provider} answered HTTP {error.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ProviderError(f"{provider} is not reachable ({type(error).__name__}).") from None
        except ValueError:
            raise ProviderError(f"{provider} returned something that is not JSON.") from None
    try:
        text = raw["choices"][0]["message"]["content"]
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError(f"{provider} returned an answer that is not one JSON object.", kind="malformed") from None
    if not isinstance(parsed, dict):
        raise ProviderError(f"{provider} returned JSON that is not an object.", kind="malformed")
    return parsed, round(time.monotonic() - started, 2)


def ladder(base=None, now=None):
    """[(provider, model)] in order, skipping cooled-down models and providers without a key."""
    cold = cooling(base, now)
    rungs = []
    for provider in configured(base):
        for model in PROVIDERS[provider]["models"]:
            if f"{provider}/{model}" not in cold and provider not in cold:
                rungs.append((provider, model))
    return rungs


def ask(system, user, *, base=None, transport=None, timeout=25, rungs=None):
    """Try each rung until one answers. Returns (parsed, {"provider", "model", "seconds", "tried"})."""
    tried = []
    for provider, model in (rungs if rungs is not None else ladder(base)):
        try:
            parsed, seconds = chat_json(provider, model, system, user, transport=transport, timeout=timeout)
            return parsed, {"provider": provider, "model": model, "seconds": seconds, "tried": tried}
        except ProviderError as error:
            tried.append(f"{provider}/{model}: {error.kind}")
            if error.kind == "quota":
                cool_down(f"{provider}/{model}", error.retry_after or QUOTA_COOLDOWN, base)
            elif error.kind == "auth":
                cool_down(provider, 24 * 3600, base)
            elif error.kind == "retired":
                cool_down(f"{provider}/{model}", 24 * 3600, base)
            elif error.kind == "unavailable":
                cool_down(f"{provider}/{model}", ERROR_COOLDOWN, base)
    raise ProviderError("No free cloud model answered: " + "; ".join(tried or ["no key stored"]), kind="exhausted")
