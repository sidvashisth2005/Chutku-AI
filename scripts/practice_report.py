"""WA4: the practice report from data/practice/YYYY-MM-DD.jsonl: held-out success per category, the daily trend and
the 20 worst held-out items (the ones that failed most often).

Usage: python scripts/practice_report.py [data folder's parent, default: Chutku's home]
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def report(base):
    days, by_category, failures = {}, defaultdict(lambda: [0, 0]), Counter()
    for path in sorted((Path(base) / "data" / "practice").glob("????-??-??.jsonl")):
        ok = n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("split") != "heldout":
                continue
            n += 1
            ok += row["reward"] == 1
            stats = by_category[row["category"]]
            stats[0] += row["reward"] == 1
            stats[1] += 1
            if row["reward"] < 1:
                failures[(row["say"], row["verdict"])] += 1
        if n:
            days[path.stem] = round(ok / n, 3)
    return {"trend": days, "by_category": {c: round(ok / n, 3) for c, (ok, n) in sorted(by_category.items())},
            "worst": [{"say": say, "verdict": verdict, "times": times}
                      for (say, verdict), times in failures.most_common(20)]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        base = Path(argv[0])
    else:
        from chutku.core.paths import home
        base = home()
    out = report(base)
    if not out["trend"]:
        print("No practice yet: Night Shift writes data/practice/ after its first night.")
        return 0
    print("Held-out success by day: " + ", ".join(f"{d} {v:.0%}" for d, v in out["trend"].items()))
    print("By category: " + ", ".join(f"{c} {v:.0%}" for c, v in out["by_category"].items()))
    print("Worst 20:")
    for row in out["worst"]:
        print(f"  {row['times']}x  {row['say']}  ({row['verdict']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
