"""Bounded, separately capability-gated Windows audio and network controls."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


_VOLUME_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
enum EDataFlow { eRender, eCapture, eAll }; enum ERole { eConsole, eMultimedia, eCommunications };
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject {}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int EnumAudioEndpoints(EDataFlow f,int m,out object d); int GetDefaultAudioEndpoint(EDataFlow f,ERole r,out IMMDevice d); }
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid id,int ctx,IntPtr p,[MarshalAs(UnmanagedType.IUnknown)] out object o); }
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
 int RegisterControlChangeNotify(IntPtr p); int UnregisterControlChangeNotify(IntPtr p); int GetChannelCount(out uint c);
 int SetMasterVolumeLevel(float l,Guid g); int SetMasterVolumeLevelScalar(float l,Guid g); int GetMasterVolumeLevel(out float l);
 int GetMasterVolumeLevelScalar(out float l); int SetChannelVolumeLevel(uint c,float l,Guid g); int SetChannelVolumeLevelScalar(uint c,float l,Guid g);
 int GetChannelVolumeLevel(uint c,out float l); int GetChannelVolumeLevelScalar(uint c,out float l); int SetMute([MarshalAs(UnmanagedType.Bool)] bool m,Guid g);
 int GetMute(out bool m); int GetVolumeStepInfo(out uint s,out uint n); int VolumeStepUp(Guid g); int VolumeStepDown(Guid g);
 int QueryHardwareSupport(out uint m); int GetVolumeRange(out float a,out float b,out float c);
}
public static class ChutkuVolume {
 static IAudioEndpointVolume Endpoint(){ var e=(IMMDeviceEnumerator)new MMDeviceEnumeratorComObject(); IMMDevice d; Marshal.ThrowExceptionForHR(e.GetDefaultAudioEndpoint(EDataFlow.eRender,ERole.eMultimedia,out d)); object o; var id=typeof(IAudioEndpointVolume).GUID; Marshal.ThrowExceptionForHR(d.Activate(ref id,23,IntPtr.Zero,out o)); return (IAudioEndpointVolume)o; }
 public static float Get(){ float v; Marshal.ThrowExceptionForHR(Endpoint().GetMasterVolumeLevelScalar(out v)); return v; }
 public static bool Muted(){ bool v; Marshal.ThrowExceptionForHR(Endpoint().GetMute(out v)); return v; }
 public static void Set(float v,bool m){ var e=Endpoint(); Marshal.ThrowExceptionForHR(e.SetMasterVolumeLevelScalar(v,Guid.Empty)); Marshal.ThrowExceptionForHR(e.SetMute(m,Guid.Empty)); }
}
'@
$r=[Console]::In.ReadToEnd()|ConvertFrom-Json
if($r.action -ceq 'set'){ [ChutkuVolume]::Set(([float]$r.level/100.0),[bool]$r.muted); Start-Sleep -Milliseconds 100 }
[pscustomobject]@{level=[int][Math]::Round([ChutkuVolume]::Get()*100); muted=[bool][ChutkuVolume]::Muted()}|ConvertTo-Json -Compress
'''

_NETWORK_SCRIPT = r'''
$ErrorActionPreference='Stop'; [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$items=@(Get-NetAdapter -Physical | Sort-Object InterfaceIndex | Select-Object -First 32 Name,InterfaceDescription,InterfaceIndex,Status,MacAddress,LinkSpeed)
@($items)|ConvertTo-Json -Compress
'''

_NETWORK_CONTROL_SCRIPT = r'''
$ErrorActionPreference='Stop'; [Console]::InputEncoding=New-Object System.Text.UTF8Encoding; [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$r=[Console]::In.ReadToEnd()|ConvertFrom-Json
function ExactAdapter {
  $a=@(Get-NetAdapter -InterfaceIndex ([int]$r.interface_index) -ErrorAction Stop)
  if($a.Count -ne 1 -or $a[0].Name -cne [string]$r.name -or $a[0].InterfaceDescription -cne [string]$r.interface_description){ throw 'Network adapter identity changed.' }
  return $a[0]
}
$a=ExactAdapter
$before=($a.Status -cne 'Disabled')
if($r.action -ceq 'set'){
  if($before -eq [bool]$r.enabled){ throw 'Requested network state is already active.' }
  if([bool]$r.enabled){ Enable-NetAdapter -InterfaceIndex $a.InterfaceIndex -Confirm:$false }else{ Disable-NetAdapter -InterfaceIndex $a.InterfaceIndex -Confirm:$false }
  $deadline=[DateTime]::UtcNow.AddSeconds(8)
  do{ Start-Sleep -Milliseconds 200; $a=ExactAdapter; $now=($a.Status -cne 'Disabled') }while($now -ne [bool]$r.enabled -and [DateTime]::UtcNow -lt $deadline)
}
[pscustomobject]@{name=[string]$a.Name;interface_description=[string]$a.InterfaceDescription;interface_index=[int]$a.InterfaceIndex;enabled=[bool]($a.Status -cne 'Disabled');status=[string]$a.Status}|ConvertTo-Json -Compress
'''

_VOLUME_SCHEMA = {"type": "object", "properties": {
    "level": {"type": "integer", "minimum": 0, "maximum": 100},
    "muted": {"type": "boolean"}}, "required": ["level", "muted"], "additionalProperties": False}
_ADAPTER_SCHEMA = {"type": "object", "properties": {
    "interface_index": {"type": "integer", "minimum": 1},
    "name": {"type": "string", "minLength": 1, "maxLength": 256},
    "interface_description": {"type": "string", "minLength": 1, "maxLength": 512},
    "enabled": {"type": "boolean"}},
    "required": ["interface_index", "name", "interface_description", "enabled"], "additionalProperties": False}


_BLUETOOTH_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); if (-not $t.Wait(6000)) { throw 'timeout' }; $t.Result }
$null = [Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType = WindowsRuntime]
$null = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$radio = @($radios | Where-Object { [string]$_.Kind -eq 'Bluetooth' })[0]
if ($null -eq $radio) { @{ present = $false } | ConvertTo-Json -Compress; exit 0 }
$access = $null
if ($request.action -eq 'set') {
    $state = if ($request.on) { [Windows.Devices.Radios.RadioState]::On } else { [Windows.Devices.Radios.RadioState]::Off }
    $access = [string](Await ($radio.SetStateAsync($state)) ([Windows.Devices.Radios.RadioAccessStatus]))
    Start-Sleep -Milliseconds 700
}
$skip = 'Enumerator|Adapter|Wireless Bluetooth|RFCOMM|Transport|Service|Protocol|AVRCP|Identification|Generic|Radio|Bluetooth Device \('
$devices = @(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -and $_.FriendlyName -notmatch $skip } |
    Select-Object -First 30 | ForEach-Object { @{ name = [string]$_.FriendlyName; connected = ([string]$_.Status -eq 'OK') } })
@{ present = $true; on = ([string]$radio.State -eq 'On'); access = $access; devices = $devices } | ConvertTo-Json -Compress -Depth 4
'''


def _powershell(script, request=None, timeout=10):
    if sys.platform != "win32":
        raise OSError("Windows system controls require Windows.")
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    done = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        input=json.dumps(request or {}, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or len(done.stdout) > 65536:
        raise OSError("The bounded Windows system query failed.")
    try:
        return json.loads(done.stdout.lstrip("\ufeff"))
    except (json.JSONDecodeError, TypeError) as error:
        raise OSError("Windows returned malformed system-control data.") from error


def _volume_call(request):
    """Volume get/set via direct Core Audio calls (~10 ms); the PowerShell script is the fallback (~0.7 s)."""
    from chutku.tools.audio_output import master_volume
    try:
        if request.get("action") == "set":
            return master_volume(level=request["level"], muted=request["muted"])
        return master_volume()
    except (OSError, AttributeError):  # AttributeError: no ctypes.windll off Windows
        return _powershell(_VOLUME_SCRIPT, request)


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("This operation takes no arguments.")


def _validate_volume(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != {"level", "muted"}
            or type(arguments["level"]) is not int or not 0 <= arguments["level"] <= 100
            or type(arguments["muted"]) is not bool):
        raise ValueError("Provide only an integer level from 0 to 100 and a muted boolean.")


def _validate_adapter(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != {"interface_index", "name", "interface_description", "enabled"}
            or type(arguments["interface_index"]) is not int or arguments["interface_index"] < 1
            or not isinstance(arguments["name"], str) or not 1 <= len(arguments["name"]) <= 256
            or not isinstance(arguments["interface_description"], str) or not 1 <= len(arguments["interface_description"]) <= 512
            or type(arguments["enabled"]) is not bool):
        raise ValueError("Provide exact adapter index, name, description and enabled state.")


def _valid_volume(value):
    return (isinstance(value, dict) and set(value) == {"level", "muted"}
            and type(value["level"]) is int and 0 <= value["level"] <= 100
            and type(value["muted"]) is bool)


def _volume_status(_arguments, _context):
    try:
        value = _volume_call({"action": "get"})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    valid = _valid_volume(value)
    return ToolResult(value if valid else {"error": "Invalid volume response."}, Verification.PASS if valid else Verification.FAIL)


def _volume_set(arguments, context):
    try:
        before = _volume_call({"action": "get"})
        if not _valid_volume(before):
            raise OSError("Windows returned an invalid initial volume state.")
        operation = context.journal.begin(context.task_id, "system.volume_set", context.granted_root / ".system-volume", before)
        after = _volume_call({"action": "set", **arguments})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    verified = _valid_volume(after) and after == arguments
    if verified:
        context.journal.complete(operation, after)
    return ToolResult({"before": before, "after": after, "verified": verified, "operation_id": operation},
                      Verification.PASS if verified else Verification.FAIL)


def _volume_restore(_arguments, context):
    record = context.journal.latest_completed("system.volume_set", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed volume change is available to restore."}, Verification.FAIL)
    try:
        actual = _volume_call({"action": "get"})
        if not _valid_volume(actual) or not _valid_volume(record["before"]) or actual != record["after"]:
            return ToolResult({"error": "Volume changed again; refusing to overwrite the newer state."}, Verification.FAIL)
        restored = _volume_call({"action": "set", **record["before"]})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    verified = _valid_volume(restored) and restored == record["before"]
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"restored": verified, "state": restored, "operation_id": record["operation_id"]},
                      Verification.PASS if verified else Verification.FAIL)


def _network_status(_arguments, _context):
    try:
        raw = _powershell(_NETWORK_SCRIPT)
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    allowed = {"Name", "InterfaceDescription", "InterfaceIndex", "Status", "MacAddress", "LinkSpeed"}
    valid = len(items) <= 32 and all(isinstance(x, dict) and set(x) <= allowed and type(x.get("InterfaceIndex")) is int for x in items)
    if not valid:
        return ToolResult({"error": "Invalid network response."}, Verification.FAIL)
    output = {"adapters": items, "count": len(items)}
    audit = {"adapters": [{**x, "MacAddress": "[REDACTED]"} for x in items], "count": len(items)}
    return ToolResult(output, Verification.PASS, audit)


def _valid_adapter(value):
    return (isinstance(value, dict) and set(value) == {"name", "interface_description", "interface_index", "enabled", "status"}
            and type(value["interface_index"]) is int and value["interface_index"] > 0
            and isinstance(value["name"], str) and isinstance(value["interface_description"], str)
            and type(value["enabled"]) is bool and isinstance(value["status"], str))


def _network_set(arguments, context):
    identity = {k: arguments[k] for k in ("interface_index", "name", "interface_description")}
    try:
        before = _powershell(_NETWORK_CONTROL_SCRIPT, {"action": "get", **identity})
        if not _valid_adapter(before) or before["enabled"] == arguments["enabled"]:
            raise OSError("Adapter identity is invalid or the requested state is already active.")
        operation = context.journal.begin(context.task_id, "network.adapter_set", context.granted_root / ".network-adapter", before)
        after = _powershell(_NETWORK_CONTROL_SCRIPT, {"action": "set", **arguments})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    verified = _valid_adapter(after) and after["enabled"] == arguments["enabled"] and all(after[k] == identity[k] for k in identity)
    if verified:
        context.journal.complete(operation, after)
    return ToolResult({"before": before, "after": after, "verified": verified, "operation_id": operation},
                      Verification.PASS if verified else Verification.FAIL)


def _network_restore(_arguments, context):
    record = context.journal.latest_completed("network.adapter_set", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed network change is available to restore."}, Verification.FAIL)
    identity = {k: record["before"][k] for k in ("interface_index", "name", "interface_description")}
    try:
        actual = _powershell(_NETWORK_CONTROL_SCRIPT, {"action": "get", **identity})
        if actual != record["after"]:
            return ToolResult({"error": "Adapter changed again; refusing to overwrite the newer state."}, Verification.FAIL)
        restored = _powershell(_NETWORK_CONTROL_SCRIPT, {"action": "set", **identity, "enabled": record["before"]["enabled"]})
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    verified = _valid_adapter(restored) and restored == record["before"]
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"restored": verified, "state": restored, "operation_id": record["operation_id"]},
                      Verification.PASS if verified else Verification.FAIL)


def _bluetooth(request):
    try:
        value = _powershell(_BLUETOOTH_SCRIPT, request, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error) or "Windows did not answer about Bluetooth."
    if not isinstance(value, dict) or not value.get("present"):
        return None, "This PC has no Bluetooth radio that Windows lets apps control."
    seen, devices = set(), []
    for device in value.get("devices") or []:   # a phone is listed once per Bluetooth profile
        if isinstance(device, dict) and device.get("name") and device["name"] not in seen:
            seen.add(device["name"])
            devices.append({"name": device["name"], "connected": any(d.get("connected") for d in value["devices"]
                                                                     if isinstance(d, dict) and d.get("name") == device["name"])})
    value["devices"] = devices[:30]
    return value, None


def _bluetooth_status(_arguments, _context):
    """Owner's convos 2026-11-10: "show bluetooth devices" and "turn on bluetooth" had no tool and were asked about."""
    value, error = _bluetooth({"action": "get"})
    if error:
        return ToolResult({"error": error}, Verification.FAIL)
    return ToolResult({"on": value["on"], "devices": value["devices"]}, Verification.PASS)


def _validate_bluetooth(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"on"} or type(arguments["on"]) is not bool:
        raise ValueError("Give on: true or false.")


def _bluetooth_set(arguments, _context):
    value, error = _bluetooth({"action": "set", "on": arguments["on"]})
    if error:
        return ToolResult({"error": error}, Verification.FAIL)
    done = value["on"] == arguments["on"]
    output = {"on": value["on"], "devices": value["devices"]}
    if not done:
        output["error"] = (f"Windows did not turn Bluetooth {'on' if arguments['on'] else 'off'} "
                           f"({value.get('access') or 'no answer'}); check the Bluetooth switch in Settings.")
    return ToolResult(output, Verification.PASS if done else Verification.FAIL)


def register_system_control_tools(registry):
    registry.register(Tool("system.bluetooth_status", "Is Bluetooth on, and which Bluetooth devices are paired or "
        "connected.", Risk.OBSERVATION, _bluetooth_status, _validate_none, required_capability="settings.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("Windows Bluetooth radio",),
        reversibility="not_applicable", success_predicate="bluetooth_radio_state_observed"))
    registry.register(Tool("system.bluetooth_set", "Turn Bluetooth on or off, then read the state back.",
        Risk.EXTERNAL_SIDE_EFFECT, _bluetooth_set, _validate_bluetooth, required_capability="settings.modify",
        argument_schema={"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"],
                         "additionalProperties": False}, prerequisites=("Windows Bluetooth radio",),
        reversibility="compensatable", success_predicate="bluetooth_radio_state_read_back"))
    registry.register(Tool("system.volume_status", "Read the default Windows output volume and mute state.",
        Risk.OBSERVATION, _volume_status, _validate_none, required_capability="audio.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("Windows Core Audio",), reversibility="not_applicable",
        success_predicate="bounded_default_endpoint_volume_observed"))
    registry.register(Tool("system.volume_set", "Set exact default Windows output volume and mute state, then read it back.",
        Risk.EXTERNAL_SIDE_EFFECT, _volume_set, _validate_volume, required_capability="audio.modify",
        argument_schema=_VOLUME_SCHEMA, prerequisites=("Windows Core Audio",), reversibility="compensatable",
        success_predicate="exact_volume_and_mute_state_read_back"))
    registry.register(Tool("system.volume_restore", "Restore the last Chutku volume change only if no newer change occurred.",
        Risk.EXTERNAL_SIDE_EFFECT, _volume_restore, _validate_none, required_capability="audio.modify",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("matching completed Chutku volume operation",),
        reversibility="single_use", success_predicate="previous_volume_state_read_back"))
    registry.register(Tool("network.status", "Read at most 32 physical Windows network adapter states.",
        Risk.OBSERVATION, _network_status, _validate_none, required_capability="network.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("Windows NetAdapter",), reversibility="not_applicable",
        success_predicate="bounded_physical_adapter_inventory_observed"))
    registry.register(Tool("network.adapter_set", "Enable or disable one exact physical adapter and verify its exact state. Needs administrator rights, so it usually fails (Chutku never runs elevated).",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _network_set, _validate_adapter, required_capability="network.modify",
        argument_schema=_ADAPTER_SCHEMA, prerequisites=("administrator-approved Windows NetAdapter change",),
        reversibility="compensatable", success_predicate="exact_adapter_identity_and_enabled_state_read_back",
        user_only=True))   # needs administrator rights, which Chutku never has: only the owner can ask for it
    registry.register(Tool("network.adapter_restore", "Restore the last Chutku adapter change if no newer change occurred.",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _network_restore, _validate_none, required_capability="network.modify",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("matching completed Chutku network operation",),
        reversibility="single_use", success_predicate="previous_exact_adapter_state_read_back"))
