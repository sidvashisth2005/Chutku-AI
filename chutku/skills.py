"""Self-written skills (master plan X15 + X16): small Python abilities Chutku writes, tests and, once the owner
approves them, offers as tools named ``skill.<name>``.

A skill is a folder ``data/skills/<name>/`` with exactly: ``skill.json`` (manifest), ``SKILL.md`` (for people),
``tool.py`` (``run(args: dict) -> dict``) and ``test_tool.py`` (unittest). New skills are written to
``data/skills/_pending/<name>/`` and are never tools there. ``skill approve <name>`` (typed by the owner, plus a click)
re-runs the tests and only on a pass moves the folder to active and records the SHA-256 of its four files in
``data/skills/approved.json``. An active skill whose files no longer match that hash is not registered.

Every skill run (``skill.<name>``, ``runs_code``) asks for a click in every mode (owner decision D5). It runs in a
child Python (``-I -B``, minimal environment, 60 s, result capped at 8 KB and marked untrusted) with the owner's own
Windows rights: the click is the boundary, not a sandbox.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from chutku.tools.registry import Risk, Tool, ToolResult, Verification, check_schema

NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
RESERVED = frozenset({"list", "create", "approve", "remove"})   # skill.list etc. are Chutku's own tools
FILES = ("skill.json", "SKILL.md", "tool.py", "test_tool.py")
MANIFEST_KEYS = frozenset({"name", "description", "arguments", "network", "writes_files"})
PROPERTY_KEYS = {"string": {"type", "description", "minLength", "maxLength", "enum"},
                 "integer": {"type", "description", "minimum", "maximum", "enum"},
                 "number": {"type", "description", "minimum", "maximum", "enum"},
                 "boolean": {"type", "description"}}
MAX_PROPERTIES = 20
TIMEOUT = 60
MAX_OUTPUT = 8192
MAX_REPAIRS = 3
RUNNER = Path(__file__).with_name("skill_runner.py")
UNTRUSTED = "_untrusted.json"   # W1: written by skill.import from a README; tested only at approve (not hashed)
STATUS = "_tests.json"   # last test result shown by skill.list (not part of the approved files)


def skills_root(base):
    return Path(base) / "data" / "skills"


def pending_root(base):
    return skills_root(base) / "_pending"


# -- manifest -----------------------------------------------------------------------------------------------------

def _check_property(key, prop):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key):
        raise ValueError(f"argument name {key[:40]!r} is not allowed (lowercase letters, digits, underscore).")
    if not isinstance(prop, dict) or prop.get("type") not in PROPERTY_KEYS:
        raise ValueError(f"argument {key}: type must be string, integer, number or boolean.")
    kind = prop["type"]
    if set(prop) - PROPERTY_KEYS[kind]:
        raise ValueError(f"argument {key}: unexpected keys {sorted(set(prop) - PROPERTY_KEYS[kind])}.")
    if not isinstance(prop.get("description", ""), str) or len(prop.get("description", "")) > 200:
        raise ValueError(f"argument {key}: description must be text up to 200 characters.")
    if "enum" in prop:
        values = prop["enum"]
        python = {"string": str, "integer": int, "number": (int, float)}[kind]
        if (not isinstance(values, list) or not 1 <= len(values) <= 50
                or any(type(v) is bool or not isinstance(v, python) or (isinstance(v, str) and len(v) > 200)
                       for v in values)):
            raise ValueError(f"argument {key}: enum must be 1 to 50 {kind} values.")
    if kind == "string":
        for bound in ("minLength", "maxLength"):
            if bound in prop and (type(prop[bound]) is not int or not 0 <= prop[bound] <= 10000):
                raise ValueError(f"argument {key}: {bound} must be 0 to 10000.")
        if "enum" not in prop and "maxLength" not in prop:
            raise ValueError(f"argument {key}: a string needs maxLength (or enum).")
    elif kind in ("integer", "number"):
        for bound in ("minimum", "maximum"):
            if bound in prop and (type(prop[bound]) not in (int, float) or abs(prop[bound]) > 1e15):
                raise ValueError(f"argument {key}: {bound} must be a number.")
        if "enum" not in prop and not {"minimum", "maximum"} <= set(prop):
            raise ValueError(f"argument {key}: a number needs minimum and maximum (or enum).")


def validate_manifest(manifest, folder_name):
    """Raise ValueError unless the manifest is exactly the allowed shape with bounded arguments."""
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        keys = sorted(set(manifest) ^ MANIFEST_KEYS) if isinstance(manifest, dict) else []
        raise ValueError(f"skill.json must have exactly name, description, arguments, network, writes_files "
                         f"(wrong: {keys}).")
    name = manifest["name"]
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in RESERVED:
        raise ValueError(f"skill name {str(name)[:60]!r} is not allowed (3-40 lowercase letters, digits, underscore, "
                         "starting with a letter; not list/create/approve/remove).")
    if name != folder_name:
        raise ValueError(f"skill.json name {name!r} does not match its folder {folder_name!r}.")
    description = manifest["description"]
    if not isinstance(description, str) or not 10 <= len(description.strip()) <= 300:
        raise ValueError("description must say what the skill does and when to use it (10 to 300 characters).")
    for flag in ("network", "writes_files"):
        if type(manifest[flag]) is not bool:
            raise ValueError(f"{flag} must be true or false.")
    schema = manifest["arguments"]
    if not isinstance(schema, dict) or set(schema) - {"type", "properties", "required", "additionalProperties"}:
        raise ValueError("arguments must be a JSON-schema object with only type, properties, required, "
                         "additionalProperties.")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError('arguments needs "type": "object" and "additionalProperties": false.')
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or len(properties) > MAX_PROPERTIES:
        raise ValueError(f"arguments.properties must be an object with at most {MAX_PROPERTIES} entries.")
    for key, prop in properties.items():
        _check_property(key, prop)
    required = schema.get("required", [])
    if not isinstance(required, list) or any(r not in properties for r in required) or len(set(required)) != len(
            required):
        raise ValueError("arguments.required must list argument names from properties.")
    return manifest


def _is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def load(folder):
    """Validate a skill folder and return its manifest; raise ValueError with the reason."""
    folder = Path(folder)
    if not folder.is_dir() or _is_link(folder):
        raise ValueError("not a real folder (links are refused).")
    for name in FILES:
        path = folder / name
        if not path.is_file() or _is_link(path):
            raise ValueError(f"{name} is missing.")
    extra = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*.py")
                   if p.relative_to(folder).as_posix() not in ("tool.py", "test_tool.py"))
    if extra:
        raise ValueError(f"only tool.py and test_tool.py may be Python files (found {', '.join(extra[:5])}).")
    raw = (folder / "skill.json").read_bytes()
    if len(raw) > 20_000:
        raise ValueError("skill.json is too large.")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"skill.json is not valid JSON ({error}).") from None
    return validate_manifest(manifest, folder.name)


def digest(folder):
    """SHA-256 over the four skill files: what the owner approved is exactly what runs."""
    hasher = hashlib.sha256()
    for name in FILES:
        hasher.update(name.encode() + b"\0" + (Path(folder) / name).read_bytes() + b"\0")
    return hasher.hexdigest()


def _approved(base):
    try:
        data = json.loads((skills_root(base) / "approved.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_approved(base, data):
    path = skills_root(base) / "approved.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


# -- running ------------------------------------------------------------------------------------------------------

def _python():
    from chutku.tools.builder import python_executables
    return python_executables()[0]


def _env():
    from chutku.tools.builder import _child_env
    return _child_env()


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_tests(folder):
    """Run the skill's own unittest file in a child Python; return (passed, output). Zero tests is a fail."""
    folder = Path(folder)
    # -I ignores the environment and keeps the current folder off sys.path; discover puts the skill folder on it.
    args = [_python(), "-I", "-B", "-X", "utf8", "-m", "unittest", "discover", "-v", "-s", ".", "-p", "test_tool.py"]
    try:
        done = subprocess.run(args, cwd=str(folder), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT, env=_env(), stdin=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, f"The tests ran longer than {TIMEOUT} s and were stopped."
    except OSError as error:
        return False, f"The tests could not start: {error}"
    output = (done.stdout[-3000:] + "\n" + done.stderr[-3000:]).strip()
    ran = re.search(r"^Ran (\d+) tests?", done.stderr, re.M)
    if done.returncode == 0 and (ran is None or int(ran.group(1)) == 0):
        return False, "test_tool.py ran no tests.\n" + output
    return done.returncode == 0, output


def _write_status(folder, passed, output):
    try:
        (Path(folder) / STATUS).write_text(json.dumps({
            "passed": passed, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": (re.findall(r"^(?:Ran \d+ tests?.*|OK.*|FAILED.*)$", output, re.M) or [output[:200]])[-1]}),
            encoding="utf-8")
    except OSError:
        pass


def run_skill(folder, arguments, approved_digest):
    """Run an approved skill in a child Python with the arguments on stdin; its JSON object is the result."""
    folder = Path(folder)
    try:
        if digest(folder) != approved_digest:
            return ToolResult({"error": "The skill's files changed since you approved them; it was not run. "
                                        "Remove it and make it again."}, Verification.FAIL)
    except OSError as error:
        return ToolResult({"error": f"The skill's files could not be read: {error}"}, Verification.FAIL)
    try:
        done = subprocess.run([_python(), "-I", "-B", "-X", "utf8", str(RUNNER), str(folder)], cwd=str(folder),
                              input=json.dumps(arguments), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT, env=_env(), creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return ToolResult({"error": f"The skill ran longer than {TIMEOUT} s and was stopped."}, Verification.FAIL)
    except OSError as error:
        return ToolResult({"error": f"The skill could not start: {error}"}, Verification.FAIL)
    stderr = done.stderr[-2000:]
    failed = None
    if done.returncode != 0:
        failed = f"The skill failed (exit {done.returncode}): {stderr[-600:].strip() or 'no error text'}"
    elif len(done.stdout.encode("utf-8")) > MAX_OUTPUT:
        failed = f"The skill's result is larger than {MAX_OUTPUT // 1024} KB."
    else:
        try:
            result = json.loads(done.stdout)
        except ValueError:
            result, failed = None, f"The skill did not return JSON: {done.stdout[:200]!r}"
        if failed is None and not isinstance(result, dict):
            failed = f"The skill returned {type(result).__name__}, not a JSON object."
    if failed:
        output = {"skill": folder.name, "error": failed, "provenance": "external_untrusted"}
        return ToolResult(output, Verification.FAIL, output | {"error": failed[:200]})
    output = {"skill": folder.name, "result": result, "stderr": stderr, "provenance": "external_untrusted"}
    return ToolResult(output, Verification.PASS, output | {"result": "[REDACTED]", "stderr": "[REDACTED]"})


def _skill_tool(folder, manifest, approved_digest):
    declares = [text for flag, text in (("network", "uses the internet"), ("writes_files", "writes files"))
                if manifest[flag]]
    description = (manifest["description"].strip() + " (self-written skill; always asks before it runs"
                   + (f"; it {' and '.join(declares)}" if declares else "") + ")")
    schema = manifest["arguments"]
    return Tool(f"skill.{manifest['name']}", description, Risk.EXTERNAL_SIDE_EFFECT,
                lambda arguments, _context: run_skill(folder, arguments, approved_digest),
                lambda arguments: check_schema(arguments, schema), required_capability="process.launch",
                argument_schema=schema, prerequisites=(f"approved skill files sha256:{approved_digest}",),
                reversibility="none", success_predicate="skill_returned_a_json_object",
                network_egress=manifest["network"], runs_code=True)


def active_skills(base):
    """(tools, skipped): a Tool for every valid, approved, unchanged active skill; reasons for the rest."""
    root, approved = skills_root(base), _approved(base)
    tools, skipped = [], []
    if not root.is_dir():
        return tools, skipped
    for folder in sorted(root.iterdir()):
        if folder.name.startswith("_") or not folder.is_dir():
            continue   # _pending holds unapproved skills: never tools
        try:
            manifest = load(folder)
            recorded = (approved.get(folder.name) or {}).get("sha256")
            if recorded is None:
                raise ValueError("it was never approved (skill approve).")
            if digest(folder) != recorded:
                raise ValueError("its files changed after approval.")
            tools.append(_skill_tool(folder, manifest, recorded))
        except (OSError, ValueError) as error:
            skipped.append({"name": folder.name[:60], "reason": str(error)[:300]})
    return tools, skipped


def _log_skipped(skipped):
    if skipped:
        from chutku.core.log import get_logger
        for item in skipped:
            get_logger("skills").warning("skill %s not registered: %s", item["name"], item["reason"])


# -- tools ----------------------------------------------------------------------------------------------------------

def _status(folder):
    try:
        data = json.loads((folder / STATUS).read_text(encoding="utf-8"))
        return ("passed" if data.get("passed") is True else "failed") + f" ({str(data.get('summary', ''))[:80]})"
    except (OSError, ValueError):
        return "not run"


def _entries(root):
    rows = []
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if folder.name.startswith("_") or not folder.is_dir():
                continue
            try:
                description = load(folder)["description"]
            except (OSError, ValueError) as error:
                description = f"(invalid: {str(error)[:120]})"
            rows.append({"name": folder.name[:60], "description": description, "tests": _status(folder)})
    return rows


def _named(arguments):
    if set(arguments) != {"name"} or not isinstance(arguments["name"], str) or not NAME.fullmatch(arguments["name"]):
        raise ValueError("Give the skill's name (3-40 lowercase letters, digits, underscore).")


def _validate_none(arguments):
    if arguments:
        raise ValueError("This takes no arguments.")


def _validate_create(arguments):
    if set(arguments) - {"request", "name"} or not isinstance(arguments.get("request"), str) \
            or not 5 <= len(arguments["request"].strip()) <= 2000:
        raise ValueError("Say what the new skill should do (5 to 2000 characters).")
    if "name" in arguments:
        _named({"name": arguments["name"]})
        if arguments["name"] in RESERVED:
            raise ValueError("That name is taken by Chutku's own skill tools.")


_NAME_SCHEMA = {"type": "object", "properties": {"name": {"type": "string", "pattern": NAME.pattern}},
                "required": ["name"], "additionalProperties": False}


def _slug(request):
    words = [w for w in re.findall(r"[a-z0-9]+", request.casefold())
             if w not in {"a", "an", "the", "that", "which", "to", "for", "me", "my", "and", "of", "skill", "make"}]
    name = "_".join(words[:3])[:40].strip("_")
    return name if NAME.fullmatch(name) and name not in RESERVED else "new_skill"


def _repair_note():
    return ("\n\nThis is a Chutku skill: keep exactly skill.json, SKILL.md, tool.py (run(args) -> dict) and "
            "test_tool.py, standard library only, and the manifest rules.")


def create_skill(base, request, name=None, *, test=True, untrusted_source=None):
    """X16: the coder writes a pending skill; its tests run and real errors go back for up to 3 repairs.

    test=False (W1, skill.import): the files are written but nothing runs, because the request was built from an
    untrusted README. The skill stays pending and untested; only `skill approve` (owner-typed plus a click) runs its
    tests. `untrusted_source` (e.g. the repo URL) is recorded so the approval says where the code came from."""
    from chutku.coder import CoderError
    from chutku.core.progress import beat
    from chutku.tools import builder
    started = time.monotonic()
    coder, note = builder.choose_coder("auto")
    beat(f"{coder.name} is writing the skill")
    ask = request + (f"\nThe skill's name must be: {name}" if name else "")
    spec, coder, note = builder._ask_with_fallback(coder, note, lambda c: c.write_skill(ask))
    files = {path: content for path, content in spec["files"].items() if path in FILES}
    if set(files) != set(FILES):
        raise CoderError(f"The model must write exactly {', '.join(FILES)} (got {', '.join(sorted(spec['files']))}).")
    try:
        manifest = json.loads(files["skill.json"])
    except ValueError:
        manifest = None
    if name is None:
        proposed = manifest.get("name") if isinstance(manifest, dict) else None
        name = proposed if isinstance(proposed, str) and NAME.fullmatch(proposed) and proposed not in RESERVED \
            else _slug(request)
    if isinstance(manifest, dict) and manifest.get("name") != name:
        manifest["name"] = name   # the folder name is the skill's name
        files["skill.json"] = json.dumps(manifest, indent=1)
    if (skills_root(base) / name).exists() or (pending_root(base) / name).exists():
        raise ValueError(f"A skill named {name} already exists; remove it first (skill remove {name}) or pick "
                         "another name.")
    folder = pending_root(base) / name
    folder.mkdir(parents=True)
    builder.write_files(folder, files)
    if not test:   # W1: written from untrusted text: run nothing now
        if untrusted_source:
            (folder / UNTRUSTED).write_text(json.dumps({"source": str(untrusted_source)[:300]}), encoding="utf-8")
        _write_status(folder, None, "Not tested yet: written from an untrusted README. 'skill approve' runs the tests.")
        return {"name": name, "folder": str(folder), "status": "pending", "tests_passed": None, "attempts": [],
                "coder": coder.name, "model": getattr(coder, "model", None), "approve_with": f"skill approve {name}",
                "seconds": round(time.monotonic() - started, 1),
                "skill_reply": (f"Skill {name} is written but NOT tested or run: its code came from an untrusted "
                                f"README. 'skill approve {name}' (then click) runs its tests and, if they pass, turns "
                                "it on.")}
    history, discarded, passed, output = [], [], False, ""
    for attempt in range(1, MAX_REPAIRS + 2):
        beat(f"testing the skill, attempt {attempt}")
        try:
            load(folder)
            passed, output = run_tests(folder)
        except (OSError, ValueError) as error:
            passed, output = False, f"skill.json/folder check failed: {error}"
        history.append({"attempt": attempt, "passed": passed, "problem": None if passed else output[-300:]})
        if passed or attempt > MAX_REPAIRS or time.monotonic() - started > builder.TOTAL_SECONDS:
            break
        current = {p: (folder / p).read_text(encoding="utf-8", errors="replace") for p in FILES}
        error_text = output + _repair_note()
        if discarded:
            error_text += (f"\n\nYour last edit to {', '.join(discarded)} was discarded: fix the program first. "
                           "Change a test only if its expected value is really wrong for the request.")
        beat(f"{coder.name} is fixing the skill")
        repair, coder, note = builder._ask_with_fallback(coder, note, lambda c: c.fix(request, current, error_text))
        changed = {p: c for p, c in repair["files"].items() if p in FILES}
        changed, dropped = builder.keep_tests_fixed(changed, output) if not discarded else (changed, [])
        if dropped:
            history[-1]["discarded_test_edits"] = discarded = dropped
        elif discarded and "test_tool.py" in changed:
            history[-1]["changed_own_tests"] = ["test_tool.py"]
        builder.write_files(folder, changed)
    _write_status(folder, passed, output)
    result = {"name": name, "folder": str(folder), "status": "pending", "tests_passed": passed, "attempts": history,
              "coder": coder.name, "model": getattr(coder, "model", None),
              "approve_with": f"skill approve {name}", "seconds": round(time.monotonic() - started, 1)}
    if note:
        result["note"] = note
    if not passed:
        result["error"] = (f"Skill {name} still fails its tests after {MAX_REPAIRS} repairs ({output[-400:]}). "
                           f"It stays pending and cannot be approved; 'skill remove {name}' clears it.")
    else:
        result["skill_reply"] = (f"Skill {name} is written and its tests pass. It is pending: type "
                                 f"'skill approve {name}' (then click) to turn it on.")
    return result


def approve_skill(base, name):
    """Re-run a pending skill's tests; only on a pass move it to active and record its files' hash."""
    folder, target = pending_root(base) / name, skills_root(base) / name
    if not folder.is_dir():
        return {"error": f"There is no pending skill named {name} (see 'skills dikhao')."}
    if target.exists():
        return {"error": f"An active skill named {name} already exists."}
    try:
        load(folder)
        before = digest(folder)
    except (OSError, ValueError) as error:
        return {"error": f"Skill {name} is not valid: {error}"}
    passed, output = run_tests(folder)   # for an imported skill this is the first time any of its code runs
    _write_status(folder, passed, output)
    if not passed:
        return {"error": f"Skill {name} fails its tests, so it was not approved: {output[-600:]}"}
    try:
        if digest(folder) != before:
            return {"error": f"Skill {name}'s files changed while its tests ran; it was not approved."}
        os.replace(folder, target)
        approved = _approved(base)
        approved[name] = {"sha256": before, "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _save_approved(base, approved)
    except OSError as error:
        return {"error": f"Skill {name} could not be activated: {error}"}
    return {"name": name, "active": True, "tool": f"skill.{name}", "sha256": before,
            "skill_reply": f"Skill {name} passed its tests again and is on. It is the tool skill.{name} from your "
                           "next request, and every run asks for your click."}


def remove_skill(base, name):
    from chutku.core import recycle_bin
    for folder, state in ((skills_root(base) / name, "active"), (pending_root(base) / name, "pending")):
        if folder.is_dir():
            try:
                recycle_bin.send(folder.resolve())
            except OSError as error:
                return {"error": f"Skill {name} could not be moved to the Recycle Bin: {error}"}
            approved = _approved(base)
            if approved.pop(name, None) is not None:
                _save_approved(base, approved)
            return {"name": name, "removed": not folder.exists(), "was": state, "where": "Windows Recycle Bin",
                    "skill_reply": f"Moved skill {name} ({state}) to the Recycle Bin."}
    return {"error": f"There is no skill named {name}."}


def _result(output):
    return ToolResult(output, Verification.FAIL if "error" in output else Verification.PASS)


def register_skill_tools(registry, base):
    """skill.list/create/approve/remove, then every approved active skill as skill.<name>."""
    base = Path(base)

    def listing(_arguments, _context):
        active, skipped = [], {s["name"]: s["reason"] for s in active_skills(base)[1]}
        for row in _entries(skills_root(base)):
            active.append(row | ({"not_on": skipped[row["name"]]} if row["name"] in skipped else {}))
        pending = _entries(pending_root(base))
        return ToolResult({"active": active, "pending": pending, "provenance": "external_untrusted",
                           "skill_reply": _say(active, pending)}, Verification.PASS)

    def creating(arguments, _context):
        from chutku.coder import CoderError
        try:
            return _result(create_skill(base, arguments["request"].strip(), arguments.get("name")))
        except (CoderError, ValueError, OSError) as error:
            return ToolResult({"error": f"The skill could not be written: {error}"}, Verification.FAIL)

    registry.register(Tool("skill.list", "List Chutku's self-written skills: active ones (tools named skill.<name>) and "
        "pending ones waiting for the owner's approval, with their test status.", Risk.OBSERVATION, listing,
        _validate_none, argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
        reversibility="not_applicable", success_predicate="skills_listed"))
    registry.register(Tool("skill.create", "Write a NEW skill (a small Python ability) from a description: the coder "
        "writes it with its own tests under data/skills/_pending, runs the tests and repairs it. It stays pending "
        "until the owner types 'skill approve <name>'. Always confirmed on screen. Takes minutes.",
        Risk.DATA_MODIFICATION, creating, _validate_create, required_capability="process.launch",
        argument_schema={"type": "object", "properties": {
            "request": {"type": "string", "minLength": 5, "maxLength": 2000},
            "name": {"type": "string", "pattern": NAME.pattern}}, "required": ["request"], "additionalProperties": False},
        reversibility="creates_a_new_pending_folder_only", success_predicate="pending_skill_passes_its_tests",
        network_egress=True, runs_code=True))
    registry.register(Tool("skill.approve", "Owner only (typed): RUN a pending skill's tests on this PC and, if they "
        "pass, turn it on as the tool skill.<name>. A skill made by skill.import was written from a GitHub README "
        "(untrusted text) and has never run: approving runs that code now. Always confirmed on screen.", Risk.EXTERNAL_SIDE_EFFECT,
        lambda arguments, _context: _result(approve_skill(base, arguments["name"])), _named,
        required_capability="process.launch", argument_schema=_NAME_SCHEMA, reversibility="none",
        success_predicate="tests_passed_and_skill_moved_to_active", user_only=True, runs_code=True))
    registry.register(Tool("skill.remove", "Move a self-written skill (active or pending) to the Windows Recycle Bin. "
        "Always asks first.", Risk.DATA_MODIFICATION,
        lambda arguments, _context: _result(remove_skill(base, arguments["name"])), _named,
        argument_schema=_NAME_SCHEMA, reversibility="recycle_bin", success_predicate="skill_folder_recycled",
        deletes=True))
    tools, skipped = active_skills(base)
    _log_skipped(skipped)
    for tool in tools:
        registry.register(tool)


def _say(active, pending):
    if not active and not pending:
        return "No skills yet. Say 'make a skill that ...' to have me write one."
    parts = []
    if active:
        parts.append("On: " + "; ".join(f"{s['name']} ({s['description'][:80]})" for s in active[:10]))
    if pending:
        parts.append("Waiting for 'skill approve <name>': " + "; ".join(
            f"{s['name']} (tests {s['tests']})" for s in pending[:10]))
    return ". ".join(parts) + "."
