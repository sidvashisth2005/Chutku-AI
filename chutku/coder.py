"""Project coder: asks a language model (Gemini when enabled, else the local model) to write
a whole small project, and to repair it from real error output.

The model answers in a plain file-block format (no JSON escaping of source code):

    PLAN: one line
    KIND: gui | cli | web
    RUN: main.py            (entry file; index.html for web)
    === FILE: main.py ===
    ...source...
    === END FILE ===

Everything returned is untrusted text: paths and sizes are checked before anything is written.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
import queue
import re
import threading

from chutku.core.progress import beat

MAX_FILES = 30
MAX_FILE_CHARS = 200_000
ALLOWED_SUFFIXES = {".py", ".html", ".htm", ".css", ".js", ".json", ".md", ".txt", ".svg", ".csv"}
KINDS = {"gui", "cli", "web"}

CODER_SYSTEM = """You are an expert software engineer. Write a complete, working, polished small project
for the user's request. Rules:
- Desktop apps: Python 3 standard library only (tkinter for the window). No pip packages.
- Browser apps, websites and browser games: plain HTML + CSS + JavaScript files, no build step, no CDN.
- Command-line tools: Python 3 standard library; must run without arguments and without asking for input.
- Put core logic in plain functions. For Python projects also write test_app.py with unittest tests of that logic
  (the tests must not open a window).
- The entry file must start the app when run directly (GUI: mainloop inside if __name__ == "__main__").
- Keep it clean, commented where useful, with a README.md explaining how to run it.
- Simplicity first: the minimum code that fully does what was asked. No extra features, no speculative options,
  no abstractions used only once. If 200 lines could be 50, write the 50. Prefer the standard library or the
  platform over hand-written code. Never cut input validation or error handling that prevents data loss.
Answer ONLY in this exact format, nothing before or after:
PLAN: <one line describing the design>
KIND: <gui|cli|web>
RUN: <entry file, e.g. main.py or index.html>
=== FILE: <relative/path> ===
<full file content>
=== END FILE ===
(repeat the FILE block for every file)"""

FIX_SYSTEM = """You are an expert software engineer fixing a project that failed its checks.
Given the files and the exact error output, return ONLY the files you change, each complete, in this format:
PLAN: <one line: the failing check, what caused it, and the fix>
=== FILE: <relative/path> ===
<full new file content>
=== END FILE ===
Keep the same rules: standard library only for Python, plain HTML/CSS/JS for web, no input() prompts.
Surgical fix: change only what the error points to and leave every other line as it was. The tests define success:
when a test assertion fails, fix the program first (a test edit in that first repair is discarded). Change a test
only if its expected value is really wrong for the request."""

_BLOCK = re.compile(r"^=== FILE: (.+?) ===[ \t]*\r?\n(.*?)^=== END FILE ===[ \t]*$", re.M | re.S)
_HEADER = re.compile(r"^(PLAN|KIND|RUN):[ \t]*(.+?)[ \t]*$", re.M)


class CoderError(ValueError):
    pass


def safe_relative(path):
    text = path.strip().strip("`\"'").replace("\\", "/")
    pure = PureWindowsPath(text)
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if (not parts or pure.drive or pure.root or text.startswith("/") or any(p == ".." for p in parts)
            or any(re.search(r'[<>:"|?*\x00-\x1f]', p) for p in parts) or len(parts) > 4):
        raise CoderError(f"Unsafe file path from the model: {path[:80]!r}")
    if PureWindowsPath(parts[-1]).suffix.casefold() not in ALLOWED_SUFFIXES:
        raise CoderError(f"File type not allowed: {parts[-1][:60]}")
    return "/".join(parts)


def parse_files(text, *, need_headers=True):
    """Return {"plan", "kind", "run", "files": {relpath: content}}; raise CoderError if unusable."""
    body = re.sub(r"^```[a-zA-Z]*[ \t]*$", "", text, flags=re.M) if "=== FILE:" not in text else text
    headers = {k.lower(): v for k, v in _HEADER.findall(body.split("=== FILE:", 1)[0])}
    files = {}
    for raw_path, content in _BLOCK.findall(body):
        path = safe_relative(raw_path)
        content = re.sub(r"\A```[a-zA-Z]*[ \t]*\r?\n", "", content)
        content = re.sub(r"\r?\n```[ \t]*\r?\n?\Z", "\n", content)
        if len(content) > MAX_FILE_CHARS:
            raise CoderError(f"{path} is too large.")
        files[path] = content
    if not files:
        raise CoderError("The model returned no files.")
    if len(files) > MAX_FILES:
        raise CoderError("The model returned too many files.")
    result = {"plan": headers.get("plan", "")[:300], "files": files}
    if need_headers:
        kind = headers.get("kind", "").strip().lower()
        if kind not in KINDS:
            kind = "web" if any(p.endswith((".html", ".htm")) for p in files) and not any(
                p.endswith(".py") for p in files) else ("gui" if any("tkinter" in c for c in files.values()) else "cli")
        run = safe_relative(headers.get("run", "")) if headers.get("run") else None
        if run not in files:
            candidates = ["index.html"] if kind == "web" else ["main.py", "app.py"]
            run = next((c for c in candidates if c in files), None) or next(
                (p for p in files if p.endswith(".html" if kind == "web" else ".py") and not p.startswith("test")), None)
        if run is None:
            raise CoderError("The model did not say which file starts the program.")
        result.update(kind=kind, run=run)
    return result


def _with_beats(call):
    """Run a blocking call on a helper thread, beating progress (and honouring Stop) meanwhile."""
    results = queue.Queue(maxsize=1)

    def work():
        try:
            results.put((True, call()))
        except BaseException as error:  # re-raised on the caller's thread
            results.put((False, error))
    threading.Thread(target=work, daemon=True).start()
    while True:
        beat()
        try:
            ok, value = results.get(timeout=1.0)
        except queue.Empty:
            continue
        if ok:
            return value
        raise value


def _fix_prompt(request, files, errors):
    listing = "\n".join(f"=== FILE: {p} ===\n{c}\n=== END FILE ===" for p, c in files.items())
    return f"Original request: {request}\n\nCurrent files:\n{listing}\n\nFailed checks (real output):\n{errors[:6000]}"


class GeminiCoder:
    name = "gemini"

    def __init__(self, key, generate_best=None):
        from chutku import gemini
        self.key = key
        self._best = generate_best or gemini.generate_best
        self.model = None

    def _ask(self, system, user):
        text, version = _with_beats(lambda: self._best(self.key, "code", system, user,
                                                       max_tokens=32768, timeout=300))
        self.model = version or self.model
        return text

    def write(self, request):
        return parse_files(self._ask(CODER_SYSTEM, "Build this: " + request))

    def fix(self, request, files, errors):
        return parse_files(self._ask(FIX_SYSTEM, _fix_prompt(request, files, errors)), need_headers=False)


class LocalCoder:
    name = "local"

    def __init__(self, service):
        self.service = service
        self.model = "Qwen3-8B (local)" if getattr(service, "variant", None) == "strong" else "Qwen3-4B (local)"

    def _ask(self, system, user, max_tokens=7000):
        text, _meta = self.service.complete_text(
            [{"role": "system", "content": system + " /no_think"}, {"role": "user", "content": user}],
            max_tokens=max_tokens, check=beat, timeout=900)
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S)

    def write(self, request):
        return parse_files(self._ask(CODER_SYSTEM, "Build this: " + request))

    def fix(self, request, files, errors):
        return parse_files(self._ask(FIX_SYSTEM, _fix_prompt(request, files, errors)), need_headers=False)
