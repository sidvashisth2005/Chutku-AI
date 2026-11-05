"""Write the App Mastery atlases for VLC, Telegram, VS Code, Notepad, File Explorer and Windows Settings (A7, A8,
A11-A13, 2026-11-01) from the documented keys and command lines in docs/apps/<app>.md. Only verified actions
(scripts: chutku.apps.lab) are ever routed instantly.

    python scripts/make_atlases.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "chutku" / "apps" / "atlas"


def act(id, title, phrases, steps, check=None, risk="safe", params=None, done=None, **extra):
    a = {"id": id, "title": title, "risk": risk, "phrases": phrases, "steps": steps,
         "check": check or {"window_open": True}}
    if params:
        a["params"] = params
    if done:
        a["done"] = done
    a.update(extra)
    return a


def keys(app_words, id, title, combo, said, done):
    return act(id, title, [f"{w} {p}" for w in app_words for p in said],
               [{"focus": True}, {"keys": combo, "wait": 0.6}], done=done)


def write(app, data):
    (OUT / f"{app}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    V = ["vlc"]
    write("vlc", {"app": "vlc", "name": "VLC media player", "aliases": ["vlc", "vlc player"],
        "window": {"exe": "vlc.exe"}, "launch": {"start_menu": "VLC media player"}, "uri_schemes": [],
        "cli": {"vlc": "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"}, "sources": ["docs/apps/vlc.md"], "actions": [
        act("open", "Open VLC", ["open vlc", "vlc kholo"], [{"focus": True}], route=False),
        act("play_file", "Play a file or folder in VLC", ["play {path} in vlc", "vlc mein {path} chalao",
            "vlc pe {path} play karo"], [{"cli": ["vlc", "--one-instance", "{path}"]}, {"sleep": 1.5}],
            params={"path": {"type": "path"}}, done="VLC mein chala diya."),
        act("pause", "Pause VLC", ["pause vlc", "vlc pause karo", "vlc roko"],
            [{"focus": True}, {"keys": "space", "wait": 0.6}], {"media_paused": True}, done="VLC rok diya."),
        act("resume", "Resume VLC", ["resume vlc", "vlc chalao", "vlc play karo"],
            [{"focus": True}, {"keys": "space", "wait": 0.6}], {"media_playing": True}, done="VLC chala diya."),
        keys(V, "next", "Next item in VLC", "n", ["next", "agla"], "Agla chala diya."),
        keys(V, "previous", "Previous item in VLC", "p", ["previous", "pichla"], "Pichla chala diya."),
        keys(V, "fullscreen", "Toggle full screen in VLC", "f", ["full screen", "fullscreen karo"], "Full screen."),
        keys(V, "volume_up", "VLC volume up", "ctrl+up", ["volume up", "awaaz badhao"], "Awaaz badha di."),
        keys(V, "volume_down", "VLC volume down", "ctrl+down", ["volume down", "awaaz kam karo"], "Awaaz kam kar di."),
        keys(V, "mute", "Mute VLC", "m", ["mute", "mute karo"], "Mute."),
        keys(V, "forward_10", "Jump 10 s forward", "alt+right", ["aage karo", "10 second aage"], "10 second aage."),
        keys(V, "back_10", "Jump 10 s back", "alt+left", ["peeche karo", "10 second peeche"], "10 second peeche."),
        keys(V, "faster", "Play faster", "]", ["faster", "tez chalao"], "Thoda tez."),
        keys(V, "slower", "Play slower", "[", ["slower", "dheere chalao"], "Thoda dheere."),
        keys(V, "subtitles", "Cycle subtitles", "v", ["subtitles", "subtitle badlo"], "Subtitle badal diya."),
    ]})

    T = ["telegram"]
    write("telegram", {"app": "telegram", "name": "Telegram", "aliases": ["telegram", "tg"],
        "window": {"exe": "Telegram.exe"}, "launch": {"start_menu": "Telegram"}, "uri_schemes": ["tg"],
        "sources": ["docs/apps/telegram.md"],
        "note": "Sending stays with message.send (unknown recipients ask). Nothing here sends a message.", "actions": [
        act("open", "Open Telegram", ["open telegram", "telegram kholo"], [{"focus": True}], route=False),
        act("saved_messages", "Open Saved Messages", ["telegram saved messages", "telegram saved messages kholo",
            "open saved messages"], [{"focus": True}, {"keys": "ctrl+0", "wait": 1.0}],
            {"ocr_contains": "Saved Messages"}, done="Saved Messages khol diya."),
        act("open_chat", "Open a Telegram chat by username", ["open {username} on telegram",
            "telegram pe {username} kholo", "telegram pe {username} ka chat kholo"],
            [{"uri": "tg://resolve?domain={username}"}, {"sleep": 1.5}], params={"username": {"type": "text"}},
            done="{username} ka chat khol diya.", drill={"username": "telegram"}),
        keys(T, "search", "Search Telegram", "ctrl+f", ["search", "mein search karo"], "Telegram search khol diya."),
        keys(T, "next_chat", "Next Telegram chat", "ctrl+tab", ["next chat", "agla chat"], "Agla chat."),
        keys(T, "previous_chat", "Previous Telegram chat", "ctrl+shift+tab", ["previous chat", "pichla chat"],
             "Pichla chat."),
        act("archive", "Open archived chats", ["telegram archive kholo", "telegram archived chats"],
            [{"focus": True}, {"keys": "ctrl+9", "wait": 1.0}], {"ocr_contains": "Archive"}, done="Archive khol diya."),
    ]})

    C = ["vs code", "vscode"]
    write("vscode", {"app": "vscode", "name": "Visual Studio Code", "aliases": ["vs code", "vscode", "visual studio code"],
        "window": {"exe": "Code.exe"}, "launch": {"start_menu": "Visual Studio Code"}, "uri_schemes": [],
        "cli": {"code": "%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe"},
        "sources": ["docs/apps/vscode.md"], "actions": [
        act("open", "Open VS Code", ["open vs code", "vs code kholo"], [{"focus": True}], route=False),
        act("open_folder", "Open a folder or file in VS Code", ["open {path} in vs code", "vs code mein {path} kholo"],
            [{"cli": ["code", "--reuse-window", "{path}"]}, {"sleep": 2}], params={"path": {"type": "path"}},
            done="VS Code mein khol diya.", drill={"path": r"D:\ChutkuScratch"}),
        keys(C, "command_palette", "Open the command palette", "ctrl+shift+p", ["command palette"], "Command palette."),
        keys(C, "quick_open", "Quick open a file", "ctrl+p", ["quick open", "file dhundo"], "Quick open khol diya."),
        keys(C, "terminal", "Toggle the terminal", "ctrl+`", ["terminal", "terminal kholo"], "Terminal khol diya."),
        keys(C, "new_terminal", "New terminal", "ctrl+shift+`", ["new terminal", "naya terminal"], "Naya terminal."),
        keys(C, "sidebar", "Toggle the side bar", "ctrl+b", ["sidebar", "sidebar toggle karo"], "Side bar badal diya."),
        keys(C, "search_files", "Search in all files", "ctrl+shift+f", ["search in files", "sab files mein search karo"],
             "Search khol diya."),
        keys(C, "source_control", "Show source control", "ctrl+shift+g", ["source control", "git dikhao"],
             "Source control khol diya."),
        keys(C, "extensions", "Show extensions", "ctrl+shift+x", ["extensions", "extensions kholo"], "Extensions."),
        keys(C, "problems", "Show problems", "ctrl+shift+m", ["problems", "errors dikhao"], "Problems dikha diye."),
        keys(C, "open_recent", "Open a recent project", "ctrl+r", ["recent projects", "recent kholo"], "Recent."),
        keys(C, "new_file", "New untitled file", "ctrl+n", ["new file", "nayi file"], "Nayi file khol di."),
        act("run", "Run without debugging", ["vs code run karo", "run the code in vs code"],
            [{"focus": True}, {"keys": "ctrl+f5", "wait": 1.0}], risk="consequential", done="Run kar diya."),
    ]})

    N = ["notepad"]
    write("notepad", {"app": "notepad", "name": "Notepad", "aliases": ["notepad"], "window": {"exe": "Notepad.exe"},
        "launch": {"start_menu": "Notepad"}, "uri_schemes": [], "cli": {"notepad": "C:\\Windows\\notepad.exe"},
        "sources": ["docs/apps/notepad.md"],
        "note": "Saving stays with filesystem.write_text (journaled undo); nothing here saves.", "actions": [
        act("open", "Open Notepad", ["open notepad", "notepad kholo"], [{"focus": True}], route=False),
        act("open_file", "Open a text file in Notepad", ["open {path} in notepad", "notepad mein {path} kholo"],
            [{"cli": ["notepad", "{path}"]}, {"sleep": 1}], params={"path": {"type": "path"}},
            done="Notepad mein khol diya.", drill={"path": r"D:\ChutkuScratch\chutku-lab.txt"}),
        keys(N, "new_tab", "New Notepad tab", "ctrl+n", ["new tab", "naya tab"], "Naya tab khol diya."),
        keys(N, "find", "Find in Notepad", "ctrl+f", ["find", "mein dhundo"], "Find khol diya."),
        keys(N, "replace", "Replace in Notepad", "ctrl+h", ["replace"], "Replace khol diya."),
        keys(N, "insert_date", "Insert date and time", "f5", ["date daalo", "insert date time"], "Date daal di."),
        keys(N, "go_to_line", "Go to line", "ctrl+g", ["go to line", "line pe jao"], "Go to line khol diya."),
    ]})

    E = ["explorer", "file explorer"]

    # Owner, 2026-11-01: "har baar new file explorer na khola kar, ek hi mein kar". Go to the folder in the Explorer
    # window that is already open (focus opens one only if there is none): address bar, type, Enter.
    def go(target):
        return [{"focus": True}, {"keys": "ctrl+l", "wait": 0.4}, {"type": target}, {"keys": "enter", "wait": 1.2}]

    def shell(id, title, name, phrases):
        return act(id, title, phrases, go(f"shell:{name}"), done=title.split(" ", 1)[1] + " khol diya.")
    write("explorer", {"app": "explorer", "name": "File Explorer", "aliases": ["explorer", "file explorer"],
        "window": {"exe": "explorer.exe"}, "launch": {"start_menu": "File Explorer"}, "uri_schemes": [],
        "cli": {"explorer": "C:\\Windows\\explorer.exe"}, "sources": ["docs/apps/explorer.md"],
        "note": "Moving, copying, renaming and deleting stay with the filesystem tools (journaled undo, asks).",
        "actions": [
        act("open", "Open File Explorer", ["open file explorer", "file explorer kholo"], [{"focus": True}], route=False),
        act("open_folder", "Open a folder", ["open folder {path}", "{path} folder kholo"],
            go("{path}"), params={"path": {"type": "path"}}, done="Folder khol diya.", drill={"path": r"D:\ChutkuScratch"}),
        act("show_file", "Show a file in its folder", ["show {path} in explorer", "{path} ko folder mein dikhao"],
            [{"cli": ["explorer", "/select,{path}"]}, {"sleep": 1.2}], params={"path": {"type": "path"}},
            done="File dikha di.", drill={"path": r"D:\ChutkuScratch\chutku-lab.txt"}),
        shell("downloads", "Open Downloads", "Downloads", ["open downloads folder", "downloads folder kholo"]),
        shell("documents", "Open Documents", "Personal", ["open documents folder", "documents folder kholo"]),
        shell("desktop", "Open Desktop", "Desktop", ["open desktop folder", "desktop folder kholo"]),
        shell("pictures", "Open Pictures", "My Pictures", ["open pictures folder", "pictures folder kholo"]),
        shell("recycle_bin", "Open Recycle Bin", "RecycleBinFolder", ["open recycle bin", "recycle bin kholo"]),
        keys(E, "new_tab", "New Explorer tab", "ctrl+t", ["new tab", "naya tab"], "Naya tab khol diya."),
        keys(E, "search", "Search in this folder", "ctrl+e", ["search", "mein search karo"], "Search khol diya."),
        keys(E, "details_view", "Details view", "ctrl+shift+6", ["details view"], "Details view."),
        keys(E, "large_icons", "Large icons view", "ctrl+shift+2", ["large icons", "bade icons"], "Bade icons."),
    ]})

    pages = [("bluetooth", "bluetooth", ["bluetooth settings", "bluetooth settings kholo"]),
             ("wifi", "network-wifi", ["wifi settings", "wifi settings kholo"]),
             ("display", "display", ["display settings", "display settings kholo"]),
             ("sound", "sound", ["sound settings", "sound settings kholo"]),
             ("power", "powersleep", ["power settings", "battery settings kholo"]),
             ("apps", "appsfeatures", ["installed apps settings", "apps settings kholo"]),
             ("default_apps", "defaultapps", ["default apps settings", "default apps kholo"]),
             ("taskbar", "taskbar", ["taskbar settings", "taskbar settings kholo"]),
             ("notifications", "notifications", ["notification settings", "notifications settings kholo"]),
             ("windows_update", "windowsupdate", ["windows update settings", "update settings kholo"]),
             ("storage", "storagesense", ["storage settings", "storage settings kholo"]),
             ("night_light", "nightlight", ["night light settings", "night light kholo"]),
             ("mouse", "mousetouchpad", ["mouse settings", "touchpad settings kholo"])]
    write("settings", {"app": "settings", "name": "Windows Settings", "aliases": ["settings", "windows settings"],
        "window": {"title": "Settings"}, "launch": {"start_menu": "Settings"}, "uri_schemes": [],
        "sources": ["docs/apps/settings.md"], "note": "Only opens pages (safe); changing a toggle stays elsewhere.",
        "actions": [act(i, f"Open {i.replace('_', ' ')} settings", ph, [{"settings_uri": f"ms-settings:{u}"},
                        {"sleep": 1.5}], done=f"{i.replace('_', ' ').title()} settings khol di.") for i, u, ph in pages]})
    print("written")


if __name__ == "__main__":
    main()
