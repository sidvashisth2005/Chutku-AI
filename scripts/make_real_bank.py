"""20x plan P0: the scenario bank from the owner's own requests. No network, no model.

    python scripts/make_real_bank.py [--base D:/Project/Chutku]

Writes two private, git-ignored files under data/task_bank/:
- real.jsonl: each distinct request that finished with tools, in the task-bank format (expect = the tools that ran),
  so Night Shift practises the owner's real phrasings and catches regressions (practice.nightly loads it).
- real_failures.jsonl: each failed, clarify or cancelled request, newest first: the P1 repro list.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.translit import has_devanagari  # noqa: E402

PROBLEMS = {"failed", "clarify", "cancelled", "stopped"}


def build(base):
    rows = []
    for line in (base / "data" / "conversations.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    rows = [r for r in rows if r.get("origin") != "script" and r.get("said")]
    bank, failures, seen = [], [], set()
    for row in reversed(rows):                                     # newest first: the latest outcome of a phrase wins
        say = " ".join(row["said"].split())[:300]
        key = say.casefold()
        if key in seen:
            continue
        if row.get("status") == "done" and row.get("tools"):
            seen.add(key)
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
            bank.append({"id": "real-" + digest[:12], "say": say, "lang": "hi" if has_devanagari(say) else "mixed",
                         "category": "real", "expect": {"tools": list(row["tools"])}, "risk": 1, "needs": [],
                         "multi_step": len(row["tools"]) > 1, "split": "heldout" if int(digest, 16) % 5 == 0 else "train"})
        elif row.get("status") in PROBLEMS:
            seen.add(key)
            failures.append({"say": say, "status": row["status"], "reply": (row.get("reply") or "")[:300],
                             "tools": row.get("tools") or [], "at": row.get("at")})
    return bank, failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(ROOT))
    base = Path(parser.parse_args(argv).base)
    bank, failures = build(base)
    out = base / "data" / "task_bank"
    out.mkdir(parents=True, exist_ok=True)
    for name, items in (("real", bank), ("real_failures", failures)):
        (out / f"{name}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), "utf-8")
    print(f"real bank: {len(bank)} requests ({sum(i['split'] == 'train' for i in bank)} train); "
          f"failures to fix: {len(failures)}")


if __name__ == "__main__":
    main()
