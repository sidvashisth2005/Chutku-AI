from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
from typing import Any

from chutku.core.memory import MemoryStore
from chutku.tools.registry import (EMPTY_ARGUMENT_SCHEMA, ExecutionContext, Risk, Tool, ToolRegistry,
                                   ToolResult, Verification)


LIMITS = [
    "The command center uses an explicit grammar. The separate local brain lab proposes bounded plans for review; it is experimental and can add unnecessary steps.",
    "Offline voice input recognizes a small English phrase list and requires review; it is not general Hindi/Hinglish recognition.",
    "Start-Chutku.cmd enables an independent heartbeat/kill guard. Direct CLI/dashboard launches have cooperative pause only; completed effects are not undone by stopping.",
    "File operations are restricted to the granted sandbox; text is limited to 64 KiB.",
    "Undo covers journaled text writes and refuses conflicting later edits.",
    "Project setup is a fixed recipe, not general autonomous planning.",
    "App launching/focus is limited to Notepad and Calculator; arbitrary typing/clicking is unavailable.",
    "Saved notes are explicit user data, not instructions or inferred facts.",
]

_MEMORY_KEY = {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"}
_MEMORY_SAVE_SCHEMA = {
    "type": "object",
    "properties": {"key": _MEMORY_KEY, "value": {"type": "string", "minLength": 1, "maxLength": 2000}},
    "required": ["key", "value"],
    "additionalProperties": False,
}
_MEMORY_SEARCH_SCHEMA = {
    "type": "object", "properties": {"query": {"type": "string", "maxLength": 200}},
    "additionalProperties": False,
}
_MEMORY_FORGET_SCHEMA = {
    "type": "object", "properties": {"key": _MEMORY_KEY}, "required": ["key"],
    "additionalProperties": False,
}


def _keys(arguments: dict, allowed: set[str], required: set[str]) -> None:
    if set(arguments) - allowed or required - set(arguments):
        raise ValueError("Unsupported or missing tool arguments.")
    if any(not isinstance(value, str) for value in arguments.values()):
        raise ValueError("All arguments must be strings.")


def _none(arguments: dict) -> None:
    _keys(arguments, set(), set())


def _save_args(arguments: dict) -> None:
    _keys(arguments, {"key", "value"}, {"key", "value"})
    MemoryStore.validate_key(arguments["key"])
    if not arguments["value"].strip() or len(arguments["value"]) > 2000:
        raise ValueError("Memory value must contain 1 to 2000 characters.")


def _search_args(arguments: dict) -> None:
    _keys(arguments, {"query"}, set())
    if len(arguments.get("query", "")) > 200:
        raise ValueError("Memory query must be at most 200 characters.")


def _forget_args(arguments: dict) -> None:
    _keys(arguments, {"key"}, {"key"})
    MemoryStore.validate_key(arguments["key"])


def _store(context: ExecutionContext) -> MemoryStore:
    if context.memory is None:
        raise ValueError("Memory storage is unavailable in this runtime.")
    return context.memory


def _save(arguments: dict, context: ExecutionContext) -> ToolResult:
    store = _store(context)
    saved = store.save(arguments["key"], arguments["value"])
    verified = saved is not None and saved["value"] == arguments["value"]
    return ToolResult({"remembered": saved["key"], "provenance": "user_stated"},
                      Verification.PASS if verified else Verification.FAIL)


def _search(arguments: dict, context: ExecutionContext) -> ToolResult:
    entries = _store(context).search(arguments.get("query", ""))
    return ToolResult({"memories": entries, "provenance": "user_stated"}, Verification.PASS,
                      {"count": len(entries), "memories": "[REDACTED]"})


def _forget(arguments: dict, context: ExecutionContext) -> ToolResult:
    forgotten = _store(context).forget(arguments["key"])
    return ToolResult({"forgotten": arguments["key"]} if forgotten else {"error": "No memory with that key exists."},
                      Verification.PASS if forgotten else Verification.FAIL)


def visible_windows() -> list[dict[str, Any]]:
    if sys.platform != "win32":
        raise OSError("Window inspection requires a Windows desktop session.")
    try:
        # Exact identities let later steps target one window without trusting titles.
        from chutku.tools.everyday import Desktop
        desktop = Desktop()
        return [{k: info[k] for k in ("title", "process_id", "window_id", "executable", "minimized")}
                for info in map(desktop.describe, desktop.windows(limit=100))]
    except (OSError, AttributeError):
        pass
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    windows = []

    @callback_type
    def collect(handle, _):
        if user32.IsWindowVisible(handle):
            length = min(user32.GetWindowTextLengthW(handle), 512)
            if length:
                text = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(handle, text, length + 1)
                process = wintypes.DWORD()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(process))
                if text.value:
                    windows.append({"title": text.value, "process_id": process.value})
        return len(windows) < 100

    if not user32.EnumWindows(collect, 0) and len(windows) < 100:
        code = ctypes.get_last_error()
        if code:
            raise ctypes.WinError(code)
        raise OSError("Windows desktop enumeration is unavailable in this session (for example, an isolated sandbox).")
    return windows


def _windows(_: dict, __: ExecutionContext) -> ToolResult:
    windows = visible_windows()
    return ToolResult({"windows": windows, "limit": 100}, Verification.PASS,
                      {"count": len(windows), "windows": "[REDACTED]"})


def capabilities(registry: ToolRegistry) -> list[dict]:
    return [tool.manifest() for tool in registry.list()]


def register_assistant_tools(registry: ToolRegistry) -> None:
    registry.register(Tool("assistant.capabilities", "Show registered capabilities and current limitations.", Risk.OBSERVATION,
        lambda _a, _c: ToolResult({"capabilities": capabilities(registry), "limits": LIMITS}, Verification.PASS), _none,
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="all_registered_tool_manifests_returned"))
    registry.register(Tool("windows.list", "List up to 100 open windows with title, window_id, process_id and executable.",
                           Risk.OBSERVATION, _windows, _none, argument_schema=EMPTY_ARGUMENT_SCHEMA,
                           prerequisites=("interactive Windows desktop",), reversibility="not_applicable",
                           success_predicate="bounded_visible_window_inventory_observed"))
    registry.register(Tool("memory.remember", "Save or replace an explicit local note (not a secrets vault).",
                           Risk.DATA_MODIFICATION, _save, _save_args, frozenset({"value"}),
                           argument_schema=_MEMORY_SAVE_SCHEMA, reversibility="compensatable",
                           success_predicate="stored_value_reloads_exactly"))
    registry.register(Tool("memory.search", "Search explicit local notes without a model or network.",
                           Risk.OBSERVATION, _search, _search_args, frozenset({"query"}),
                           argument_schema=_MEMORY_SEARCH_SCHEMA, reversibility="not_applicable",
                           success_predicate="bounded_local_query_completed"))
    registry.register(Tool("memory.forget", "Permanently remove one explicit local note by key.",
                           Risk.DATA_MODIFICATION, _forget, _forget_args,
                           argument_schema=_MEMORY_FORGET_SCHEMA, reversibility="irreversible",
                           success_predicate="memory_key_no_longer_exists", deletes=True))
