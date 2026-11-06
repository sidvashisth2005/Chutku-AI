"""Evolve, applying an approved idea (master plan Y2), in its own process:
``python -m chutku.evolve_apply <base> <id>``.

skill: ``skills.create_skill`` writes a pending skill (it still needs 'skill approve').
code:
1. a git worktree ``data/evolve/work/<id>`` on a new branch ``evolve/<id>`` from the current HEAD of main;
2. the unit suite and scripts/check_phrases.py run there first on the unchanged code (the baseline: a fresh checkout
   lacks the git-ignored models and data, so some tests fail before any change);
3. the coder writes the change there; the boundary below is checked before anything is written;
4. the same checks run again; new failures go back to the coder (at most 3 repairs; after a failed assertion the
   first repair may not edit tests: builder.keep_tests_fixed);
5. pass = no check that passed before fails now, and no fewer checks ran; then a commit "Evolve <id>: <title>", the
   boundary again on the committed diff, and ``git merge --ff-only`` into main (refused by git if the owner's
   uncommitted work would be overwritten, refused here if main moved meanwhile);
6. on anything else the worktree and branch are deleted: the main checkout was never touched.

The boundary (``check``) refuses a diff that touches a protected path, changes a safety line (risk, approval,
provenance, process/network/code-running primitives...), removes or changes existing lines of a test or of
scripts/check_phrases.py, skips tests, or is larger than 400 lines or 8 files. Pushing to GitHub happens only with the
owner's ``evolve_push`` preference (default off).
"""
from __future__ import annotations

from datetime import datetime
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from chutku import evolve

PROTECTED_PREFIXES = ("chutku/policy/", "chutku/core/", "chutku/remote/", "chutku/relay/", "android/", "chutku/router/",
                      ".github/", ".claude/", "data/", "models/")
PROTECTED_FILES = frozenset({
    "chutku/runtime.py", "chutku/guard.py", "chutku/tools/registry.py", "chutku/skills.py", "chutku/skill_runner.py",
    "chutku/app.py", "chutku/agent_loop.py", "chutku/agent_execution.py", "chutku/cloud_planner.py",
    "chutku/dashboard.py", "chutku/coder.py", "chutku/tools/builder.py",
    "agents.md", "claude.md", "docs/security.md", "requirements.lock", "pyproject.toml", ".gitignore",
    ".gitattributes", "scripts/security_counts.py", "scripts/ci_tests.py"})
PROTECTED_PATTERNS = (
    "chutku/evolve*.py", "tests/test_evolve*.py", "tests/test_docs_truth.py", "tests/test_trusted_task.py",
    "tests/test_autonomy_policy.py", "tests/test_protected_zones.py", "tests/test_taint*.py", "tests/test_elevation.py",
    "tests/test_injection*.py", "tests/test_failclosed*.py", "tests/test_guard.py", "tests/test_runtime.py",
    "tests/test_capability_grants.py", "tests/test_resource_grants.py", "tests/test_paths_property.py",
    "tests/test_never_rules.py", "tests/test_approvals.py", "tests/test_voice_approval.py",
    "tests/test_skills_x15_x16.py", "tests/test_owner_mode.py", "tests/test_voice_lock.py",
    "tests/test_code_confirm.py", "tests/test_fewer_asks.py", "tests/test_ledger.py", "tests/test_action_log.py")
# A changed (added or removed) line containing one of these is a safety line: refused in every file (in the app atlas
# JSON a "risk" class, a URI scheme or an exe is one too).
SAFETY_TOKENS = ("Risk.", "base_risk", "user_only", "runs_code", "deletes", "required_capability", "resource_access",
                 "network_egress", "sensitive_argument", "reversibility", "provenance", "autonomy", "approv",
                 "confirm", "TAINT", "PRIVATE_TOOLS", "INSTANT_TOOLS", "never_rule", "protect", "grant", "elevat",
                 "subprocess", "Popen", "os.system", "startfile", "ctypes", "winreg", "socket", "urllib", "http.client",
                 "requests.", "import requests", '"risk"', "uri_schemes", '"exe"', "eval(", "exec(", "__import__",
                 "importlib", "rmtree", "os.remove", "unlink(", "rmdir")
TEST_TOKENS = ("skip", "os._exit", "sys.exit", "TestCase.run", "sys.modules", "load_tests", "expectedFailure")
APPEND_ONLY = ("tests/", "scripts/check_phrases.py")
MAX_CHANGED_LINES = 400
MAX_FILES = 8
MAX_REPAIRS = 3
MAX_AREA_BYTES = 200_000
STALE_LOCK = 4 * 3600
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EvolveError(RuntimeError):
    pass


# -- the boundary -------------------------------------------------------------------------------------------------

def _norm(path):
    path = str(path).replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def protected(path):
    """True for a path an Evolve change may never touch."""
    text = _norm(path).casefold()
    return (text.startswith(PROTECTED_PREFIXES) or text in PROTECTED_FILES
            or any(fnmatch.fnmatchcase(text, pattern) for pattern in PROTECTED_PATTERNS)
            or any(part.startswith(".") or part == "" for part in text.split("/")))


def _is_test(path):
    return _norm(path).casefold().startswith("tests/")


def check(changes):
    """Reasons to refuse a diff (empty: allowed). ``changes``: {path: {"status", "added", "removed", "binary"}} with
    the added and removed lines."""
    reasons = []
    if len(changes) > MAX_FILES:
        reasons.append(f"{len(changes)} files changed (at most {MAX_FILES})")
    total = sum(len(c["added"]) + len(c["removed"]) for c in changes.values())
    if total > MAX_CHANGED_LINES:
        reasons.append(f"{total} lines changed (at most {MAX_CHANGED_LINES})")
    for path, change in sorted(changes.items()):
        lowered = _norm(path).casefold()
        if protected(path):
            reasons.append(f"touches the protected path {path}")
            continue
        if change.get("binary"):
            reasons.append(f"{path} is not a text change")
        if change["status"].startswith(("D", "R")):
            reasons.append(f"deletes or renames {path}")
        if lowered.startswith(APPEND_ONLY) and change["removed"]:
            reasons.append(f"changes or removes existing lines of {path} (tests and the phrase check are append-only)")
        for line in change["added"] + change["removed"]:
            token = next((t for t in SAFETY_TOKENS if t.casefold() in line.casefold()), None)
            if token:
                reasons.append(f"changes a safety line in {path} ({token!r}: {line.strip()[:80]!r})")
                break
        if _is_test(path):
            token = next((t for line in change["added"] for t in TEST_TOKENS if t in line), None)
            if token:
                reasons.append(f"{path} would skip or bypass tests ({token!r})")
    return reasons


def _git(repo, *args, check_rc=True, timeout=300):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    if check_rc and done.returncode != 0:
        raise EvolveError(f"git {args[0]} failed: {(done.stderr or done.stdout).strip()[:400]}")
    return done.stdout.strip()


def diff(repo, *spec):
    """The diff ``spec`` (e.g. ``--cached <base>`` or ``<base> HEAD``) as check() input; renames count as delete+add."""
    changes = {}
    for line in _git(repo, "diff", "--no-renames", "--name-status", *spec).splitlines():
        status, _tab, path = line.partition("\t")
        changes[_norm(path)] = {"status": status, "added": [], "removed": [], "binary": False}
    for line in _git(repo, "diff", "--no-renames", "--numstat", *spec).splitlines():
        added, removed, path = (line.split("\t", 2) + ["", ""])[:3]
        if added == "-" and _norm(path) in changes:
            changes[_norm(path)]["binary"] = True
    current = None
    for line in _git(repo, "diff", "--no-renames", "-U0", "--no-color", *spec).splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ ") or line.startswith("--- "):
            name = line[4:].strip()
            if name != "/dev/null":
                current = _norm(name[2:] if name[:2] in ("a/", "b/") else name)
        elif current in changes and line.startswith("+"):
            changes[current]["added"].append(line[1:])
        elif current in changes and line.startswith("-"):
            changes[current]["removed"].append(line[1:])
    return changes


def write_change(work, files):
    """Write the coder's files into the worktree (never outside it), keeping each existing file's line endings."""
    root = Path(work).resolve()
    for relative, content in files.items():
        if protected(relative):
            raise EvolveError(f"the coder wrote the protected path {relative}")
        path = (root / relative).resolve()
        if root not in path.parents:
            raise EvolveError(f"{relative} is outside the worktree")
        crlf = path.is_file() and b"\r\n" in path.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.replace("\r\n", "\n"), encoding="utf-8", newline="\r\n" if crlf else "\n")


# -- checks -------------------------------------------------------------------------------------------------------

_FAILURE = re.compile(r"^(?:FAIL|ERROR): .+$|^\s*MISS .+$", re.M)
_COUNT = re.compile(r"^Ran (\d+) tests?|^instant: \d+/(\d+)", re.M)


def _python():
    python = Path(sys.executable)
    console = python.with_name("python.exe")
    return str(console if console.is_file() else python)


def default_checks(python=None):
    python = python or _python()
    return [("unit tests", [python, "-m", "unittest", "discover", "-s", "tests"], 3600),
            ("instant phrases", [python, "scripts/check_phrases.py"], 600)]


def _env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    return env | {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}


def run_checks(work, checks):
    """{name: {"ran", "code", "failures", "count", "tail"}} for each check, run in the worktree."""
    results = {}
    for name, args, timeout in checks:
        try:
            done = subprocess.run(args, cwd=str(work), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=_env(),
                                  creationflags=_NO_WINDOW)
        except (subprocess.TimeoutExpired, OSError) as error:
            tail = f"timed out ({timeout} s)" if isinstance(error, subprocess.TimeoutExpired) else f"could not start: {error}"
            results[name] = {"ran": False, "code": None, "failures": [], "count": 0, "tail": tail}
            continue
        output = done.stdout + "\n" + done.stderr
        counts = [int(a or b) for a, b in _COUNT.findall(output)]
        results[name] = {"ran": bool(counts), "code": done.returncode, "count": counts[-1] if counts else 0,
                         "failures": sorted({m.strip() for m in _FAILURE.findall(output)}), "tail": output[-4000:]}
    return results


def compare(baseline, after):
    """Problems with ``after`` compared to the unchanged code (empty: the change keeps everything that worked)."""
    problems = []
    for name, now in after.items():
        before = baseline[name]
        if not now["ran"]:
            problems.append(f"{name} did not finish: {now['tail'][-600:]}")
            continue
        new = sorted(set(now["failures"]) - set(before["failures"]))
        if new:
            problems.append(f"{name}: new failures: " + "; ".join(new[:10]))
        if now["count"] < before["count"]:
            problems.append(f"{name}: {before['count']} checks ran before the change, {now['count']} after")
        if now["code"] != 0 and not now["failures"]:
            problems.append(f"{name} exited with {now['code']}: {now['tail'][-600:]}")
    return problems


def _summary(results):
    return {name: {"ran": r["ran"], "count": r["count"], "failures": len(r["failures"]), "code": r["code"]}
            for name, r in results.items()}


# -- the code lane ------------------------------------------------------------------------------------------------

FIRST = ("This is not a failing check: it is an improvement plan the owner approved. Implement exactly these steps "
         "with the smallest change. Add its unit test in a NEW file tests/test_improve_{id}.py (unittest; no network, "
         "no windows). Never change or remove existing lines of a test or of scripts/check_phrases.py; never touch "
         "policy, runtime, core, guard, the tool registry, skills, Evolve, tool risk levels, approvals or "
         "process/network calls (such a change is refused); at most {lines} changed lines in at most {files} files.\n\n"
         "Plan:\n{plan}")


def _request(proposal):
    steps = "\n".join(f"{n}. {s}" for n, s in enumerate(proposal["steps"], 1))
    return f"{proposal['title']}\n{steps}\nTests: {'; '.join(proposal['tests']['unit'])}"


def _current(work, paths):
    files = {}
    for relative in paths:
        path = Path(work) / relative
        if path.is_file() and path.stat().st_size <= MAX_AREA_BYTES and not protected(relative):
            files[_norm(relative)] = path.read_text(encoding="utf-8", errors="replace")
    return files


def _cleanup(repo, work, branch):
    if Path(work).exists():
        _git(repo, "worktree", "remove", "--force", str(work), check_rc=False)
        shutil.rmtree(work, ignore_errors=True)
    _git(repo, "worktree", "prune", check_rc=False)
    if _git(repo, "branch", "--list", branch, check_rc=False):
        _git(repo, "branch", "-D", branch, check_rc=False)


def apply_code(base, proposal, *, repo=None, coder=None, checks=None):
    """Write, test and (only if everything passes) merge one approved code idea. Returns (status, details)."""
    from chutku.tools import builder
    repo = Path(repo or evolve.PROJECT_ROOT)
    pid = proposal["id"]
    work, branch = evolve.root(base) / "work" / pid, f"evolve/{pid}"
    checks = checks or default_checks()
    _cleanup(repo, work, branch)   # leftovers of an interrupted run
    if _git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        return "failed", {"reason": "the Chutku checkout is not on main"}
    start = _git(repo, "rev-parse", "HEAD")
    work.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, str(work), start)
    details = {"from_commit": start, "attempts": []}
    try:
        baseline = run_checks(work, checks)
        details["baseline"] = _summary(baseline)
        if not all(r["ran"] for r in baseline.values()):
            return "failed", details | {"reason": "the checks do not run on the unchanged code"}
        note = None
        if coder is None:
            coder, note = builder.choose_coder("auto")
        request = _request(proposal)
        areas = list(proposal["change"]["areas"])
        instruction = FIRST.format(id=pid, lines=MAX_CHANGED_LINES, files=MAX_FILES, plan=request)
        spec, coder, note = builder._ask_with_fallback(coder, note, lambda c: c.fix(request, _current(work, areas),
                                                                                    instruction))
        files, discarded = spec["files"], []
        for attempt in range(1, MAX_REPAIRS + 2):
            refused = [f"the coder wrote the protected path {p}" for p in files if protected(p)]
            if not refused:
                write_change(work, files)
                _git(work, "add", "-A")
                refused = check(diff(work, "--cached", start))
            if refused:
                return "refused", details | {"reason": "; ".join(refused)[:1000]}
            after = run_checks(work, checks)
            problems = compare(baseline, after)
            details["attempts"].append({"attempt": attempt, "files": sorted(files), "checks": _summary(after),
                                        "problems": [p[:300] for p in problems]})
            if not problems:
                break
            if attempt > MAX_REPAIRS:
                return "failed", details | {"reason": problems[0][:600]}
            errors = "\n".join(problems) + "\n\n" + "\n\n".join(r["tail"] for r in after.values() if r["failures"])
            if discarded:
                errors += (f"\n\nYour last edit to {', '.join(discarded)} was discarded: fix the program first.")
            areas = sorted(set(areas) | set(files))
            current = _current(work, areas)
            repair, coder, note = builder._ask_with_fallback(coder, note, lambda c: c.fix(request, current, errors))
            files = repair["files"]
            files, dropped = builder.keep_tests_fixed(files, errors) if not discarded else (files, [])
            if dropped:
                details["attempts"][-1]["discarded_test_edits"] = discarded = dropped
        details["coder"] = getattr(coder, "name", "?")
        _git(work, "-c", "user.name=Chutku Evolve", "-c", "user.email=evolve@chutku.local", "commit", "-q", "-m",
             f"Evolve {pid}: {proposal['title']}")
        refused = check(diff(work, start, "HEAD"))   # the enforced check, on exactly what would be merged
        if refused:
            return "refused", details | {"reason": "; ".join(refused)[:1000]}
        if _git(repo, "rev-parse", "HEAD") != start or _git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
            return "failed", details | {"reason": "main moved while the change was tested; approve it again"}
        commit = _git(work, "rev-parse", "HEAD")
        _git(repo, "merge", "--ff-only", "-q", branch)
        if _git(repo, "rev-parse", "HEAD") != commit:
            return "failed", details | {"reason": "the merge did not land"}
        details["commit"] = commit
        if evolve._push_on(base):
            pushed = subprocess.run(["git", "-C", str(repo), "push", "origin", "main"], capture_output=True, text=True,
                                    timeout=300, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            details["pushed"] = pushed.returncode == 0
        else:
            details["pushed"] = "off (preference evolve_push)"
        return "merged", details
    finally:
        _cleanup(repo, work, branch)


# -- the process --------------------------------------------------------------------------------------------------

def _lock(base):
    path = evolve.root(base) / "apply.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > STALE_LOCK:
        path.unlink(missing_ok=True)
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))   # FileExistsError: another apply is running
    return path


def run(base, pid, *, repo=None, coder=None, checks=None):
    """Apply one approved skill or code idea; the proposal file and history.jsonl get the outcome."""
    proposal = evolve.load_proposal(base, pid)
    if proposal is None:
        return {"error": f"no idea {pid}"}
    approval = proposal.get("approval") or {}
    if proposal.get("status") != "approved" or approval.get("sha256") != evolve.plan_hash(proposal):
        return {"error": f"idea {pid} is not approved as it stands (status {proposal.get('status')})"}
    if proposal["kind"] not in evolve.BACKGROUND:
        return {"error": f"{proposal['kind']} ideas are applied when approved"}
    try:
        lock = _lock(base)
    except FileExistsError:
        return {"error": "another Evolve change is being applied; approve this one again later"}
    try:
        proposal["status"] = "applying"
        evolve.save_proposal(base, proposal)
        started = time.monotonic()
        try:
            if proposal["kind"] == "skill":
                from chutku import skills
                made = skills.create_skill(base, proposal["payload"]["request"])
                status = "applied" if made.get("tests_passed") else "failed"
                details = {"skill": made.get("name"), "reason": made.get("error") or made.get("skill_reply")}
            else:
                status, details = apply_code(base, proposal, repo=repo, coder=coder, checks=checks)
        except Exception as error:   # whatever broke, the main checkout stays as it was
            status, details = "failed", {"reason": f"{type(error).__name__}: {error}"[:600]}
        details["seconds"] = round(time.monotonic() - started, 1)
        proposal["status"] = status
        proposal["result"] = (f"merged as {details['commit'][:10]} (undo: git revert {details['commit'][:10]})"
                              if status == "merged" else str(details.get("reason") or status))[:600]
        proposal["applied"] = details | {"at": datetime.now().isoformat(timespec="seconds")}
        evolve.save_proposal(base, proposal)
        evolve.record(base, proposal, status, **{k: v for k, v in details.items() if k != "attempts"})
        return {"id": pid, "status": status, "result": proposal["result"], "details": details}
    finally:
        lock.unlink(missing_ok=True)


def main(argv):
    if len(argv) != 2:
        print("usage: python -m chutku.evolve_apply <base folder> <idea id>")
        return 2
    out = run(Path(argv[0]), argv[1])
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0 if out.get("status") in ("merged", "applied") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
