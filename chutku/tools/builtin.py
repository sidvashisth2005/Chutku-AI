from __future__ import annotations

from datetime import UTC, datetime
import platform
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from chutku.tools.registry import (EMPTY_ARGUMENT_SCHEMA, ExecutionContext, Risk, Tool, ToolRegistry,
                                   ToolResult, Verification)
from chutku.core.paths import sandbox_target, read_bounded_text, atomic_write_text, MAX_TEXT_BYTES


MAX_TEXT_READ_BYTES = 64 * 1024

_PATH_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "maxLength": 1000}},
    "additionalProperties": False,
}
_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 1000},
        "content": {"type": "string", "description": "UTF-8 encoding must not exceed 65536 bytes."},
    },
    "required": ["path", "content"],
    "additionalProperties": False,
}
_OPERATION_ID_SCHEMA = {
    "type": "object",
    "properties": {"operation_id": {"type": "integer", "minimum": 1}},
    "required": ["operation_id"],
    "additionalProperties": False,
}


def parse_nvidia_smi(output: str) -> list[dict[str, str]]:
    gpus: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3 or not all(fields):
            continue
        gpus.append({"name": fields[0], "driver_version": fields[1], "vram_mib": fields[2]})
    return gpus


def parse_windows_audio_devices(output: str) -> list[dict[str, str]]:
    parsed = json.loads(output)
    entries = parsed if isinstance(parsed, list) else [parsed]
    devices: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        status = entry.get("Status")
        if isinstance(name, str) and isinstance(status, str):
            devices.append({"name": name, "status": status})
    return devices


def _get_time(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    now = datetime.now(UTC)
    local = now.astimezone()
    return ToolResult({"utc_time": now.isoformat(), "local_time": local.strftime("%A, %d %B %Y, %I:%M %p"),
                       "timezone": local.tzname()}, Verification.PASS)


def _local_drives():
    """Free/total space of fixed local drives (bounded to 26 letters)."""
    import ctypes
    import string
    drives = []
    kernel = ctypes.WinDLL("kernel32") if sys.platform == "win32" else None
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if kernel is not None and kernel.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        drives.append({"drive": f"{letter}:", "free_gib": round(usage.free / 1024**3, 1),
                       "total_gib": round(usage.total / 1024**3, 1)})
    return drives


def _environment(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    workspace = Path.cwd().resolve()
    disk = shutil.disk_usage(workspace)
    output = {
        "os": platform.platform(),
        "windows_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "workspace": str(workspace),
        "free_disk_gib": round(disk.free / (1024**3), 2),
        "drives": _local_drives(),
    }
    verified = bool(output["os"] and output["python_version"] and disk.free > 0)
    return ToolResult(output, Verification.PASS if verified else Verification.UNKNOWN)


def _gpu_status(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return ToolResult({"error": f"NVIDIA diagnostics unavailable: {type(error).__name__}."}, Verification.FAIL)
    gpus = parse_nvidia_smi(completed.stdout)
    if completed.returncode != 0 or not gpus:
        return ToolResult({"error": "NVIDIA diagnostics returned no parseable GPU data."}, Verification.FAIL)
    return ToolResult({"gpus": gpus, "query_timeout_seconds": 3}, Verification.PASS)


def _audio_devices(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    query = "Get-CimInstance -ClassName Win32_SoundDevice | Select-Object Name,Status | ConvertTo-Json -Compress"
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return ToolResult({"error": f"Windows audio diagnostics unavailable: {type(error).__name__}."}, Verification.FAIL)
    try:
        devices = parse_windows_audio_devices(completed.stdout)
    except json.JSONDecodeError:
        devices = []
    if completed.returncode != 0 or not devices:
        return ToolResult({"error": "Windows audio diagnostics returned no parseable device data."}, Verification.FAIL)
    return ToolResult({"devices": devices, "query_timeout_seconds": 3}, Verification.PASS)


def _audio_input_status(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    try:
        from chutku.voice.audio_probe import local_input_devices

        devices = local_input_devices()
    except ModuleNotFoundError:
        return ToolResult({"error": "Local audio input support is not installed. Use the project .venv environment."}, Verification.FAIL)
    except Exception as error:
        return ToolResult({"error": f"Local audio input probe failed: {type(error).__name__}."}, Verification.FAIL)
    if not devices:
        return ToolResult({"error": "No microphone-capable local audio device was found."}, Verification.FAIL)
    return ToolResult({"input_devices": devices, "recording_started": False}, Verification.PASS)


def _microphone_level_check(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    try:
        import numpy
        import sounddevice
        from chutku.voice.audio_probe import measure_default_input_level

        measurement = measure_default_input_level(sounddevice, numpy)
    except ModuleNotFoundError:
        return ToolResult({"error": "Local microphone probe support is not installed. Use the project .venv environment."}, Verification.FAIL)
    except Exception as error:
        return ToolResult({"error": f"Microphone level check failed: {type(error).__name__}."}, Verification.FAIL)
    measurement["raw_audio_persisted"] = False
    return ToolResult(measurement, Verification.PASS)


def _microphone_activity_check(_: dict[str, Any], __: ExecutionContext) -> ToolResult:
    try:
        import numpy
        import sounddevice
        from chutku.voice.audio_probe import measure_input_activity

        measurement = measure_input_activity(sounddevice, numpy)
    except ModuleNotFoundError:
        return ToolResult({"error": "Local microphone probe support is not installed. Use the project .venv environment."}, Verification.FAIL)
    except Exception as error:
        return ToolResult({"error": f"Microphone activity check failed: {type(error).__name__}."}, Verification.FAIL)
    measurement["raw_audio_persisted"] = False
    return ToolResult(measurement, Verification.PASS)


def _validate_no_arguments(arguments: dict[str, Any]) -> None:
    if arguments:
        raise ValueError("This tool does not accept arguments.")


def _sandbox_target(arguments: dict[str, Any], context: ExecutionContext) -> tuple[Path, Path]:
    sandbox_root = context.granted_root
    target = sandbox_target(sandbox_root, arguments.get("path", "."))
    return sandbox_root, target


def _validate_path_arguments(arguments: dict[str, Any]) -> None:
    allowed = {"path"}
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"Unsupported arguments: {', '.join(sorted(unknown))}")
    if not isinstance(arguments.get("path", "."), str) or len(arguments.get("path", ".")) > 1000:
        raise ValueError("path must be a string of at most 1000 characters.")


def _list_files(arguments: dict[str, Any], __: ExecutionContext) -> ToolResult:
    sandbox_root, target = _sandbox_target(arguments, __)
    if not target.exists() or not target.is_dir():
        return ToolResult({"error": "Requested directory does not exist."}, Verification.FAIL)
    items = sorted(target.iterdir(), key=lambda item: item.name)
    entries = [item.name for item in items]
    # Exact counts so no model has to count (live check 2026-10-05: names alone made the planner say "5 files"
    # for a Desktop with 3 files and 3 folders).
    folders = [item.name for item in items if item.is_dir()]
    files = [item.name for item in items if not item.is_dir()]
    return ToolResult({"path": str(target), "entries": entries, "file_count": len(files), "folder_count": len(folders),
                       "files": files, "folders": folders}, Verification.PASS)


def _read_text(arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
    _sandbox_root, target = _sandbox_target(arguments, context)
    if not target.exists() or not target.is_file():
        return ToolResult({"error": "Requested file does not exist or is not a regular file."}, Verification.FAIL)
    size = target.stat().st_size
    if size > MAX_TEXT_READ_BYTES:
        return ToolResult({"error": f"File exceeds the {MAX_TEXT_READ_BYTES}-byte safe read limit."}, Verification.FAIL)
    try:
        content = read_bounded_text(target)
    except UnicodeDecodeError:
        return ToolResult({"error": "File is not valid UTF-8 text."}, Verification.FAIL)
    return ToolResult(
        {"path": str(target), "content": content, "provenance": "external_untrusted"},
        Verification.PASS,
        {"path": str(target), "content": "[REDACTED]", "bytes_read": size, "provenance": "external_untrusted"},
    )


def _create_directory(arguments: dict[str, Any], __: ExecutionContext) -> ToolResult:
    sandbox_root, target = _sandbox_target(arguments, __)
    if target == sandbox_root:
        return ToolResult({"error": "Creating the sandbox root is not an allowed operation."}, Verification.FAIL)
    if not sandbox_root.exists() or not sandbox_root.is_dir():
        return ToolResult({"error": "Granted sandbox root does not exist."}, Verification.FAIL)
    if target.exists():
        return ToolResult({"error": "Target directory already exists."}, Verification.FAIL)
    try:
        target.mkdir(parents=False)
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    verified = target.exists() and target.is_dir() and target.parent == (sandbox_root / Path(arguments.get("path", ".")).parent).resolve()
    return ToolResult({"path": str(target), "created": True}, Verification.PASS if verified else Verification.UNKNOWN)


def _validate_write_arguments(arguments: dict[str, Any]) -> None:
    allowed = {"path", "content"}
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"Unsupported arguments: {', '.join(sorted(unknown))}")
    if not isinstance(arguments.get("path", "."), str) or len(arguments.get("path", ".")) > 1000:
        raise ValueError("path must be a string of at most 1000 characters.")
    if not isinstance(arguments.get("content"), str):
        raise ValueError("content must be a string.")
    if arguments.get("path", ".") in {"", "."}:
        raise ValueError("path must name a file.")
    if len(arguments["content"].encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"Text exceeds the {MAX_TEXT_BYTES}-byte write limit.")


def _write_text(arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
    sandbox_root, target = _sandbox_target(arguments, context)
    if not sandbox_root.exists() or not sandbox_root.is_dir():
        return ToolResult({"error": "Granted sandbox root does not exist."}, Verification.FAIL)
    if target == sandbox_root or target.exists() and not target.is_file():
        return ToolResult({"error": "Target must be a regular file inside the sandbox."}, Verification.FAIL)
    if not target.parent.exists() or not target.parent.is_dir():
        return ToolResult({"error": "Target parent directory does not exist."}, Verification.FAIL)
    existed = target.exists()
    before = {"existed": existed, "content": read_bounded_text(target) if existed else None,
              "planned_content": arguments["content"]}
    operation_id = context.journal.begin(context.task_id, "filesystem.write_text", target, before)
    try:
        atomic_write_text(target, arguments["content"])
        actual = read_bounded_text(target)
    except OSError as error:
        return ToolResult({"operation_id": operation_id, "error": str(error)}, Verification.FAIL)
    after = {"content": actual}
    if actual == arguments["content"]:
        context.journal.complete(operation_id, after)
    return ToolResult({"path": str(target), "operation_id": operation_id, "bytes_written": len(actual.encode("utf-8"))}, Verification.PASS if actual == arguments["content"] else Verification.UNKNOWN)


def _undo_last_write(arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
    _sandbox_root, requested_root = _sandbox_target(arguments, context)
    record = context.journal.chosen("filesystem.write_text", context.granted_root, arguments.get("operation_id"))
    if record is None:
        return ToolResult({"error": "No completed write operation is available to undo."}, Verification.FAIL)
    target = record["target"].resolve()
    if target != requested_root and requested_root not in target.parents:
        return ToolResult({"error": "The journaled target is outside the granted sandbox root."}, Verification.FAIL)
    target = sandbox_target(context.granted_root, str(record["target"].relative_to(context.granted_root)))
    if not target.is_file() or read_bounded_text(target) != record["after"]["content"]:
        return ToolResult({"error": "Undo conflict: the file changed after Chutku wrote it. Your current file was preserved.",
                           "operation_id": record["operation_id"]}, Verification.FAIL)
    before = record["before"]
    try:
        if before["existed"]:
            atomic_write_text(target, before["content"])
            verified = target.is_file() and read_bounded_text(target) == before["content"]
        else:
            target.unlink()
            verified = not target.exists()
    except OSError as error:
        return ToolResult({"operation_id": record["operation_id"], "error": str(error)}, Verification.FAIL)
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"path": str(target), "operation_id": record["operation_id"], "undone": verified}, Verification.PASS if verified else Verification.UNKNOWN)


def _validate_operation_id(arguments: dict[str, Any]) -> None:
    allowed = {"operation_id"}
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"Unsupported arguments: {', '.join(sorted(unknown))}")
    if not isinstance(arguments.get("operation_id"), int) or arguments["operation_id"] < 1:
        raise ValueError("operation_id must be a positive integer.")


def _list_incomplete_writes(arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
    _sandbox_root, granted_root = _sandbox_target(arguments, context)
    records = []
    for record in context.journal.incomplete("filesystem.write_text"):
        target = record["target"].resolve()
        if target == granted_root or granted_root in target.parents:
            records.append({"operation_id": record["operation_id"], "task_id": record["task_id"], "target": str(target)})
    return ToolResult({"operations": records}, Verification.PASS)


def _recover_incomplete_write(arguments: dict[str, Any], context: ExecutionContext) -> ToolResult:
    _sandbox_root, granted_root = _sandbox_target(arguments, context)
    record = next((item for item in context.journal.incomplete("filesystem.write_text") if item["operation_id"] == arguments["operation_id"]), None)
    if record is None:
        return ToolResult({"error": "No unfinished write operation matches operation_id."}, Verification.FAIL)
    target = record["target"].resolve()
    if target == granted_root or granted_root not in target.parents:
        return ToolResult({"error": "The journaled target is outside the granted sandbox root."}, Verification.FAIL)
    target = sandbox_target(granted_root, str(record["target"].relative_to(granted_root)))
    before = record["before"]
    current = read_bounded_text(target) if target.is_file() else None
    if "planned_content" not in before or current not in (before["content"], before["planned_content"]):
        return ToolResult({"error": "Recovery conflict: no matching recorded state. Current files were preserved; manual review is required."}, Verification.FAIL)
    try:
        if before["existed"]:
            atomic_write_text(target, before["content"])
            verified = target.is_file() and read_bounded_text(target) == before["content"]
        else:
            if target.exists():
                target.unlink()
            verified = not target.exists()
    except OSError as error:
        return ToolResult({"operation_id": record["operation_id"], "error": str(error)}, Verification.FAIL)
    if verified:
        context.journal.mark_recovered(record["operation_id"])
    return ToolResult({"path": str(target), "operation_id": record["operation_id"], "recovered": verified}, Verification.PASS if verified else Verification.UNKNOWN)


def register_builtin_tools(registry: ToolRegistry) -> None:
    from chutku.tools.assistant import register_assistant_tools
    from chutku.tools.windows_apps import register_windows_apps
    from chutku.tools.speech import register_speech
    from chutku.tools.processes import register_process_tools
    from chutku.tools.filesystem_extended import register_extended_filesystem_tools
    from chutku.tools.clipboard import register_clipboard_tools
    from chutku.tools.screen import register_screen_tools
    from chutku.tools.uia import register_uia_tools
    from chutku.tools.uia_actions import register_uia_action_tools
    from chutku.tools.system_controls import register_system_control_tools
    from chutku.tools.windows_settings import register_windows_settings_tools
    from chutku.tools.power_controls import register_power_tools
    from chutku.tools.browser import register_browser_tools
    register_assistant_tools(registry)
    register_windows_apps(registry)
    register_speech(registry)
    register_process_tools(registry)
    register_extended_filesystem_tools(registry)
    register_clipboard_tools(registry)
    register_screen_tools(registry)
    register_uia_tools(registry)
    register_uia_action_tools(registry)
    register_system_control_tools(registry)
    register_windows_settings_tools(registry)
    register_power_tools(registry)
    register_browser_tools(registry)
    from chutku.tools.everyday import register_everyday_tools
    register_everyday_tools(registry)
    from chutku.tools.desktop_controls import register_desktop_controls
    register_desktop_controls(registry)
    from chutku.tools.internet import register_internet_tools
    register_internet_tools(registry)
    from chutku.tools.reminders import register_reminder_tools
    register_reminder_tools(registry)
    from chutku.tools.documents import register_document_tools
    register_document_tools(registry)
    from chutku.tools.apps_extra import register_extra_app_tools
    register_extra_app_tools(registry)
    from chutku.tools.builder import register_builder_tools
    register_builder_tools(registry)
    from chutku.tools.files_plus import register_files_plus_tools
    register_files_plus_tools(registry)
    from chutku.routines import register_routine_tools
    register_routine_tools(registry)
    from chutku.tools.audio_output import register_audio_output_tools
    register_audio_output_tools(registry)
    from chutku.tools.image_vision import register_image_vision_tools
    register_image_vision_tools(registry)
    from chutku.notes import register_note_tools
    register_note_tools(registry)
    from chutku.tools.mind_tools import register_mind_tools
    register_mind_tools(registry)
    from chutku.tools.ledger_tools import register_ledger_tools
    register_ledger_tools(registry)
    from chutku.tools.schedule_tools import register_schedule_tools
    register_schedule_tools(registry)
    from chutku.tools.voice_lock_tools import register_voice_lock_tools
    register_voice_lock_tools(registry)
    from chutku.apps.tools import register_app_tools
    register_app_tools(registry)   # App Mastery atlases: app.<app>.<action>
    from chutku.tools.visible import register_visible_tools
    register_visible_tools(registry)
    from chutku.tools.history_tools import register_history_tools
    register_history_tools(registry)
    from chutku.tools.never_tools import register_never_tools
    register_never_tools(registry)
    from chutku.tools.free_input import register_free_input_tools
    register_free_input_tools(registry)
    from chutku.tools.net_check import register_net_check_tools
    register_net_check_tools(registry)
    from chutku.health import register_health_tools
    register_health_tools(registry)
    from chutku.tools.screen_vision import register_screen_vision
    register_screen_vision(registry)
    from chutku.voice.recognition import register_recognition
    register_recognition(registry)
    registry.register(Tool("system.get_time", "Read the current local date and time (and UTC).", Risk.OBSERVATION, _get_time,
        _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="UTC_timestamp_returned"))
    registry.register(Tool("system.environment", "Read the OS version, Python version and free/total disk space of every local drive.", Risk.OBSERVATION,
        _environment, _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="OS_runtime_and_disk_facts_observed"))
    registry.register(Tool("system.gpu_status", "Read NVIDIA GPU name, driver version, and VRAM using a bounded local query.",
        Risk.OBSERVATION, _gpu_status, _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("nvidia-smi",), reversibility="not_applicable", success_predicate="GPU_inventory_parsed"))
    registry.register(Tool("system.audio_devices", "Read Windows-reported audio device names and status using a bounded local query.",
        Risk.OBSERVATION, _audio_devices, _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("Windows CIM",), reversibility="not_applicable", success_predicate="audio_device_inventory_parsed"))
    registry.register(Tool("voice.audio_input_status", "Inspect local microphone-capable devices without recording audio.",
        Risk.OBSERVATION, _audio_input_status, _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("local audio input library",), reversibility="not_applicable",
        success_predicate="microphone_capable_device_inventory_returned"))
    registry.register(Tool("voice.microphone_level_check", "Run one fixed one-second in-memory microphone level check; raw audio is discarded.",
        Risk.REVERSIBLE, _microphone_level_check, _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("microphone",), reversibility="transient", success_predicate="one_second_level_measurement_completed"))
    registry.register(Tool("voice.microphone_activity_check", "Run one fixed three-second in-memory microphone activity check; raw audio is discarded.",
        Risk.REVERSIBLE, _microphone_activity_check, _validate_no_arguments, argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("microphone",), reversibility="transient", success_predicate="three_second_activity_measurement_completed"))
    registry.register(Tool("filesystem.list", "List files inside the granted sandbox root.", Risk.OBSERVATION, _list_files,
        _validate_path_arguments, resource_access="observe", argument_schema=_PATH_SCHEMA, reversibility="not_applicable",
        success_predicate="bounded_directory_inventory_returned"))
    registry.register(Tool("filesystem.read_text", "Read a bounded UTF-8 text file inside the granted sandbox; content is untrusted.",
        Risk.OBSERVATION, _read_text, _validate_path_arguments, resource_access="observe", argument_schema=_PATH_SCHEMA,
        reversibility="not_applicable", success_predicate="bounded_UTF8_content_returned"))
    registry.register(Tool("filesystem.create_directory", "Create one new directory inside the granted sandbox root.",
        Risk.REVERSIBLE, _create_directory, _validate_path_arguments, resource_access="modify", argument_schema=_PATH_SCHEMA,
        reversibility="compensatable", success_predicate="exact_directory_exists_inside_grant"))
    registry.register(Tool("filesystem.write_text", "Write UTF-8 text to one sandboxed file and journal its prior state.",
        Risk.DATA_MODIFICATION, _write_text, _validate_write_arguments, frozenset({"content"}), resource_access="modify",
        argument_schema=_WRITE_SCHEMA, reversibility="journaled", success_predicate="exact_UTF8_content_reloaded"))
    registry.register(Tool("filesystem.undo_last_write", "Undo the most recent journaled text write inside the sandbox.",
        Risk.DATA_MODIFICATION, _undo_last_write, _validate_path_arguments, resource_access="modify", argument_schema=_PATH_SCHEMA,
        prerequisites=("unchanged completed write",), reversibility="journaled", success_predicate="recorded_pre_write_state_restored"))
    registry.register(Tool("filesystem.list_incomplete_writes", "List unfinished journaled text writes inside the sandbox.",
        Risk.OBSERVATION, _list_incomplete_writes, _validate_path_arguments, resource_access="observe", argument_schema=_PATH_SCHEMA,
        reversibility="not_applicable", success_predicate="bounded_incomplete_operation_inventory_returned"))
    registry.register(Tool("filesystem.recover_incomplete_write", "Roll back one unfinished journaled text write to its recorded pre-write state.",
        Risk.DATA_MODIFICATION, _recover_incomplete_write, _validate_operation_id, resource_access="modify",
        argument_schema=_OPERATION_ID_SCHEMA, prerequisites=("matching unfinished journal record",),
        reversibility="journaled", success_predicate="recorded_pre_write_state_restored"))
