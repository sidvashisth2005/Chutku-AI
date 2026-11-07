"""Names the owner's apps proved to have (F6, 2026-10-29): a playlist, artist or album Chutku once played with a
passing check is remembered, so later loose sentences ("after party bajao", "Spotify pe After Party chalao",
"Mera Spotify open kar aur after party playlist chala") play that exact item instantly instead of searching or
asking the model. Only names whose own check passed are stored (data/apps/known.json, local)."""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading

from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
REMEMBERED = {("spotify", "play_playlist"): "playlist", ("spotify", "play_artist"): "artist",
              ("spotify", "play_album"): "album"}
_lock = threading.Lock()


def _file(base=None):
    return Path(base or PROJECT_ROOT) / "data" / "apps" / "known.json"


def norm(name):
    return " ".join(re.findall(r"[a-z0-9]+", str(name).casefold()))


def load(base=None):
    try:
        data = json.loads(_file(base).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(app, action_id, name, base=None):
    kind = REMEMBERED.get((app, action_id))
    if kind is None or not norm(name) or len(str(name)) > 80:
        return False
    with _lock:
        data = load(base)
        names = data.setdefault(app, {}).setdefault(kind, [])
        if norm(name) not in {norm(n) for n in names}:
            names.append(str(name).strip())
            data[app][kind] = names[-200:]
            path = _file(base)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def known(app, kind, base=None):
    return list(load(base).get(app, {}).get(kind, []))


_PLAY = re.compile(r"\b(?:play|chalao|chala|chalade|chala do|chala de|bajao|baja|baja do|lagao|laga|laga do|sunao|"
                   r"start|shuru)\b", re.I)
_FILLER = frozenset("""spotify pe par on mein me mera meri mere my the a open kholo khol kar karke karo kar do kardo
and aur phir then playlist playlists wali wala vali vala play chalao chala chalade do de bajao baja lagao laga sunao
start shuru please pls zara bhai yaar chutku oye ki ka ke song songs gaana gaane music""".split())


def spoken_playlist(text, base=None):
    """The exact known Spotify playlist a play sentence names, or None."""
    if not _PLAY.search(text or ""):
        return None
    words = [w for w in norm(text).split() if w not in _FILLER]
    if not words:
        return None
    rest = " ".join(words)
    for name in known("spotify", "playlist", base):
        if norm(name) == rest:
            return name
    return None
