r"""Rewrite the tool-count table in docs/SECURITY.md from the live tool registry (tests/test_docs_truth.py checks it).

    .venv\Scripts\python.exe scripts\security_counts.py

Run it after adding or removing a tool, or after a merge where both sides changed the table. A git conflict inside
the table is resolved by taking the first side; the numbers and R3/R4 lists are then rebuilt from the registry.
"""
from collections import Counter
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.app import create_runtime  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp) / "state") as runtime:
        tools = runtime.registry.list()
    core = [t for t in tools if not t.name.startswith("app.")]
    apps = [t for t in tools if t.name.startswith("app.")]
    counts = Counter(int(t.base_risk) for t in core)
    names = {level: ", ".join(sorted(t.name for t in core if int(t.base_risk) == level)) for level in (3, 4)}
    path = ROOT / "docs" / "SECURITY.md"
    text = path.read_bytes().decode("utf-8")
    text = re.sub(r"<<<<<<< [^\r\n]*\r?\n(.*?)=======\r?\n.*?>>>>>>> [^\r\n]*\r?\n", r"\1", text, flags=re.S)
    text = re.sub(r"\(\d+ registered, plus \d+ app actions\)", f"({len(core)} registered, plus {len(apps)} app actions)",
                  text)
    text = re.sub(r"\| R0 observation \| \d+ \|", f"| R0 observation | {counts[0]} |", text)
    text = re.sub(r"\| R1 reversible \| \d+ \|", f"| R1 reversible | {counts[1]} |", text)
    text = re.sub(r"\| R2 data modification \| \d+ \|", f"| R2 data modification | {counts[2]} |", text)
    text = re.sub(r"\| R3 external side effect \| \d+ \| [^|]*\|",
                  f"| R3 external side effect | {counts[3]} | {names[3]} |", text)
    text = re.sub(r"\| R4 destructive / privileged \| \d+ \| [^|]*\|",
                  f"| R4 destructive / privileged | {counts[4]} | {names[4]} |", text)
    path.write_bytes(text.encode("utf-8"))
    print(f"{len(core)} tools + {len(apps)} app actions: " + ", ".join(f"R{k} {counts[k]}" for k in range(5)))


if __name__ == "__main__":
    main()
