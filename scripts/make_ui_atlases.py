"""App Mastery 2, step 6: turn the survey's maps (data/apps/<app>/uimap.json, scripts/app_survey.py) into atlases of
ready-made navigation actions: chutku/apps/atlas/ui_<app>.json.

Each page the survey reached becomes one safe action: open the app behind the owner's window, press the page's item by
its name (UI Automation `do`), and check that an element only that page shows is there. Phrases in English and
Hinglish. Like every atlas action, it routes instantly only after the Action Lab verified it 3 times on this PC.

    python scripts/make_ui_atlases.py
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chutku.apps import atlas as atlas_module  # noqa: E402

OUT = ROOT / "chutku" / "apps" / "atlas"
# spoken names per app id (the survey's ids); the Start-menu name is always one too
SPOKEN = {"calculator": ["calculator", "calc"], "clock": ["clock", "ghadi"], "paint": ["paint", "ms paint"],
          "photos": ["photos", "photo app"], "settings": ["settings", "setting"], "explorer": ["file explorer", "explorer"],
          "notepad": ["notepad"], "media_player": ["media player"], "snipping": ["snipping tool"],
          "todo": ["to do", "todo", "microsoft to do"], "sticky_notes": ["sticky notes"], "word": ["word", "ms word"],
          "excel": ["excel"], "powerpoint": ["powerpoint", "ppt"], "weather": ["weather", "mausam app"],
          "task_manager": ["task manager"], "store": ["microsoft store", "store"], "vscode": ["vs code", "vscode"],
          "onenote": ["onenote"], "sound_recorder": ["sound recorder", "voice recorder"], "calendar": ["calendar"]}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")[:40] or "page"


def marker(page_name, page, home):
    """An element name only this page shows (proof the page opened); None when the page added nothing readable."""
    for item in page.get("new_elements", []):
        role, _, name = item.partition(":")
        if name and name != page_name and len(name) <= 60 and item not in home and role not in {"scrollbar", "group"}:
            return name
    return None


def phrases(words, page):
    short = re.sub(r"\s+(?:calculator|converter|page|tab)$", "", page, flags=re.I).strip() or page
    out = []
    for word in words:
        for name in dict.fromkeys([page.casefold(), short.casefold()]):
            out += [f"open {name} in {word}", f"{word} mein {name} kholo", f"{word} me {name} kholo",
                    f"{word} mein {name} dikhao", f"go to {name} in {word}"]
    return list(dict.fromkeys(out))


def build(uimap):
    app, window = uimap["app"], uimap.get("window") or {}
    home = set(uimap["pages"].get("home", {}).get("elements", []))
    actions, seen = [], set()
    for page_name, page in uimap["pages"].items():
        if page_name == "home" or page.get("error") or str(page.get("delivery", "")).startswith("error"):
            continue
        check = marker(page_name, page, home)
        action_id = slug(page_name)
        if action_id in seen or not atlas_module._ID.match(action_id) or check is None:
            continue   # no proof the page opened: not an action
        seen.add(action_id)
        actions.append({"id": action_id, "title": f"Open {page_name}", "risk": "safe",
                        "phrases": phrases(SPOKEN.get(app, [uimap["start_menu"].casefold()]), page_name),
                        "steps": [{"launch": "behind"}, {"do": page_name, "action": "click"}],
                        "check": {"has_element": check}, "source": "survey " + uimap.get("at", "")})
    if not actions:
        return None
    return {"app": f"ui_{app}", "name": uimap["start_menu"], "aliases": SPOKEN.get(app, []),
            "window": {"exe": window.get("exe") or "", "title": window.get("title") or uimap["start_menu"]},
            "launch": {"start_menu": uimap["start_menu"]}, "uri_schemes": [], "cli": {},
            "sources": [f"data/apps/{app}/uimap.json"], "actions": actions}


def main():
    written = []
    for path in sorted((ROOT / "data" / "apps").glob("*/uimap.json")):
        uimap = json.loads(path.read_text(encoding="utf-8"))
        atlas = build(uimap) if uimap.get("pages") else None
        if atlas is None:
            continue
        atlas_module.validate(atlas)   # a generated atlas must pass the same validator (risky names refused)
        (OUT / f"{atlas['app']}.json").write_text(json.dumps(atlas, indent=1, ensure_ascii=False), encoding="utf-8")
        written.append((atlas["app"], len(atlas["actions"])))
    for app, count in written:
        print(f"{app}: {count} actions")


if __name__ == "__main__":
    main()
