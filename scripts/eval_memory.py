r"""Does meaning-based search find better past examples than word overlap? (master plan S12 gate)

Every real request with known tools (data/conversations.jsonl + data/experience.jsonl) is used as a query against all
the others. A retrieved request counts as relevant when it ran the same set of tools: an independent label taken from
what was actually executed, not from either method. Reports recall@3 and MRR for word overlap and embeddings.

Usage: .venv\Scripts\python.exe scripts\eval_memory.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku import experience, memory_index  # noqa: E402


def examples():
    rows, seen = [], set()
    for line in (ROOT / "data/conversations.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("tools") and row["said"] not in seen:
            seen.add(row["said"])
            rows.append((row["said"], frozenset(row["tools"])))
    for row in experience.load(ROOT):
        if row["goal"] not in seen:
            seen.add(row["goal"])
            rows.append((row["goal"], frozenset(step["tool"] for step in row["steps"])))
    return rows


def score(rankings, labels):
    hits, reciprocal, queries = 0, 0.0, 0
    for index, order in enumerate(rankings):
        relevant = {j for j, tools in enumerate(labels) if j != index and tools == labels[index]}
        if not relevant:
            continue
        queries += 1
        order = [j for j in order if j != index]
        hits += any(j in relevant for j in order[:3])
        first = next((rank for rank, j in enumerate(order, 1) if j in relevant), None)
        reciprocal += 1 / first if first else 0
    return {"queries": queries, "recall_at_3": round(hits / max(queries, 1), 3), "mrr": round(reciprocal / max(queries, 1), 3)}


def main():
    rows = examples()
    goals, labels = [g for g, _ in rows], [t for _, t in rows]
    words = [experience._words(g) for g in goals]
    jaccard = []
    for a in words:
        scores = [len(a & b) / len(a | b) if a | b else 0 for b in words]
        jaccard.append(sorted(range(len(goals)), key=lambda j: -scores[j]))
    started = time.perf_counter()
    vectors = memory_index.embed(goals, "passage", ROOT)
    queries = memory_index.embed(goals, "query", ROOT)
    embedded = [list((-(vectors @ q)).argsort()) for q in queries]
    seconds = time.perf_counter() - started
    hybrid = []   # word overlap first; meaning breaks ties and ranks requests that share no words at all
    for i, a in enumerate(words):
        cosine = vectors @ queries[i]
        scores = [(len(a & b) / len(a | b) if a | b else 0) + HYBRID_WEIGHT * float(cosine[j]) for j, b in enumerate(words)]
        hybrid.append(sorted(range(len(goals)), key=lambda j: -scores[j]))
    fts, fts_ms = fts_rankings(goals)
    result = {"examples": len(rows), "jaccard": score(jaccard, labels), "embeddings": score(embedded, labels),
              "hybrid": score(hybrid, labels), "fts5": score(fts, labels), "embed_seconds": round(seconds, 2),
              "fts5_query_ms_p95": fts_ms}
    print(json.dumps(result, indent=1))
    best = max(("jaccard", "embeddings", "hybrid", "fts5"), key=lambda k: (result[k]["recall_at_3"], result[k]["mrr"]))
    print(f"Best: {best}.")
    return result


HYBRID_WEIGHT = 0.3


def fts_rankings(goals):
    """The history search's own ranking (Phase 3b H4): SQLite FTS5 + bm25 over the same requests, any topic word."""
    import sqlite3
    from chutku.history_index import terms
    from chutku.translit import roman
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE t USING fts5(said, said_roman, tokenize='unicode61 remove_diacritics 2', "
               "prefix='2 3')")
    db.executemany("INSERT INTO t(rowid, said, said_roman) VALUES (?,?,?)",
                   [(i, g, roman(g)) for i, g in enumerate(goals)])
    rankings, times = [], []
    for goal in goals:
        started = time.perf_counter()
        wanted = terms(goal)
        found = [] if not wanted else [r[0] for r in db.execute(
            "SELECT rowid FROM t WHERE t MATCH ? ORDER BY bm25(t)",
            (" OR ".join(f'{{said said_roman}} : "{w}"*' for w in wanted),)).fetchall()]
        times.append((time.perf_counter() - started) * 1000)
        rankings.append(found + [j for j in range(len(goals)) if j not in set(found)])
    times.sort()
    return rankings, round(times[int(len(times) * 0.95)], 2)


if __name__ == "__main__":
    main()
