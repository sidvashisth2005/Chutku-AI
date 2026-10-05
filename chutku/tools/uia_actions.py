"""Exact-target UI Automation actions with action-specific postconditions."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import Risk, Tool, ToolResult, Verification
from chutku.tools.windows_apps import APPS, WindowsDesktop


MAX_VALUE = 4096
_SELECTOR = {
    "type": "object",
    "properties": {
        "automation_id": {"type": "string", "maxLength": 512},
        "name": {"type": "string", "maxLength": 512},
        "control_type": {"type": "string", "pattern": "^ControlType\\.[A-Za-z]+$", "maxLength": 64},
    },
    "required": ["control_type"], "additionalProperties": False,
}
_WINDOW = {"type": "object", "properties": {
    "window_id": {"type": "integer", "minimum": 1},
    "process_id": {"type": "integer", "minimum": 1},
    "executable": {"type": "string", "minLength": 1, "maxLength": 1000},
}, "required": ["window_id", "process_id", "executable"], "additionalProperties": False}
_BASE = {"app": {"type": "string", "enum": sorted(APPS)}, "window": _WINDOW, "selector": _SELECTOR}


def _schema(extra, required):
    return {"type": "object", "properties": _BASE | extra,
            "required": ["selector", *required], "oneOf": [{"required": ["app"]}, {"required": ["window"]}],
            "additionalProperties": False}


_EXPECT_SCHEMA = {
    "type": "object", "properties": {
        "selector": _SELECTOR,
        "property": {"type": "string", "enum": ["exists", "value", "name", "is_selected"]},
        "expected": {"type": ["boolean", "string"], "maxLength": MAX_VALUE},
    }, "required": ["selector", "property", "expected"], "additionalProperties": False,
}
_INVOKE_SCHEMA = _schema({"expect": _EXPECT_SCHEMA}, ["expect"])
_VALUE_SCHEMA = _schema({"value": {"type": "string", "maxLength": MAX_VALUE}}, ["value"])
_SELECT_SCHEMA = _schema({}, [])
_SCROLL_SCHEMA = _schema({"axis": {"type": "string", "enum": ["vertical", "horizontal"]},
                          "direction": {"type": "string", "enum": ["increment", "decrement"]}},
                         ["axis", "direction"])
_TYPE_SCHEMA = _schema({"text": {"type": "string", "maxLength": 1024}}, ["text"])

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ChutkuInput {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
}
'@
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][int64]$r.hwnd)
if ($null -eq $root) { throw 'Could not bind the reviewed window.' }
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
function FindExact($selector) {
  $queue = New-Object System.Collections.Queue; $queue.Enqueue($root); $found=@(); $seen=0
  while ($queue.Count -gt 0 -and $seen -lt 500) {
    $e=$queue.Dequeue(); $seen++
    try {
      $c=$e.Current
      $idOk=([string]::IsNullOrEmpty([string]$selector.automation_id) -or $c.AutomationId -ceq [string]$selector.automation_id)
      $nameOk=([string]::IsNullOrEmpty([string]$selector.name) -or $c.Name -ceq [string]$selector.name)
      if ($idOk -and $nameOk -and $c.ControlType.ProgrammaticName -ceq [string]$selector.control_type) { $found += $e }
      $child=$walker.GetFirstChild($e)
      while ($null -ne $child -and ($queue.Count + $seen) -lt 500) { $queue.Enqueue($child); $child=$walker.GetNextSibling($child) }
    } catch [System.Windows.Automation.ElementNotAvailableException] { throw 'A UI element became stale.' }
  }
  return @($found)
}
function One($selector) { $m=@(FindExact $selector); if ($m.Count -ne 1) { throw "Selector matched $($m.Count) elements, expected exactly one." }; return $m[0] }
function Pattern($e,$p) { $v=$null; if (-not $e.TryGetCurrentPattern($p,[ref]$v)) { throw 'Required UI Automation pattern is unavailable.' }; return $v }
function EscapeKeys([string]$text) {
  $b=New-Object System.Text.StringBuilder
  foreach($ch in $text.ToCharArray()) {
    if ('+^%~()[]{}'.Contains([string]$ch)) { [void]$b.Append('{').Append($ch).Append('}') } else { [void]$b.Append($ch) }
  }; return $b.ToString()
}
function VerifyExpect($expect) {
  $m=@(FindExact $expect.selector)
  if ($expect.property -ceq 'exists') { return (($m.Count -gt 0) -eq [bool]$expect.expected) }
  if ($m.Count -ne 1) { return $false }; $e=$m[0]
  if ($expect.property -ceq 'value') { return ([string](Pattern $e ([System.Windows.Automation.ValuePattern]::Pattern)).Current.Value -ceq [string]$expect.expected) }
  if ($expect.property -ceq 'name') { return ([string]$e.Current.Name -ceq [string]$expect.expected) }
  if ($expect.property -ceq 'is_selected') { return ([bool](Pattern $e ([System.Windows.Automation.SelectionItemPattern]::Pattern)).Current.IsSelected -eq [bool]$expect.expected) }
  return $false
}
$target=One $r.selector; if (-not $target.Current.IsEnabled) { throw 'Target element is disabled.' }
$before=$null; $verified=$false
if ($r.action -ceq 'invoke') {
  if (VerifyExpect $r.expect) { throw 'Invoke postcondition was already true; action effect would be ambiguous.' }
  (Pattern $target ([System.Windows.Automation.InvokePattern]::Pattern)).Invoke(); Start-Sleep -Milliseconds 150
  $verified=VerifyExpect $r.expect
} elseif ($r.action -ceq 'expand') {
  if (VerifyExpect $r.expect) { throw 'Expand postcondition was already true; action effect would be ambiguous.' }
  (Pattern $target ([System.Windows.Automation.ExpandCollapsePattern]::Pattern)).Expand(); Start-Sleep -Milliseconds 150
  $verified=VerifyExpect $r.expect
} elseif ($r.action -ceq 'set_value') {
  (Pattern $target ([System.Windows.Automation.ValuePattern]::Pattern)).SetValue([string]$r.value); Start-Sleep -Milliseconds 100
  $again=One $r.selector; $verified=([string](Pattern $again ([System.Windows.Automation.ValuePattern]::Pattern)).Current.Value -ceq [string]$r.value)
} elseif ($r.action -ceq 'select') {
  (Pattern $target ([System.Windows.Automation.SelectionItemPattern]::Pattern)).Select(); Start-Sleep -Milliseconds 100
  $again=One $r.selector; $verified=[bool](Pattern $again ([System.Windows.Automation.SelectionItemPattern]::Pattern)).Current.IsSelected
} elseif ($r.action -ceq 'scroll') {
  $p=Pattern $target ([System.Windows.Automation.ScrollPattern]::Pattern)
  $before=if ($r.axis -ceq 'vertical') {$p.Current.VerticalScrollPercent} else {$p.Current.HorizontalScrollPercent}
  $amount=if ($r.direction -ceq 'increment') {[System.Windows.Automation.ScrollAmount]::SmallIncrement} else {[System.Windows.Automation.ScrollAmount]::SmallDecrement}
  if ($r.axis -ceq 'vertical') {$p.Scroll([System.Windows.Automation.ScrollAmount]::NoAmount,$amount)} else {$p.Scroll($amount,[System.Windows.Automation.ScrollAmount]::NoAmount)}
  Start-Sleep -Milliseconds 100; $again=Pattern (One $r.selector) ([System.Windows.Automation.ScrollPattern]::Pattern)
  $after=if ($r.axis -ceq 'vertical') {$again.Current.VerticalScrollPercent} else {$again.Current.HorizontalScrollPercent}
  $verified=if ($r.direction -ceq 'increment') {$after -gt $before} else {$after -lt $before}
} elseif ($r.action -ceq 'type_text') {
  if ([ChutkuInput]::GetForegroundWindow().ToInt64() -ne [int64]$r.hwnd) { throw 'Reviewed window lost foreground.' }
  $target.SetFocus(); Start-Sleep -Milliseconds 50
  [System.Windows.Forms.SendKeys]::SendWait('^a'); [System.Windows.Forms.SendKeys]::SendWait((EscapeKeys ([string]$r.text)))
  Start-Sleep -Milliseconds 100
  $verified=([string](Pattern (One $r.selector) ([System.Windows.Automation.ValuePattern]::Pattern)).Current.Value -ceq [string]$r.text)
} elseif ($r.action -ceq 'click') {
  if ([ChutkuInput]::GetForegroundWindow().ToInt64() -ne [int64]$r.hwnd) { throw 'Reviewed window lost foreground.' }
  if (VerifyExpect $r.expect) { throw 'Click postcondition was already true; action effect would be ambiguous.' }
  $box=$target.Current.BoundingRectangle; $outer=$root.Current.BoundingRectangle
  if ($box.IsEmpty -or $box.Width -le 0 -or $box.Height -le 0) { throw 'Target has no clickable bounds.' }
  $x=[int]($box.Left + $box.Width/2); $y=[int]($box.Top + $box.Height/2)
  if ($x -lt $outer.Left -or $x -ge $outer.Right -or $y -lt $outer.Top -or $y -ge $outer.Bottom) { throw 'Target center is outside the reviewed window.' }
  if (-not [ChutkuInput]::SetCursorPos($x,$y)) { throw 'Could not position the pointer.' }
  [ChutkuInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [ChutkuInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 150; $verified=VerifyExpect $r.expect
}
[bool]$verified = $verified -and ([ChutkuInput]::GetForegroundWindow().ToInt64() -eq [int64]$r.hwnd)
[pscustomobject]@{verified=[bool]$verified; action=[string]$r.action; before=$before} | ConvertTo-Json -Compress
'''


def _selector(value):
    if not isinstance(value, dict) or not set(value) <= {"automation_id", "name", "control_type"}:
        raise ValueError("selector accepts only automation_id, name and control_type.")
    if not isinstance(value.get("control_type"), str) or not value["control_type"].startswith("ControlType."):
        raise ValueError("selector requires a ControlType.* control_type.")
    identities = [value.get("automation_id"), value.get("name")]
    if not any(isinstance(item, str) and item for item in identities):
        raise ValueError("selector requires a non-empty automation_id or exact name.")
    if any(item is not None and (not isinstance(item, str) or len(item) > 512) for item in identities):
        raise ValueError("selector identity must be a string of at most 512 characters.")


def _base(arguments, extras):
    if not isinstance(arguments, dict) or set(arguments) not in (
            {"app", "selector", *extras}, {"window", "selector", *extras}):
        raise ValueError("UI action arguments do not match the exact contract.")
    if "app" in arguments and arguments["app"] not in APPS:
        raise ValueError("Choose exactly one supported app: notepad or calculator.")
    if "window" in arguments:
        window = arguments["window"]
        if (not isinstance(window, dict) or set(window) != {"window_id", "process_id", "executable"}
                or type(window["window_id"]) is not int or window["window_id"] < 1
                or type(window["process_id"]) is not int or window["process_id"] < 1
                or not isinstance(window["executable"], str) or not 1 <= len(window["executable"]) <= 1000
                or not Path(window["executable"]).is_absolute()):
            raise ValueError("window requires positive HWND/PID and an absolute executable path.")
    _selector(arguments["selector"])


def _validate_invoke(a):
    _base(a, {"expect"})
    e = a["expect"]
    if not isinstance(e, dict) or set(e) != {"selector", "property", "expected"}:
        raise ValueError("expect requires selector, property and expected.")
    _selector(e["selector"])
    if e["property"] not in {"exists", "value", "name", "is_selected"}:
        raise ValueError("Unsupported invoke postcondition.")
    if e["property"] in {"exists", "is_selected"} and type(e["expected"]) is not bool:
        raise ValueError("Boolean postcondition expected.")
    if e["property"] in {"value", "name"} and (not isinstance(e["expected"], str) or len(e["expected"]) > MAX_VALUE):
        raise ValueError("Value postcondition is invalid.")


def _validate_value(a):
    _base(a, {"value"})
    if not isinstance(a["value"], str) or len(a["value"]) > MAX_VALUE:
        raise ValueError("value must be at most 4096 characters.")


def _validate_select(a): _base(a, set())


def _validate_scroll(a):
    _base(a, {"axis", "direction"})
    if a["axis"] not in {"vertical", "horizontal"} or a["direction"] not in {"increment", "decrement"}:
        raise ValueError("Choose an exact scroll axis and direction.")


def _validate_type(a):
    _base(a, {"text"})
    if not isinstance(a["text"], str) or len(a["text"]) > 1024:
        raise ValueError("text must be at most 1024 characters.")


def _invoke(request):
    if sys.platform != "win32": raise OSError("UI Automation actions require Windows.")
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    done = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        input=json.dumps(request, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=10, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or len(done.stdout) > 65536: raise OSError("Windows UI Automation action failed.")
    try: result = json.loads(done.stdout.lstrip("\ufeff"))
    except (json.JSONDecodeError, TypeError) as error: raise OSError("UI Automation returned invalid action output.") from error
    if not isinstance(result, dict) or type(result.get("verified")) is not bool: raise OSError("UI Automation returned invalid action output.")
    return result


def _perform(action):
    def run(arguments, _context):
        desktop = WindowsDesktop()
        if "app" in arguments:
            windows = desktop.windows(arguments["app"])
            window = windows[0] if len(windows) == 1 else None
            target = {"app": arguments["app"]}
        else:
            identity = arguments["window"]
            window = desktop.exact_window(identity["window_id"], identity["process_id"], identity["executable"])
            target = {"window_id": identity["window_id"], "process_id": identity["process_id"]}
        if window is None or not desktop.responsive(window["window_id"]):
            return ToolResult({"error": "Action requires exactly one responsive matching app window."}, Verification.FAIL)
        if desktop.foreground() != window["window_id"]:
            return ToolResult({"error": "The exact target window must already own foreground focus."}, Verification.FAIL)
        request = {k: v for k, v in arguments.items() if k not in {"app", "window"}} | {
            "action": action, "hwnd": window["window_id"]}
        try: result = _invoke(request)
        except OSError as error: return ToolResult({"error": str(error)}, Verification.FAIL)
        if "app" in arguments:
            after = desktop.windows(arguments["app"])
            stable = len(after) == 1 and after[0]["window_id"] == window["window_id"] and after[0]["process_id"] == window["process_id"]
        else:
            identity = arguments["window"]
            stable = desktop.exact_window(identity["window_id"], identity["process_id"], identity["executable"]) is not None
        passed = result["verified"] and stable and desktop.foreground() == window["window_id"]
        output = {**target, "action": action, "verified": passed, "window_id": window["window_id"]}
        if not passed: output["error"] = "Postcondition, window identity, or foreground ownership was not verified."
        return ToolResult(output, Verification.PASS if passed else Verification.FAIL)
    return run


def register_uia_action_tools(registry):
    common = dict(base_risk=Risk.EXTERNAL_SIDE_EFFECT, required_capability="desktop.input",
                  prerequisites=("one exact responsive foreground app window and unique fresh selector",),
                  reversibility="application_dependent", success_predicate="exact_action_postcondition_and_window_focus_reobserved")
    registry.register(Tool("uia.invoke", "Invoke one exact button or menu element and verify an explicit UI postcondition.",
        execute=_perform("invoke"), validate_arguments=_validate_invoke, argument_schema=_INVOKE_SCHEMA, **common))
    registry.register(Tool("uia.expand", "Expand one exact menu or tree element and verify an explicit UI postcondition.",
        execute=_perform("expand"), validate_arguments=_validate_invoke, argument_schema=_INVOKE_SCHEMA, **common))
    registry.register(Tool("uia.set_value", "Set one exact text/value element and verify exact UIA value read-back.",
        execute=_perform("set_value"), validate_arguments=_validate_value, sensitive_argument_names=frozenset({"value"}), argument_schema=_VALUE_SCHEMA, **common))
    registry.register(Tool("uia.select", "Select one exact UI element and verify SelectionItem state.",
        execute=_perform("select"), validate_arguments=_validate_select, argument_schema=_SELECT_SCHEMA, **common))
    registry.register(Tool("uia.scroll", "Scroll one exact UI element and verify directional percent movement.",
        execute=_perform("scroll"), validate_arguments=_validate_scroll, argument_schema=_SCROLL_SCHEMA, **common))
    registry.register(Tool("input.type_text", "Type bounded text through the keyboard into one exact foreground field and verify exact UIA read-back.",
        execute=_perform("type_text"), validate_arguments=_validate_type, sensitive_argument_names=frozenset({"text"}), argument_schema=_TYPE_SCHEMA, **common))
    registry.register(Tool("input.click", "Click the center of one exact visible foreground UI element and verify an explicit postcondition.",
        execute=_perform("click"), validate_arguments=_validate_invoke, argument_schema=_INVOKE_SCHEMA, **common))
