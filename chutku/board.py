"""H15 task board (Hermes kanban): the owner's to-dos and Chutku's background research, in data/board.db.

Statuses: todo (waits for its parents) -> ready -> running -> done, or blocked / review; archived hides a task.
  owner tasks     "ye kaam board pe daal do: DBMS notes banana". Chutku never runs them; she tracks and reminds.
  research tasks  "research karke batao X" (task.delegate). The dispatcher runs them with chutku.research, at most
                  MAX_WORKERS at once, beside normal work. A result with fewer than 2 fetched sources goes to
                  review ("theek hai" / "dobara karo"); a failure is retried twice with a growing wait; 3 failures
                  in an hour open the circuit (research pauses for an hour, with one notice).
Nothing is ever deleted: archive only. Tasks that were running when Chutku stopped go back to ready at start.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time

STATUSES = ("todo", "ready", "running", "blocked", "review", "done", "archived")
KINDS = ("research", "owner")
MAX_WORKERS = 2
MAX_ATTEMPTS = 3            # the first run + 2 retries
RETRY_SECONDS = 30          # wait before retry n is n * RETRY_SECONDS
STALL_SECONDS = 90          # a running worker that reports nothing for this long is blocked
BREAKER_FAILURES = 3
BREAKER_WINDOW = 3600
BREAKER_SECONDS = 3600
TITLE_CHARS = 200
_LOCK = threading.RLock()


def db_path(base) -> Path:
    return Path(base) / "data" / "board.db"


def research_folder(base) -> Path:
    return Path(base) / "data" / "research"


def _connect(base):
    path = db_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, goal TEXT, kind TEXT NOT NULL,
        status TEXT NOT NULL, parent_ids TEXT NOT NULL DEFAULT '[]', created_by TEXT NOT NULL,
        result_path TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_heartbeat REAL, not_before REAL,
        error TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    return db


class _Db:
    def __init__(self, base):
        self.base = base

    def __enter__(self):
        _LOCK.acquire()
        try:
            self.db = _connect(self.base)
        except BaseException:
            _LOCK.release()
            raise
        return self.db

    def __exit__(self, kind, *_):
        try:
            if kind is None:
                self.db.commit()
            self.db.close()
        finally:
            _LOCK.release()


def _row(row):
    item = dict(row)
    item["parent_ids"] = json.loads(item["parent_ids"] or "[]")
    return item


def add(base, title, *, kind="owner", goal=None, parents=(), created_by="owner", now=None):
    """A new task. Returns it. Research tasks need a goal; parents must exist."""
    title = " ".join(str(title or "").split())[:TITLE_CHARS]
    if not title:
        raise ValueError("Say what the task is.")
    if kind not in KINDS:
        raise ValueError("Unknown task kind.")
    goal = " ".join(str(goal or title).split())[:1000]
    now = now or time.time()
    with _Db(base) as db:
        parents = [int(p) for p in parents]
        for parent in parents:
            if db.execute("SELECT 1 FROM tasks WHERE id=?", (parent,)).fetchone() is None:
                raise ValueError(f"There is no task {parent}.")
        status = "todo" if parents else "ready"
        cursor = db.execute("INSERT INTO tasks (title, goal, kind, status, parent_ids, created_by, created, updated) "
                            "VALUES (?,?,?,?,?,?,?,?)", (title, goal, kind, status, json.dumps(parents),
                                                         created_by, now, now))
        task_id = cursor.lastrowid
    promote(base)
    return get(base, task_id)


def get(base, task_id):
    with _Db(base) as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
    if row is None:
        raise ValueError(f"There is no task {task_id}.")
    return _row(row)


def tasks(base, *, include_archived=False, kind=None):
    with _Db(base) as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    items = [_row(r) for r in rows]
    return [t for t in items if (include_archived or t["status"] != "archived") and (kind is None or t["kind"] == kind)]


def set_status(base, task_id, status, *, error=None, result_path=None, now=None):
    if status not in STATUSES:
        raise ValueError("Unknown status.")
    now = now or time.time()
    with _Db(base) as db:
        changed = db.execute("UPDATE tasks SET status=?, error=COALESCE(?, error), result_path=COALESCE(?, result_path), "
                             "updated=? WHERE id=?", (status, error, result_path, now, int(task_id))).rowcount
    if not changed:
        raise ValueError(f"There is no task {task_id}.")
    if status == "done":
        promote(base)
    return get(base, task_id)


def promote(base):
    """todo -> ready when every parent is done. Returns the promoted ids."""
    with _Db(base) as db:
        done = {r["id"] for r in db.execute("SELECT id FROM tasks WHERE status='done'")}
        promoted = []
        for row in db.execute("SELECT id, parent_ids FROM tasks WHERE status='todo'").fetchall():
            if set(json.loads(row["parent_ids"] or "[]")) <= done:
                db.execute("UPDATE tasks SET status='ready', updated=? WHERE id=?", (time.time(), row["id"]))
                promoted.append(row["id"])
    return promoted


def recover(base):
    """At start: tasks cut off while running go back to ready (attempt +1). Returns their ids."""
    with _Db(base) as db:
        rows = db.execute("SELECT id FROM tasks WHERE status='running'").fetchall()
        db.execute("UPDATE tasks SET status='ready', attempts=attempts+1, updated=? WHERE status='running'",
                   (time.time(),))
    return [r["id"] for r in rows]


def find_open(base, words):
    """The open owner task whose title matches these words best ("DBMS notes ho gaya"), or None."""
    wanted = {w for w in str(words).casefold().split() if len(w) > 2}
    best, score = None, 0
    for task in tasks(base, kind="owner"):
        if task["status"] in {"done", "archived"}:
            continue
        overlap = len(wanted & set(task["title"].casefold().split()))
        if overlap > score:
            best, score = task, overlap
    return best if best is not None and score >= max(1, len(wanted) // 2) else None


# -- dispatcher -----------------------------------------------------------------------------------------------------

def _meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def breaker_open(base, now=None):
    now = now or time.time()
    with _Db(base) as db:
        return float(_meta(db, "breaker_until", "0")) > now


def _record_failure(base, now):
    """Returns True when this failure opened the circuit."""
    with _Db(base) as db:
        failures = [t for t in json.loads(_meta(db, "failures", "[]")) if now - t < BREAKER_WINDOW] + [now]
        db.execute("INSERT OR REPLACE INTO meta VALUES ('failures', ?)", (json.dumps(failures[-10:]),))
        if len(failures) >= BREAKER_FAILURES:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('breaker_until', ?)", (str(now + BREAKER_SECONDS),))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('failures', '[]')")
            return True
    return False


class Dispatcher:
    """Runs ready research tasks beside normal work. `worker(task, heartbeat, cancelled)` returns
    {"text": markdown answer, "sources": [urls actually fetched]} or raises; `notify(title, message)` tells the
    owner; `paused()` is True while the owner paused Chutku (H2): then nothing new starts."""

    def __init__(self, base, worker, *, notify=None, paused=None, clock=time.time):
        self.base, self.worker, self.clock = Path(base), worker, clock
        self.notify = notify or (lambda title, message: None)
        self.paused = paused or (lambda: False)
        self.running = {}      # task id -> {"thread", "cancel": Event}
        self.lock = threading.Lock()
        self.breaker_noted = False

    def start(self, stop, tick=5.0):
        recover(self.base)
        thread = threading.Thread(target=self._loop, args=(stop, tick), name="chutku-board", daemon=True)
        thread.start()
        return thread

    def _loop(self, stop, tick):
        from chutku.core.log import get_logger
        while not stop.wait(tick):
            try:
                self.tick()
            except Exception:
                get_logger("board").exception("board dispatcher tick failed")

    def tick(self):
        """One pass: block stalled workers, then start what is ready. Returns the ids started."""
        now = self.clock()
        with self.lock:
            for task_id, worker in list(self.running.items()):
                if not worker["thread"].is_alive():
                    self.running.pop(task_id)
        with self.lock:
            live = dict(self.running)
        for task in tasks(self.base, kind="research"):
            if task["status"] == "running" and task["id"] in live and task["last_heartbeat"] \
                    and now - task["last_heartbeat"] > STALL_SECONDS:
                live[task["id"]]["cancel"].set()
                set_status(self.base, task["id"], "blocked", error=f"No progress for {STALL_SECONDS} s.")
                self.notify("Research rukh gayi", f"'{task['title'][:60]}': {STALL_SECONDS} s se koi progress nahi.")
        if self.paused():
            return []
        if breaker_open(self.base, now):
            if not self.breaker_noted:
                self.breaker_noted = True
                self.notify("Research paused", "3 research tasks failed within an hour; trying again in an hour.")
            return []
        self.breaker_noted = False
        started = []
        for task in tasks(self.base, kind="research"):
            with self.lock:
                if len(self.running) >= MAX_WORKERS:
                    break
                if task["status"] != "ready" or task["id"] in self.running or (task["not_before"] or 0) > now:
                    continue
                with _Db(self.base) as db:
                    db.execute("UPDATE tasks SET status='running', last_heartbeat=?, updated=? WHERE id=?",
                               (now, now, task["id"]))
                cancel = threading.Event()
                thread = threading.Thread(target=self._run, args=(task, cancel), name=f"chutku-research-{task['id']}",
                                          daemon=True)
                self.running[task["id"]] = {"thread": thread, "cancel": cancel}
                thread.start()
                started.append(task["id"])
        return started

    def join(self, timeout=5.0):
        """Wait for the running workers (shutdown and tests)."""
        with self.lock:
            threads = [worker["thread"] for worker in self.running.values()]
        for thread in threads:
            thread.join(timeout)

    def stop_task(self, task_id):
        """The running-workers strip's Stop button."""
        with self.lock:
            worker = self.running.get(int(task_id))
        if worker is None:
            return False
        worker["cancel"].set()
        set_status(self.base, task_id, "blocked", error="Stopped by the owner.")
        return True

    def _beat(self, task_id):
        with _Db(self.base) as db:
            db.execute("UPDATE tasks SET last_heartbeat=? WHERE id=? AND status='running'", (self.clock(), task_id))

    def _run(self, task, cancel):
        try:
            result = self.worker(task, lambda: self._beat(task["id"]), cancel)
            if cancel.is_set():
                return   # stopped or stalled: its status was already set
            path = self._save(task, result)
            sources = result.get("sources") or []
            status = "done" if len(sources) >= 2 else "review"
            set_status(self.base, task["id"], status, result_path=str(path))
            note = "" if status == "done" else " (sources kam the, ek baar check kar lo)"
            self.notify(f"Research: {task['title'][:60]}", (result.get("text") or "")[:200] + note)
        except Exception as error:
            if cancel.is_set():
                return
            self._failed(task, error)

    def _failed(self, task, error):
        now = self.clock()
        current = get(self.base, task["id"])
        attempts = current["attempts"] + 1
        reason = str(error)[:300] or type(error).__name__
        with _Db(self.base) as db:
            if attempts < MAX_ATTEMPTS:
                db.execute("UPDATE tasks SET status='ready', attempts=?, not_before=?, error=?, updated=? WHERE id=?",
                           (attempts, now + RETRY_SECONDS * attempts, reason, now, task["id"]))
            else:
                db.execute("UPDATE tasks SET status='blocked', attempts=?, error=?, updated=? WHERE id=?",
                           (attempts, reason, now, task["id"]))
        if attempts >= MAX_ATTEMPTS:
            self.notify(f"Research nahi ho payi: {task['title'][:50]}", reason[:200])
        if _record_failure(self.base, now):
            self.breaker_noted = True
            self.notify("Research paused", "3 research tasks failed within an hour; trying again in an hour.")

    def _save(self, task, result):
        folder = research_folder(self.base)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{task['id']}.md"
        sources = "\n".join(f"- {url}" for url in result.get("sources") or []) or "- (none fetched)"
        path.write_text(f"# {task['title']}\n\n{result.get('text') or ''}\n\n## Sources fetched\n{sources}\n",
                        encoding="utf-8")
        return path


# -- tools ----------------------------------------------------------------------------------------------------------

def summary(base, kind=None):
    rows = tasks(base, kind=kind)
    if not rows:
        return "Board khaali hai. Bolo 'ye kaam board pe daal do: ...' ya 'research karke batao ...'."
    names = {"todo": "intezaar", "ready": "line mein", "running": "chal raha", "blocked": "ruka hua",
             "review": "check karo", "done": "ho gaya"}
    return "Board: " + "; ".join(f"{t['id']}. {t['title'][:50]} ({'research' if t['kind'] == 'research' else 'tumhara'}"
                                 f", {names.get(t['status'], t['status'])})" for t in rows[-10:]) + "."


def register_board_tools(registry, base):
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification
    text = {"type": "string", "minLength": 2, "maxLength": TITLE_CHARS}

    def delegate(arguments, _context):
        first = add(base, arguments["goal"], kind="research", created_by="owner")
        made = [first]
        if arguments.get("then"):
            made.append(add(base, arguments["then"], kind="research", parents=[first["id"]], created_by="owner"))
        stored = [get(base, t["id"]) for t in made]
        reply = (f"Research shuru: '{first['title'][:60]}'. Ho jaane pe bata dungi." if len(made) == 1 else
                 f"Pehle '{made[0]['title'][:40]}', phir '{made[1]['title'][:40]}'. Ho jaane pe bata dungi.")
        return ToolResult({"tasks": stored, "summary": reply}, Verification.PASS)

    def add_owner(arguments, _context):
        task = add(base, arguments["title"], kind="owner")
        return ToolResult({"task": task, "summary": f"Board pe daal diya: {task['id']}. {task['title'][:60]}."},
                          Verification.PASS if get(base, task["id"])["status"] == "ready" else Verification.FAIL)

    def listing(arguments, _context):
        kind = arguments.get("kind")
        return ToolResult({"tasks": tasks(base, kind=kind), "summary": summary(base, kind)}, Verification.PASS)

    def resolve(arguments):
        if "id" in arguments:
            return get(base, arguments["id"])
        task = find_open(base, arguments["title"])
        if task is None:
            raise ValueError(f"Board pe '{arguments['title'][:60]}' jaisa koi khula kaam nahi mila.")
        return task

    def done(arguments, _context):
        try:
            task = resolve(arguments)
        except ValueError as error:
            return ToolResult({"error": str(error)}, Verification.FAIL)
        if task["kind"] == "research" and task["status"] not in {"review", "blocked"}:
            return ToolResult({"error": "Research khud khatam hoti hai; sirf 'check karo' wali ko theek hai bolo."},
                              Verification.FAIL)
        task = set_status(base, task["id"], "done")
        return ToolResult({"task": task, "summary": f"{task['id']}. {task['title'][:60]}: ho gaya."},
                          Verification.PASS if task["status"] == "done" else Verification.FAIL)

    def again(arguments, _context):
        try:
            task = resolve(arguments)
        except ValueError as error:
            return ToolResult({"error": str(error)}, Verification.FAIL)
        if task["kind"] != "research":
            return ToolResult({"error": "Sirf research dobara chalti hai."}, Verification.FAIL)
        with _Db(base) as db:
            db.execute("UPDATE tasks SET status='ready', attempts=0, not_before=NULL, error=NULL, updated=? "
                       "WHERE id=?", (time.time(), task["id"]))
        return ToolResult({"task": get(base, task["id"]), "summary": "Theek hai, dobara research karti hoon."},
                          Verification.PASS)

    def archive(arguments, _context):
        try:
            task = set_status(base, arguments["id"], "archived")
        except ValueError as error:
            return ToolResult({"error": str(error)}, Verification.FAIL)
        return ToolResult({"task": task, "summary": f"{task['id']} archive kar diya (mitaya nahi)."},
                          Verification.PASS)

    pick = {"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}, "title": text},
            "additionalProperties": False, "oneOf": [{"required": ["id"]}, {"required": ["title"]}]}
    registry.register(Tool("task.delegate", "Research something on the public web in the background while other "
        "work goes on ('research karke batao X', 'pehle X pata karo, phir Y' = then). Only public web tools; the "
        "result is a toast and a board entry.", Risk.REVERSIBLE, delegate, argument_schema={
            "type": "object", "properties": {"goal": {"type": "string", "minLength": 3, "maxLength": 500},
                                             "then": {"type": "string", "minLength": 3, "maxLength": 500}},
            "required": ["goal"], "additionalProperties": False}, reversibility="compensatable"))
    registry.register(Tool("board.add", "Put one of the owner's own to-dos on the task board (Chutku only tracks "
        "it; she never does it).", Risk.REVERSIBLE, add_owner, argument_schema={
            "type": "object", "properties": {"title": text}, "required": ["title"], "additionalProperties": False},
        reversibility="compensatable"))
    registry.register(Tool("board.list", "Show the task board: the owner's to-dos and the research tasks with their "
        "status.", Risk.OBSERVATION, listing, argument_schema={
            "type": "object", "properties": {"kind": {"type": "string", "enum": list(KINDS)}},
            "additionalProperties": False}, reversibility="not_applicable"))
    registry.register(Tool("board.done", "Mark a board task done (an owner to-do, or a research result the owner "
        "checked).", Risk.REVERSIBLE, done, argument_schema=pick, reversibility="compensatable"))
    registry.register(Tool("board.again", "Run a research task again ('dobara karo').", Risk.REVERSIBLE, again,
        argument_schema=pick, reversibility="compensatable"))
    registry.register(Tool("board.archive", "Archive a board task (hidden, never deleted).", Risk.REVERSIBLE,
        archive, argument_schema={"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}},
                                  "required": ["id"], "additionalProperties": False}, reversibility="compensatable"))
