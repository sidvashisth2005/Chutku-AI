"""Instant file commands that name full paths (the local model fumbled these in the 2026-10-04 benchmark:
it listed recent files and then claimed "renamed"/"deleted").

    "delete D:\\x\\junk.tmp" / "D:\\x\\junk.tmp delete karo"            -> filesystem.recycle (Recycle Bin; asks first)
    "rename D:\\x\\draft.txt to final.txt"                             -> filesystem.move (asks first: a file change)
    "make a copy of D:\\x\\a.txt named D:\\x\\b.txt" / "copy A to B"     -> filesystem.copy
    "move D:\\x\\a.txt to D:\\y"                                        -> filesystem.move
    "write 'hello' into D:\\x\\a.txt"                                   -> filesystem.write_text
    "create the folder D:\\x\\notes" / "D:\\x mein notes naam ka folder banao" -> filesystem.create_directory

Returns (tool, arguments, purpose, reply) or None. Wildcards, whole drives and "everything" are never matched.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
import re

_PATH = r"[a-z]:\\(?:(?!\s+(?:and|then|aur|phir)\s)[^?*\x22'<>|]){1,240}?"  # stops at " and " / quotes: never swallows the next clause
from chutku.intents.lexicon import LEAD as _P, TAIL as _T   # one Hinglish vocabulary for every parser
_Q = r"[\"'“”‘’]"
_PATTERNS = [
    ("delete", re.compile(_P + r"(?:delete|remove|recycle|trash|bin)\s+(?:the\s+)?(?:file\s+|folder\s+)?(?P<path>" + _PATH + r")" + _T, re.I)),
    ("delete", re.compile(_P + r"(?P<path>" + _PATH + r")\s+(?:ko\s+)?(?:delete|hata|mita)\s*(?:karo|kar do|do|de)" + _T, re.I)),
    ("rename", re.compile(_P + r"rename\s+(?:the\s+)?(?:file\s+|folder\s+)?(?P<src>" + _PATH + r")\s+(?:to|as)\s+(?P<dst>" + _PATH + r"|(?:(?!\s+(?:and|then|aur|phir)\s)[^\\/:*?\x22<>|]){1,120}?)" + _T, re.I)),
    ("copy", re.compile(_P + r"(?:make\s+a\s+copy\s+of|copy)\s+(?P<src>" + _PATH + r")\s+(?:named|called|as|to|into)\s+(?P<dst>" + _PATH + r")" + _T, re.I)),
    ("move", re.compile(_P + r"move\s+(?P<src>" + _PATH + r")\s+(?:to|into)\s+(?P<dst>" + _PATH + r")" + _T, re.I)),
    ("write", re.compile(_P + r"write\s+(?:the\s+text\s+)?" + _Q + r"(?P<text>[^\"“”]{1,2000}?)" + _Q + r"\s+(?:into|to|in)\s+(?P<path>" + _PATH + r")" + _T, re.I)),
    ("write", re.compile(_P + r"create\s+(?P<path>" + _PATH + r"\.[a-z0-9]{1,5})\s+with\s+(?:the\s+)?(?:text\s+)?" + _Q + r"?(?P<text>[^\"“”]{1,2000}?)" + _Q + r"?" + _T, re.I)),
    ("folder", re.compile(_P + r"(?:create|make)\s+(?:a\s+|the\s+)?(?:new\s+)?folder\s+(?:called\s+|named\s+|at\s+)?(?P<path>" + _PATH + r")" + _T, re.I)),
    ("folder_in", re.compile(_P + r"(?P<parent>" + _PATH + r")\s+(?:mein|me|main)\s+(?P<name>[\w .-]{1,60}?)\s+naam\s+ka\s+folder\s+(?:banao|bana do|banado|create karo)" + _T, re.I)),
]
_VAGUE = re.compile(r"\b(?:everything|all files|sab kuch|saari files)\b|\*", re.I)


_BATCH = re.compile(_P + r"in\s+(?P<dir>" + _PATH + r"),?\s+(?:create|make|write)\s+(?P<items>.+?)"
                    r"(?P<list>,?\s+(?:and\s+)?then\s+(?:list|show)\s+(?:the\s+)?(?:folder|files|contents))?" + _T, re.I)
_ITEM = re.compile(r"(?P<name>[\w .-]{1,80}?\.[a-z0-9]{1,5})\s+(?:containing|with(?:\s+the\s+text)?)\s+" + _Q
                   + r"(?P<text>[^\"'“”‘’]{0,2000})" + _Q, re.I)


def parse_file_batch(goal: str):
    """'In D:\\x create a.txt containing 'one' and b.txt containing 'two', then list the folder' -> steps."""
    text = " ".join(goal.split())
    match = _BATCH.match(text)
    if not match or _VAGUE.search(text):
        return None
    folder = PureWindowsPath(_clean(match.group("dir")))
    items = list(_ITEM.finditer(match.group("items")))
    leftover = _ITEM.sub("", match.group("items"))
    if not items or re.sub(r"[\s,]|\band\b|\baur\b", "", leftover):
        return None  # something in the request was not a "name containing 'text'" item: let the planner read it
    def name(item):
        return re.sub(r"^(?:and|aur|then)\s+", "", item.group("name").strip(), flags=re.I)
    steps = [{"tool": "filesystem.write_text", "arguments": {"path": str(folder / name(m)), "content": m.group("text")},
              "purpose": f"Write {name(m)}"} for m in items]
    if match.group("list"):
        steps.append({"tool": "filesystem.list", "arguments": {"path": str(folder)}, "purpose": f"List {folder}"})
    return steps


def _clean(path):
    return path.strip().rstrip(" .")


def _is_drive_root(path):
    return re.fullmatch(r"[a-z]:\\?", path, re.I) is not None


def parse_file_command(goal: str):
    text = " ".join(goal.split())
    if _VAGUE.search(text):
        return None
    for kind, pattern in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        g = match.groupdict()
        if kind == "delete":
            path = _clean(g["path"])
            if _is_drive_root(path):
                return None
            return "filesystem.recycle", {"path": path}, f"Move {path} to the Recycle Bin", f"Moved {path} to the Recycle Bin."
        if kind in ("rename", "copy", "move"):
            src, dst = _clean(g["src"]), _clean(g["dst"])
            if _is_drive_root(src):
                return None
            if kind == "rename" and not re.match(r"[a-z]:\\", dst, re.I):
                dst = str(PureWindowsPath(src).with_name(dst))       # "rename X to final.txt": same folder
            tool = "filesystem.copy" if kind == "copy" else "filesystem.move"
            verb = {"rename": "Renamed", "copy": "Copied", "move": "Moved"}[kind]
            return tool, {"source": src, "destination": dst}, f"{verb[:-1]} {src} to {dst}", f"{verb} {src} to {dst}."
        if kind == "write":
            path = _clean(g["path"])
            return ("filesystem.write_text", {"path": path, "content": g["text"]}, f"Write into {path}",
                    f"Wrote the text into {path}.")
        if kind == "folder":
            path = _clean(g["path"])
            return None if _is_drive_root(path) else ("filesystem.create_directory", {"path": path},
                                                      f"Create the folder {path}", f"Created the folder {path}.")
        if kind == "folder_in":
            path = str(PureWindowsPath(_clean(g["parent"])) / g["name"].strip())
            return "filesystem.create_directory", {"path": path}, f"Create the folder {path}", f"Created the folder {path}."
    return None
