"""Add --hash lines to requirements.lock, so `pip install --require-hashes` refuses any file that is not exactly the
one pinned here. The hashes are PyPI's own SHA-256 for every file of each pinned version (all wheels and the sdist).

    python scripts/hash_lock.py            # rewrite requirements.lock in place (comments and order kept)
    python scripts/hash_lock.py --check    # exit 1 if a pin has no hash
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import urllib.request

LOCK = Path(__file__).resolve().parents[1] / "requirements.lock"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)")


def entries(text):
    """(comment lines, pin, hashes) groups from a lock with or without hashes."""
    logical = re.sub(r"\\\r?\n\s*", " ", text).splitlines()
    for line in logical:
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            yield line, None, []
            continue
        match = PIN.match(parts[0])
        if not match or any(not p.startswith("--hash=sha256:") for p in parts[1:]):
            raise ValueError(f"Not a pinned requirement: {line!r}")
        yield None, (match[1], match[2]), [p.removeprefix("--hash=sha256:") for p in parts[1:]]


def pypi_hashes(name, version):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        files = json.load(response)["urls"]
    hashes = sorted({f["digests"]["sha256"] for f in files})
    if not hashes:
        raise ValueError(f"PyPI lists no files for {name}=={version}")
    return hashes


def main():
    text = LOCK.read_text(encoding="utf-8")
    groups = list(entries(text))
    if "--check" in sys.argv:
        missing = [pin for _, pin, hashes in groups if pin and not hashes]
        print("missing hashes:", missing or "none")
        return 1 if missing else 0
    out = []
    for comment, pin, _ in groups:
        if pin is None:
            out.append(comment)
            continue
        hashes = pypi_hashes(*pin)
        out.append(f"{pin[0]}=={pin[1]} \\\n" + " \\\n".join(f"    --hash=sha256:{h}" for h in hashes))
    LOCK.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{sum(1 for _, pin, _ in groups if pin)} pins hashed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
