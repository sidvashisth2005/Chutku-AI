"""Fast search over everything the owner and Chutku said (Phase 3b H4): "pichhle hafte DBMS ke baare mein kya baat hui".

data/conversations.jsonl is indexed into data/history.db, a SQLite FTS5 table, read incrementally by byte offset
(a shorter file means it was rotated or rewritten: the index is rebuilt). Hindi script is indexed in Roman letters
too (translit.roman), so a Devanagari question finds a Roman-letter turn and the other way round. No model is used:
a query takes milliseconds. Idea from hermes-agent's session_search (SQLite FTS5, MIT, Nous Research).
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

from chutku.translit import roman

_LOCK = threading.Lock()
# Words that carry no topic: they would match almost every turn.
_STOP = frozenset("""a an the is are was were be been do did does i me my you your we our it its this that what which who
when where why how about of in on at to for from with and or not no yes say said tell told talk talked chat chatted
kya kab kaise kahan kaun kitna kitni ke ki ka ko mein me se par pe aur ya hai hain tha thi the hua hui hue baat baatein
baare bare mera meri mere tum tumne tumhe maine humne hum kal aaj pichhle pichle hafte week day din raat subah shaam
batao bata dhoondo dhundo search find wali wala wale karo kiya kar raha rahi rahe yesterday today tomorrow last
earlier before ago parso abhi""".split())


def db_path(base) -> Path:
    return Path(base) / "data" / "history.db"


def _connect(base):
    path = db_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS turns USING fts5(said, reply, said_roman, reply_roman, "
               "at UNINDEXED, origin UNINDEXED, hidden UNINDEXED, tokenize='unicode61 remove_diacritics 2', "
               "prefix='2 3')")
    return db


class _Db:
    """One connection per use, committed and closed (no leaked handles on Windows)."""
    def __init__(self, base):
        self.base = base

    def __enter__(self):
        self.db = _connect(self.base)
        return self.db

    def __exit__(self, kind, *_):
        try:
            if kind is None:
                self.db.commit()
        finally:
            self.db.close()


def _meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def sync(base) -> int:
    """Index new lines of conversations.jsonl; returns how many turns were added."""
    from chutku.recall import conversations_path, hidden_turns
    source = conversations_path(base)
    hidden = hidden_turns(base)   # H29: a re-index (rotation, repair) must keep forgotten turns hidden
    with _LOCK, _Db(base) as db:
        try:
            size = source.stat().st_size
        except FileNotFoundError:
            return 0
        offset = int(_meta(db, "offset", "0"))
        if size < offset:   # rotated or rewritten: start again
            db.execute("DELETE FROM turns")
            offset = 0
        added = 0
        with source.open("rb") as stream:
            stream.seek(offset)
            for raw in stream:
                if not raw.endswith(b"\n"):
                    break   # a line still being written: next time
                offset += len(raw)
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                said, reply = str(row.get("said") or ""), str(row.get("reply") or "")
                if not said and not reply:
                    continue
                db.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?)",
                           (said, reply, roman(said), roman(reply), float(row.get("at") or 0),
                            str(row.get("origin") or ""), 1 if row.get("hidden") or row.get("at") in hidden else 0))
                added += 1
        db.execute("INSERT OR REPLACE INTO meta VALUES ('offset', ?)", (str(offset),))
        return added


def set_hidden(base, at, hidden: bool):
    """H29: mark an indexed turn hidden (or visible again); search skips hidden turns."""
    sync(base)
    with _LOCK, _Db(base) as db:
        db.execute("UPDATE turns SET hidden = ? WHERE at = ?", (1 if hidden else 0, float(at)))


def terms(query: str) -> list[str]:
    """Topic words of a question, in Roman letters, safe to quote into an FTS5 query."""
    words = re.findall(r"\w+", roman(str(query)).casefold())
    return [w for w in words if w not in _STOP and len(w) >= 2][:8]


def search(base, query: str, *, days: int | None = None, limit: int = 5, now: float | None = None) -> dict:
    """Best matching past turns, newest first among equals. Every word is quoted, so FTS operators typed by the user
    (OR, NEAR, *, quotes) are plain text here."""
    started = time.perf_counter()
    sync(base)
    wanted = terms(query)
    if not wanted:
        return {"query": query, "terms": [], "matches": [], "note": "Give a topic word to search for."}
    fields = "{said reply said_roman reply_roman}"
    since = (now or time.time()) - days * 86400 if days else 0
    matches = []
    with _LOCK, _Db(base) as db:
        for joiner in (" AND ", " OR "):   # all words first; if nothing has them all, any word
            expression = joiner.join(f'{fields} : "{w}"*' for w in wanted)
            rows = db.execute("SELECT said, reply, at, origin, bm25(turns) FROM turns WHERE turns MATCH ? "
                              "AND hidden = 0 AND at >= ? ORDER BY bm25(turns), at DESC LIMIT ?",
                              (expression, since, limit)).fetchall()
            if rows:
                break
    for said, reply, at, origin, _rank in rows:
        matches.append({"date": datetime.fromtimestamp(at).strftime("%a %d %b %Y, %I:%M %p"), "origin": origin,
                        "said": said[:200], "reply": reply[:200]})
    return {"query": query, "terms": wanted, "matches": matches,
            "ms": round((time.perf_counter() - started) * 1000, 1)}
