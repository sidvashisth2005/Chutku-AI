"""Security scans for every change (Software Security & Testing Checklist, Part 2 and "Recommended order" step 1).

    python scripts/security_scan.py                 # SAST + dependency CVEs + secrets in the tracked files
    python scripts/security_scan.py --history       # ... and secrets anywhere in the git history
    python scripts/security_scan.py --sbom sbom.json  # also write a CycloneDX SBOM of requirements.lock

- SAST: bandit over chutku/ (medium+ severity and confidence; the reviewed skips are in pyproject.toml [tool.bandit]).
- SCA: pip-audit over requirements.lock (every pin, hashed) against the PyPI advisory database.
- Secrets: the release gate's key formats (scripts/build_release.SECRETS) in every tracked file and, with
  --history, in every line any commit added.
Needs `pip install bandit==1.9.4 pip-audit==2.10.1` (dev only; not part of Chutku). Exit 1 on any finding.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_release import SECRETS  # noqa: E402  (one definition of a secret, shared with the release gate)


def _run(args):
    print("$", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT).returncode


def sast():
    return _run([sys.executable, "-m", "bandit", "-q", "-r", "chutku", "-c", "pyproject.toml", "-ll", "-ii"])


def dependencies(sbom=None):
    code = _run([sys.executable, "-m", "pip_audit", "-r", "requirements.lock", "--no-deps", "--disable-pip",
                 "--progress-spinner", "off"])
    if sbom:
        code |= _run([sys.executable, "-m", "pip_audit", "-r", "requirements.lock", "--no-deps", "--disable-pip",
                      "--progress-spinner", "off", "-f", "cyclonedx-json", "-o", str(sbom)])
    return code


def find_secrets(data: bytes):
    """[(line number, the first characters)] for every secret-shaped string in data."""
    return [(data.count(b"\n", 0, m.start()) + 1, m.group()[:12].decode("ascii", "replace"))
            for m in SECRETS.finditer(data)]


def secrets_in_files():
    names = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    hits = 0
    for name in filter(None, names.decode("utf-8").split("\0")):
        path = ROOT / name
        try:
            if path.stat().st_size > 5_000_000:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        for line, start in find_secrets(data):
            print(f"SECRET? {start}... in {name}:{line}")
            hits += 1
    print(f"secrets in tracked files: {hits}")
    return 1 if hits else 0


def secrets_in_history():
    log = subprocess.run(["git", "log", "-p", "--all", "--no-color", "--format=commit %H"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    hits = 0
    for chunk in log.split(b"\ncommit "):
        commit = chunk.removeprefix(b"commit ")[:12].decode("ascii", "replace")
        added = b"\n".join(line[1:] for line in chunk.splitlines() if line.startswith(b"+") and
                           not line.startswith(b"+++"))
        for _, start in find_secrets(added):
            print(f"SECRET? {start}... added in commit {commit}")
            hits += 1
    print(f"secrets in git history: {hits}")
    return 1 if hits else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", action="store_true", help="also scan every commit for secrets")
    parser.add_argument("--sbom", type=Path, help="write a CycloneDX SBOM of requirements.lock here")
    args = parser.parse_args(argv)
    results = {"SAST (bandit)": sast(), "dependencies (pip-audit)": dependencies(args.sbom),
               "secrets (files)": secrets_in_files()}
    if args.history:
        results["secrets (history)"] = secrets_in_history()
    for name, code in results.items():
        print(f"{'PASS' if code == 0 else 'FAIL'}  {name}")
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
