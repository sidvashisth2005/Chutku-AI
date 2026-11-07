"""H9: one name for why a brain call failed, so the fallback and the owner's message agree (Hermes error_classifier).

Classes: rate_limited, server, auth, not_found, empty, invalid, network, local_oom, local_down, unknown.
providers.ask already turns these into cooldowns per provider (429 -> retry-after or 60 s, 401/403 -> 24 h,
404 -> 24 h); agent_loop uses the class in the reply when every brain failed, so "Gemini key rejected" is not shown
as "could not plan".
"""
from __future__ import annotations

import re

_PROVIDER_KINDS = {"quota": "rate_limited", "auth": "auth", "retired": "not_found", "malformed": "invalid",
                   "no_key": "auth", "unavailable": "server", "exhausted": "rate_limited"}
_STATUS = ((429, "rate_limited"), (401, "auth"), (403, "auth"), (404, "not_found"))
_TEXT = (
    (re.compile(r"\b(?:429|quota|rate.?limit|resource.?exhausted|too many requests)\b", re.I), "rate_limited"),
    (re.compile(r"\b(?:401|403|api key|key was rejected|permission|unauthori[sz]ed|forbidden)\b", re.I), "auth"),
    (re.compile(r"\b(?:404|no longer offers|not found|retired)\b", re.I), "not_found"),
    (re.compile(r"out of memory|\boom\b|vram|cuda error|vulkan.*(?:alloc|memory)", re.I), "local_oom"),
    (re.compile(r"llama-server|local model (?:is )?not (?:running|installed)|brain unavailable", re.I), "local_down"),
    (re.compile(r"\b(?:empty|no answer|no text)\b", re.I), "empty"),
    (re.compile(r"\b(?:malformed|invalid|not json|not one json|unparsable)\b", re.I), "invalid"),
    (re.compile(r"not reachable|timed? ?out|timeout|connection|urlerror|getaddrinfo|network", re.I), "network"),
    (re.compile(r"\b5\d\d\b|server error|unavailable|overloaded", re.I), "server"),
)

MESSAGES = {
    "rate_limited": "the free cloud quota is used up for now",
    "auth": "a cloud key is missing or was rejected (set it again with chutku.cli cloud set-key)",
    "not_found": "the cloud model was retired",
    "network": "the internet or the provider is not reachable",
    "server": "the cloud provider had an error",
    "local_oom": "the GPU ran out of memory for the local model",
    "local_down": "the local model is not running (say 'khud ko theek karo')",
    "empty": "the brain gave an empty answer",
    "invalid": "the brain gave an answer Chutku could not use",
}


def classify(error) -> str:
    """The failure class of an exception (or an error string)."""
    kind = getattr(error, "kind", None)
    if kind in _PROVIDER_KINDS:
        return _PROVIDER_KINDS[kind]
    status = getattr(error, "status", None) or getattr(error, "code", None)
    for code, name in _STATUS:
        if status == code:
            return name
    if isinstance(status, int) and 500 <= status < 600:
        return "server"
    if isinstance(error, TimeoutError):
        return "network"
    text = str(error or "")
    for pattern, name in _TEXT:
        if pattern.search(text):
            return name
    return "unknown"


def explain(errors) -> str:
    """One owner-facing reason for a list of errors (the first one with a known class), or ""."""
    for error in errors:
        kind = classify(error)
        if kind in MESSAGES:
            return MESSAGES[kind]
    return ""
