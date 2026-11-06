"""Instant routing of app phrases (App Mastery A3): "After Party playlist chalao" -> app.spotify.play_playlist.

Each atlas phrase with `{slots}` becomes one anchored regex. Only actions the Action Lab has verified on this PC are
routed (lab.verified_actions), so an unproven recipe never runs without the planner. When several phrases match, the
one with the most fixed words wins; a tie between two different actions is ambiguous and nothing is routed. Actions
marked `"route": false` are left to Chutku's general rules (e.g. "open spotify" stays apps.launch).

`app_scope` keeps the planner's tool menu small: an app's actions are offered only when the request names that app
(its id, name or an alias) or one of its actions was already used.
"""
from __future__ import annotations

import re

MAX_SLOT = 80
_POLITE = r"(?:(?:please|plz|pls|chutku|oye|hey|zara|jara)[\s,]+)*"
_TAIL = r"(?:[\s,]+(?:please|plz|pls|na|jaldi|abhi|zara))*[\s.!?]*"
_CACHE = {}


def regex_for(template):
    parts = re.split(r"(\{[a-z][a-z0-9_]*\})", template.strip())
    out, slots = [], []
    for part in parts:
        slot = re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", part)
        if slot:
            name = slot.group(1)
            if name in slots:
                return None, []
            slots.append(name)
            out.append(rf"(?P<{name}>\S.{{0,{MAX_SLOT - 1}}}?)")
        elif part:
            words = part.split()
            text = r"\s+".join(re.escape(w) for w in words)
            if part[:1].isspace() and out:
                text = r"\s+" + text
            if part[-1:].isspace() and words:
                text += r"\s+"
            out.append(text)
    return re.compile("^" + _POLITE + "".join(out) + _TAIL + "$", re.I), slots


def compiled(atlases):
    """[(regex, fixed_chars, app, action)] for every phrase of every atlas (cached per atlas set)."""
    key = id(atlases)
    if key not in _CACHE:
        rows = []
        for app, atlas in atlases.items():
            for action in atlas["actions"]:
                if action.get("route") is False:
                    continue
                for phrase in action.get("phrases") or []:
                    pattern, slots = regex_for(phrase)
                    if pattern is not None:
                        rows.append((pattern, len(re.sub(r"\{[a-z0-9_]+\}|\s", "", phrase)), app, action))
        _CACHE.clear()
        _CACHE[key] = rows
    return _CACHE[key]


def shortcut(action):
    """Z3 (owner 2026-11-06: "keep everything in a single step"): a safe action that only brings its app to the front
    and presses one documented keyboard shortcut. It routes without a lab run (reload, back, captions...: the lab
    skips several of them so as not to disturb the owner); the runner still refuses when the app is not in front or,
    for YouTube keys, not on a YouTube tab. A lab run that failed stops it again."""
    steps = action.get("steps") or []
    return action.get("risk") == "safe" and not action.get("params") and any("keys" in s for s in steps) \
        and all("focus" in s or "keys" in s for s in steps)


def match(goal, atlases=None, verified=None, failed=None):
    """(tool name, arguments, action) for a verified app action (or a plain shortcut) whose phrase matches the whole
    request, else None."""
    if atlases is None:
        from chutku.apps.atlas import load_all
        atlases = _atlases(load_all)
    if verified is None or failed is None:
        from chutku.app import PROJECT_ROOT
        from chutku.apps.lab import failed_actions, verified_actions
        verified = verified_actions(PROJECT_ROOT) if verified is None else verified
        failed = failed_actions(PROJECT_ROOT) if failed is None else failed
    text = " ".join(str(goal).split())
    if not text or len(text) > 200:
        return None
    best = []
    for pattern, fixed, app, action in compiled(atlases):
        if action["id"] not in verified.get(app, ()) and \
                (not shortcut(action) or action["id"] in failed.get(app, ())):
            continue
        found = pattern.match(text)
        if not found:
            continue
        arguments = {k: v.strip(" ,.!?\"'") for k, v in found.groupdict().items()}
        if any(not v for v in arguments.values()):
            continue
        best.append((fixed, app, action, arguments))
    if not best:
        return None
    best.sort(key=lambda row: -row[0])
    top = [row for row in best if row[0] == best[0][0]]
    if len({(app, action["id"]) for _f, app, action, _a in top}) > 1:
        return None   # two different actions read the same: let the planner decide
    _fixed, app, action, arguments = top[0]
    return f"app.{app}.{action['id']}", arguments, action


_LOADED = {}


def _atlases(load_all):
    if "atlases" not in _LOADED:
        _LOADED["atlases"] = load_all()[0]
    return _LOADED["atlases"]


def named_apps(goal, atlases):
    words = set(re.findall(r"[a-z0-9]+", str(goal).casefold()))
    named = set()
    for app, atlas in atlases.items():
        names = {app, str(atlas.get("name", "")).casefold()} | {a.casefold() for a in atlas.get("aliases") or []}
        if any(n and set(n.split()) <= words for n in names):
            named.add(app)
    return named


def app_scope(rows, goal, used=(), atlases=None):
    """Drop app.<app>.* rows whose app the request does not name (and that were not used already)."""
    if atlases is None:
        from chutku.apps.atlas import load_all
        atlases = _atlases(load_all)
    named = named_apps(goal, atlases)
    keep = []
    for row in rows:
        name = row["name"]
        if name.startswith("app.") and name not in used and name.split(".")[1] not in named:
            continue
        keep.append(row)
    return keep
