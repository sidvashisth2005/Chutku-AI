"""Reflex Compiler (master plan S17): Chutku turns requests the model planned well into instant skills.

When two or more differently worded requests of the same shape ("tell me if VLC is installed", "tell me if Steam is
installed") were planned by the model and every step was verified, the words that changed between them become a
slot and the rest becomes a fixed phrase. The next request of that shape is planned without the model.

A skill is kept only when all of these hold:
- each example, matched by the phrase built from the others, gives back exactly its own verified plan;
- the phrase matches no logged request that used different tools, and no instant phrase whose tool differs;
- no step sends a message, deletes, runs code, changes files, needs the owner's own words, or carries private text;
- at match time each filled-in value passes the tool's schema, and an app name must be an installed app.

A skill is switched off by itself after one failed or unverified run, after "galat kiya" on a request it handled,
or when the earned-autonomy record of one of its steps says it keeps failing. Hand-written rules always win.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

from chutku.core.jsonstore import lock_for, write_json
from chutku.intents.lexicon import LEAD, TAIL

FILE = ("data", "reflexes.json")
MAX_SLOT = 60
_STOP = {"the", "a", "an", "to", "on", "in", "of", "for", "my", "me", "is", "it", "and", "ko", "ka", "ki", "ke", "se",
         "pe", "par", "mein", "me", "hai", "kya", "do", "karo"}
_INSTANT = {"quick", "reflex", "replay"}


def _path(base):
    return Path(base).joinpath(*FILE)


def normalize(goal):
    """Hindi script read as Hinglish, spaces collapsed, polite lead-ins and trailing fillers removed. Case is kept, so
    a filled-in value keeps the owner's spelling; every match ignores case."""
    from chutku.translit import roman
    text = " ".join(roman(str(goal)).split())
    text = re.sub(LEAD, "", text, flags=re.I)
    text = re.sub(TAIL, "", text, flags=re.I)
    return text.strip(" ,")


def skeleton(steps):
    return [[s["tool"], sorted(s.get("arguments") or {})] for s in steps]


# -- compiling ---------------------------------------------------------------------------------------------------------

def _eligible_tool(tool):
    # Screen, mouse and keyboard steps act on whatever is in front right now: never a fixed reflex.
    return (tool.base_risk <= 1 and not tool.name.startswith(("message.", "screen.", "mouse.", "keyboard.", "input.",
                                                                 "uia.", "clipboard."))
            and not tool.deletes and not tool.runs_code
            and tool.resource_access != "modify" and not tool.user_only and not tool.sensitive_argument_names)


def _eligible_row(row, registry):
    steps = row.get("steps") or []
    if row.get("rating") == "bad" or row.get("tainted") or not steps or not row.get("goal"):
        return False
    planners = set(row.get("planners") or [])
    if planners and planners <= _INSTANT:
        return False   # only plans the model made teach anything new
    for step in steps:
        try:
            tool = registry.get(step["tool"])
        except KeyError:
            return False
        if not _eligible_tool(tool):
            return False
    return True


def _values(row):
    """(step index, argument) -> value, for every argument of every step."""
    return {(i, arg): value for i, step in enumerate(row["steps"]) for arg, value in (step.get("arguments") or {}).items()}


def _key(value):
    return " ".join(value.split()).casefold() if isinstance(value, str) else value


def _slot_kind(tool_name, arg, value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if isinstance(value, int):
        return "int"
    return "app" if tool_name == "apps.launch" and arg == "name" else "str"


def _template(text, classes, values):
    """The phrase with each slot's value replaced by {sN}; None when a value is missing, repeated or overlapping."""
    spans = []
    for k, members in enumerate(classes):
        value = values[members[0]]
        needle = " ".join(str(value).split())
        if len(needle) < 2 and not isinstance(value, int):
            return None
        found = [m.span() for m in re.finditer(rf"(?<!\w){re.escape(needle)}(?!\w)", text, re.I)]
        if len(found) != 1:
            return None
        spans.append((found[0][0], found[0][1], k))
    spans.sort()
    out, at = [], 0
    for start, end, k in spans:
        if start < at:
            return None
        literal = text[at:start]
        if out and not re.search(r"\w", literal):
            return None   # two slots side by side cannot be told apart
        out.append(literal + "{s%d}" % k)
        at = end
    out.append(text[at:])
    template = "".join(out)
    literal_words = [w for w in re.findall(r"[a-z]+", re.sub(r"\{s\d+\}", " ", template).casefold())
                     if len(w) >= 3 and w not in _STOP]
    return template if literal_words else None


def regex_for(template, slots):
    parts = re.split(r"(\{s\d+\})", template)
    pattern = []
    for part in parts:
        slot = re.fullmatch(r"\{(s\d+)\}", part)
        if slot:
            name = slot.group(1)
            kind = slots[name]["kind"]
            pattern.append(rf"(?P<{name}>\d{{1,6}})" if kind == "int" else
                           rf"(?P<{name}>\w[\w .+&'-]{{0,{MAX_SLOT - 1}}}?)" if kind == "app" else
                           rf"(?P<{name}>\S.{{0,{MAX_SLOT - 1}}}?)")
        else:
            words = part.split()
            text = r"\s+".join(re.escape(w) for w in words)
            if part[:1].isspace() and pattern:
                text = r"\s+" + text
            if part[-1:].isspace() and words:
                text += r"\s+"
            if not words and part:
                text = r"\s+"
            pattern.append(text)
    return "^" + "".join(pattern) + "$"


def _fill(reflex, match):
    steps = copy.deepcopy(reflex["steps"])
    for name, slot in reflex["slots"].items():
        raw = " ".join(match.group(name).split())
        value = int(raw) if slot["kind"] == "int" else raw
        for i, arg in slot["fills"]:
            steps[i]["arguments"][arg] = value
    return steps


def _same_plan(filled, row, reflex):
    slot_args = {(i, arg) for slot in reflex["slots"].values() for i, arg in slot["fills"]}
    if [s["tool"] for s in filled] != [s["tool"] for s in row["steps"]]:
        return False
    for i, (mine, theirs) in enumerate(zip(filled, row["steps"])):
        if set(mine["arguments"]) != set(theirs.get("arguments") or {}):
            return False
        for arg, value in mine["arguments"].items():
            other = theirs["arguments"][arg]
            if (_key(value) != _key(other)) if (i, arg) in slot_args else (value != other):
                return False
    return True


def _candidate(rows, tools):
    """One skill from rows of one shape, or (None, reason)."""
    texts = [normalize(r["goal"]) for r in rows]
    values = [_values(r) for r in rows]
    varying = sorted(k for k in values[0] if len({json.dumps(_key(v[k])) for v in values}) > 1)
    if not varying:
        return None, "nothing changes between the examples"
    if any(_slot_kind(tools[i], arg, values[0][(i, arg)]) is None for i, arg in varying):
        return None, "a changing value is not text or a number"
    classes = []   # arguments that always carry the same value share one slot
    for key in varying:
        for members in classes:
            if all(_key(v[members[0]]) == _key(v[key]) for v in values):
                members.append(key)
                break
        else:
            classes.append([key])
    templates = {_template(text, classes, v) for text, v in zip(texts, values)}
    if len(templates) != 1 or None in templates:
        return None, "the examples are not worded the same way around the changing words"
    template = templates.pop()
    slots = {f"s{k}": {"kind": _slot_kind(tools[members[0][0]], members[0][1], values[0][members[0]]),
                       "fills": [list(m) for m in members], "label": members[0][1]} for k, members in enumerate(classes)}
    steps = [{"tool": s["tool"], "arguments": dict(s.get("arguments") or {}), "purpose": s.get("purpose") or s["tool"]}
             for s in rows[0]["steps"]]
    reflex = {"template": template, "slots": slots, "steps": steps, "regex": regex_for(template, slots),
              "example_values": {name: str(values[0][tuple(slot["fills"][0])]) for name, slot in slots.items()}}
    # Leave one out: the phrase built from the other examples gives back each example's exact plan.
    for index, (row, text) in enumerate(zip(rows, texts)):
        others = [t for j, t in enumerate(texts) if j != index]
        other_templates = {_template(t, classes, v) for j, (t, v) in enumerate(zip(texts, values)) if j != index}
        if not others or other_templates != {template}:
            return None, "leave-one-out: the other examples do not give the same phrase"
        match = re.match(regex_for(template, slots), text, re.I)
        if match is None or not _same_plan(_fill(reflex, match), row, reflex):
            return None, f"leave-one-out: {row['goal'][:60]!r} does not come back as its own plan"
    return reflex, None


def _phrase_cases():
    """The instant phrases (scripts/check_phrases.py CASES) with their expected tools."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_phrases.py"
    try:
        spec = importlib.util.spec_from_file_location("_chutku_phrases", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return list(module.CASES)
    except (OSError, AttributeError, ImportError, SyntaxError):
        return []


def _collision(reflex, base, rows):
    """The phrase must not match any request that was done with different tools."""
    pattern = re.compile(reflex["regex"], re.I)
    tools = [s["tool"] for s in reflex["steps"]]
    from chutku import recall
    for turn in recall.turns(base, 2000):
        if turn.get("status") == "done" and turn.get("tools") and pattern.match(normalize(turn.get("said", ""))) \
                and list(turn["tools"]) != tools:
            return f"would also catch {turn['said'][:60]!r}, which used {', '.join(turn['tools'][:3])}"
    for row in rows:
        if pattern.match(normalize(row["goal"])) and [s["tool"] for s in row["steps"]] != tools:
            return f"would also catch {row['goal'][:60]!r}, which used {row['steps'][0]['tool']}"
    for phrase, tool in _phrase_cases():
        if pattern.match(normalize(phrase)) and tool not in tools:
            return f"would also catch the instant phrase {phrase!r} ({tool})"
    return None


def _id(reflex):
    return hashlib.sha256(json.dumps([skeleton(reflex["steps"]), reflex["template"].casefold()]).encode()).hexdigest()[:10]


def compile_all(base, registry, only=None):
    """Build skills from the worked examples. ``only`` limits it to one plan shape (after a new verified session).
    Existing skills keep their counts and on/off state. Returns what was added and what was turned down, with why."""
    from chutku import experience
    rows = [r for r in experience.load(base) if _eligible_row(r, registry)]
    groups = {}
    for row in rows:
        shape = json.dumps(skeleton(row["steps"]))
        if only is None or shape == json.dumps(only):
            groups.setdefault(shape, []).append(row)
    all_rows = experience.load(base)
    added, rejected = [], []
    with lock_for(_path(base)):
        skills = load(base)
        known = {s["id"]: s for s in skills}
        for shape, members in groups.items():
            distinct = {}
            for row in members:
                distinct.setdefault(normalize(row["goal"]).casefold(), row)
            members = list(distinct.values())
            if len(members) < 2:
                continue
            tools = [s["tool"] for s in members[0]["steps"]]
            # Rows of one shape may be worded in several ways: each wording with 2+ examples is its own candidate.
            clusters = _clusters(members, tools)
            if not clusters:
                rejected.append({"examples": [r["goal"][:80] for r in members][:4],
                                 "reason": _candidate(members[:2], tools)[1]})
            for cluster in clusters:
                reflex, reason = _candidate(cluster, tools)
                if reflex is None:
                    rejected.append({"examples": [r["goal"][:80] for r in cluster][:4], "reason": reason})
                    continue
                reason = _collision(reflex, base, all_rows)
                if reason:
                    rejected.append({"template": reflex["template"], "reason": reason})
                    continue
                reflex["id"] = _id(reflex)
                if reflex["id"] in known:
                    known[reflex["id"]]["examples"] = sorted({*known[reflex["id"]]["examples"],
                                                              *(r["goal"][:120] for r in cluster)})[:8]
                    continue
                reflex.update({"examples": [r["goal"][:120] for r in cluster][:8], "created": time.time(), "hits": 0,
                               "passes": 0, "fails": 0, "enabled": True})
                skills.append(reflex)
                known[reflex["id"]] = reflex
                added.append(reflex["template"])
        write_json(_path(base), skills)
    return {"added": added, "rejected": rejected, "skills": len(skills)}


def _clusters(rows, tools):
    """Split rows of one shape into groups worded the same way around their changing values."""
    remaining, out = list(rows), []
    while len(remaining) >= 2:
        seed = remaining[0]
        group = [seed] + [r for r in remaining[1:] if _candidate([seed, r], tools)[0] is not None]
        if len(group) > 2 and _candidate(group, tools)[0] is None:
            group = group[:2]
        if len(group) >= 2:
            out.append(group)
        remaining = [r for r in remaining if all(r is not g for g in group)]
    return out


# -- using -------------------------------------------------------------------------------------------------------------

def load(base):
    try:
        data = json.loads(_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _update(base, reflex_id, change):
    with lock_for(_path(base)):
        skills = load(base)
        for skill in skills:
            if skill.get("id") == reflex_id:
                change(skill)
                write_json(_path(base), skills)
                return skill
    return None


def set_enabled(base, reflex_id, enabled, reason=""):
    def change(skill):
        skill["enabled"] = bool(enabled)
        skill["disabled_reason"] = "" if enabled else (reason or "switched off by the owner")
    return _update(base, reflex_id, change)


def feedback(base, reflex_id, passed, goal=""):
    """After a session a skill planned: count it; any failure switches the skill off."""
    def change(skill):
        skill["hits"] = skill.get("hits", 0) + 1
        skill["passes" if passed else "fails"] = skill.get("passes" if passed else "fails", 0) + 1
        if not passed:
            skill["enabled"] = False
            skill["disabled_reason"] = f"did not work for {goal[:80]!r}"
    return _update(base, reflex_id, change)


def on_bad_rating(base, goal):
    """"galat kiya" on a request: every skill that would plan it is switched off."""
    text = normalize(goal)
    turned_off = []
    for skill in load(base):
        if skill.get("enabled") and re.match(skill["regex"], text, re.I):
            set_enabled(base, skill["id"], False, f"owner said it was wrong for {goal[:80]!r}")
            turned_off.append(skill["id"])
    return turned_off


def match(base, goal, runtime, apps=None):
    """(proposal, skill id) for the most specific enabled skill that fits this request, else None."""
    from chutku.tools.registry import check_schema
    text = normalize(goal)
    skills = [s for s in load(base) if s.get("enabled")]
    skills.sort(key=lambda s: -len(re.sub(r"\{s\d+\}", "", s["template"])))
    for skill in skills:
        found = re.match(skill["regex"], text, re.I)
        if found is None:
            continue
        steps = _fill(skill, found)
        try:
            for step in steps:
                tool = runtime.registry.get(step["tool"])
                if not _eligible_tool(tool):
                    raise ValueError("no longer an instant-safe tool")
                check_schema(step["arguments"], tool.argument_schema)
                tool.validate_arguments(step["arguments"])
                if step["tool"] == "apps.launch":
                    from chutku.tools.everyday import resolve_app, start_apps
                    step["arguments"]["name"] = resolve_app(step["arguments"], apps if apps is not None
                                                            else start_apps())["name"]
        except (KeyError, ValueError, OSError):
            continue   # a filled-in value that does not fit (or an app that is not installed): no match
        from chutku.core.ledger import unreliable
        weak = next((s for s in steps if unreliable(_reliability(runtime, s))), None)
        if weak is not None:
            set_enabled(base, skill["id"], False, f"{weak['tool']} keeps failing (earned autonomy)")
            continue
        for step in steps:
            step["purpose"] = _purpose(skill, step["purpose"], found)
        actions_only = all(runtime.registry.get(s["tool"]).base_risk == 1 for s in steps)
        reply = ("Done: " + "; ".join(s["purpose"] for s in steps) + ".") if actions_only else ""
        return ({"status": "continue", "reply": reply, "declared_plan": [s["purpose"] for s in steps],
                 "next_steps": steps, "finish": actions_only}, skill["id"])
    return None


def _reliability(runtime, step):
    try:
        return runtime.reliability(runtime.registry.get(step["tool"]), step["arguments"])
    except (AttributeError, KeyError):
        return None


def _purpose(skill, purpose, found):
    for name, old in (skill.get("example_values") or {}).items():
        if old and len(old) >= 2:
            purpose = re.sub(rf"(?<!\w){re.escape(old)}(?!\w)", lambda _m, n=name: " ".join(found.group(n).split()),
                             purpose, flags=re.I)
    return purpose[:120]


def summary(base):
    skills = load(base)
    this_week, last_week = instant_share(base)
    return {"skills": [{"id": s["id"], "phrase": display(s), "examples": s.get("examples", [])[:3],
                        "hits": s.get("hits", 0), "passes": s.get("passes", 0), "fails": s.get("fails", 0),
                        "enabled": bool(s.get("enabled")), "disabled_reason": s.get("disabled_reason", ""),
                        "tools": [st["tool"] for st in s["steps"]]} for s in skills],
            "count": len(skills), "enabled": sum(1 for s in skills if s.get("enabled")),
            "instant_this_week": this_week, "instant_last_week": last_week}


def display(skill):
    return re.sub(r"\{(s\d+)\}", lambda m: "{" + skill["slots"][m.group(1)]["label"] + "}", skill["template"])


def instant_share(base, now=None):
    """Share of requests answered without the model (rules, learned skills, exact repeats), this week and last week."""
    from chutku import recall
    now = now or time.time()
    weeks = [[0, 0], [0, 0]]
    for turn in recall.turns(base, 5000):
        planners = turn.get("planners") or []
        age = now - float(turn.get("at") or 0)
        if not planners or not 0 <= age < 14 * 86400:
            continue
        week = weeks[0 if age < 7 * 86400 else 1]
        week[1] += 1
        week[0] += all(p in _INSTANT for p in planners)
    return tuple(round(hit / total, 3) if total else None for hit, total in weeks)


def after_session(base, session, runtime, recorded):
    """Count a skill's run (a failure switches it off), or learn from a newly verified model plan of this shape."""
    snap = session.snapshot()
    planners = snap.get("planners") or []
    used = next((str(p.get("backend"))[7:] for p in planners if str(p.get("backend") or "").startswith("reflex:")),
                None)
    if used:
        if snap["status"] in {"done", "failed"}:   # waiting, stopped by the owner or unclear: not a verdict
            steps = snap.get("steps") or []
            feedback(base, used, snap["status"] == "done" and bool(steps)
                     and all(s["state"] == "COMPLETED" for s in steps), snap["goal"])
        return None
    if recorded and any(p.get("planner") not in _INSTANT for p in planners):
        return compile_all(base, runtime.registry, only=skeleton(snap["steps"]))
    return None


class ReflexPlanner:
    """Planner facade for the session: first round only, after the hand-written rules."""
    name = "reflex"

    def __init__(self, base):
        self.base = Path(base)

    def propose(self, session, runtime, check=None):
        from chutku.agent_loop import validate_proposal
        found = match(self.base, session.goal, runtime)
        if found is None:
            raise LookupError("no learned skill")
        raw, reflex_id = found
        allowed = {tool.name for tool in runtime.registry.list()}
        return validate_proposal(raw, runtime, allowed), {"planner": self.name, "seconds": 0,
                                                          "backend": "reflex:" + reflex_id}
