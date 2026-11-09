"""20x plan scoreboard: the owner's burden per 100 requests (B100), from Chutku's own logs. No network, no model.

    python scripts/scoreboard.py [--days 7] [--base D:/Project/Chutku]

B100 = per 100 action requests: 5 x failed or given up, 3 x complained-about (wrong action), 2 x each question or
approval the owner had to answer, 1 x each 5 s waited beyond 5 s, 20 x each hang. See docs/TWENTY_X_PLAN.md.
"""
import argparse
import collections
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMPLAINT = re.compile(r"\b(?:galat|wrong|nahi hua|not working|kaam nahi|bakwas|ye nahi|yeh nahi|not this|"
                       r"phir se|dobara|again|kyu nahi|why didn'?t)\b", re.I)
FAILED = {"failed", "cancelled", "stopped"}


def _jsonl(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def score(base, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    turns = [r for r in _jsonl(base / "data" / "conversations.jsonl")
             if r.get("origin") != "script" and datetime.fromtimestamp(r.get("at", 0), timezone.utc) >= since]
    actions = [r for r in turns if r.get("status") != "said"]          # "said" = chat in a voice conversation
    failed = sum(r.get("status") in FAILED for r in actions)
    clarify = sum(r.get("status") == "clarify" for r in actions)
    complaints = sum(1 for before, after in zip(turns, turns[1:])
                     if after.get("at", 0) - before.get("at", 0) <= 180 and COMPLAINT.search(after.get("said", "")))
    log = [r for r in _jsonl(base / "data" / "actions.log.jsonl")
           if datetime.fromisoformat(r.get("time", "1970-01-01T00:00:00+00:00")) >= since]
    approvals = sum(r.get("state") == "WAITING_CONFIRMATION" for r in log)
    hangs = [p.name for p in (base / "data" / "logs").glob("hang-*.txt")
             if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) >= since]
    timed = sorted(r["seconds"] for r in actions if isinstance(r.get("seconds"), (int, float)))
    waited = sum(max(0.0, s - 5.0) / 5.0 for s in timed)
    burden = 5 * failed + 3 * complaints + 2 * (clarify + approvals) + waited + 20 * len(hangs)
    tools = collections.defaultdict(collections.Counter)
    for row in log:
        tools[row.get("tool")][row.get("state")] += 1
    worst = sorted(((name, c) for name, c in tools.items() if sum(c.values()) >= 3),
                   key=lambda item: (item[1]["COMPLETED"] / sum(item[1].values()), -sum(item[1].values())))[:12]
    tiers = collections.Counter("+".join(sorted(set(r.get("planners") or ["?"]))) for r in actions)

    def pct(q):
        return round(timed[min(len(timed) - 1, int(len(timed) * q))], 1) if timed else None
    return {"days": days, "requests": len(actions), "turns": len(turns), "failed": failed, "complaints": complaints,
            "clarify": clarify, "approvals": approvals, "hangs": hangs, "timed": len(timed), "p50": pct(0.5),
            "p90": pct(0.9), "waited_points": round(waited, 1),
            "B100": round(100 * burden / len(actions), 1) if actions else None,
            "worst_tools": [(name, c["COMPLETED"], sum(c.values()), dict(c)) for name, c in worst],
            "tiers": tiers.most_common(6)}


def markdown(s):
    lines = [f"### Scoreboard: last {s['days']} days ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"**B100 = {s['B100']}** over {s['requests']} requests ({s['turns']} turns). 20x target: B100 / 20.", "",
             "| Burden | Count |", "|---|---|",
             f"| Failed or given up (x5) | {s['failed']} |", f"| Complaints next turn (x3) | {s['complaints']} |",
             f"| Clarify questions (x2) | {s['clarify']} |", f"| Approvals asked (x2) | {s['approvals']} |",
             f"| Waiting beyond 5 s (points) | {s['waited_points']} ({s['timed']} timed turns, p50 {s['p50']} s, "
             f"p90 {s['p90']} s) |", f"| Hangs (x20) | {len(s['hangs'])} |", "",
             "| Worst tools | Completed / total | States |", "|---|---|---|"]
    lines += [f"| `{name}` | {ok}/{total} | {states} |" for name, ok, total, states in s["worst_tools"]]
    lines += ["", "Tiers: " + ", ".join(f"{name} {n}" for name, n in s["tiers"])]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--base", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown(score(Path(args.base), args.days)))


if __name__ == "__main__":
    main()
