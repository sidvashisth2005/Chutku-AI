"""WA2 (Chutku 1.2): system tools. No admin first; elevation only through chutku/elevate.py for services.

apps.install / apps.uninstall   winget, --scope user first (winget raises Windows' own prompt for a machine installer)
settings.set                    named Windows settings, read before and after (journaled)
registry.set_user               HKCU\\Software only, typed values (journaled; Policies and Defender keys refused)
services.list / services.set    Get-Service / sc.exe through the elevation broker (security services refused)
startup.list / startup.toggle   HKCU Run entries, switched through StartupApproved like Task Manager (journaled)
system.undo_last                puts the newest journaled change back; an install is undone by uninstalling

Every change records what it replaced in data/system_journal.jsonl (chutku/system_journal.py).
The registry (REG), the command runner (RUN) and the broker (ELEVATE) are module attributes so tests use fakes.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

from chutku import system_journal
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
# name -> (key, value name, {choice: registry value}); power_plan goes through powercfg
SETTINGS = {
    "file_extensions": (ADVANCED, "HideFileExt", {"show": 0, "hide": 1}),
    "hidden_files": (ADVANCED, "Hidden", {"show": 1, "hide": 2}),
    "taskbar_alignment": (ADVANCED, "TaskbarAl", {"left": 0, "center": 1}),
    "transparency": (PERSONALIZE, "EnableTransparency", {"on": 1, "off": 0}),
    "notifications": (r"Software\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled", {"on": 1, "off": 0}),
}
POWER_PLANS = {"balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
               "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
               "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a"}
# shortcut: night light, display scale, Bluetooth/Wi-Fi radios need WinRT or undocumented blobs; the planner uses the
# Settings app (app.settings.* atlas actions) for those until they get a reliable read-back.
SECURITY_SERVICES = frozenset(s.casefold() for s in (
    "WinDefend", "WdNisSvc", "Sense", "SecurityHealthService", "wscsvc", "MpsSvc", "BFE", "EventLog", "CryptSvc",
    "RpcSs", "RpcEptMapper", "DcomLaunch", "Winmgmt", "TrustedInstaller", "SamSs", "LSM", "gpsvc", "wuauserv",
    "Schedule", "ProfSvc", "Power", "PlugPlay", "AppIDSvc", "KeyIso", "VaultSvc"))
_APP = re.compile(r"^[\w][\w .+\-]{0,79}$")
_SERVICE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")
NO_USER_INSTALLER = (-1978335216, 2316632080, -1978335212, 2316632084)   # winget 0x8A150010 (seen on the PC 2026-11-09) / 0x8A150014
ENABLED, DISABLED = bytes([2] + [0] * 11), bytes([3] + [0] * 11)


class _WinReg:
    """HKCU only."""

    def _key(self, path, write=False):
        import winreg
        access = winreg.KEY_READ | (winreg.KEY_SET_VALUE if write else 0)
        if write:
            return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, access)
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, access)

    def get(self, path, name):
        import winreg
        try:
            with self._key(path) as key:
                value, kind = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return {"value": value.hex() if isinstance(value, bytes) else value,
                "type": {winreg.REG_DWORD: "dword", winreg.REG_BINARY: "binary"}.get(kind, "string")}

    def set(self, path, name, value, kind):
        import winreg
        reg_type = {"dword": winreg.REG_DWORD, "binary": winreg.REG_BINARY}.get(kind, winreg.REG_SZ)
        data = bytes.fromhex(value) if kind == "binary" else int(value) if kind == "dword" else str(value)
        with self._key(path, write=True) as key:
            winreg.SetValueEx(key, name, 0, reg_type, data)

    def delete(self, path, name):
        import winreg
        try:
            with self._key(path, write=True) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def names(self, path):
        import winreg
        try:
            with self._key(path) as key:
                out, index = [], 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        return out
                    out.append((name, value))
                    index += 1
        except FileNotFoundError:
            return []


def _run(argv, timeout=600):
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _elevate(argv):
    from chutku import elevate
    return elevate.run(argv)


REG = None
RUN = _run
ELEVATE = _elevate


def _reg():
    global REG
    if REG is None:
        if sys.platform != "win32":
            raise OSError("Windows settings can only be changed on Windows.")
        REG = _WinReg()
    return REG


def _base(context):
    return Path(context.granted_root).parent   # the sandbox lives in Chutku's home


def _fail(text):
    return ToolResult({"error": text}, Verification.FAIL)


# -- apps -------------------------------------------------------------------------------------------------------------

def _app_args(app):
    return ["--id", app, "--exact"] if "." in app and " " not in app else ["--name", app]


def _validate_app(arguments):
    if set(arguments) != {"app"} or not isinstance(arguments["app"], str) or not _APP.match(arguments["app"].strip()):
        raise ValueError("Name one app (letters, numbers, spaces, . + -), e.g. 'VLC' or 'VideoLAN.VLC'.")


def _install(arguments, context):
    app = arguments["app"].strip()
    common = ["--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
    code, out = RUN(["winget", "install", *_app_args(app), "--scope", "user", *common])
    scope = "user"
    if code in NO_USER_INSTALLER:   # a machine-wide installer: winget asks Windows' own prompt itself
        code, out = RUN(["winget", "install", *_app_args(app), *common])
        scope = "machine"
    if code != 0:
        return _fail(f"winget could not install {app}: {out.strip()[-300:] or code}")
    system_journal.record(_base(context), "install", app, None, "installed", scope=scope)
    return ToolResult({"installed": app, "scope": scope, "summary": f"{app} install ho gaya."}, Verification.PASS)


def _uninstall(arguments, context):
    app = arguments["app"].strip()
    code, out = RUN(["winget", "uninstall", *_app_args(app), "--accept-source-agreements", "--disable-interactivity"])
    if code != 0:
        return _fail(f"winget could not uninstall {app}: {out.strip()[-300:] or code}")
    return ToolResult({"uninstalled": app, "summary": f"{app} uninstall ho gaya."}, Verification.PASS)


# -- settings and the registry ------------------------------------------------------------------------------------------

def _power_plan():
    code, out = RUN(["powercfg", "/getactivescheme"], timeout=20)
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out, re.I)
    return match.group(0).lower() if code == 0 and match else None


def _apply_setting(name, raw):
    if name == "power_plan":
        code, out = RUN(["powercfg", "/setactive", raw], timeout=20)
        if code != 0:
            raise OSError(out.strip()[-200:] or "powercfg failed")
        return
    key, value_name, _choices = SETTINGS[name]
    if raw is None:
        _reg().delete(key, value_name)
    else:
        _reg().set(key, value_name, raw, "dword")


def _read_setting(name):
    if name == "power_plan":
        return _power_plan()
    key, value_name, _choices = SETTINGS[name]
    current = _reg().get(key, value_name)
    return None if current is None else current["value"]


def _validate_setting(arguments):
    name, value = arguments.get("name"), arguments.get("value")
    choices = POWER_PLANS if name == "power_plan" else (SETTINGS.get(name) or (None, None, {}))[2]
    if set(arguments) != {"name", "value"} or not choices or value not in choices:
        raise ValueError("Settings I can change: " + "; ".join(
            f"{n} ({'/'.join(c)})" for n, c in [(n, s[2]) for n, s in SETTINGS.items()] + [("power_plan", POWER_PLANS)]))


def _setting(arguments, context):
    name, choice = arguments["name"], arguments["value"]
    raw = POWER_PLANS[choice] if name == "power_plan" else SETTINGS[name][2][choice]
    try:
        before = _read_setting(name)
        _apply_setting(name, raw)
        after = _read_setting(name)
    except OSError as error:
        return _fail(str(error))
    if after != raw:
        return _fail(f"Windows did not keep {name} = {choice}.")
    system_journal.record(_base(context), "setting", name, before, raw)
    return ToolResult({"setting": name, "value": choice, "summary": f"{name.replace('_', ' ')}: {choice}."},
                      Verification.PASS)


def _validate_registry(arguments):
    key, name, kind, value = (arguments.get(k) for k in ("key", "name", "type", "value"))
    if set(arguments) != {"key", "name", "type", "value"} or not isinstance(key, str) or not isinstance(name, str):
        raise ValueError("Give key (HKCU\\Software\\...), name, type (dword or string) and value.")
    path = key.replace("/", "\\")
    if not path.casefold().startswith(("hkcu\\software\\", "hkey_current_user\\software\\")) or ".." in path:
        raise ValueError("Only your own settings under HKCU\\Software can be changed this way.")
    if re.search(r"\\(?:policies|windows defender)(?:\\|$)", path, re.I):
        raise ValueError("Policy and Defender settings are security settings; they are not changed.")
    if not 1 <= len(name) <= 100 or kind not in {"dword", "string"}:
        raise ValueError("The value name is 1-100 characters and the type is dword or string.")
    if kind == "dword" and not (isinstance(value, int) and 0 <= value <= 0xFFFFFFFF):
        raise ValueError("A dword is a whole number from 0 to 4294967295.")
    if kind == "string" and not (isinstance(value, str) and len(value) <= 1000):
        raise ValueError("A string value is up to 1000 characters.")


def _registry(arguments, context):
    path = arguments["key"].replace("/", "\\").split("\\", 1)[1]
    try:
        before = _reg().get(path, arguments["name"])
        _reg().set(path, arguments["name"], arguments["value"], arguments["type"])
        after = _reg().get(path, arguments["name"])
    except OSError as error:
        return _fail(str(error))
    if after is None or after["value"] != arguments["value"]:
        return _fail("Windows did not keep that value.")
    system_journal.record(_base(context), "registry", [path, arguments["name"]], before,
                          {"value": arguments["value"], "type": arguments["type"]})
    return ToolResult({"key": arguments["key"], "name": arguments["name"], "summary": "Setting saved."},
                      Verification.PASS)


# -- startup apps ---------------------------------------------------------------------------------------------------------

def _startup_list(_arguments, _context):
    try:
        approved = dict(_reg().names(APPROVED))
        apps = [{"name": name, "command": str(command)[:200],
                 "enabled": not (isinstance(approved.get(name), bytes) and approved[name][:1] == b"\x03")}
                for name, command in _reg().names(RUN_KEY)]
    except OSError as error:
        return _fail(str(error))
    names = ", ".join(f"{a['name']} ({'on' if a['enabled'] else 'off'})" for a in apps) or "none"
    return ToolResult({"apps": apps, "summary": f"Startup apps: {names}."}, Verification.PASS)


def _validate_startup(arguments):
    if set(arguments) != {"name", "enabled"} or not isinstance(arguments["name"], str) \
            or type(arguments["enabled"]) is not bool or not 1 <= len(arguments["name"]) <= 100:
        raise ValueError("Give the startup app's name and enabled true/false.")


def _startup_toggle(arguments, context):
    name = arguments["name"]
    try:
        listed = {n.casefold(): n for n, _c in _reg().names(RUN_KEY)}
        if name.casefold() not in listed:
            return _fail(f"No startup app called {name}. Say 'startup apps dikhao' for the list.")
        name = listed[name.casefold()]
        before = _reg().get(APPROVED, name)
        _reg().set(APPROVED, name, (ENABLED if arguments["enabled"] else DISABLED).hex(), "binary")
    except OSError as error:
        return _fail(str(error))
    system_journal.record(_base(context), "startup", name, before, "on" if arguments["enabled"] else "off")
    return ToolResult({"name": name, "enabled": arguments["enabled"],
                       "summary": f"{name} {'starts' if arguments['enabled'] else 'no longer starts'} with Windows."},
                      Verification.PASS)


# -- services -------------------------------------------------------------------------------------------------------------

def _services(name=None):
    script = ("Get-Service" + (f" -Name '{name}'" if name else "")
              + " | Select-Object Name,DisplayName,@{n='Status';e={[string]$_.Status}},@{n='StartType';e={[string]$_.StartType}}"
              " | ConvertTo-Json -Compress")
    code, out = RUN(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=60)
    if code != 0:
        raise OSError(out.strip()[-200:] or "Get-Service failed")
    data = json.loads(out or "[]")
    return data if isinstance(data, list) else [data]


def _services_list(_arguments, _context):
    try:
        rows = _services()
    except (OSError, ValueError) as error:
        return _fail(str(error))
    running = [r["Name"] for r in rows if r.get("Status") == "Running"]
    return ToolResult({"services": rows[:400], "summary": f"{len(running)} of {len(rows)} services are running."},
                      Verification.PASS)


def _validate_service(arguments):
    if set(arguments) != {"name", "action"} or not isinstance(arguments["name"], str) \
            or not _SERVICE.match(arguments["name"]) \
            or arguments["action"] not in {"start", "stop", "restart", "automatic", "manual", "disabled"}:
        raise ValueError("Give the service name and an action: start, stop, restart, automatic, manual or disabled.")


def _service(arguments, context):
    name, action = arguments["name"], arguments["action"]
    if name.casefold() in SECURITY_SERVICES:
        return _fail(f"{name} keeps Windows secure or running, so I won't change it.")
    try:
        [before] = _services(name)[:1] or [None]
        if before is None:
            return _fail(f"There is no service called {name}.")
        if action in {"automatic", "manual", "disabled"}:
            argv = ["sc.exe", "config", before["Name"], "start=", {"automatic": "auto", "manual": "demand",
                                                                   "disabled": "disabled"}[action]]
            code, out = ELEVATE(argv)
        else:
            code, out = 0, ""
            for verb in (["stop"] if action == "stop" else ["start"] if action == "start" else ["stop", "start"]):
                code, out = ELEVATE(["sc.exe", verb, before["Name"]])
        [after] = _services(name)[:1] or [None]
    except PermissionError as error:   # the broker refused, or the user said No to Windows' prompt
        return _fail(str(error))
    except (OSError, ValueError) as error:
        return _fail(str(error))
    if code != 0:
        return _fail(f"Windows did not {action} {name}: {out.strip()[-200:] or code}")
    system_journal.record(_base(context), "service", before["Name"], before, after)
    return ToolResult({"service": before["Name"], "action": action, "now": after,
                       "summary": f"{before.get('DisplayName') or name}: {action} done."}, Verification.PASS)


# -- undo -----------------------------------------------------------------------------------------------------------------

def _undo(_arguments, context):
    base = _base(context)
    entry = system_journal.last(base)
    if entry is None:
        return _fail("There is no system change of mine left to undo.")
    kind, target, before = entry["kind"], entry["target"], entry["before"]
    try:
        if kind == "setting":
            _apply_setting(target, before)
        elif kind == "registry":
            path, name = target
            if before is None:
                _reg().delete(path, name)
            else:
                _reg().set(path, name, before["value"], before["type"])
        elif kind == "startup":
            if before is None:
                _reg().delete(APPROVED, target)
            else:
                _reg().set(APPROVED, target, before["value"], "binary")
        elif kind == "service":
            start = {"Automatic": "auto", "Manual": "demand", "Disabled": "disabled"}.get(before.get("StartType"))
            if start:
                ELEVATE(["sc.exe", "config", target, "start=", start])
            ELEVATE(["sc.exe", "start" if before.get("Status") == "Running" else "stop", target])
        elif kind == "install":
            code, out = RUN(["winget", "uninstall", *_app_args(target), "--accept-source-agreements",
                             "--disable-interactivity"])
            if code != 0:
                return _fail(f"Could not uninstall {target}: {out.strip()[-200:]}")
    except (OSError, PermissionError) as error:
        return _fail(str(error))
    system_journal.mark_undone(base, entry)
    return ToolResult({"undone": kind, "target": target, "summary": f"Wapas kar diya: {kind} {target}."},
                      Verification.PASS)


def register_system_tools(registry):
    app_schema = {"type": "object", "properties": {"app": {"type": "string", "minLength": 1, "maxLength": 80}},
                  "required": ["app"], "additionalProperties": False}
    registry.register(Tool("apps.install", "Install an app with winget (per-user first; a machine installer shows "
        "Windows' own prompt). app = name or winget id.", Risk.EXTERNAL_SIDE_EFFECT, _install, _validate_app,
        required_capability="apps.manage", argument_schema=app_schema, network_egress=True,
        reversibility="compensatable", success_predicate="winget_exit_zero"))
    registry.register(Tool("apps.uninstall", "Uninstall an app with winget (always asks).", Risk.EXTERNAL_SIDE_EFFECT,
        _uninstall, _validate_app, required_capability="apps.manage", argument_schema=app_schema,
        reversibility="none", success_predicate="winget_exit_zero"))
    registry.register(Tool("settings.set", "Change a named Windows setting: file_extensions (show/hide), hidden_files "
        "(show/hide), taskbar_alignment (left/center), transparency (on/off), notifications (on/off), power_plan "
        "(balanced/high_performance/power_saver). Undo with system.undo_last.", Risk.REVERSIBLE, _setting,
        _validate_setting, required_capability="settings.modify", argument_schema={"type": "object", "properties": {
            "name": {"type": "string", "enum": sorted([*SETTINGS, "power_plan"])}, "value": {"type": "string"}},
            "required": ["name", "value"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="setting_read_back"))
    registry.register(Tool("registry.set_user", "Set one of your own registry values under HKCU\\Software (dword or "
        "string). Policies and Defender keys are refused. Undo with system.undo_last.", Risk.DATA_MODIFICATION,
        _registry, _validate_registry, required_capability="settings.modify", argument_schema={
            "type": "object", "properties": {"key": {"type": "string", "maxLength": 300},
                                             "name": {"type": "string", "maxLength": 100},
                                             "type": {"type": "string", "enum": ["dword", "string"]},
                                             "value": {"type": ["integer", "string"]}},
            "required": ["key", "name", "type", "value"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="registry_value_read_back"))
    registry.register(Tool("startup.list", "List the apps that start with Windows (yours, HKCU) and whether each is on.",
        Risk.OBSERVATION, _startup_list, required_capability="settings.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="startup_entries_listed"))
    registry.register(Tool("startup.toggle", "Turn one startup app on or off (like Task Manager's Startup tab).",
        Risk.REVERSIBLE, _startup_toggle, _validate_startup, required_capability="settings.modify",
        argument_schema={"type": "object", "properties": {"name": {"type": "string", "maxLength": 100},
                                                          "enabled": {"type": "boolean"}},
                         "required": ["name", "enabled"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="startup_state_written"))
    registry.register(Tool("services.list", "List Windows services, their status and start type.", Risk.OBSERVATION,
        _services_list, required_capability="process.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        reversibility="not_applicable", success_predicate="services_listed"))
    registry.register(Tool("services.set", "Start, stop or restart a service, or set its start type (automatic, "
        "manual, disabled). Needs Windows' administrator prompt; security services are refused.",
        Risk.EXTERNAL_SIDE_EFFECT, _service, _validate_service, required_capability="settings.modify",
        argument_schema={"type": "object", "properties": {"name": {"type": "string", "maxLength": 80},
                                                          "action": {"type": "string", "enum": [
                                                              "start", "stop", "restart", "automatic", "manual",
                                                              "disabled"]}},
                         "required": ["name", "action"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="service_state_read_back"))
    registry.register(Tool("system.undo_last", "Put back the newest system change Chutku made (a setting, registry "
        "value, startup app, service, or uninstall what it installed).", Risk.DATA_MODIFICATION, _undo,
        required_capability="settings.modify", argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="single_use",
        success_predicate="previous_system_state_restored"))
