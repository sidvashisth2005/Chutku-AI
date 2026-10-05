"""Capability-gated, bounded Windows text clipboard access."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


MAX_CLIPBOARD_BYTES = 64 * 1024

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($request.action -eq 'read') {
    $value = Get-Clipboard -Raw -TextFormatType Text
    if ($null -eq $value) { $value = '' }
    [pscustomobject]@{text=[string]$value; characters=([string]$value).Length} | ConvertTo-Json -Compress
} elseif ($request.action -eq 'write') {
    $expected = [string]$request.text
    Set-Clipboard -Value $expected
    $actual = Get-Clipboard -Raw -TextFormatType Text
    if ($null -eq $actual) { $actual = '' }
    if ([string]$actual -cne $expected) { throw 'Clipboard verification mismatch.' }
    [pscustomobject]@{written=$true; characters=$actual.Length} | ConvertTo-Json -Compress
} else {
    throw 'Unsupported clipboard action.'
}
'''

_WRITE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "UTF-8 encoding must not exceed 65536 bytes."}},
    "required": ["text"],
    "additionalProperties": False,
}


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("Clipboard read takes no arguments.")


def _validate_write(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"text"} or not isinstance(arguments["text"], str):
        raise ValueError("Provide only text as a string.")
    if len(arguments["text"].encode("utf-8")) > MAX_CLIPBOARD_BYTES:
        raise ValueError(f"Clipboard text exceeds the {MAX_CLIPBOARD_BYTES}-byte limit.")


def _invoke(request):
    if sys.platform != "win32":
        raise OSError("Clipboard access requires Windows.")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        input=json.dumps(request, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=8, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > MAX_CLIPBOARD_BYTES * 2:
        raise OSError("Windows text clipboard operation failed or returned oversized output.")
    try:
        result = json.loads(completed.stdout.lstrip("\ufeff"))
    except (json.JSONDecodeError, TypeError) as error:
        raise OSError("Windows text clipboard returned an invalid response.") from error
    if not isinstance(result, dict):
        raise OSError("Windows text clipboard returned an invalid response.")
    return result


def _read(arguments, context):
    result = _invoke({"action": "read"})
    text = result.get("text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_CLIPBOARD_BYTES:
        return ToolResult({"error": "Clipboard text was invalid or exceeded the safe limit."}, Verification.FAIL)
    output = {"text": text, "characters": len(text), "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS,
                      {"text": "[REDACTED]", "characters": len(text), "provenance": "external_untrusted"})


def _write(arguments, context):
    result = _invoke({"action": "write", "text": arguments["text"]})
    verified = result.get("written") is True and result.get("characters") == len(arguments["text"])
    return ToolResult({"written": verified, "characters": len(arguments["text"])},
                      Verification.PASS if verified else Verification.FAIL)


def register_clipboard_tools(registry):
    registry.register(Tool("clipboard.read_text", "Read at most 64 KiB of Windows clipboard text as untrusted data.",
        Risk.OBSERVATION, _read, _validate_none, required_capability="clipboard.read",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("interactive Windows clipboard",),
        reversibility="not_applicable", success_predicate="bounded_text_returned_and_audit_redacted"))
    registry.register(Tool("clipboard.write_text", "Replace Windows clipboard text and verify the exact value.",
        Risk.DATA_MODIFICATION, _write, _validate_write, frozenset({"text"}), required_capability="clipboard.write",
        argument_schema=_WRITE_SCHEMA, prerequisites=("interactive Windows clipboard",),
        reversibility="transient", success_predicate="clipboard_text_matches_exact_requested_value"))
