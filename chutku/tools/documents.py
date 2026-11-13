"""Documents and screen text (Mark's file_processor / screen vision, done locally),
confirmed Python script runs (code_helper 'run'), and folder organising with undo.

Extracted text is untrusted data. Screen text is recognised in memory with the Windows
OCR engine; the image is never saved or sent anywhere.
"""
from __future__ import annotations

import base64
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import zipfile
from xml.etree import ElementTree as ET

from chutku.core.paths import protection_reason, sandbox_target
from chutku.tools.registry import Risk, Tool, ToolResult, Verification

TEXT_CHARS = 8000
MAX_FILE_BYTES = 50 * 1024 * 1024
TEXT_TYPES = {".txt", ".md", ".log", ".json", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".css", ".java", ".c",
              ".cpp", ".h", ".cs", ".go", ".rs", ".ini", ".cfg", ".yaml", ".yml", ".toml", ".bat", ".ps1", ".sql"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}

_OCR_SETUP = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and
  $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); if (-not $t.Wait(30000)) { throw 'OCR timed out' }; $t.Result }
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
function Ocr($r) {
  if ($null -eq $engine) { throw 'No Windows OCR language is installed.' }
  if ($r.mode -eq 'screen') {
    $bmp = New-Object System.Drawing.Bitmap([int]$r.width, [int]$r.height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen([int]$r.left, [int]$r.top, 0, 0, $bmp.Size)
    $g.Dispose()
  } else {
    $bmp = New-Object System.Drawing.Bitmap([string]$r.path)
  }
  $ms = New-Object System.IO.MemoryStream
  $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose(); $ms.Position = 0
  $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($ms)
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $boxes = @($result.Lines | ForEach-Object {
    $rects = @($_.Words | ForEach-Object { $_.BoundingRect })
    @{ text = ([string]$_.Text) -replace '[\x00-\x1F]', ' ';
       x0 = [int](($rects | ForEach-Object { $_.X } | Measure-Object -Minimum).Minimum);
       y0 = [int](($rects | ForEach-Object { $_.Y } | Measure-Object -Minimum).Minimum);
       x1 = [int](($rects | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum);
       y1 = [int](($rects | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum) } })
  @{ language = [string]$engine.RecognizerLanguage.LanguageTag; lines = @($result.Lines | ForEach-Object { ([string]$_.Text) -replace '[\x00-\x1F]', ' ' }); boxes = $boxes }
}
'''

# One-shot: a fresh PowerShell per call (~0.6 s, mostly setup). Used when the worker is unavailable.
_OCR = _OCR_SETUP + r'''
Ocr ([Console]::In.ReadToEnd() | ConvertFrom-Json) | ConvertTo-Json -Compress -Depth 4
'''

# Worker: the same setup once, then one JSON request per stdin line -> one JSON reply line (~0.1 s each).
_OCR_WORKER = _OCR_SETUP + r'''
[Console]::Out.WriteLine('{"ready":true}'); [Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  try { $out = @{ ok = $true; result = (Ocr ($line | ConvertFrom-Json)) } }
  catch { $out = @{ ok = $false; error = [string]$_.Exception.Message } }
  [Console]::Out.WriteLine(($out | ConvertTo-Json -Compress -Depth 5)); [Console]::Out.Flush()
}
'''


class OcrFailed(OSError):
    """OCR itself reported an error (bad image, no language): retrying in a fresh process would not help."""


class _OcrWorker:
    # A long-lived PowerShell that keeps the Windows OCR engine loaded. One request at a time; any
    # timeout, crash or malformed reply kills it, and that call falls back to a one-shot process.

    def __init__(self):
        self.lock = threading.Lock()
        self.process = None

    def _start(self):
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        encoded = base64.b64encode(_OCR_WORKER.encode("utf-16-le")).decode("ascii")
        self.process = subprocess.Popen(
            [str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if self._read_line(20) != '{"ready":true}':
            raise OSError("The OCR worker did not start.")

    def _read_line(self, timeout):
        box = []
        reader = threading.Thread(target=lambda: box.append(self.process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout)
        if not box:
            self.stop()
            raise OSError("The OCR worker timed out.")
        return box[0].strip().lstrip("\ufeff")

    def stop(self):
        process, self.process = self.process, None
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self, request, timeout=45):
        with self.lock:
            try:
                if self.process is None or self.process.poll() is not None:
                    self._start()
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
                reply = json.loads(self._read_line(timeout), strict=False)
            except (OSError, ValueError) as error:
                self.stop()
                raise OSError(f"OCR worker failed: {error}") from error
            if not isinstance(reply, dict) or not reply.get("ok"):
                raise OcrFailed("Windows OCR failed: " + str(reply.get("error") if isinstance(reply, dict) else reply))
            return reply.get("result")


_WORKER = _OcrWorker()


def _run_ocr(request):
    if sys.platform == "win32":
        try:
            return _WORKER.run(request)
        except OcrFailed:
            raise
        except OSError:
            pass  # the worker broke: one fresh attempt below, the old way
    from chutku.tools.everyday import _powershell
    return _powershell(_OCR, request, timeout=45)


def warm_ocr():
    """Start the OCR worker ahead of the first screen read (Chutku startup)."""
    try:
        _WORKER.run({"mode": "screen", "left": 0, "top": 0, "width": 8, "height": 8}, timeout=30)
    except OSError:
        pass


def ocr_lines(request):
    # Windows OCR lines with boxes in image pixels: [{"text", "rect": (x0, y0, x1, y1)}].
    result = _run_ocr(request)
    if not isinstance(result, dict):
        raise OSError("Windows OCR returned no result.")
    boxes = result.get("boxes") or []
    boxes = boxes if isinstance(boxes, list) else [boxes]
    lines = []
    for box in boxes:
        if isinstance(box, dict) and isinstance(box.get("text"), str):
            try:
                lines.append({"text": box["text"], "rect": tuple(int(box[k]) for k in ("x0", "y0", "x1", "y1"))})
            except (KeyError, TypeError, ValueError):
                continue
    return lines


def ocr(request):
    result = _run_ocr(request)
    if not isinstance(result, dict):
        raise OSError("Windows OCR returned no result.")
    lines = result.get("lines") or []
    return "\n".join(lines if isinstance(lines, list) else [lines]), result.get("language")


# -- extraction ---------------------------------------------------------------------

def _xml_text(data, tag_suffix, paragraph_suffix=None):
    root = ET.fromstring(data)
    parts = []
    for element in root.iter():
        if element.tag.endswith(tag_suffix) and element.text:
            parts.append(element.text)
        elif paragraph_suffix and element.tag.endswith(paragraph_suffix):
            parts.append("\n")
    return "".join(parts)


def _part(archive, name):
    """One part of an Office file, refused when it would unpack to more than MAX_FILE_BYTES (a zip bomb)."""
    if archive.getinfo(name).file_size > MAX_FILE_BYTES:
        raise ValueError(f"{name} unpacks to more than {MAX_FILE_BYTES // (1024 * 1024)} MB (possible zip bomb).")
    return archive.read(name)


def _docx(path):
    with zipfile.ZipFile(path) as archive:
        return _xml_text(_part(archive, "word/document.xml"), "}t", "}p")


def _pptx(path):
    with zipfile.ZipFile(path) as archive:
        slides = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n\n".join(f"[Slide {i}]\n" + _xml_text(_part(archive, n), "}t", "}p").strip()
                           for i, n in enumerate(slides, 1))


def _pptx_images(path, limit=10):
    """OCR the pictures of an image-only deck (temporary copies are deleted at once)."""
    import tempfile
    parts = []
    with zipfile.ZipFile(path) as archive:
        media = sorted(n for n in archive.namelist()
                       if n.startswith("ppt/media/") and Path(n).suffix.casefold() in IMAGE_TYPES)[:limit]
        for index, name in enumerate(media, 1):
            with tempfile.TemporaryDirectory() as folder:
                image = Path(folder) / f"slide{Path(name).suffix}"
                image.write_bytes(_part(archive, name))
                text, _language = ocr({"mode": "file", "path": str(image)})
            if text.strip():
                parts.append(f"[Picture {index}]\n{text.strip()}")
    return "\n\n".join(parts)


def _xlsx(path, max_rows=200):
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(_part(archive, "xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in root
                      if si.tag.endswith("}si")]
        sheets = sorted(n for n in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        lines = []
        for sheet in sheets[:3]:
            lines.append(f"[{Path(sheet).stem}]")
            root = ET.fromstring(_part(archive, sheet))
            for row in [r for r in root.iter() if r.tag.endswith("}row")][:max_rows]:
                cells = []
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    value = next((v.text for v in cell if v.tag.endswith("}v")), None)
                    if cell.get("t") == "s" and value is not None and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter() if t.tag.endswith("}t"))
                    cells.append(value or "")
                lines.append(" | ".join(cells))
        return "\n".join(lines)


def _pdf(path, max_pages=40):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [f"[Page {i}]\n" + (page.extract_text() or "").strip() for i, page in enumerate(reader.pages[:max_pages], 1)]
    return "\n\n".join(pages), len(reader.pages)


def extract(path):
    """Return (text, kind, detail) for a supported document or image."""
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        text, pages = _pdf(path)
        if len(text.replace("[Page", "").strip()) < 20:
            return text, "pdf", f"{pages} pages; little embedded text (it may be a scan)"
        return text, "pdf", f"{pages} pages"
    if suffix == ".docx":
        return _docx(path), "word", ""
    if suffix == ".pptx":
        text = _pptx(path)
        if len(re.sub(r"\[Slide \d+\]", "", text).strip()) < 20:
            return _pptx_images(path), "powerpoint (slides are pictures: OCR)", "text recognised from slide images"
        return text, "powerpoint", ""
    if suffix in {".xlsx", ".xlsm"}:
        return _xlsx(path), "excel", "first 3 sheets, 200 rows each"
    if suffix in {".csv", ".tsv"}:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t" if suffix == ".tsv" else ","))
        return "\n".join(" | ".join(row) for row in rows[:300]), "table", f"{len(rows)} rows"
    if suffix in IMAGE_TYPES:
        text, language = ocr({"mode": "file", "path": str(path)})
        return text, "image (OCR)", f"OCR language {language}"
    if suffix in TEXT_TYPES:
        return path.read_text(encoding="utf-8", errors="replace"), "text", ""
    raise ValueError(f"Reading {suffix or 'this'} files is not supported (PDF, Word, PowerPoint, Excel, CSV, text "
                     "and images are).")


def _validate_path(arguments):
    if set(arguments) != {"path"} or not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 1000:
        raise ValueError("Provide only path.")


def _extract_text(arguments, context):
    target = sandbox_target(context.granted_root, arguments["path"])
    if not target.is_file():
        return ToolResult({"error": "That file does not exist."}, Verification.FAIL)
    if target.stat().st_size > MAX_FILE_BYTES:
        return ToolResult({"error": "The file is larger than 50 MB."}, Verification.FAIL)
    try:
        text, kind, detail = extract(target)
    except (ValueError, OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as error:
        return ToolResult({"error": str(error)[:300]}, Verification.FAIL)
    except Exception as error:  # a malformed document must not crash the agent
        return ToolResult({"error": f"The document could not be read ({type(error).__name__})."}, Verification.FAIL)
    text = text.strip()
    output = {"path": str(target), "kind": kind, "detail": detail, "characters": len(text),
              "text": text[:TEXT_CHARS], "truncated": len(text) > TEXT_CHARS, "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS, output | {"text": "[REDACTED]", "path": "[REDACTED]"})


def _read_screen(arguments, _context):
    from chutku.tools.desktop_controls import target_window
    import ctypes
    from ctypes import wintypes as w
    try:
        if arguments.get("target", "window") == "screen":
            user = ctypes.WinDLL("user32")
            rect = {"left": 0, "top": 0, "width": user.GetSystemMetrics(0), "height": user.GetSystemMetrics(1)}
            label = "whole screen"
        else:
            _desktop, info = target_window({k: v for k, v in arguments.items() if k != "target"})
            box = w.RECT()
            ctypes.WinDLL("user32").GetWindowRect(info["window_id"], ctypes.byref(box))
            rect = {"left": box.left, "top": box.top, "width": max(box.right - box.left, 1),
                    "height": max(box.bottom - box.top, 1)}
            label = info["title"][:120]
        text, language = ocr({"mode": "screen", **rect})
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    output = {"source": label, "language": language, "text": text[:TEXT_CHARS], "lines": text.count("\n") + 1,
              "image_saved": False, "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS if text.strip() else Verification.FAIL,
                      output | {"text": "[REDACTED]", "source": "[REDACTED]"})


# -- python scripts -----------------------------------------------------------------

def _validate_run(arguments):
    if set(arguments) - {"path", "args"} or not isinstance(arguments.get("path"), str):
        raise ValueError("Provide path and optional args.")
    args = arguments.get("args", [])
    if not isinstance(args, list) or len(args) > 20 or any(not isinstance(a, str) or len(a) > 300 for a in args):
        raise ValueError("args must be up to 20 strings.")
    if Path(arguments["path"]).is_absolute() and protection_reason(Path(arguments["path"])):
        raise ValueError("Scripts inside system or Chutku folders are not run.")  # refuse before asking to confirm


def _run_python(arguments, context):
    target = sandbox_target(context.granted_root, arguments["path"])
    if not target.is_file() or target.suffix.casefold() != ".py":
        return ToolResult({"error": "Choose an existing .py file."}, Verification.FAIL)
    if protection_reason(target):
        return ToolResult({"error": "Scripts inside system or Chutku folders are not run."}, Verification.FAIL)
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP",
                                                                "USERPROFILE", "HOMEDRIVE", "HOMEPATH"}}
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        done = subprocess.run([sys.executable, "-I", str(target), *arguments.get("args", [])], cwd=str(target.parent),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                              env=env, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return ToolResult({"error": "The script ran longer than 60 seconds and was stopped."}, Verification.FAIL)
    output = {"exit_code": done.returncode, "stdout": done.stdout[-4000:], "stderr": done.stderr[-2000:],
              "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS, output | {"stdout": "[REDACTED]", "stderr": "[REDACTED]"})


MAX_COMMAND = 500
OUTPUT_CHARS = 8000


def _validate_powershell(arguments):
    if set(arguments) != {"command"} or not isinstance(arguments["command"], str):
        raise ValueError("Give one PowerShell command.")
    command = arguments["command"]
    if not command.strip() or len(command) > MAX_COMMAND:
        raise ValueError(f"The command must be 1 to {MAX_COMMAND} characters.")
    if not command.isprintable():   # newlines, tabs, NUL, U+2028...: one visible line is what the owner approves
        raise ValueError("Only one single-line command is allowed.")


def _powershell_command(arguments, _context):
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    # -EncodedCommand runs exactly the approved text (-Command would re-split its quotes); output as UTF-8.
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + arguments["command"]
    try:
        done = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                               base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                              cwd=os.path.expanduser("~"), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return ToolResult({"error": "The command ran longer than 60 seconds and was stopped."}, Verification.FAIL)
    except OSError as error:
        return ToolResult({"error": f"PowerShell could not start: {error}"}, Verification.FAIL)
    output = {"exit_code": done.returncode, "stdout": done.stdout[:OUTPUT_CHARS], "stderr": done.stderr[:OUTPUT_CHARS],
              "truncated": len(done.stdout) > OUTPUT_CHARS or len(done.stderr) > OUTPUT_CHARS,
              "provenance": "external_untrusted"}
    if done.returncode != 0:
        output["error"] = f"PowerShell reported exit code {done.returncode}."
    return ToolResult(output, Verification.PASS if done.returncode == 0 else Verification.FAIL,
                      output | {"stdout": "[REDACTED]", "stderr": "[REDACTED]"})


# -- organise a folder --------------------------------------------------------------

CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".ico", ".tif", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".ppt", ".pptx", ".xls", ".xlsx", ".csv"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi", ".msix", ".appx"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".json", ".ipynb"},
}
MAX_ORGANIZE = 300


def _plan(folder):
    moves = []
    for child in sorted(folder.iterdir()):
        if not child.is_file() or child.is_symlink() or child.name.startswith(".") or child.suffix.casefold() in {".lnk", ".ini", ".url"}:
            continue
        category = next((name for name, types in CATEGORIES.items() if child.suffix.casefold() in types), None)
        if category:
            destination = folder / category / child.name
            if not destination.exists():
                moves.append((child, destination))
    return moves


def _organize(arguments, context):
    folder = sandbox_target(context.granted_root, arguments["path"])
    if not folder.is_dir():
        return ToolResult({"error": "That folder does not exist."}, Verification.FAIL)
    if protection_reason(folder / "x"):
        return ToolResult({"error": "System and Chutku folders are not reorganised."}, Verification.FAIL)
    moves = _plan(folder)
    if len(moves) > MAX_ORGANIZE:
        return ToolResult({"error": f"{len(moves)} files is more than the {MAX_ORGANIZE}-file safety limit."},
                          Verification.FAIL)
    record_id = secrets.token_hex(4)
    done, skipped = [], []
    for source, destination in moves:
        destination.parent.mkdir(exist_ok=True)
        try:
            os.rename(source, destination)  # never replaces: a file that appeared there meanwhile is left alone
        except FileExistsError:
            skipped.append(source.name)
            continue
        done.append({"from": str(source), "to": str(destination), "size": destination.stat().st_size})
    record = _records_dir() / f"organize-{record_id}.json"
    record.write_text(json.dumps({"folder": str(folder), "moves": done,
                                  "at": datetime.now().isoformat(timespec="seconds")}, indent=1), encoding="utf-8")
    ok = all(Path(m["to"]).is_file() and not Path(m["from"]).exists() for m in done)
    summary = {}
    for move in done:
        summary[Path(move["to"]).parent.name] = summary.get(Path(move["to"]).parent.name, 0) + 1
    output = {"folder": str(folder), "moved": len(done), "by_category": summary, "undo_id": record_id,
              "undo_hint": f"files.organize_undo id={record_id}"}
    if skipped:
        output["skipped_because_a_file_appeared"] = skipped[:20]
    return ToolResult(output, Verification.PASS if ok else Verification.FAIL, output | {"folder": "[REDACTED]"})


def _records_dir():
    from chutku.app import PROJECT_ROOT
    path = PROJECT_ROOT / "data" / "organize"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _organize_undo(arguments, _context):
    record = _records_dir() / f"organize-{arguments['id']}.json"
    if not record.is_file():
        return ToolResult({"error": "No organise action has that id."}, Verification.FAIL)
    data = json.loads(record.read_text(encoding="utf-8"))
    restored, conflicts = 0, []
    for move in reversed(data["moves"]):
        source, destination = Path(move["to"]), Path(move["from"])
        if protection_reason(source) or protection_reason(destination):
            conflicts.append(source.name)  # a record never makes Chutku touch a protected area
            continue
        if not source.is_file() or destination.exists() or source.stat().st_size != move["size"]:
            conflicts.append(source.name)  # moved or edited since: leave it where it is
            continue
        try:
            os.rename(source, destination)
        except FileExistsError:
            conflicts.append(source.name)
            continue
        restored += 1
    for category in {Path(m["to"]).parent for m in data["moves"]}:
        try:
            category.rmdir()  # only if now empty
        except OSError:
            pass
    record.unlink()
    output = {"restored": restored, "left_in_place_because_changed": conflicts}
    return ToolResult(output, Verification.PASS if not conflicts else Verification.UNKNOWN)


def _validate_screen(arguments):
    if set(arguments) - {"target"} or arguments.get("target", "window") not in {"window", "screen"}:
        raise ValueError("target must be window or screen.")


def _validate_undo_id(arguments):
    if set(arguments) != {"id"} or not isinstance(arguments["id"], str) or not re.fullmatch(r"[0-9a-f]{8}", arguments["id"]):
        raise ValueError("Give the 8-character undo id.")


def register_document_tools(registry):
    path_schema = {"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}},
                   "required": ["path"], "additionalProperties": False}
    registry.register(Tool("file.extract_text", "Read the text of a PDF, Word, PowerPoint, Excel, CSV, text or image "
        "file (images via local OCR) to summarise it or answer questions about it.",
        Risk.OBSERVATION, _extract_text, _validate_path, resource_access="observe", argument_schema=path_schema,
        reversibility="not_applicable", success_predicate="document_text_extracted"))
    registry.register(Tool("screen.read_text", "Read the text visible in the window the user is using (or the whole "
        "screen with target=screen) using local OCR; nothing is saved.",
        Risk.OBSERVATION, _read_screen,
        _validate_screen,
        required_capability="screen.observe",
        argument_schema={"type": "object", "properties": {"target": {"type": "string", "enum": ["window", "screen"]}},
                         "additionalProperties": False},
        prerequisites=("interactive Windows desktop",), reversibility="not_applicable",
        success_predicate="screen_text_recognised"))
    registry.register(Tool("code.run_python", "Run a .py script from the user's folders (60 s limit) and return its "
        "output. Always needs on-screen confirmation.",
        Risk.EXTERNAL_SIDE_EFFECT, _run_python, _validate_run, resource_access="observe",
        required_capability="process.launch",
        argument_schema={"type": "object", "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000},
            "args": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 300}}},
            "required": ["path"], "additionalProperties": False},
        reversibility="none", success_predicate="script_finished_with_captured_output", runs_code=True))
    registry.register(Tool("system.powershell", "Run ONE single-line Windows PowerShell command (max 500 characters, "
        "60 s limit) and return its output. Always needs on-screen confirmation; use a dedicated tool when one fits.",
        Risk.DESTRUCTIVE_OR_PRIVILEGED, _powershell_command, _validate_powershell,
        required_capability="process.launch",
        argument_schema={"type": "object", "properties": {
            "command": {"type": "string", "minLength": 1, "maxLength": MAX_COMMAND}},
            "required": ["command"], "additionalProperties": False},
        reversibility="none", success_predicate="command_finished_with_exit_code_zero", runs_code=True))
    registry.register(Tool("files.organize", "Tidy a folder (e.g. Desktop or Downloads): move its files into "
        "Images, Documents, Videos, Music, Archives, Installers and Code subfolders. Undo with files.organize_undo.",
        Risk.EXTERNAL_SIDE_EFFECT, _organize, _validate_path, resource_access="modify", argument_schema=path_schema,
        reversibility="compensatable", success_predicate="every_planned_file_moved"))
    registry.register(Tool("files.organize_undo", "Put files back where they were before a files.organize (by undo id).",
        Risk.DATA_MODIFICATION, _organize_undo,
        _validate_undo_id,
        resource_access="modify",
        argument_schema={"type": "object", "properties": {"id": {"type": "string", "pattern": "^[0-9a-f]{8}$"}},
                         "required": ["id"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="files_returned_unless_changed"))
