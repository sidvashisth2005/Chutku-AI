"""Capability-gated Windows display inventory and verified local PNG capture."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

from chutku.core.paths import sandbox_target
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


MAX_CAPTURE_BYTES = 100 * 1024 * 1024

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$screens = @([System.Windows.Forms.Screen]::AllScreens)
function Inventory {
    $items = @()
    for ($i = 0; $i -lt $screens.Count; $i++) {
        $screen = $screens[$i]
        $items += [pscustomobject]@{
            index=$i; device=[string]$screen.DeviceName; primary=[bool]$screen.Primary;
            x=$screen.Bounds.X; y=$screen.Bounds.Y;
            width=$screen.Bounds.Width; height=$screen.Bounds.Height
        }
    }
    return $items
}
if ($request.action -eq 'inventory') {
    [pscustomobject]@{displays=@(Inventory)} | ConvertTo-Json -Depth 4 -Compress
} elseif ($request.action -eq 'capture') {
    $index = [int]$request.display_index
    if ($index -lt 0 -or $index -ge $screens.Count) { throw 'Display index is unavailable.' }
    $screen = $screens[$index]
    $bitmap = [System.Drawing.Bitmap]::new(
        $screen.Bounds.Width, $screen.Bounds.Height,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $stream = $null
    try {
        $graphics.CopyFromScreen($screen.Bounds.X, $screen.Bounds.Y, 0, 0, $screen.Bounds.Size,
            [System.Drawing.CopyPixelOperation]::SourceCopy)
        $stream = [System.IO.File]::Open([string]$request.path,
            [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None)
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    [pscustomobject]@{display_index=$index; width=$screen.Bounds.Width;
        height=$screen.Bounds.Height; device=[string]$screen.DeviceName} | ConvertTo-Json -Compress
} else {
    throw 'Unsupported screen action.'
}
'''

_CAPTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "display_index": {"type": "integer", "minimum": 0, "maximum": 15},
        "path": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
    "required": ["display_index", "path"],
    "additionalProperties": False,
}


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("Display inventory takes no arguments.")


def _validate_capture(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"display_index", "path"}:
        raise ValueError("Provide only display_index and path.")
    if type(arguments["display_index"]) is not int or not 0 <= arguments["display_index"] <= 15:
        raise ValueError("display_index must be an integer from 0 to 15.")
    if not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 1000:
        raise ValueError("path must contain 1 to 1000 characters.")


def _invoke(request):
    if sys.platform != "win32":
        raise OSError("Screen observation requires Windows.")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
        input=json.dumps(request, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=20, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or len(completed.stdout) > 262144:
        raise OSError("Windows display operation failed or returned oversized output.")
    try:
        result = json.loads(completed.stdout.lstrip("\ufeff"))
    except (json.JSONDecodeError, TypeError) as error:
        raise OSError("Windows display operation returned invalid output.") from error
    if not isinstance(result, dict):
        raise OSError("Windows display operation returned invalid output.")
    return result


def _inventory():
    result = _invoke({"action": "inventory"})
    displays = result.get("displays")
    if isinstance(displays, dict):
        displays = [displays]
    if not isinstance(displays, list) or not 1 <= len(displays) <= 16:
        raise OSError("Windows returned no bounded display inventory.")
    normalized = []
    required = {"index", "device", "primary", "x", "y", "width", "height"}
    for expected_index, display in enumerate(displays):
        if (not isinstance(display, dict) or set(display) != required
                or type(display["index"]) is not int or display["index"] != expected_index
                or not isinstance(display["device"], str) or len(display["device"]) > 260
                or type(display["primary"]) is not bool
                or any(type(display[key]) is not int for key in ("x", "y", "width", "height"))
                or not 1 <= display["width"] <= 32768 or not 1 <= display["height"] <= 32768):
            raise OSError("Windows returned an invalid display inventory.")
        normalized.append(display)
    return normalized


def _png_identity(path: Path):
    size = path.stat().st_size
    if not 24 <= size <= MAX_CAPTURE_BYTES:
        raise ValueError("Captured PNG has an invalid or oversized length.")
    with path.open("rb") as stream:
        header = stream.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError("Captured file is not a PNG with an IHDR header.")
        width, height = struct.unpack(">II", header[16:24])
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"size": size, "sha256": digest, "width": width, "height": height}


def _list_displays(arguments, context):
    displays = _inventory()
    return ToolResult({"displays": displays, "count": len(displays)}, Verification.PASS)


def _capture(arguments, context):
    root = context.granted_root
    target = sandbox_target(root, arguments["path"])
    if target.suffix.casefold() != ".png" or target.exists() or not target.parent.is_dir():
        return ToolResult({"error": "Capture path must be a new .png file with an existing parent."}, Verification.FAIL)
    before_displays = _inventory()
    index = arguments["display_index"]
    if index >= len(before_displays):
        return ToolResult({"error": "Requested display index is unavailable."}, Verification.FAIL)
    fingerprint = before_displays[index]
    before = {"path": target.relative_to(root).as_posix(), "display": fingerprint, "existed": False}
    operation_id = context.journal.begin(context.task_id, "screen.capture", target, before)
    try:
        result = _invoke({"action": "capture", "display_index": index, "path": str(target)})
        identity = _png_identity(target)
        after_displays = _inventory()
        if index >= len(after_displays) or after_displays[index] != fingerprint:
            raise OSError("Display layout changed during capture.")
        if identity["width"] != fingerprint["width"] or identity["height"] != fingerprint["height"]:
            raise OSError("Captured PNG dimensions do not match the reviewed display.")
        if (result.get("width"), result.get("height"), result.get("device")) != (
                fingerprint["width"], fingerprint["height"], fingerprint["device"]):
            raise OSError("Capture adapter result does not match the reviewed display.")
        context.journal.complete(operation_id, identity)
        return ToolResult({"path": before["path"], "operation_id": operation_id, **identity,
                           "pixels_persisted_locally": True, "pixels_sent_to_model": False}, Verification.PASS)
    except (OSError, ValueError) as error:
        if target.is_file():
            try:
                target.unlink()
                context.journal.mark_recovered(operation_id)
            except OSError:
                pass
        return ToolResult({"operation_id": operation_id, "error": str(error)}, Verification.FAIL)


def _undo_capture(arguments, context):
    record = context.journal.latest_completed("screen.capture", context.granted_root)
    if record is None:
        return ToolResult({"error": "No completed screen capture is available to undo."}, Verification.FAIL)
    target = sandbox_target(context.granted_root, record["before"]["path"])
    if not target.is_file() or _png_identity(target) != record["after"]:
        return ToolResult({"error": "Undo conflict: captured PNG changed or disappeared."}, Verification.FAIL)
    target.unlink()
    verified = not target.exists()
    if verified:
        context.journal.mark_undone(record["operation_id"])
    return ToolResult({"operation_id": record["operation_id"], "undone": verified},
                      Verification.PASS if verified else Verification.FAIL)


def register_screen_tools(registry):
    registry.register(Tool("screen.displays", "List exact Windows display device names, bounds and primary identity.",
        Risk.OBSERVATION, _list_displays, _validate_none, required_capability="screen.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, prerequisites=("interactive Windows desktop",),
        reversibility="not_applicable", success_predicate="bounded_display_inventory_returned"))
    registry.register(Tool("screen.capture", "Capture one reviewed display to a new local PNG and verify layout, dimensions and SHA-256.",
        Risk.DATA_MODIFICATION, _capture, _validate_capture, resource_access="modify",
        required_capability="screen.observe", argument_schema=_CAPTURE_SCHEMA,
        prerequisites=("stable display inventory and new PNG path",), reversibility="journaled",
        success_predicate="display_fingerprint_stable_and_PNG_dimensions_hash_verified"))
    registry.register(Tool("screen.undo_last_capture", "Delete the latest unchanged Chutku screen capture.",
        Risk.DATA_MODIFICATION, _undo_capture, _validate_none, resource_access="modify",
        required_capability="screen.observe", argument_schema=EMPTY_ARGUMENT_SCHEMA,
        prerequisites=("unchanged completed screen capture",), reversibility="journaled",
        success_predicate="captured_PNG_no_longer_exists"))
