r"""Replay the owner's real typed requests through the instant tier and compare with what actually ran.

Owner (2026-10-04): "real life scenarios ke liye train kr". Every logged request (data/conversations.jsonl) whose tools
are known is matched again with today's quick tier; a request that used to be instant and no longer is, or now picks
a different tool, is printed as a possible regression. Nothing is executed.

Usage: .venv\Scripts\python.exe scripts\replay_real_goals.py [--all]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.quick_intents import quick_proposal  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="print every request, not only changes")
    args = parser.parse_args()
    rows = []
    for line in (ROOT / "data" / "conversations.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    seen, same, changed, model = set(), 0, 0, 0
    for row in rows:
        said, tools = row.get("said", ""), row.get("tools") or []
        if not said or not tools or said in seen:
            continue
        seen.add(said)
        proposal = quick_proposal(said)
        now = [step["tool"] for step in proposal["next_steps"]] if proposal else []
        if not now:
            model += 1
            status = "model"
        elif set(now) <= set(tools):
            same += 1
            status = "same"
        else:
            changed += 1
            status = "CHANGED"
        if args.all or status == "CHANGED":
            print(f"{status:8} {said[:70]!r}  then={tools}  now={now}")
    print(f"{len(seen)} distinct real requests: {same} instant with the same tool, {changed} changed, "
          f"{model} go to the model")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
