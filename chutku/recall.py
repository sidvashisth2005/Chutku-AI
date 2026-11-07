"""What Chutku remembers about the owner and past conversations, as one small, topic-relevant slice.

Owner (2026-10-04): "remember my details and the context of all my previous chats"; Gemini may get only what relates
to the current topic, and that must not cost extra tokens (so: one bounded slice, no extra calls).

- about_you(goal, budget): people, facts, open list items, saved notes and earlier conversation that relate to the
  goal (word overlap, then recency), trimmed to `budget` characters of JSON. Local planner: 1200; cloud and voice: 800.
- log_conversation(): data/conversations.jsonl (local only): what the owner said, Chutku's reply (without the
  verification tail), tools used, status. Text only; rotates at 20 MB.
- earlier(goal): the last 3 turns from today + up to 3 older turns sharing words with the goal.
- talked_about(day): a plain summary of one day's conversation ("what did we talk about yesterday").
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import threading
import time

from chutku.core.paths import home as _home
from chutku.core.paths import CODE_ROOT
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
ROTATE_BYTES = 20_000_000
_lock = threading.Lock()
_STOP = {"the", "a", "an", "to", "of", "and", "or", "is", "it", "in", "on", "for", "me", "my", "i", "you", "do",
         "karo", "kar", "ko", "ka", "ki", "ke", "hai", "h", "se", "me", "mein", "main", "pe", "par", "ye", "yeh",
         "wo", "woh", "kya", "please", "chutku", "oye", "hi", "aur", "bhi", "na", "toh", "to", "do", "de", "dena"}
_VERIFIED_TAIL = re.compile(r"\s*\[Verified:.*\]\s*$", re.S)
# Words that say nothing about a topic (for the mind map's "recent topics").
_PLAIN = {"what", "did", "does", "about", "today", "talk", "tell", "show", "open", "close", "play", "good", "job",
          "map", "mind", "time", "with", "this", "that", "there", "here", "your", "from", "have", "has", "will",
          "can", "could", "would", "should", "how", "when", "where", "which", "who", "why", "dikhao", "batao",
          "kholo", "chalao", "band", "bhejo", "kitna", "kitne", "kaha", "kaise", "abhi", "kal", "aaj", "baje",
          "please", "thanks", "thank", "okay", "yes", "now", "then", "again", "just", "want", "need", "make",
          "send", "set", "put", "get", "give", "find", "search", "start", "stop", "kya", "hai", "karo", "wala",
          "wali", "wale", "waala", "mera", "meri", "mere", "tum", "aap", "hum", "humne", "maine", "tha", "thi"}
# Requests about Chutku's memory itself ("what did we talk about", "good job", "mind map") are not topics or history.
_META_TOOLS = {"mind.feedback", "mind.map"}


def _meta(row):
    if set(row.get("tools") or ()) & _META_TOOLS:
        return True
    from chutku.quick_intents import HISTORY, MIND_MAP
    return bool(HISTORY.search(row.get("said", "")) or MIND_MAP.search(row.get("said", "")))


def words(text):
    from chutku.translit import roman
    return {w for w in re.findall(r"[a-z0-9]+", roman(str(text or "")).casefold()) if w not in _STOP and len(w) > 1}


def conversations_path(base=None):
    return Path(base or PROJECT_ROOT) / "data" / "conversations.jsonl"


# -- whose turn was it (F7, 2026-10-29) ----------------------------------------------------------------------
# Habits, suggestions, worked examples and the nightly replay learn from the OWNER only. Before 2026-10-30 the test
# scripts that drive the live Chutku logged as "text" like the owner: "which is bigger, 2 to the power 10 or 10
# cubed?" became a 2 AM habit and a suggestion toast. Since then they send X-Chutku-Synthetic and log as "script";
# older turns are recognised by the scripts' own questions.
OWNER_ORIGINS = frozenset({"text", "voice", "phone", "phone_voice"})
_script_goals = None


def script_goals():
    """The questions scripts/live_check.py and scripts/time_live_chat.py ask (normalised), read without running them."""
    global _script_goals
    if _script_goals is None:
        import ast
        found = set()
        for name, variable in (("live_check.py", "CASES"), ("time_live_chat.py", "QUESTIONS")):
            try:
                tree = ast.parse((CODE_ROOT / "scripts" / name).read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == variable for t in node.targets) \
                        and isinstance(node.value, (ast.List, ast.Tuple)):
                    for item in node.value.elts:
                        value = item.elts[1] if isinstance(item, ast.Tuple) and len(item.elts) > 1 else item
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            found.add(" ".join(value.value.casefold().split()))
        _script_goals = frozenset(found)
    return _script_goals


def owner_turn(turn):
    """True for a turn the owner really asked (typed, spoken or from the phone); False for scripts and tests."""
    if turn.get("origin", "text") not in OWNER_ORIGINS:
        return False
    return " ".join(str(turn.get("said") or "").casefold().split()) not in script_goals()


# -- conversation log --------------------------------------------------------------------------------------

def log_conversation(said, reply, *, origin="text", status="done", tools=(), base=None, at=None, planners=None,
                     tainted=False):
    said, reply = " ".join(str(said or "").split()), _VERIFIED_TAIL.sub("", str(reply or "")).strip()
    if not said:
        return
    row = {"at": at or time.time(), "origin": origin, "said": said[:600], "reply": reply[:800], "status": status,
           "tools": sorted({str(t) for t in tools})[:12]}
    if planners:
        row["planners"] = [str(p) for p in planners][:8]   # quick / replay / local / local-8b / gemini
    if tainted:
        row["tainted"] = True   # the reply followed outside content: shown to later planners only as data
    file = conversations_path(base)
    with _lock:
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            if file.exists() and file.stat().st_size > ROTATE_BYTES:
                file.replace(file.with_suffix(".old.jsonl"))
            with file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass  # memory is a help, never a reason for a task to fail


def log_session(snapshot, base=None):
    """One finished agent session (text, hotkey, wake or a voice-conversation task)."""
    if not snapshot or snapshot.get("status") in (None, "planning", "running", "queued", "waiting_confirmation"):
        return
    tools = [s.get("tool") for s in snapshot.get("steps", []) if s.get("state") == "COMPLETED"]
    log_conversation(snapshot.get("goal"), snapshot.get("reply"), origin=snapshot.get("origin", "text"),
                     status=snapshot.get("status"), tools=tools, base=base,
                     planners=[p.get("planner") for p in snapshot.get("planners", []) if p.get("planner")],
                     tainted=bool(snapshot.get("tainted")))


def log_voice(transcript, base=None):
    """A finished voice conversation: each owner turn with Chutku's answer to it (meaningful turns only)."""
    from chutku.voice.heard import meaningful
    pending = None
    for speaker, text in transcript or []:
        text = " ".join(str(text).split())
        if speaker == "you":
            if pending:
                log_conversation(pending, "", origin="voice", status="said", base=base)
            pending = text if meaningful(text) else None
        elif pending:
            log_conversation(pending, text, origin="voice", status="said", base=base)
            pending = None
    if pending:
        log_conversation(pending, "", origin="voice", status="said", base=base)


def turns(base=None, limit=2000, *, include_hidden=False):
    """The newest conversation turns. Turns the owner asked to forget ("ye baat bhool jao", H29) are left out unless
    include_hidden: the log itself is append-only, so they stay in the file, listed in data/hidden-turns.json."""
    try:
        lines = conversations_path(base).read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    hidden = set() if include_hidden else hidden_turns(base)
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("at") not in hidden:
            rows.append(row)
    return rows


# -- forgetting a turn (H29) ---------------------------------------------------------------------------------
def _hidden_path(base=None):
    return Path(base or PROJECT_ROOT) / "data" / "hidden-turns.json"


def hidden_turns(base=None):
    try:
        return set(json.loads(_hidden_path(base).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def _set_hidden(base, ats):
    path = _hidden_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(ats)), encoding="utf-8")


def forget_last(base=None):
    """Hide the latest owner turn from recall, search, learning and review; the row stays in the log."""
    last = next((t for t in reversed(turns(base, 200)) if owner_turn(t)), None)
    if last is None:
        return None
    _set_hidden(base, hidden_turns(base) | {last["at"]})
    from chutku import history_index
    history_index.set_hidden(base or PROJECT_ROOT, last["at"], True)
    return last


def unforget_last(base=None):
    """Bring back the most recently hidden turn ("wapas yaad karo")."""
    hidden = hidden_turns(base)
    if not hidden:
        return None
    latest = max(hidden)
    _set_hidden(base, hidden - {latest})
    from chutku import history_index
    history_index.set_hidden(base or PROJECT_ROOT, latest, False)
    return next((t for t in turns(base, 2000, include_hidden=True) if t.get("at") == latest), {"at": latest})


def earlier(goal, base=None, *, now=None):
    """Last 3 turns of today, plus up to 3 older turns that share words with the goal (newest first)."""
    now = now or time.time()
    rows = turns(base)
    today = datetime.fromtimestamp(now).date()
    same_day = [r for r in rows if datetime.fromtimestamp(r["at"]).date() == today][-3:]
    wanted = words(goal)
    older = []
    if wanted:
        scored = [(len(wanted & words(r["said"] + " " + r.get("reply", ""))), r["at"], r) for r in rows
                  if r not in same_day]
        older = [r for score, _, r in sorted(scored, key=lambda x: (x[0], x[1]), reverse=True) if score >= 1][:3]
    # Newest of today first, then the best older matches: _fit trims from the end, so the least relevant goes first.
    return [_brief(r) for r in list(reversed(same_day)) + older]


def _brief(row):
    when = datetime.fromtimestamp(row["at"]).strftime("%d %b %H:%M")
    # A reply written after reading a web page or a message is data, never an instruction for a later session.
    key = "chutku_data" if row.get("tainted") else "chutku"
    return {"when": when, "you": row["said"][:200], key: row.get("reply", "")[:200], "status": row.get("status")}


def talked_about(day: date, base=None, limit=580):
    rows = [r for r in turns(base) if datetime.fromtimestamp(r["at"]).date() == day and not _meta(r)]
    if not rows:
        return None
    head = f"{len(rows)} thing{'s' if len(rows) != 1 else ''} on {day.strftime('%d %b')}"
    lines = []
    for r in reversed(rows):   # newest first into the budget: a reply must stay under 600 characters
        line = (f"{datetime.fromtimestamp(r['at']).strftime('%H:%M')} {r['said'][:60]}"
                + (f" → {' '.join(r['reply'].split())[:45]}" if r.get("reply") else ""))
        if len(head) + 20 + sum(len(x) + 1 for x in lines) + len(line) > limit:
            break
        lines.insert(0, line)
    shown = f" (latest {len(lines)})" if len(lines) < len(rows) else ""
    return head + shown + ":\n" + "\n".join(lines)


def day_from_words(text, today=None):
    text = str(text or "").casefold()
    today = today or date.today()
    if re.search(r"\b(?:yesterday|kal)\b", text):
        return today - timedelta(days=1)
    if re.search(r"\b(?:parso|day before yesterday)\b", text):
        return today - timedelta(days=2)
    return today


def recent_topics(base=None, *, days=14, limit=8, now=None):
    """Words the owner used most in the last two weeks (2+ times), for the mind map."""
    from collections import Counter
    since = (now or time.time()) - days * 86400
    counts = Counter()
    for row in turns(base):
        if row["at"] >= since and not _meta(row):
            counts.update(w for w in words(row["said"]) if not w.isdigit() and len(w) > 2 and w not in _PLAIN)
    return [w for w, n in counts.most_common(limit) if n >= 2]


def mind_map(base=None, *, now=None):
    """Everything the mind map shows: people, facts, lists, habits and recent topics."""
    from chutku.mind import Mind
    data = Mind(Path(base or PROJECT_ROOT)).load()
    return {"people": data["people"], "facts": data["facts"], "lists": data["lists"],
            "habits": [h["text"] for h in (data.get("habits") or {}).values()],
            "topics": recent_topics(base, now=now)}


# -- the memory slice --------------------------------------------------------------------------------------

def about_you(goal, *, budget=1200, base=None, notes=None, include_earlier=True, now=None):
    """A compact, goal-relevant view of what the owner told Chutku; JSON-sized to at most `budget` characters."""
    from chutku.mind import Mind
    data = Mind(Path(base or PROJECT_ROOT)).load()
    wanted = words(goal)

    def score(*texts):
        return len(wanted & words(" ".join(str(t) for t in texts)))

    people = sorted(data["people"], key=lambda p: -score(p.get("name"), p.get("relation"), *p.get("aliases", [])))
    people = [{k: v for k, v in {"name": p["name"], "also_called": p.get("aliases") or None,
                                 "relation": p.get("relation") or None, "whatsapp": p.get("whatsapp") or None,
                                 "notes": p.get("notes")[-2:] if p.get("notes") else None}.items() if v}
              for p in people]
    facts = dict(sorted(data["facts"].items(), key=lambda kv: -score(*kv)))
    for row in notes or []:          # older memory.db notes ("remember city = Pune") are facts too
        facts.setdefault(row["key"], row["value"])
    open_items = []
    for name, items in data["lists"].items():
        for item in items:
            if not item.get("done"):
                open_items.append((score(name, item["text"]), item.get("added", ""), f"{name}: {item['text']}"))
    open_items = [text for _, _, text in sorted(open_items, reverse=True)]
    view = {"people": people, "facts": facts, "open": open_items}
    if include_earlier:
        view["earlier"] = earlier(goal, base, now=now)
    habits = data.get("habits") or {}
    if habits:
        view["habits"] = [h["text"] for h in sorted(habits.values(), key=lambda h: -h.get("count", 0))][:5]
    return _fit(view, budget)


def memory_usage(base=None, budget=None):
    """How much of what the owner told Chutku fits in one prompt (Phase 3b H3; Hermes shows "[67% — 1,474/2,200]").
    Each request sends only the most relevant part, up to `budget` characters (the local model's profile)."""
    if budget is None:
        from chutku.profiles import QWEN
        budget = QWEN.about_you_chars
    full = about_you("", budget=10 ** 9, base=base, include_earlier=False)
    chars = len(json.dumps(full, ensure_ascii=False))
    return {"chars": chars, "budget": budget, "percent": round(100 * chars / budget) if budget else None,
            "all_fits": chars <= budget,
            "summary": f"Yaad: {chars}/{budget} characters ({round(100 * chars / budget)}%) — "
                       + ("sab ek baar mein prompt mein jaata hai." if chars <= budget else
                          "har request ke saath sirf sabse kaam ki baatein jaati hain.")}


def _fit(view, budget):
    """Drop the least relevant tail of each part until the JSON fits (each list is already ordered best-first)."""
    def size():
        return len(json.dumps(view, ensure_ascii=False))
    order = ["habits", "earlier", "open", "facts", "people"]
    while size() > budget:
        for key in order:
            part = view.get(key)
            if part:
                if isinstance(part, dict):
                    part.pop(list(part)[-1])
                else:
                    part.pop(-1)   # every list is ordered most relevant first
                break
        else:
            break
    return {k: v for k, v in view.items() if v}
