"""Reversible, capability-gated Windows user settings."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


_THEME_SCRIPT = r'''
$ErrorActionPreference='Stop'; [Console]::InputEncoding=New-Object System.Text.UTF8Encoding; [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$r=[Console]::In.ReadToEnd()|ConvertFrom-Json
$path='HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
if(-not (Test-Path $path)){ New-Item -Path $path -Force|Out-Null }
if($r.action -ceq 'set'){
  $value=if($r.mode -ceq 'light'){1}else{0}
  Set-ItemProperty -Path $path -Name AppsUseLightTheme -Type DWord -Value $value
  Set-ItemProperty -Path $path -Name SystemUsesLightTheme -Type DWord -Value $value
  Start-Sleep -Milliseconds 100
}
$p=Get-ItemProperty -Path $path
$apps=if($null -eq $p.AppsUseLightTheme){1}else{[int]$p.AppsUseLightTheme}
$system=if($null -eq $p.SystemUsesLightTheme){1}else{[int]$p.SystemUsesLightTheme}
[pscustomobject]@{apps=if($apps -eq 1){'light'}else{'dark'};system=if($system -eq 1){'light'}else{'dark'}}|ConvertTo-Json -Compress
'''

_THEME_SCHEMA = {"type": "object", "properties": {"mode": {"type": "string", "enum": ["light", "dark"]}},
                 "required": ["mode"], "additionalProperties": False}


_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _registry_theme(request):
    """The same read/write as _THEME_SCRIPT, straight through the registry (~1 ms instead of ~0.5 s)."""
    import time
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _PERSONALIZE, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        if request.get("action") == "set":
            value = 1 if request["mode"] == "light" else 0
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
            time.sleep(0.1)

        def read(name):
            try:
                return int(winreg.QueryValueEx(key, name)[0])
            except FileNotFoundError:
                return 1  # Windows' default is light
        return {"apps": "light" if read("AppsUseLightTheme") == 1 else "dark",
                "system": "light" if read("SystemUsesLightTheme") == 1 else "dark"}


def _invoke(request):
    if sys.platform != "win32":
        raise OSError("Windows settings require Windows.")
    try:
        return _registry_theme(request)
    except (OSError, ValueError, TypeError):
        pass  # fall back to the PowerShell script below
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(_THEME_SCRIPT.encode("utf-16-le")).decode("ascii")
    done = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        input=json.dumps(request), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or len(done.stdout) > 4096:
        raise OSError("The bounded Windows theme operation failed.")
    try:
        value = json.loads(done.stdout.lstrip("\ufeff"))
    except (json.JSONDecodeError, TypeError) as error:
        raise OSError("Windows returned malformed theme data.") from error
    if not isinstance(value, dict) or set(value) != {"apps", "system"} or value["apps"] not in {"light", "dark"} or value["system"] not in {"light", "dark"}:
        raise OSError("Windows returned invalid theme data.")
    return value


def _none(arguments):
    if arguments != {}:
        raise ValueError("This operation takes no arguments.")


def _theme(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"mode"} or arguments["mode"] not in {"light", "dark"}:
        raise ValueError("Choose exactly light or dark mode.")


def _status(_arguments, _context):
    try:
        value = _invoke({"action": "get"})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult(value, Verification.PASS)


def _set(arguments, context):
    try:
        before = _invoke({"action": "get"})
        if before == {"apps": arguments["mode"], "system": arguments["mode"]}:
            return ToolResult({"error": "The requested theme is already fully active."}, Verification.FAIL)
        operation = context.journal.begin(context.task_id, "settings.theme_set", context.granted_root / ".windows-theme", before)
        after = _invoke({"action": "set", **arguments})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    expected = {"apps": arguments["mode"], "system": arguments["mode"]}
    verified = after == expected
    if verified:
        context.journal.complete(operation, after)
    return ToolResult({"before": before, "after": after, "verified": verified, "operation_id": operation},
                      Verification.PASS if verified else Verification.FAIL)


def _restore(_arguments, context):
    record = context.journal.latest_completed("settings.theme_set", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed theme change is available to restore."}, Verification.FAIL)
    if record["before"].get("apps") != record["before"].get("system"):
        return ToolResult({"error": "The earlier mixed theme cannot be restored by this bounded tool."}, Verification.FAIL)
    try:
        current = _invoke({"action": "get"})
        if current != record["after"]:
            return ToolResult({"error": "Theme changed again; refusing to overwrite the newer state."}, Verification.FAIL)
        restored = _invoke({"action": "set", "mode": record["before"]["apps"]})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    verified = restored == record["before"]
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"restored": verified, "state": restored, "operation_id": record["operation_id"]},
                      Verification.PASS if verified else Verification.FAIL)


def register_windows_settings_tools(registry):
    registry.register(Tool("settings.theme_status", "Read the current Windows application and system light/dark theme.",
        Risk.OBSERVATION, _status, _none, required_capability="settings.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("interactive Windows user profile",), reversibility="not_applicable", success_predicate="exact_theme_values_observed"))
    registry.register(Tool("settings.theme_set", "Set both Windows application and system theme and verify exact read-back.",
        Risk.EXTERNAL_SIDE_EFFECT, _set, _theme, required_capability="settings.modify", argument_schema=_THEME_SCHEMA,
        prerequisites=("interactive Windows user profile",), reversibility="compensatable", success_predicate="exact_theme_values_read_back"))
    registry.register(Tool("settings.theme_restore", "Restore the last Chutku theme change if no newer change occurred.",
        Risk.EXTERNAL_SIDE_EFFECT, _restore, _none, required_capability="settings.modify", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("matching completed Chutku theme operation",), reversibility="single_use", success_predicate="previous_theme_values_read_back"))
