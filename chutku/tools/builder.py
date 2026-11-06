"""code.build_project: turn "build me a calculator app" into a real, checked project.

Steps: a coder model (Gemini when the owner enabled it, else the local model) writes the
files -> they are written to a new folder inside the owner's grant -> the folder opens in
VS Code -> real checks run (compile, the project's own unit tests, the app window actually
appearing, a headless browser load for web pages) -> real error output goes back to the
coder for up to 3 repair rounds. Success is reported only when the final checks pass.

Generated code is untrusted: paths are validated, it runs with a stripped environment and
time limits, and the tool is R3 (confirmed on screen before anything is written or run).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from chutku.app import PROJECT_ROOT
from chutku.core.paths import protection_reason, sandbox_target
from chutku.core.progress import beat
from chutku.tools.registry import Risk, Tool, ToolResult, Verification

MAX_REPAIRS = 3
TOTAL_SECONDS = 1500
MARKER = ".chutku_build.json"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_COMPILE = "import sys\nfor f in sys.argv[1:]:\n    compile(open(f, encoding='utf-8').read(), f, 'exec')"


# -- coder selection -----------------------------------------------------------------

def gemini_allowed(base=PROJECT_ROOT):
    """Gemini codes only when the owner granted cloud.gemini and stored a key."""
    from chutku.cloud_planner import api_key
    from chutku.core.capability_grants import CapabilityGrantStore
    try:
        store = CapabilityGrantStore(Path(base) / "data/capability_grants.db")
        try:
            store.get("cloud.gemini")
        finally:
            store.close()
    except (ValueError, OSError):
        return None
    return api_key()


def choose_coder(preference="auto"):
    """Gemini when enabled and online; offline (or without a key) the local 8B, else the everyday 4B."""
    from chutku.coder import GeminiCoder, LocalCoder
    from chutku.online import reachable
    key = gemini_allowed() if preference in ("auto", "gemini") else None
    if key and reachable():
        return GeminiCoder(key), None
    note = None
    if preference == "gemini":
        note = ("Gemini is not reachable right now (offline?); " if key else
                "Gemini is not enabled (store a key and grant cloud.gemini); ") + "used the local model instead."
    from chutku.brain_service import shared_service, strong_service
    return LocalCoder(strong_service() or shared_service()), note


def _ask_with_fallback(coder, note, ask):
    """Use the chosen coder; if Gemini is down (after its own retries), finish with the local model."""
    from chutku.gemini import GeminiUnavailable
    try:
        return ask(coder), coder, note
    except GeminiUnavailable as error:
        if coder.name != "gemini":
            raise
        from chutku.brain_service import shared_service, strong_service
        from chutku.coder import LocalCoder
        local = LocalCoder(strong_service() or shared_service())
        return ask(local), local, f"Gemini was unavailable ({error}); the local model wrote this instead."


# -- helpers -------------------------------------------------------------------------

def python_executables():
    base = Path(getattr(sys, "_base_executable", sys.executable) or sys.executable)
    windowed = base.with_name("pythonw.exe")
    return str(base), str(windowed if windowed.exists() else base)


def _child_env():
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "LOCALAPPDATA", "APPDATA", "TCL_LIBRARY", "TK_LIBRARY"}}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(args, cwd, timeout):
    try:
        done = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=_child_env(), stdin=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, f"{Path(args[-1]).name} ran longer than {timeout} s."
    return done.returncode, (done.stdout[-3000:] + "\n" + done.stderr[-3000:]).strip()


def _free_folder(target):
    if not target.exists() or (target.is_dir() and not any(target.iterdir())):
        return target
    for n in range(2, 100):
        candidate = target.with_name(f"{target.name}-{n}")
        if not candidate.exists():
            return candidate
    raise ValueError("Too many projects with that name; choose another folder name.")


def write_files(folder, files):
    root = folder.resolve()
    for relative, content in files.items():
        path = (folder / relative).resolve()
        if root not in path.parents:
            raise ValueError("A generated file path escaped the project folder.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def is_test_file(path):
    return Path(path).name.startswith("test") and str(path).endswith(".py")


def keep_tests_fixed(files, errors):
    """After a failed test assertion (unittest "FAIL:"), the first repair must fix the program, not rewrite the test
    to pass, so its test-file edits are dropped. The same coder wrote those tests and can be wrong, so later repairs
    may change them; the build output then says so."""
    if not re.search(r"^FAIL: ", errors, re.M):
        return files, []
    dropped = sorted(p for p in files if is_test_file(p))
    return {p: c for p, c in files.items() if p not in dropped}, dropped


def vscode_executable():
    candidates = []
    found = shutil.which("code")
    if found:
        candidates.append(Path(found).resolve().parent.parent / "Code.exe")
    for env, sub in (("LOCALAPPDATA", r"Programs\Microsoft VS Code"), ("ProgramFiles", "Microsoft VS Code")):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / sub / "Code.exe")
    return next((c for c in candidates if c.is_file()), None)


def vscode_env():
    """The user's environment minus variables leaked by a parent VS Code/Electron process
    (ELECTRON_RUN_AS_NODE=1 would make Code.exe run as plain Node and open no window)."""
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(("ELECTRON_", "VSCODE_")) and k.upper() != "NODE_OPTIONS"}


def open_in_vscode(folder, entry):
    """Open the project in VS Code and confirm a VS Code window for it appears."""
    executable = vscode_executable()
    if executable is None:
        return {"opened": False, "reason": "VS Code was not found."}
    from chutku.core.launch import popen_user_app
    popen_user_app([str(executable), "--new-window", str(folder), str(folder / entry)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=vscode_env(), creationflags=_NO_WINDOW)
    try:
        from chutku.tools.everyday import Desktop
        desktop = Desktop()
    except OSError:
        return {"opened": None, "reason": "Launched; no desktop to confirm the window."}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        beat()
        for hwnd in desktop.windows():
            info = desktop.describe(hwnd)
            if (info["executable"] or "").casefold().endswith("code.exe") and folder.name.casefold() in info["title"].casefold():
                return {"opened": True, "title": info["title"][:200]}
        time.sleep(0.5)
    return {"opened": False, "reason": "No VS Code window showing the project appeared within 20 s."}


def _window_for(pid, seconds):
    from chutku.tools.everyday import Desktop
    desktop = Desktop()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        beat()
        for hwnd in desktop.windows():
            info = desktop.describe(hwnd)
            if info["process_id"] == pid:
                return info
        time.sleep(0.3)
    return None


# -- checks --------------------------------------------------------------------------

_EXTERNAL = re.compile(r"""<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)\s*=\s*["']?(?:https?:)?//|"""
                       r"""\bimport\b[^;\n]*?["'](?:https?:)?//|@import\s+(?:url\()?["']?(?:https?:)?//""", re.I)


def production_checklist(folder, spec):
    """X18 (2026-11-06): what "production ready" means here, checked, never just claimed: a README; tests for
    Python projects; web apps that load nothing from a CDN or another site (they must work offline)."""
    problems = []
    if not (folder / "README.md").is_file():
        problems.append("Production checklist: README.md is missing (how to run it, what it does).")
    if spec["kind"] != "web" and not any(is_test_file(p.name) for p in folder.rglob("test*.py")):
        problems.append("Production checklist: there are no tests (write test_app.py with unittest tests).")
    if spec["kind"] == "web":
        for page in sorted(folder.rglob("*")):
            if page.suffix.casefold() in {".html", ".htm", ".js", ".css"} and page.is_file():
                hit = _EXTERNAL.search(page.read_text(encoding="utf-8", errors="replace"))
                if hit:
                    problems.append(f"Production checklist: {page.relative_to(folder)} loads something from another "
                                    f"site ({hit.group(0)[:60]!r}); use only local files so it works offline.")
    return problems


def check_python(folder, spec, launch):
    """Compile, run the project's tests, then start the app. Returns (errors, running_process)."""
    problems = production_checklist(folder, spec)
    if problems:
        return problems, [], None
    python, pythonw = python_executables()
    for cache in list(folder.rglob("__pycache__")):  # never test stale bytecode after a repair
        shutil.rmtree(cache, ignore_errors=True)
    sources = sorted(str(p.relative_to(folder)) for p in folder.rglob("*.py"))
    checks = []
    code, output = _run([python, "-E", "-s", "-B", "-c", _COMPILE, *sources], folder, 60)
    if code != 0:
        return [f"Compile error:\n{output}"], checks, None
    checks.append(f"compiled {len(sources)} Python file(s)")
    tests = [s for s in sources if is_test_file(s)]
    if tests:
        beat("running the project's tests")
        code, output = _run([python, "-E", "-s", "-B", "-m", "unittest", "-v", *[Path(t).with_suffix("").as_posix().replace("/", ".") for t in tests]], folder, 90)
        if code != 0:
            return [f"Unit tests failed:\n{output}"], checks, None
        passed = re.search(r"Ran (\d+) tests?", output)
        checks.append(f"unit tests passed ({passed.group(1) if passed else '?'} tests)")
    if spec["kind"] == "cli":
        code, output = _run([python, "-E", "-s", "-B", spec["run"]], folder, 30)
        if code != 0:
            return [f"Running {spec['run']} failed (exit {code}):\n{output}"], checks, None
        checks.append(f"{spec['run']} ran and exited cleanly; output: {output[-300:]!r}")
        return [], checks, None
    if not launch:
        return [], checks, None
    beat("starting the app")
    log = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    from chutku.core.launch import popen_user_app
    process = popen_user_app([pythonw, "-E", "-s", "-B", spec["run"]], cwd=str(folder), env=_child_env(),
                               stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    try:
        window = _window_for(process.pid, 15)
        if window is not None:
            time.sleep(1.5)  # errors raised while building the UI surface just after the window maps
        if window is None or process.poll() is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            log.seek(0)
            detail = log.read()[-3000:] or "The app exited or showed no window within 15 s."
            return [f"The app did not stay open with a window:\n{detail}"], checks, None
        checks.append(f"app window appeared: {window['title'][:80]!r}")
        return [], checks, process
    finally:
        log.close()


def check_web(folder, spec):
    problems = production_checklist(folder, spec)
    if problems:
        return problems, []
    checks, errors = ["production checklist: README, no CDN"], []
    node = shutil.which("node")
    for script in sorted(folder.rglob("*.js")):
        if node:
            code, output = _run([node, "--check", str(script)], folder, 30)
            if code != 0:
                errors.append(f"JavaScript syntax error in {script.relative_to(folder)}:\n{output}")
    if errors:
        return errors, checks
    if node:
        checks.append("JavaScript syntax checked")
    beat("loading the page in a headless browser")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        checks.append("browser load check skipped (Playwright not installed)")
        return [], checks
    page_errors = []
    try:
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.on("pageerror", lambda error: page_errors.append(f"Uncaught error: {error}"))
                page.on("console", lambda m: page_errors.append(f"Console error: {m.text}") if m.type == "error" else None)
                page.route(re.compile(r"^https?://"), lambda route: route.abort())  # offline, no fetching
                page.goto((folder / spec["run"]).resolve().as_uri(), wait_until="load", timeout=15000)
                page.wait_for_timeout(1500)
                visible = page.evaluate("document.body ? document.body.innerText.trim().length + "
                                        "document.querySelectorAll('canvas,button,input,svg').length : 0")
                title = page.title()
            finally:
                browser.close()
    except Exception as error:  # browser missing etc. -> say so, don't claim a pass
        return [], checks + [f"browser load check could not run ({type(error).__name__})"]
    if page_errors:
        return ["The page reported errors when loaded:\n" + "\n".join(page_errors[:15])], checks
    if not visible:
        return ["The page loaded but shows nothing (empty body)."], checks
    checks.append(f"page loaded without errors: {title[:80]!r}")
    return [], checks


# -- the tool ------------------------------------------------------------------------

def _build(arguments, context):
    started = time.monotonic()
    target = sandbox_target(context.granted_root, arguments["path"])
    if protection_reason(target):
        return ToolResult({"error": f"Projects cannot be created in a protected folder ({protection_reason(target)})."},
                          Verification.FAIL)
    request = arguments["request"].strip()
    coder, note = choose_coder(arguments.get("coder", "auto"))
    beat(f"{coder.name} is writing the project")
    spec, coder, note = _ask_with_fallback(coder, note, lambda c: c.write(request))
    folder = _free_folder(target)
    folder.mkdir(parents=True, exist_ok=True)
    write_files(folder, spec["files"])
    (folder / MARKER).write_text(json.dumps({"request": request, "coder": coder.name, "kind": spec["kind"],
                                             "run": spec["run"]}, indent=1), encoding="utf-8")
    vscode = open_in_vscode(folder, spec["run"])
    history, process, checks, errors, discarded = [], None, [], [], []
    for attempt in range(1, MAX_REPAIRS + 2):
        beat(f"checking attempt {attempt}")
        if spec["kind"] == "web":
            errors, checks = check_web(folder, spec)
        else:
            errors, checks, process = check_python(folder, spec, launch=spec["kind"] == "gui")
        history.append({"attempt": attempt, "passed": not errors, "problem": errors[0][:300] if errors else None})
        if not errors or attempt > MAX_REPAIRS or time.monotonic() - started > TOTAL_SECONDS:
            break
        beat(f"{coder.name} is fixing: {errors[0][:80]}")
        current = {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8", errors="replace")
                   for p in sorted(folder.rglob("*")) if p.is_file() and p.name != MARKER
                   and "__pycache__" not in p.parts and p.stat().st_size <= 200_000}
        error_text = "\n\n".join(errors)
        if discarded:
            error_text += (f"\n\nYour last edit to {', '.join(discarded)} was discarded: fix the program first. "
                           "Change a test only if its expected value is really wrong for the request.")
        repair, coder, note = _ask_with_fallback(coder, note, lambda c: c.fix(request, current, error_text))
        files, dropped = keep_tests_fixed(repair["files"], error_text) if not discarded else (repair["files"], [])
        if dropped:
            history[-1]["discarded_test_edits"] = discarded = dropped
        elif discarded and any(is_test_file(p) for p in files):
            history[-1]["changed_own_tests"] = sorted(p for p in files if is_test_file(p))
        write_files(folder, files)
    if not errors and spec["kind"] == "web":
        os.startfile(str(folder / spec["run"]))  # show it in the default browser
    output = {"folder": str(folder), "request": request, "kind": spec["kind"], "entry_file": spec["run"],
              "design": spec["plan"], "files": sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                                                      if p.is_file() and "__pycache__" not in p.parts),
              "coder": coder.name, "model": getattr(coder, "model", None), "attempts": history,
              "checks": checks, "vscode": vscode, "app_running": process is not None,
              "seconds": round(time.monotonic() - started, 1)}
    if note:
        output["note"] = note
    if errors:
        output["error"] = f"The project still fails its checks after {MAX_REPAIRS} repair rounds: {errors[0][:600]}"
        return ToolResult(output, Verification.FAIL)
    return ToolResult(output, Verification.PASS)


def _validate(arguments):
    if set(arguments) - {"request", "path", "coder"} or not {"request", "path"} <= set(arguments):
        raise ValueError("Give request (what to build) and path (new project folder).")
    if not isinstance(arguments["request"], str) or not 5 <= len(arguments["request"].strip()) <= 2000:
        raise ValueError("Describe what to build in 5 to 2000 characters.")
    if not isinstance(arguments["path"], str) or not 1 <= len(arguments["path"]) <= 300:
        raise ValueError("Give a folder path for the new project.")
    if arguments.get("coder", "auto") not in {"auto", "gemini", "local"}:
        raise ValueError("coder must be auto, gemini or local.")
    if Path(arguments["path"]).is_absolute() and protection_reason(Path(arguments["path"])):
        raise ValueError("Projects cannot be created in system or Chutku folders.")


def register_builder_tools(registry):
    registry.register(Tool("code.build_project", "Build a complete small app/program/website/game from a description: "
        "writes the code into a NEW folder (e.g. D:\\ChutkuProjects\\calculator), opens it in VS Code, runs and tests "
        "it, fixes errors itself, and leaves the working app open. Uses Gemini when enabled, else the local model. "
        "Always confirmed on screen. Takes minutes.",
        Risk.EXTERNAL_SIDE_EFFECT, _build, _validate, resource_access="modify",
        required_capability="process.launch",
        argument_schema={"type": "object", "properties": {
            "request": {"type": "string", "minLength": 5, "maxLength": 2000},
            "path": {"type": "string", "minLength": 1, "maxLength": 300},
            "coder": {"type": "string", "enum": ["auto", "gemini", "local"]}},
            "required": ["request", "path"], "additionalProperties": False},
        prerequisites=("Python 3 (tkinter) for desktop apps", "VS Code to show the code"),
        reversibility="creates_a_new_folder_only_delete_it_to_undo",
        success_predicate="generated_project_passes_compile_tests_and_launch_checks", network_egress=True))
