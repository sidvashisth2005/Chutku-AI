"""Persona exam (App Mastery 2, step 8): how well Chutku serves each kind of user, from chutku/apps/tasks.jsonl.

    python scripts/persona_exam.py            # offline: the instant router only, no side effects
    python scripts/persona_exam.py --live     # through the running Chutku (scripts/live_replay.py), owner away only

Offline, each sentence is "instant and right" when the instant router plans it with the expected tools, "instant but
wrong" when it plans other tools, and "planner" when it leaves the sentence to the model. Live, each sentence is sent
to /api/chat marked synthetic: nothing is approved, sends are never confirmed, and the seconds are measured.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def offline(rows):
    from chutku.quick_intents import quick_proposal
    results = []
    for row in rows:
        started = time.perf_counter()
        proposal = quick_proposal(row["say"])
        seconds = time.perf_counter() - started
        tools = [s["tool"] for s in (proposal or {}).get("next_steps", [])]
        if not proposal:
            verdict = "planner"
        elif not tools:
            verdict = "answered"          # a direct answer (time, chit-chat) or a refusal
        elif set(row["expect"]) & set(tools):
            verdict = "right"
        else:
            verdict = "wrong"
        results.append({"id": row["id"], "personas": row["personas"], "lang": row["lang"], "say": row["say"],
                        "verdict": verdict, "tools": tools, "expect": row["expect"], "ms": round(seconds * 1000, 1)})
    return results


def live(rows):
    results = []
    for row in rows:
        started = time.monotonic()
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "live_replay.py"), row["say"]], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        results.append({"id": row["id"], "personas": row["personas"], "lang": row["lang"], "say": row["say"],
                        "seconds": round(time.monotonic() - started, 1), "output": done.stdout.strip()[-400:]})
    return results


def table(results):
    by = defaultdict(lambda: defaultdict(int))
    for row in results:
        for group in row["personas"] + [row["lang"]]:
            by[group][row["verdict"]] += 1
            by[group]["total"] += 1
    lines = ["| Group | Sentences | Instant & right | Answered directly | Planner | Instant but wrong |",
             "|---|---:|---:|---:|---:|---:|"]
    for group in sorted(by):
        c = by[group]
        lines.append(f"| {group} | {c['total']} | {c['right']} | {c['answered']} | {c['planner']} | {c['wrong']} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    from chutku.task_table import rows
    catalog = rows()
    results = live(catalog) if args.live else offline(catalog)
    out = ROOT / "data" / "persona_exam.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    if not args.live:
        print(table(results))
        wrong = [r for r in results if r["verdict"] == "wrong"]
        for row in wrong:
            print(f"WRONG {row['id']}: {row['say']!r} -> {row['tools']} (expected {row['expect']})")
        ms = sorted(r["ms"] for r in results)
        print(f"routing time: median {ms[len(ms) // 2]} ms, max {ms[-1]} ms")


if __name__ == "__main__":
    main()
