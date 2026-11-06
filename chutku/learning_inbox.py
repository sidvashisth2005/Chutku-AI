"""What Chutku learns, with the owner's OK (Hermes background review + skills, done Chutku's way, 2026-11-07).

Nothing a review finds is saved silently: it goes to the learning inbox (data/inbox.json, 14 days), and the owner keeps
or discards it ("kya seekha", "sab rakh lo", "number 2 rakho" / "number 2 hatao"). Rules only, no model:
- H10 lesson: a request failed (or was stopped / unclear) and within 10 minutes the same request VERIFIED with other
  tools -> "for <goal>: use <these>, avoid <those>". Kept lessons (data/lessons.json) reach the planner for similar
  goals (CONTEXT.lessons, top 2); a lesson used by a request that then fails is disabled.
- H11 procedure draft: a VERIFIED, untainted request the model planned in 3+ steps -> a SKILL.md draft (steps as text).
- H27 "ye seekh lo: <file or link>": a procedure draft from a document (a web page's text stays marked learned-web).
H13 curator (Night Shift): lessons unused for 30 days go stale, for 60 days archived; imported procedures unread for
60 days move to _procedures/.archive. Never deleted; procedures the owner added are not touched.
H28 journey(): everything learned, newest first, with counts.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import time

INBOX_DAYS, INBOX_MAX = 14, 50
LESSON_WINDOW = 600
STALE_DAYS, ARCHIVE_DAYS = 30, 60
_NAME = re.compile(r"[^a-z0-9]+")


def _path(base, name):
    return Path(base) / "data" / name


def _load(base, name):
    try:
        data = json.loads(_path(base, name).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(base, name, rows):
    path = _path(base, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)


# -- the inbox ---------------------------------------------------------------------------------------------------
def items(base, now=None):
    now = now or time.time()
    return [i for i in _load(base, "inbox.json") if now - i["created"] < INBOX_DAYS * 86400]


def propose(base, kind, text, payload, why, now=None):
    """Add one proposal (a duplicate of a waiting one is ignored); returns it, or None."""
    from chutku import scan
    if scan.threats(text):
        return None   # H3: nothing that hides characters or gives orders is offered for saving
    rows = items(base, now)
    if any(i["kind"] == kind and i["text"] == text for i in rows):
        return None
    item = {"id": max([i["id"] for i in _load(base, "inbox.json")] or [0]) + 1, "kind": kind, "text": text[:400],
            "payload": payload, "why": why[:200], "created": now or time.time()}
    _save(base, "inbox.json", (rows + [item])[-INBOX_MAX:])
    return item


def describe(rows):
    if not rows:
        return "Inbox khali hai: abhi kuch naya seekhne ko nahi mila."
    names = {"lesson": "Galti se seekha", "procedure": "Naya tareeka"}
    return "\n".join(f"{i['id']}. {names.get(i['kind'], i['kind'])}: {i['text']}" for i in rows) + \
        "\nRakhna hai? \"sab rakh lo\", \"number N rakho\" ya \"number N hatao\"."


def keep(base, item_id=None):
    """Save one proposal (or all): lessons into lessons.json, procedures as SKILL.md. Returns the kept items."""
    rows = items(base)
    chosen = [i for i in rows if item_id is None or i["id"] == item_id]
    if item_id is not None and not chosen:
        raise ValueError(f"No inbox item {item_id}.")
    for item in chosen:
        if item["kind"] == "lesson":
            lessons = _load(base, "lessons.json")
            lessons.append({**item["payload"], "id": max([lesson["id"] for lesson in lessons] or [0]) + 1,
                            "state": "active", "hits": 0, "created": time.time(), "used": time.time()})
            _save(base, "lessons.json", lessons)
        elif item["kind"] == "procedure":
            _write_procedure(base, item["payload"])
    _save(base, "inbox.json", [i for i in rows if i not in chosen])
    return chosen


def discard(base, item_id):
    rows = items(base)
    if not any(i["id"] == item_id for i in rows):
        raise ValueError(f"No inbox item {item_id}.")
    _save(base, "inbox.json", [i for i in rows if i["id"] != item_id])


def _write_procedure(base, payload):
    from chutku.skill_import import procedures_root
    name, text = payload["name"], payload["text"]
    if (procedures_root(base) / name).exists():   # the folder name and the SKILL.md name must stay the same
        fresh = f"{name[:50]}-{int(time.time())}"
        text, name = text.replace(f"name: {name}\n", f"name: {fresh}\n", 1), fresh
    folder = procedures_root(base) / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    (folder / "source.json").write_text(json.dumps({"learned": payload.get("source", "session")}), encoding="utf-8")


def _slug(text, limit=40):
    """A procedure name skill_import accepts: lowercase, starts with a letter, 3+ characters."""
    slug = _NAME.sub("-", text.casefold()).strip("-")[:limit].strip("-")
    return slug if re.match(r"^[a-z][a-z0-9-]{2,}$", slug) else ("p-" + slug if len(slug) >= 1 else "procedure")


def procedure_text(name, description, steps, source):
    lines = [f"- {s}" if not re.match(r"^\s*(?:\d+[.)]|-)\s", s) else s for s in steps]
    return (f"---\nname: {name}\ndescription: {description[:60]}\nsource: {source}\n---\n"
            "## Procedure\n" + "\n".join(lines) + "\n")


# -- the review after each request (rules only) --------------------------------------------------------------------
def after_session(base, session):
    """Look at a finished request; returns the proposals made (possibly none)."""
    from chutku import recall
    from chutku.learning import _same_request
    snap = session.snapshot()
    made = []
    _demote(base, session, snap)
    if snap["status"] != "done" or snap.get("tainted") or snap.get("suspicious"):
        return made
    steps = [s for s in snap["steps"] if s.get("state") == "COMPLETED"]
    if not steps or len(steps) != len(snap["steps"]) or any(s["tool"].startswith("message.") for s in steps):
        return made
    planners = {str(p.get("planner", "")) for p in snap.get("planners", [])}
    tools = [s["tool"] for s in steps]
    previous = [t for t in recall.turns(base, 50) if recall.owner_turn(t)]
    if previous and previous[-1].get("said") == snap["goal"] and previous[-1].get("status") == "done":
        previous = previous[:-1]   # this request's own log line (the same wording retried still counts)
    if previous:
        last = previous[-1]
        if last.get("status") in ("failed", "stopped", "clarify") and time.time() - last["at"] <= LESSON_WINDOW \
                and _same_request(last["said"], snap["goal"], gap=time.time() - last["at"]) \
                and sorted(set(last.get("tools") or [])) != sorted(set(tools)):
            avoid = sorted(set(last.get("tools") or []) - set(tools))
            note = f"For '{snap['goal'][:80]}': {', '.join(tools[:6])} worked" + \
                   (f"; {', '.join(avoid[:4])} did not" if avoid else "")
            item = propose(base, "lesson", note, {"when": snap["goal"][:200], "use": tools[:8], "avoid": avoid[:6],
                                                  "note": note}, "a failed try was fixed right after")
            made += [item] if item else []
    if len(steps) >= 3 and planners and not planners <= {"quick", "reflex"}:
        name = _slug(snap["goal"])
        lines = [f"{n}. {s.get('purpose') or s['tool']} ({s['tool']})" for n, s in enumerate(steps, 1)]
        item = propose(base, "procedure", f"'{snap['goal'][:80]}' in {len(steps)} steps",
                       {"name": name, "text": procedure_text(name, snap["goal"], lines, "session"),
                        "source": "session"}, "a verified multi-step task")
        made += [item] if item else []
    return made


def _demote(base, session, snap):
    """A lesson that was offered to a request which then failed is disabled (H10 demotion); one that helped counts."""
    used = {lesson.get("id") for lesson in ((session.context.get("lessons") or {}).get("items") or [])}
    if not used:
        return
    lessons = _load(base, "lessons.json")
    for lesson in lessons:
        if lesson["id"] in used:
            if snap["status"] == "failed":
                lesson["state"] = "disabled"
            elif snap["status"] == "done":
                lesson["hits"] += 1
                lesson["used"] = time.time()
    _save(base, "lessons.json", lessons)


def relevant_lessons(base, goal, limit=2):
    from chutku.recall import words
    wanted = set(words(goal))
    scored = []
    for lesson in _load(base, "lessons.json"):
        if lesson.get("state") != "active":
            continue
        overlap = len(wanted & set(words(lesson["when"])))
        if overlap >= max(1, len(set(words(lesson["when"]))) // 3):
            scored.append((-overlap, lesson["id"], lesson))
    return [{"id": lesson["id"], "note": lesson["note"], "use": lesson["use"], "avoid": lesson["avoid"]}
            for *_rank, lesson in sorted(scored)[:limit]]


# -- H27: learn on request ---------------------------------------------------------------------------------------
def learn_from(base, path=None, url=None):
    """A procedure draft from a local .md/.txt file or a public web page; it goes to the inbox."""
    if url:
        from chutku.tools.internet import fetch, html_to_text
        html, final = fetch(str(url).strip())
        page_title, page_text = html_to_text(html)
        text, origin, title = page_text[:20_000], "learned-web", page_title or final
    else:
        path = Path(str(path or "").strip().strip("\"'"))
        if path.suffix.casefold() not in {".md", ".txt"} or not path.is_file():
            raise ValueError("Give a .md or .txt file path, or a web link.")
        text, origin, title = path.read_text(encoding="utf-8", errors="replace")[:20_000], "learned-file", path.stem
    steps = [line.strip() for line in text.splitlines() if re.match(r"^\s*(?:\d+[.)]|[-*])\s+\S", line)][:40]
    if not steps:
        raise ValueError("I found no numbered or bulleted steps to learn from.")
    name = _slug(title)
    item = propose(base, "procedure", f"'{title[:60]}' ({len(steps)} steps, from {origin})",
                   {"name": name, "text": procedure_text(name, f"Learned from {title}", steps, origin),
                    "source": origin}, "you asked me to learn it")
    if item is None:
        raise ValueError("That is already waiting in the inbox, or it contains hidden characters.")
    return item


# -- H13: curator ------------------------------------------------------------------------------------------------
def curate(base, now=None):
    """Rules only; archive, never delete. Owner-added procedures are not touched."""
    from chutku.skill_import import procedures_root
    now = now or time.time()
    report = {"stale_lessons": 0, "archived_lessons": 0, "archived_procedures": []}
    lessons = _load(base, "lessons.json")
    for lesson in lessons:
        age = (now - lesson.get("used", lesson.get("created", now))) / 86400
        if lesson.get("state") in ("active", "stale") and age >= ARCHIVE_DAYS:
            lesson["state"], report["archived_lessons"] = "archived", report["archived_lessons"] + 1
        elif lesson.get("state") == "active" and age >= STALE_DAYS:
            lesson["state"], report["stale_lessons"] = "stale", report["stale_lessons"] + 1
    _save(base, "lessons.json", lessons)
    root = procedures_root(base)
    for source in sorted(root.glob("*/source.json")) if root.exists() else []:
        try:
            info = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not info.get("repo"):
            continue   # added by the owner or learned with the owner's OK: kept
        last = info.get("last_read") or source.stat().st_mtime
        if (now - last) / 86400 >= ARCHIVE_DAYS:
            target = root / ".archive" / source.parent.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source.parent), str(target))
            report["archived_procedures"].append(source.parent.name)
    return report


# -- H28: the learning journey -------------------------------------------------------------------------------------
def journey(base):
    from chutku.skill_import import list_procedures
    from chutku.mind import Mind
    lessons = _load(base, "lessons.json")
    reflexes = _load(base, "reflexes.json")
    try:
        mind = Mind(base).load()
    except (OSError, ValueError, AttributeError):
        mind = {}
    counts = {"lessons": sum(1 for lesson in lessons if lesson.get("state") == "active"),
              "procedures": len(list_procedures(base)), "instant_skills": len(reflexes),
              "people": len(mind.get("people") or {}), "facts": len(mind.get("facts") or {}),
              "habits": len(mind.get("habits") or []), "waiting_in_inbox": len(items(base))}
    latest = sorted(([lesson.get("created", 0), "lesson", lesson["note"]] for lesson in lessons), reverse=True)[:3]
    lines = [f"{n} {k.replace('_', ' ')}" for k, n in counts.items() if n]
    summary = ("Ab tak seekha: " + ", ".join(lines) + "." if lines else "Abhi tak kuch khaas nahi seekha.")
    if latest:
        summary += " Naya: " + "; ".join(f"{datetime.fromtimestamp(at).strftime('%d %b')}: {text[:60]}"
                                         for at, _kind, text in latest)
    return {"counts": counts, "summary": summary}


def register_learning_tools(registry, base):
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification
    from chutku.tools.everyday import EMPTY_ARGUMENT_SCHEMA, _validate_none

    def safely(work):
        def run(arguments, _context):
            try:
                return ToolResult(work(arguments), Verification.PASS)
            except (ValueError, OSError) as error:
                return ToolResult({"error": str(error)[:300]}, Verification.FAIL)
        return run

    def one(name, spec):
        schema = {"type": "object", "properties": {name: spec}, "required": [name], "additionalProperties": False}

        def validate(arguments):
            if set(arguments) != {name}:
                raise ValueError(f"Provide {name}.")
        return schema, validate

    item_schema, item_check = one("id", {"type": "integer", "minimum": 1, "maximum": 100000})
    source_schema = {"type": "object", "properties": {"path": {"type": "string", "minLength": 4, "maxLength": 400},
                                                      "url": {"type": "string", "minLength": 8, "maxLength": 400}},
                     "additionalProperties": False}

    def source_check(arguments):
        if len(set(arguments) & {"path", "url"}) != 1 or set(arguments) - {"path", "url"}:
            raise ValueError("Give either a file path or a web link.")
    registry.register(Tool("learning.inbox", "What Chutku proposes to learn (lessons from mistakes, new procedures), "
        "waiting for the owner's OK.", Risk.OBSERVATION, safely(lambda _a: {"summary": describe(items(base)),
                                                                            "items": items(base)}),
        _validate_none, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="inbox_listed"))
    registry.register(Tool("learning.keep_all", "Keep everything in the learning inbox.", Risk.REVERSIBLE,
        safely(lambda _a: {"summary": f"Rakh liya: {len(keep(base))} cheez(en)."}), _validate_none,
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="compensatable", success_predicate="inbox_kept"))
    registry.register(Tool("learning.keep", "Keep one learning inbox item.", Risk.REVERSIBLE,
        safely(lambda a: {"summary": f"Number {a['id']} rakh liya." if keep(base, a["id"]) else "Kuch nahi mila."}),
        item_check, argument_schema=item_schema, reversibility="compensatable", success_predicate="inbox_kept"))
    registry.register(Tool("learning.discard", "Discard one learning inbox item.", Risk.REVERSIBLE,
        safely(lambda a: (discard(base, a["id"]), {"summary": f"Number {a['id']} hata diya."})[1]), item_check,
        argument_schema=item_schema, reversibility="compensatable", success_predicate="inbox_discarded"))
    registry.register(Tool("learning.learn", "Learn a procedure from a local .md/.txt file or a public web page "
        "(\"ye seekh lo\"); the draft waits in the learning inbox.", Risk.REVERSIBLE,
        safely(lambda a: {"summary": "Seekh liya, inbox mein hai: "
                                     + learn_from(base, a.get("path"), a.get("url"))["text"]}),
        source_check, argument_schema=source_schema, network_egress=True, resource_access="observe",
        reversibility="compensatable", success_predicate="draft_in_inbox"))
    registry.register(Tool("learning.journey", "Everything Chutku has learned so far: lessons, procedures, instant "
        "skills, people, facts, habits.", Risk.OBSERVATION, safely(lambda _a: journey(base)), _validate_none,
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable", success_predicate="journey_listed"))
