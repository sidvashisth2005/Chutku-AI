"""app.howto (App Mastery A3): "Spotify mein shuffle kaise karte hain?" answered from the app's feature map.

The feature maps (docs/apps/<app>.md, written in A0 from official docs and checked into the repo) are split into
lines (bullets, table rows, shortcut cells). The best-matching lines by word overlap are returned, together with the
atlas actions Chutku can do herself for that question, and whether the Action Lab has verified them on this PC.
No web text is read here (the harvested pages stay as background for the maps), so the answer does not taint the
session.
"""
from __future__ import annotations

from pathlib import Path
import re

MAPS = Path(__file__).resolve().parents[2] / "docs" / "apps"
_STOP = {"the", "and", "how", "can", "you", "for", "with", "what", "where", "kaise", "karte", "karun", "karu", "kare",
         "hain", "hai", "mein", "main", "kya", "kahan", "hota", "use", "this", "that", "from", "into", "want", "bata",
         "batao", "tell", "please", "chutku", "kar", "karo", "app", "ko", "se", "pe", "par"}
_ALIASES = {"gaana": "song", "gaane": "song", "awaaz": "volume", "dhoondo": "search", "dhundo": "search",
            "kholo": "open", "band": "close", "bhejo": "send", "chalao": "play", "bajao": "play", "agla": "next",
            "pichhla": "previous", "roko": "pause", "naya": "new", "nayi": "new", "mitao": "delete", "hatao": "delete",
            "kholte": "open", "kholu": "open", "kholun": "open", "bhejte": "send", "bhejun": "send", "chalate": "play",
            "dhoondte": "search", "badhate": "increase", "badhaun": "increase", "banate": "create", "banaun": "create",
            "hatate": "delete", "band karte": "close"}


APP_NAMES = {"spotify": ("spotify",), "whatsapp": ("whatsapp", "whats app"), "brave": ("brave", "youtube", "browser"),
             "vscode": ("vs code", "vscode", "visual studio code"), "settings": ("settings", "windows settings"),
             "chatgpt": ("chatgpt", "chat gpt"), "discord": ("discord",), "vlc": ("vlc",), "telegram": ("telegram",),
             "explorer": ("file explorer", "explorer"), "notepad": ("notepad",)}


def resolve(name):
    """The feature-map id for an app name the owner said ("VS Code" -> "vscode"), else None."""
    said = " ".join(re.findall(r"[a-z0-9]+", str(name).casefold()))
    for app, names in APP_NAMES.items():
        if said in names:
            return app
    return None


def words(text):
    found = set()
    for word in re.findall(r"[a-z0-9+]{2,}", str(text).casefold()):
        word = _ALIASES.get(word, word)
        if word not in _STOP and (len(word) >= 3 or any(c.isdigit() for c in word)):
            found.add(word[:5])
    return found


def _lines(app):
    path = MAPS / f"{app}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out, section = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
            continue
        if not line or set(line) <= set("|-: "):
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and cells[0].casefold() in {"id", "area", "what"}:
                continue
            # A shortcut row lists many "keys thing" items: split them so each is its own answer.
            if len(cells) == 2 and "·" in cells[1]:
                out.extend((section, f"{cells[0]}: {part.strip()}") for part in cells[1].split("·") if part.strip())
                continue
            line = " | ".join(cells)
        out.append((section, line.lstrip("-* ").strip()))
    return [(section, line.replace("**", "").strip(" .")) for section, line in out
            if not line.casefold().startswith(("sources", "risk:", "everything below"))]


def answer(question, app, atlas=None, verified=frozenset()):
    """{"app", "question", "answers": [{"text", "section"}], "can_do": [{"tool", "title", "verified"}]}."""
    wanted = words(question) - words(app)
    scored = []
    for index, (section, line) in enumerate(_lines(app)):
        overlap = wanted & words(line)
        if overlap:
            scored.append((-len(overlap), index, section, line))
    scored.sort()
    answers = [{"text": line[:240], "section": section} for _n, _i, section, line in scored[:3]]
    can_do = []
    for action in (atlas or {}).get("actions", []):
        overlap = wanted & words(action["title"] + " " + action["id"].replace("_", " "))
        if len(overlap) >= max(1, min(2, len(wanted))):
            can_do.append((-len(overlap), action["id"], action["title"]))
    can_do.sort()
    return {"app": app, "question": question, "answers": answers,
            "can_do": [{"tool": f"app.{app}.{action_id}", "title": title, "verified": action_id in verified}
                       for _n, action_id, title in can_do[:3]]}


DISPLAY = {"vscode": "VS Code", "chatgpt": "ChatGPT", "whatsapp": "WhatsApp", "vlc": "VLC", "explorer": "File Explorer"}


def say(out):
    app = DISPLAY.get(out.get("app", ""), str(out.get("app", "")).capitalize())
    if not out.get("answers") and not out.get("can_do"):
        return f"Mujhe {app} ke notes mein iska jawab nahi mila."
    parts = []
    if out.get("answers"):
        parts.append(f"{app} mein: " + "; ".join(a["text"] for a in out["answers"][:2]) + ".")
    ready = [c for c in out.get("can_do", []) if c["verified"]]
    if ready:
        parts.append("Main ye khud kar sakti hoon: " + ", ".join(c["title"] for c in ready) + ".")
    elif out.get("can_do"):
        parts.append("Iska tareeka mere paas hai, par is PC pe abhi test nahi hua: "
                     + ", ".join(c["title"] for c in out["can_do"]) + ".")
    return " ".join(parts)
