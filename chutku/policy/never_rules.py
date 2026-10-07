"""The owner's "never" rules (Phase 3b H1): things Chutku must never touch, checked before every other policy rule.

"D:\\Exams ko kabhi mat chhoona" / "never touch D:\\Exams" adds a rule in data/never_rules.json. Three kinds:
- path: a folder or file; nothing Chutku does may read or change it or anything inside it;
- tool: a tool name or pattern (fnmatch), e.g. message.send;
- command: a word or phrase that a program Chutku launches or a script she runs must never contain.

A matching step is refused in every autonomy mode, and an on-screen approval cannot override it. An unreadable rules
file refuses every step that changes anything (fail closed). Idea adapted from hermes-agent's approval floors and
`approvals.deny` rules (tools/approval_floors.py, MIT, Nous Research).
"""
from __future__ import annotations

from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import secrets
import time
import unicodedata

PREFIX = "Ye main kabhi nahi karungi"
RULE_KINDS = ("path", "tool", "command")
_FILE = "data/never_rules.json"
_PATH_KEYS = frozenset({"path", "src", "dst", "source", "destination", "folder", "target", "directory", "file",
                        "executable", "expected_executable", "root", "to", "from", "into"})
_MAX_SCRIPT = 2_000_000


def rules_path(base) -> Path:
    return Path(base) / _FILE


def load_rules(base) -> list[dict]:
    path = rules_path(base)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("never_rules.json must hold a list")
    for item in raw:
        if not (isinstance(item, dict) and item.get("kind") in RULE_KINDS and isinstance(item.get("id"), str)
                and isinstance(item.get("pattern"), str) and item["pattern"].strip()):
            raise ValueError("never_rules.json has a malformed rule")
    return raw


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text)).casefold())


def _norm_path(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().strip('"').replace("/", "\\")
    if text.startswith("~"):
        text = os.path.expanduser(text)
    if re.match(r"^[a-zA-Z]:\\|^\\\\", text):
        text = os.path.normcase(os.path.abspath(text))
    text = text.casefold()
    return text.rstrip("\\") if len(text) > 3 else text


def _path_matches(value: str, pattern: str) -> bool:
    candidate, rule = _norm_path(value), _norm_path(pattern)
    if any(ch in rule for ch in "*?["):
        base = rule[:-2] if rule.endswith("\\*") else None
        return fnmatchcase(candidate, rule) or (base is not None and (candidate == base or candidate.startswith(base + "\\")))
    return candidate == rule or candidate.startswith(rule + "\\")


def _paths_in(arguments, granted_root):
    found = []

    def visit(key, value):
        if isinstance(value, str):
            if re.match(r"^\s*(?:[a-zA-Z]:[\\/]|\\\\|~)", value):
                found.append(value)
            elif key in _PATH_KEYS and value.strip() and granted_root is not None:
                found.append(str(Path(granted_root) / value))
        elif isinstance(value, dict):
            for k, v in value.items():
                visit(str(k).casefold(), v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                visit(key, v)

    visit("", arguments)
    return found


def _command_text(tool, arguments, granted_root):
    """What a code tool would run: the script text plus its arguments, or the program and its arguments."""
    name = getattr(tool, "name", "")
    if not getattr(tool, "runs_code", False) or not isinstance(arguments, dict):
        return None
    parts = [str(v) for v in arguments.values() if isinstance(v, str)]
    parts += [str(a) for v in arguments.values() if isinstance(v, list) for a in v]
    if name == "code.run_python" and isinstance(arguments.get("path"), str):
        script = Path(arguments["path"])
        if not script.is_absolute() and granted_root is not None:
            script = Path(granted_root) / script
        try:
            if script.is_file() and script.stat().st_size <= _MAX_SCRIPT:
                parts.append(script.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(parts)


def rule_reason(rules, tool, arguments, granted_root=None) -> str | None:
    name = getattr(tool, "name", "")
    if name.startswith("never."):   # the rules' own tools are never locked out by a rule
        return None
    command = None
    for rule in rules:
        pattern = rule["pattern"]
        if rule["kind"] == "tool" and fnmatchcase(name.casefold(), pattern.strip().casefold()):
            return f"aapka niyam: '{pattern}' kabhi use nahi karna"
        if rule["kind"] == "path":
            if any(_path_matches(value, pattern) for value in _paths_in(arguments, granted_root)):
                return f"aapka niyam: {pattern} ko kabhi nahi chhoona"
        if rule["kind"] == "command":
            if command is None:
                command = _norm_text(_command_text(tool, arguments, granted_root) or "")
            wanted = _norm_text(pattern).strip()
            if command and (fnmatchcase(command, f"*{wanted}*") if any(c in wanted for c in "*?[") else wanted in command):
                return f"aapka niyam: '{pattern}' kabhi nahi chalana"
    return None


def floor_reason(tool, arguments, *, granted_root=None, base=None) -> str | None:
    """The refusal text when a never-rule matches this step, else None."""
    if base is None:
        return None
    try:
        rules = load_rules(base)
    except (OSError, ValueError) as error:
        if int(getattr(tool, "base_risk", 0)) >= 1 and not getattr(tool, "name", "").startswith("never."):
            return f"{PREFIX}: mere 'never' niyam padhe nahi ja sake ({type(error).__name__}); pehle unhe theek karo."
        return None
    reason = rule_reason(rules, tool, arguments, granted_root)
    return f"{PREFIX}: {reason}" if reason else None


def add_rule(base, kind: str, pattern: str, said: str = "") -> dict:
    if kind not in RULE_KINDS:
        raise ValueError("kind must be path, tool or command")
    pattern = str(pattern).strip().strip('"').strip()
    if not pattern or len(pattern) > 300:
        raise ValueError("Give a pattern of 1-300 characters.")
    if kind == "path" and not re.match(r"^(?:[a-zA-Z]:[\\/]|\\\\|~)", pattern):
        raise ValueError("A path rule needs a full path like D:\\Exams.")
    from chutku.core.jsonstore import lock_for, write_json
    path = rules_path(base)
    with lock_for(path):
        rules = load_rules(base)
        for rule in rules:
            if rule["kind"] == kind and rule["pattern"].casefold() == pattern.casefold():
                return rule | {"existing": True}
        if len(rules) >= 100:
            raise ValueError("At most 100 never-rules.")
        rule = {"id": secrets.token_hex(3), "kind": kind, "pattern": pattern, "said": str(said)[:300],
                "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
        write_json(path, rules + [rule])
    return rule


def remove_rule(base, rule_id: str) -> dict | None:
    from chutku.core.jsonstore import lock_for, write_json
    path = rules_path(base)
    with lock_for(path):
        rules = load_rules(base)
        kept = [r for r in rules if r["id"] != rule_id]
        if len(kept) == len(rules):
            return None
        write_json(path, kept)
    return next(r for r in rules if r["id"] == rule_id)
