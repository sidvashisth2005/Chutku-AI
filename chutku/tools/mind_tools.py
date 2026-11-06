"""Tools over the owner's personal memory (chutku/mind.py): people, facts about the owner, and lists."""
from __future__ import annotations

from chutku import mind
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

_TEXT = {"type": "string", "minLength": 1, "maxLength": 500}
_SHORT = {"type": "string", "minLength": 1, "maxLength": 60}


def _run(work):
    try:
        return ToolResult(work(), Verification.PASS)
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)


def _person(arguments, _context):
    return _run(lambda: {"person": mind.default().remember_person(
        arguments["name"], aliases=arguments.get("aliases", []), relation=arguments.get("relation", ""),
        whatsapp=arguments.get("whatsapp", ""), phone=arguments.get("phone", ""), note=arguments.get("note", ""),
        email=arguments.get("email", ""))})


def _fact(arguments, _context):
    return _run(lambda: {"fact": mind.default().set_fact(arguments["key"], arguments["value"])})


def _add(arguments, _context):
    return _run(lambda: {"item": mind.default().add(arguments["list"], arguments["text"])})


def _done(arguments, _context):
    return _run(lambda: {"item": mind.default().mark_done(arguments["list"], arguments["id"],
                                                          arguments.get("done", True))})


def _who(arguments, _context):
    person = mind.default().find_person(arguments["name"])
    if person is None:
        return ToolResult({"name": arguments["name"], "known": False}, Verification.PASS)
    return ToolResult({"name": arguments["name"], "known": True, "person": person}, Verification.PASS,
                      {"known": True, "person": "[REDACTED]"})   # phone numbers stay out of the audit trail


def _show(arguments, _context):
    data = mind.default().summary()
    part = arguments.get("part", "all")
    if part == "people":
        data = {"people": data["people"]}
    elif part == "facts":
        data = {"facts": data["facts"]}
    elif part != "all":
        name = mind.LIST_WORDS.get(mind.norm(part), part)
        data = {"lists": {name: mind.default().load()["lists"].get(name, [])}}
    if part == "all":   # the memory meter (Phase 3b H3)
        from chutku.recall import memory_usage
        try:
            data["memory_meter"] = memory_usage(mind.PROJECT_ROOT)["summary"]
        except (OSError, ValueError):
            pass
    return ToolResult({"part": part, **data}, Verification.PASS, {"part": part, "content": "[REDACTED]"})


def _forget(arguments, _context):
    return _run(lambda: mind.default().forget(arguments["kind"], arguments["key"]))


def _feedback(arguments, _context):
    from chutku import learning
    goal = learning.rate_latest(arguments["rating"])
    if goal is None:
        return ToolResult({"rated": None, "note": "No earlier task to rate yet."}, Verification.PASS)
    return ToolResult({"rated": goal, "rating": arguments["rating"]}, Verification.PASS)


def _map(arguments, _context):
    from chutku.dashboard import _session_file
    import json
    import webbrowser
    try:
        url = json.loads(_session_file(mind.PROJECT_ROOT).read_text(encoding="utf-8"))["url"]
    except (OSError, ValueError, KeyError):
        return ToolResult({"error": "The dashboard is not running."}, Verification.FAIL)
    url = url + ("&" if "#" in url else "#") + "tab=mind"
    try:
        from chutku.tools.everyday import browser_exe, preferred_browser
        import subprocess
        exe = browser_exe(preferred_browser())
        if exe:
            subprocess.Popen([exe, url], shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    data = mind.default().summary()
    return ToolResult({"opened": "mind map", "people": len(data["people"]), "facts": len(data["facts"]),
                       "lists": {k: len(v) for k, v in data["lists"].items()}}, Verification.PASS)


def _offline(arguments, _context):
    from chutku.core.preferences import Preferences
    from chutku import online
    prefs = Preferences(mind.PROJECT_ROOT)
    before = prefs.load().get("offline_mode", False)
    prefs.update({"offline_mode": bool(arguments["on"])})
    online.forget()
    now = prefs.load()["offline_mode"]
    return ToolResult({"offline_mode": now, "was": before}, Verification.PASS if now == bool(arguments["on"])
                      else Verification.FAIL)


# Phase 4 switches (2026-10-29), each a reversible preference: the Gemini Live talk mode (now opt-in), Hindi listening
# (Whisper picks English or Hindi), the cloud-first brain, and a 24 h window in which room talk is written to heard.jsonl.
SWITCHES = {
    "conversation": ("conversation", lambda on: bool(on)),
    "hindi_listening": ("stt_language", lambda on: "en|hi" if on else "en"),
    "cloud_brain": ("brain", lambda on: "cloud_first" if on else "local"),
    "heard_debug": ("heard_ambient_until", lambda on: (__import__("time").time() + 86400.0) if on else 0.0),
}


def _switch(arguments, _context):
    from chutku.core.preferences import Preferences
    key, value_for = SWITCHES[arguments["setting"]]
    prefs = Preferences(mind.PROJECT_ROOT)
    before = prefs.load()[key]
    wanted = value_for(arguments["on"])
    prefs.update({key: wanted})
    now = prefs.load()[key]
    return ToolResult({"setting": arguments["setting"], "preference": key, "now": now, "was": before},
                      Verification.PASS if now == wanted else Verification.FAIL)


def _reply_style(arguments, _context):
    """H17: how replies sound (normal / formal / short / masti); the persona and identity stay the same."""
    from chutku.core.preferences import REPLY_STYLES, Preferences
    if arguments.get("style") not in REPLY_STYLES:
        return ToolResult({"error": "Choose normal, formal, short or masti."}, Verification.FAIL)
    prefs = Preferences(mind.PROJECT_ROOT)
    before = prefs.load()["reply_style"]
    prefs.update({"reply_style": arguments["style"]})
    now = prefs.load()["reply_style"]
    return ToolResult({"reply_style": now, "was": before}, Verification.PASS if now == arguments["style"] else
                      Verification.FAIL)


def _check(required, optional=()):
    def validate(arguments):
        if not isinstance(arguments, dict) or not set(required) <= set(arguments) or set(arguments) - set(required) - set(optional):
            raise ValueError(f"Provide {', '.join(required)}" + (f" (optional: {', '.join(optional)})." if optional else "."))
    return validate


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def register_mind_tools(registry):
    registry.register(Tool("mind.person", "Remember a person in the owner's memory: name, nicknames/aliases (e.g. 'gf', "
        "'mammi', 'DL wale sir'), relation, exact WhatsApp chat name and/or phone. Merges into an existing person.",
        Risk.REVERSIBLE, _person, _check(("name",), ("aliases", "relation", "whatsapp", "phone", "note", "email")),
        argument_schema=_schema({"name": _SHORT, "aliases": {"type": "array", "items": _SHORT, "maxItems": 20},
                                 "relation": _SHORT, "whatsapp": _SHORT,
                                 "phone": {"type": "string", "pattern": r"^\+?[0-9 -]{7,20}$"}, "note": _TEXT,
                                 "email": {"type": "string", "minLength": 6, "maxLength": 254}},
                                ("name",)),
        reversibility="compensatable", success_predicate="person_stored"))
    registry.register(Tool("mind.fact", "Remember one fact about the owner (e.g. key 'home', value 'Pune').",
        Risk.REVERSIBLE, _fact, _check(("key", "value")), argument_schema=_schema({"key": _SHORT, "value": _TEXT},
                                                                                 ("key", "value")),
        reversibility="compensatable", success_predicate="fact_stored"))
    registry.register(Tool("mind.add", "Add an item to one of the owner's lists: " + ", ".join(mind.LISTS) + ".",
        Risk.REVERSIBLE, _add, _check(("list", "text")),
        argument_schema=_schema({"list": {"type": "string", "enum": list(mind.LISTS)}, "text": _TEXT}, ("list", "text")),
        reversibility="compensatable", success_predicate="item_stored"))
    registry.register(Tool("mind.done", "Mark an item of an owner list done (done=false reopens it).",
        Risk.REVERSIBLE, _done, _check(("list", "id"), ("done",)),
        argument_schema=_schema({"list": {"type": "string", "enum": list(mind.LISTS)},
                                 "id": {"type": "integer", "minimum": 1}, "done": {"type": "boolean"}}, ("list", "id")),
        reversibility="compensatable", success_predicate="item_state_written"))
    registry.register(Tool("mind.who", "Look up who a name, nickname or relation means in the owner's memory "
        "(e.g. 'gf', 'mammi', 'DL wale sir').", Risk.OBSERVATION, _who, _check(("name",)),
        argument_schema=_schema({"name": _SHORT}, ("name",)), reversibility="not_applicable",
        success_predicate="lookup_done"))
    registry.register(Tool("mind.show", "Show what Chutku remembers about the owner: part = all, people, facts, or a "
        "list name (" + ", ".join(mind.LISTS) + ").", Risk.OBSERVATION, _show, _check((), ("part",)),
        argument_schema=_schema({"part": {"type": "string", "maxLength": 40}}, ()), reversibility="not_applicable",
        success_predicate="memory_read"))
    registry.register(Tool("mind.feedback", "Record the owner's feedback on Chutku's latest task (rating good or "
        "bad); bad plans are never reused as examples.", Risk.REVERSIBLE, _feedback, _check(("rating",)),
        argument_schema=_schema({"rating": {"type": "string", "enum": ["good", "bad"]}}, ("rating",)),
        reversibility="compensatable", success_predicate="feedback_stored"))
    registry.register(Tool("mind.map", "Open the owner's visual mind map (dashboard Mind map tab) in the browser.",
        Risk.OBSERVATION, _map, _check(()), argument_schema=_schema({}, ()), reversibility="not_applicable",
        success_predicate="mind_map_opened"))
    registry.register(Tool("settings.offline_mode", "Turn Chutku's offline mode on or off. On: only local models "
        "(planner, vision, voice) are used and nothing is sent to Gemini, even with internet.", Risk.REVERSIBLE,
        _offline, _check(("on",)), argument_schema=_schema({"on": {"type": "boolean"}}, ("on",)),
        reversibility="compensatable", success_predicate="preference_written"))
    registry.register(Tool("settings.chutku", "Switch one of Chutku's own options on or off: conversation (Gemini Live "
        "talk mode), hindi_listening (speech-to-text may pick Hindi), cloud_brain (free cloud models plan first, local "
        "as backup), heard_debug (store overheard room talk for 24 h).", Risk.REVERSIBLE, _switch,
        _check(("setting", "on")), argument_schema=_schema({"setting": {"type": "string", "enum": sorted(SWITCHES)},
                                                            "on": {"type": "boolean"}}, ("setting", "on")),
        reversibility="compensatable", success_predicate="preference_written"))
    registry.register(Tool("settings.reply_style", "How replies sound: normal, formal (respectful, no slang), short "
        "(one sentence) or masti (playful).", Risk.REVERSIBLE, _reply_style, _check(("style",)),
        argument_schema=_schema({"style": {"type": "string", "enum": ["normal", "formal", "short", "masti"]}},
                                ("style",)), reversibility="compensatable", success_predicate="preference_written"))
    registry.register(Tool("mind.forget", "Forget a person, a fact, or a list item ('assignments:3') from the owner's "
        "memory.", Risk.DATA_MODIFICATION, _forget, _check(("kind", "key")),
        argument_schema=_schema({"kind": {"type": "string", "enum": ["person", "fact", "item"]}, "key": _SHORT},
                                ("kind", "key")),
        reversibility="irreversible", success_predicate="memory_entry_removed", deletes=True))
