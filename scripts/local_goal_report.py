r"""Which requests does the slow local model plan most often? Those are the best candidates for new instant rules
(chutku/daily_intent.py, file_intent.py ...), which answer in under a second without any model.

Usage: .venv\Scripts\python.exe scripts\local_goal_report.py [--days 14] [--top 20]
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku import recall  # noqa: E402
from chutku.experience import normal_goal  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    since = time.time() - args.days * 86400
    model_planned = Counter()
    examples = {}
    for row in recall.turns(ROOT):
        planners = row.get("planners") or []
        if row["at"] < since or not any(p in ("local", "local-8b", "gemini") for p in planners):
            continue
        key = normal_goal(row["said"])
        model_planned[key] += 1
        examples[key] = (row["said"], row.get("tools"), planners)
    print(f"Requests planned by a model in the last {args.days} days (most frequent first):")
    for key, count in model_planned.most_common(args.top):
        said, tools, planners = examples[key]
        print(f"{count:3d}x  {said[:70]!r}  tools={tools}  planners={planners}")


if __name__ == "__main__":
    main()
