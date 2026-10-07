"""history.search (Phase 3b H4): find past conversation turns by topic, in milliseconds, without a model."""
from __future__ import annotations

from pathlib import Path

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_SEARCH = {"type": "object", "properties": {
    "query": {"type": "string", "minLength": 1, "maxLength": 200},
    "days": {"type": "integer", "minimum": 1, "maximum": 3650}},
    "required": ["query"], "additionalProperties": False}


def _root():
    from chutku import mind
    return Path(mind.PROJECT_ROOT)


def _search(arguments, _context):
    from chutku import history_index
    result = history_index.search(_root(), arguments["query"], days=arguments.get("days"))
    return ToolResult(result, Verification.PASS, {"query": "[REDACTED]", "count": len(result["matches"])})


def _validate(arguments):
    if set(arguments) - {"query", "days"} or not isinstance(arguments.get("query"), str) \
            or not 0 < len(arguments["query"]) <= 200:
        raise ValueError("Give a query (and optionally days).")
    if "days" in arguments and not (type(arguments["days"]) is int and 1 <= arguments["days"] <= 3650):
        raise ValueError("days must be 1 to 3650.")


def register_history_tools(registry):
    registry.register(Tool("history.search", "Search everything the owner and Chutku said before (every past "
        "conversation, voice and typed) by topic words; optional days limits it to the last N days. Returns dates, "
        "what was said and the reply.", Risk.OBSERVATION, _search, _validate, argument_schema=_SEARCH,
        reversibility="not_applicable", success_predicate="history_searched"))
