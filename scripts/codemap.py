"""Write docs/CODEMAP.md: one line per module from its own docstring, so an agent can find code without reading it all.

Usage: .venv\\Scripts\\python.exe scripts\\codemap.py      (tests/test_codemap.py fails when a module is missing)
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

HEADER = """# Code map

One line per module, taken from each module's own docstring. Read this first, then open only the files you need.
Regenerate with `scripts/codemap.py` after adding or removing a module (`tests/test_codemap.py` checks it).

## How a request flows

1. Text or voice reaches `dashboard.py` (web app), `cli.py` or `voice/`.
2. `quick_intents.QuickPlanner` / `quick_proposal` try the instant router (no model).
3. Otherwise `agent_loop.AgentSession` plans with `cloud_planner` (cloud-first) or `LocalAgentPlanner`.
4. Every step goes through `runtime.Runtime.run` -> `policy/kernel.PolicyKernel.authorize` -> the tool -> its verifier
   -> `core/event_log` and the hash-chained action log.
5. Tools are registered in `app.create_runtime`; each lives in `tools/` (or `apps/` for app actions from the atlas).

Safety rules are in `docs/SECURITY.md`; the owner-facing phrases are in `docs/OWNER_GUIDE.md`.
"""


def first_sentence(path):
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    text = " ".join(doc.split("\n\n")[0].split())
    first = re.split(r"(?<=[.!?])\s", text)[0]
    return first if len(first) <= 140 else first[:137].rsplit(" ", 1)[0] + "…"


def main():
    groups = defaultdict(list)
    for path in sorted((ROOT / "chutku").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        groups[relative.rsplit("/", 1)[0]].append(f"- `{path.name}`: {first_sentence(path) or '(no docstring)'}")
    lines = HEADER.splitlines()
    for folder in sorted(groups):
        lines += ["", f"## `{folder}/`", ""] + groups[folder]
    (ROOT / "docs" / "CODEMAP.md").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    print(sum(len(rows) for rows in groups.values()), "modules")


if __name__ == "__main__":
    main()
