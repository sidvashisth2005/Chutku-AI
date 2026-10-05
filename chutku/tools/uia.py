"""Bounded, read-only Windows UI Automation inspection for exact app windows."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import Risk, Tool, ToolResult, Verification
from chutku.tools.windows_apps import APPS, WindowsDesktop


MAX_ELEMENTS = 250
MAX_DEPTH = 5

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][int64]$request.hwnd)
if ($null -eq $root) { throw 'UI Automation could not bind the reviewed window.' }
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
function SafeInt([double]$value) {
    if ([double]::IsNaN($value) -or [double]::IsInfinity($value)) { return 0 }
    if ($value -gt [int]::MaxValue) { return [int]::MaxValue }
    if ($value -lt [int]::MinValue) { return [int]::MinValue }
    return [int][Math]::Round($value)
}
$queue = New-Object System.Collections.Queue
$queue.Enqueue([pscustomobject]@{element=$root; depth=0; parent=-1})
$items = @()
while ($queue.Count -gt 0 -and $items.Count -lt [int]$request.max_elements) {
    $node = $queue.Dequeue()
    $element = $node.element
    try {
        $current = $element.Current
        $rect = $current.BoundingRectangle
        $patterns = @()
        $patternObject = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$patternObject)) { $patterns += 'invoke' }
        $patternObject = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$patternObject)) { $patterns += 'value' }
        $patternObject = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$patternObject)) { $patterns += 'selection_item' }
        $patternObject = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.ScrollPattern]::Pattern, [ref]$patternObject)) { $patterns += 'scroll' }
        $patternObject = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$patternObject)) { $patterns += 'expand_collapse' }
        $item = [pscustomobject]@{
            index=$items.Count; parent=[int]$node.parent; depth=[int]$node.depth;
            name=[string]$current.Name; automation_id=[string]$current.AutomationId;
            class_name=[string]$current.ClassName;
            control_type=[string]$current.ControlType.ProgrammaticName;
            enabled=[bool]$current.IsEnabled; offscreen=[bool]$current.IsOffscreen;
            patterns=@($patterns);
            x=(SafeInt $rect.X); y=(SafeInt $rect.Y);
            width=(SafeInt $rect.Width); height=(SafeInt $rect.Height)
        }
        $items += $item
        $thisIndex = $items.Count - 1
        if ([int]$node.depth -lt [int]$request.max_depth) {
            $child = $walker.GetFirstChild($element)
            while ($null -ne $child -and ($queue.Count + $items.Count) -lt [int]$request.max_elements) {
                $queue.Enqueue([pscustomobject]@{element=$child; depth=([int]$node.depth + 1); parent=$thisIndex})
                $child = $walker.GetNextSibling($child)
            }
        }
    } catch [System.Windows.Automation.ElementNotAvailableException] {
        throw 'The reviewed UI element disappeared during inspection.'
    }
}
[pscustomobject]@{root_hwnd=[int64]$request.hwnd; elements=@($items); truncated=($queue.Count -gt 0)} |
    ConvertTo-Json -Depth 5 -Compress
'''

_SCHEMA = {
    "type": "object",
    "properties": {
        "app": {"type": "string", "enum": sorted(APPS)},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": MAX_DEPTH},
        "max_elements": {"type": "integer", "minimum": 1, "maximum": MAX_ELEMENTS},
    },
    "required": ["app"],
    "additionalProperties": False,
}


def _validate(arguments):
    if not isinstance(arguments, dict) or not set(arguments) <= {"app", "max_depth", "max_elements"}:
        raise ValueError("Provide only app, max_depth and max_elements.")
    if arguments.get("app") not in APPS:
        raise ValueError("Choose exactly one supported app: notepad or calculator.")
    depth = arguments.get("max_depth", 3)
    count = arguments.get("max_elements", 100)
    if type(depth) is not int or not 0 <= depth <= MAX_DEPTH:
        raise ValueError(f"max_depth must be an integer from 0 to {MAX_DEPTH}.")
    if type(count) is not int or not 1 <= count <= MAX_ELEMENTS:
        raise ValueError(f"max_elements must be an integer from 1 to {MAX_ELEMENTS}.")


def _invoke(request):
    if sys.platform != "win32":
        raise OSError("UI Automation inspection requires Windows.")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        input=json.dumps(request, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=10, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or len(completed.stdout) > 2 * 1024 * 1024:
        raise OSError("Windows UI Automation inspection failed or returned oversized output.")
    try:
        output = json.loads(completed.stdout.lstrip("\ufeff"))
    except (json.JSONDecodeError, TypeError) as error:
        raise OSError("Windows UI Automation returned invalid output.") from error
    if not isinstance(output, dict):
        raise OSError("Windows UI Automation returned invalid output.")
    return output


def _bounded_text(value, field):
    if not isinstance(value, str) or len(value) > 512:
        raise OSError(f"UI Automation returned an invalid {field}.")
    return value


def _normalize(raw, hwnd, max_depth, max_elements):
    if raw.get("root_hwnd") != hwnd or type(raw.get("truncated")) is not bool:
        raise OSError("UI Automation root identity did not match the reviewed window.")
    elements = raw.get("elements")
    if isinstance(elements, dict):
        elements = [elements]
    if not isinstance(elements, list) or not 1 <= len(elements) <= max_elements:
        raise OSError("UI Automation returned an invalid bounded element list.")
    normalized = []
    keys = {"index", "parent", "depth", "name", "automation_id", "class_name", "control_type",
            "enabled", "offscreen", "patterns", "x", "y", "width", "height"}
    for index, item in enumerate(elements):
        if (not isinstance(item, dict) or set(item) != keys
                or type(item["index"]) is not int or item["index"] != index
                or type(item["parent"]) is not int or item["parent"] >= index
                or type(item["depth"]) is not int or not 0 <= item["depth"] <= max_depth
                or type(item["enabled"]) is not bool or type(item["offscreen"]) is not bool
                or not isinstance(item["patterns"], list)
                or not set(item["patterns"]) <= {"invoke", "value", "selection_item", "scroll", "expand_collapse"}
                or any(type(item[key]) is not int for key in ("x", "y", "width", "height"))
                or item["width"] < 0 or item["height"] < 0):
            raise OSError("UI Automation returned a malformed element.")
        normalized.append({**item,
                           "name": _bounded_text(item["name"], "name"),
                           "automation_id": _bounded_text(item["automation_id"], "automation id"),
                           "class_name": _bounded_text(item["class_name"], "class name"),
                           "control_type": _bounded_text(item["control_type"], "control type")})
    if normalized[0]["parent"] != -1 or normalized[0]["depth"] != 0:
        raise OSError("UI Automation root element was malformed.")
    return normalized


def _inspect(arguments, _context):
    desktop = WindowsDesktop()
    windows = desktop.windows(arguments["app"])
    if len(windows) != 1:
        return ToolResult({"error": "Inspection requires exactly one verified matching app window."},
                          Verification.FAIL)
    window = windows[0]
    if not desktop.responsive(window["window_id"]):
        return ToolResult({"error": "The reviewed app window is not responding."}, Verification.FAIL)
    depth = arguments.get("max_depth", 3)
    count = arguments.get("max_elements", 100)
    try:
        raw = _invoke({"hwnd": window["window_id"], "max_depth": depth, "max_elements": count})
        elements = _normalize(raw, window["window_id"], depth, count)
        after = desktop.windows(arguments["app"])
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    if len(after) != 1 or after[0]["window_id"] != window["window_id"] \
            or after[0]["process_id"] != window["process_id"]:
        return ToolResult({"error": "App window identity changed during UI Automation inspection."},
                          Verification.FAIL)
    output = {"app": arguments["app"], "window_id": window["window_id"],
              "process_id": window["process_id"], "elements": elements,
              "count": len(elements), "truncated": raw["truncated"],
              "provenance": "external_untrusted", "read_only": True}
    audit = {**output, "elements": "[REDACTED_UI_TEXT]"}
    return ToolResult(output, Verification.PASS, audit)


def register_uia_tools(registry):
    registry.register(Tool(
        "uia.inspect", "Inspect a bounded UI Automation tree for exactly one verified app window; text is untrusted.",
        Risk.OBSERVATION, _inspect, _validate, required_capability="screen.observe",
        argument_schema=_SCHEMA, prerequisites=("exactly one responsive supported app window",),
        reversibility="not_applicable", success_predicate="same_window_identity_and_bounded_UIA_tree_returned"))
