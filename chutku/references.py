"""@-references in typed chat (Phase 3b H6, from hermes-agent's context references, MIT, Nous Research).

"@file:D:\\notes\\a.txt ka summary do", "@folder:D:\\Study mein kya hai", "@url:https://example.com padho", "@clip ka
translation". Each reference is read *before* planning by Chutku's own tools through the runtime (so grants,
protected zones, the owner's never-rules and the action log all apply), and handed to the planner as
CONTEXT.attached = [{"source": ..., "untrusted_data": ...}]. Attached text is outside content: the session is tainted
(and exposed for private sources), and instruction-like lines are removed as in S15.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
import re

MAX_REFERENCES = 3
MAX_CHARS = 6000          # per attachment, after which the text is cut (and says so)
_REF = re.compile(r"@(?P<kind>file|folder|url):(?:\"(?P<quoted>[^\"]+)\"(?P<qrange>:\d{1,6}-\d{1,6})?|(?P<plain>\S+))"
                  r"|@(?P<clip>clip)\b", re.I)
_RANGE = re.compile(r"^(?P<path>.+?):(?P<a>\d{1,6})-(?P<b>\d{1,6})$")
# Secrets that must never be attached even when they sit in an allowed folder (Hermes's list, for Windows).
_SECRET_PARTS = (r"\.ssh\\", r"\.aws\\", r"\.kube\\", r"\.gnupg\\", r"\\microsoft\\credentials\\",
                 r"\\microsoft\\protect\\")
_SECRET_NAMES = re.compile(r"^(?:\.env(?:\..*)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)"
                           r"(?:\.pub)?|login data|cookies|web data|.*\.kdbx|.*\.pfx|.*\.p12|.*\.pem|.*\.key)$", re.I)
TOOLS = {"file": "file.extract_text", "folder": "filesystem.list", "url": "web.read", "clip": "clipboard.read_text"}
PRIVATE = {"file", "folder", "clip"}


class ReferenceError(ValueError):
    """A reference that cannot be attached; the request is refused with this reason."""


def find(text):
    return list(_REF.finditer(text or ""))


def secret_reason(path: str) -> str | None:
    norm = str(path).replace("/", "\\").casefold()
    if any(re.search(part, norm) for part in _SECRET_PARTS) or _SECRET_NAMES.match(PureWindowsPath(norm).name):
        return f"{PureWindowsPath(path).name} looks like a password, key or login file; it is never attached."
    return None


def _read(router, kind, target):
    tool = TOOLS[kind]
    arguments = {} if kind == "clip" else {"url": target} if kind == "url" else {"path": target}
    runtime = router.for_step({"tool": tool, "arguments": arguments})
    result = runtime.run(tool, arguments)   # the owner's own typed words: provenance user_stated
    if str(result.get("state")) != "COMPLETED":
        raise ReferenceError(f"@{kind} {target or ''}: " + str(result.get("error") or result.get("reason")
                                                             or result.get("state")))
    out = result.get("output") or {}
    if kind == "file":
        return out.get("text", ""), out.get("characters"), (tool, arguments, result)
    if kind == "folder":
        listing = (f"{out.get('path')}: {out.get('file_count')} files, {out.get('folder_count')} folders\n"
                   + "\n".join((out.get("entries") or [])[:200]))
        return listing, None, (tool, arguments, result)
    if kind == "url":
        return str(out.get("text") or out.get("content") or out), None, (tool, arguments, result)
    return str(out.get("text") or ""), None, (tool, arguments, result)


def expand(goal, router):
    """(goal with each reference replaced by [attached: name], attachments, kinds). Raises ReferenceError."""
    from chutku.agent_loop import _defang
    found = find(goal)
    if not found:
        return goal, [], set()
    if len(found) > MAX_REFERENCES:
        raise ReferenceError(f"At most {MAX_REFERENCES} @-references in one request.")
    attachments, kinds, text = [], set(), goal
    for match in found:
        kind = "clip" if match.group("clip") else match.group("kind").casefold()
        target = ((match.group("quoted") or "") + (match.group("qrange") or "") if match.group("quoted")
                  else (match.group("plain") or "").rstrip(".,;"))
        lines = None
        if kind == "file" and (ranged := _RANGE.match(target)):
            target, lines = ranged.group("path"), (int(ranged.group("a")), int(ranged.group("b")))
        if kind in {"file", "folder"} and (reason := secret_reason(target)):
            raise ReferenceError(reason)
        content, total, (tool, arguments, result) = _read(router, kind, target)
        if lines:
            first, last = sorted(lines)
            content = "\n".join(content.splitlines()[first - 1:last])
        cut = len(content) > MAX_CHARS
        removed = [0]
        clean = _defang(content[:MAX_CHARS], removed)
        source = f"@{kind}" + (f":{target}" if target else "") + (f":{lines[0]}-{lines[1]}" if lines else "")
        note = f"cut at {MAX_CHARS} of {total or len(content)} characters" if cut else None
        # The step the session records: the planner reads it like any step it ran itself (answers come from STEPS).
        shown = {"attached_by_owner": source, "text": content[:MAX_CHARS], **({"note": note} if note else {})}
        step = {"tool": tool, "arguments": arguments, "purpose": f"You attached {source}"}
        attachments.append({"source": source, "untrusted_data": clean, **({"note": note} if note else {}),
                            **({"suspicious_lines_removed": removed[0]} if removed[0] else {}),
                            "step": step, "result": dict(result) | {"output": shown}})
        kinds.add(kind)
        name = PureWindowsPath(target).name if kind in {"file", "folder"} else target or "clipboard"
        text = text.replace(match.group(0), f"[attached: {name}]", 1)
    return text, attachments, kinds
