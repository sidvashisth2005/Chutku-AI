"""Write chutku/apps/tasks.jsonl: synthetic workflows for every kind of user (owner 2026-11-10: "synthetic workflows of
all possible tasks a user can give, all type of personalities ... into a hash table for lookup").

Each workflow is written once with how different people say it (English, Hinglish, Hindi script). A workflow with
`steps` is a ready plan for chutku/task_table.py (looked up by the normalised sentence). One without steps is still an
exam question: `expect` names the tools a correct plan uses (scripts/persona_exam.py scores it).

Personas: genz (curious, fun, instant), office (busy, multi-step, correct), student, elder (first-time user, plain
words), creator (media, screenshots, files).

    python scripts/make_task_table.py
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "chutku" / "apps" / "tasks.jsonl"
PRACTICE = r"D:\ChutkuPractice"


def s(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


# (id, personas, title, sayings, steps or None, expect tools)
W = [
    # -- quick facts and status (everyone) --
    ("time", "elder genz", "Tell the time", ["what time is it", "time kya hua hai", "कितने बजे हैं", "abhi kitne baje"],
     [s("system.get_time")], None),
    ("weather", "elder office genz", "Today's weather", ["aaj ka mausam", "how is the weather today", "मौसम कैसा है",
                                                         "bahar mausam kaisa hai"], [s("web.weather")], None),
    ("news", "office elder", "Latest news", ["aaj ki news sunao", "latest news", "ताज़ा खबरें", "what's in the news"],
     [s("web.news")], None),
    ("disk", "office student", "Disk space", ["how much space is left", "kitni storage bachi hai", "disk space batao",
                                              "मेरे पीसी में कितनी जगह बची है"], [s("system.disk_space")], None),
    ("slow", "office genz elder", "Why the PC is slow", ["why is my pc slow", "pc slow kyu chal raha hai",
                                                        "laptop hang kyu ho raha", "कंप्यूटर धीमा क्यों है"],
     [s("system.performance")], None),
    ("health", "elder office", "PC health", ["is my pc healthy", "pc ki health check karo", "laptop theek hai na"],
     [s("system.health")], None),
    ("internet", "elder office genz", "Internet check", ["is the internet working", "net chal raha hai kya",
                                                         "इंटरनेट चल रहा है", "wifi kaam kar raha hai kya"],
     [s("net.check")], None),
    ("battery_bt", "genz", "Bluetooth status", ["is bluetooth on", "bluetooth on hai kya", "bluetooth ka status batao"],
     [s("system.bluetooth_status")], None),
    ("gpu", "genz creator", "GPU status", ["gpu kitna use ho raha", "how busy is my graphics card", "gpu status batao"],
     [s("system.gpu_status")], None),
    ("what_open", "elder office", "What is open", ["what's open on my screen", "kaun kaun si windows khuli hain",
                                                   "screen pe kya kya khula hai"], [s("windows.list")], None),
    ("recent_files", "office student", "Recent files", ["show my recent files", "recent files dikhao",
                                                       "haal ki files dikhao", "abhi kaun si files khuli thi"],
     [s("files.recent")], None),
    ("cleanup_report", "office elder", "What is filling the disk", ["what is taking space", "kya jagah le raha hai",
                                                                    "storage saaf karne layak kya hai"],
     [s("storage.cleanup_report")], None),
    ("capabilities", "genz elder", "What Chutku can do", ["what can you do", "tum kya kya kar sakti ho",
                                                          "तुम क्या क्या कर सकती हो", "show me something cool"],
     [s("assistant.capabilities")], None),
    ("games", "genz", "Installed games", ["which games do i have", "mere games dikhao", "kaun kaun se games hai"],
     [s("games.list")], None),
    ("unread", "genz office", "Unread messages", ["any new messages", "kisi ka message aaya kya",
                                                  "unread messages kitne hai"], [s("message.unread_count")], None),
    ("now_playing", "genz", "What is playing", ["konsa gaana chal raha hai", "what song is this", "gaane ka naam kya hai"],
     [s("media.status")], None),
    ("reminders", "office student", "My reminders", ["show my reminders", "mere reminders dikhao", "kya kya yaad dilana hai"],
     [s("reminder.list")], None),
    ("notes", "student office", "My notes", ["show my notes", "meri notes dikhao", "notes list"], [s("note.list")], None),

    # -- sound, screen, look and feel --
    ("vol_up", "genz elder", "Volume up", ["volume badhao", "turn the volume up", "आवाज़ बढ़ाओ", "thoda tez karo awaaz"],
     [s("audio.volume", action="up")], None),
    ("vol_down", "genz elder office", "Volume down", ["volume kam karo", "turn the volume down", "आवाज़ कम करो"],
     [s("audio.volume", action="down")], None),
    ("mute", "office", "Mute", ["mute karo", "mute the sound", "awaaz band karo"], [s("audio.volume", action="mute")], None),
    ("bright_down", "student genz", "Brightness down", ["brightness kam karo", "screen ko dim karo",
                                                        "lower the brightness"], [s("display.brightness", action="down")],
     None),
    ("bright_up", "student genz", "Brightness up", ["brightness badhao", "increase the brightness",
                                                    "screen bright karo"], [s("display.brightness", action="up")], None),
    ("night_study", "student", "Night study setup", ["night study mode", "raat ki padhai mode",
                                                     "padhai ke liye screen set karo"],
     [s("display.brightness", action="set", level=40), s("audio.volume", action="set", level=20),
      s("settings.set", name="notifications", value="off")], None),
    ("focus", "office student", "Focus mode", ["focus mode on", "mujhe focus karna hai", "disturb mat karna",
                                               "no notifications for a while"],
     [s("settings.set", name="notifications", value="off")], None),
    ("notifs_on", "office student", "Notifications back on", ["notifications wapas on karo", "turn notifications on"],
     [s("settings.set", name="notifications", value="on")], None),
    ("show_ext", "office creator", "Show file extensions", ["show file extensions", "file extension dikhao"],
     [s("settings.set", name="file_extensions", value="show")], None),
    ("taskbar_left", "genz", "Taskbar to the left", ["taskbar left mein karo", "move the taskbar icons left"],
     [s("settings.set", name="taskbar_alignment", value="left")], None),
    ("power_saver", "student elder", "Save battery", ["battery bachao", "power saver on karo", "save battery mode"],
     [s("settings.set", name="power_plan", value="power_saver")], None),
    ("performance", "genz creator", "Full performance", ["full performance mode", "gaming ke liye fast karo",
                                                         "high performance on karo"],
     [s("settings.set", name="power_plan", value="high_performance")], None),
    ("dark", "genz", "Dark mode", ["dark mode on karo", "turn on dark mode", "डार्क मोड चालू करो"],
     [s("settings.theme_set", mode="dark")], None),
    ("light", "elder", "Light mode", ["light mode karo", "turn on light mode"], [s("settings.theme_set", mode="light")],
     None),
    ("lock", "office", "Lock the PC", ["lock my pc", "pc lock karo", "laptop lock kar do"], [s("system.lock")], None),

    # -- media --
    ("pause", "genz office", "Pause music", ["gaana roko", "pause the music", "music pause karo"],
     [s("media.control", action="pause")], None),
    ("play", "genz", "Resume music", ["gaana chalao wapas", "resume the music", "music play karo"],
     [s("media.control", action="play")], None),
    ("next", "genz", "Next song", ["next song", "agla gaana", "अगला गाना"], [s("media.control", action="next")], None),
    ("prev", "genz", "Previous song", ["previous song", "pichla gaana", "pichhla gaana lagao"],
     [s("media.control", action="previous")], None),
    ("lofi", "student genz", "Lofi on YouTube", ["play lofi on youtube", "youtube pe lofi chalao", "padhai wala lofi lagao"],
     [s("youtube.play", query="lofi hip hop study")], None),

    # -- apps --
    ("open_calc", "student office", "Calculator", ["open calculator", "calculator kholo", "कैलकुलेटर खोलो"],
     [s("apps.launch", name="Calculator")], None),
    ("open_word", "office student", "Word", ["open word", "word kholo", "ms word open karo"], [s("apps.launch", name="Word")],
     None),
    ("open_excel", "office", "Excel", ["open excel", "excel kholo", "excel sheet kholo"], [s("apps.launch", name="Excel")],
     None),
    ("open_ppt", "office student", "PowerPoint", ["open powerpoint", "ppt kholo", "powerpoint kholo"],
     [s("apps.launch", name="PowerPoint")], None),
    ("open_paint", "genz creator", "Paint", ["open paint", "paint kholo", "drawing karni hai paint kholo"],
     [s("apps.launch", name="Paint")], None),
    ("open_snip", "creator office", "Snipping Tool", ["open snipping tool", "snipping tool kholo", "screenshot tool kholo"],
     [s("apps.launch", name="Snipping Tool")], None),
    ("open_clock", "student", "Clock (timers)", ["open clock", "clock app kholo", "timer wala app kholo"],
     [s("apps.launch", name="Clock")], None),
    ("open_settings", "elder", "Settings", ["open settings", "settings kholo", "सेटिंग्स खोलो"],
     [s("apps.launch", name="Settings")], None),
    ("open_explorer", "elder office", "File Explorer", ["open my files", "file explorer kholo", "files kholo"],
     [s("apps.launch", name="File Explorer")], None),
    ("open_task_manager", "office genz", "Task Manager", ["open task manager", "task manager kholo"],
     [s("apps.launch", name="Task Manager")], None),
    ("scientific", "student", "Scientific calculator", ["open scientific calculator", "scientific calculator kholo",
                                                        "calculator mein scientific kholo"],
     [s("app.calculator.scientific")], None),
    ("currency", "office genz", "Currency converter", ["currency converter kholo", "open the currency converter",
                                                       "calculator mein currency kholo"],
     None, ["apps.launch"]),
    ("graphing", "student", "Graphing calculator", ["graphing calculator kholo", "open graphing calculator"],
     [s("app.calculator.graphing")], None),

    # -- web and mail (office) --
    ("gmail", "office", "Open Gmail", ["check my mail", "gmail kholo", "mera email kholo", "मेल खोलो"],
     [s("web.open", url="https://mail.google.com")], None),
    ("calendar", "office", "Open my calendar", ["open my calendar", "aaj ki meetings dikhao calendar mein",
                                                "google calendar kholo"],
     [s("web.open", url="https://calendar.google.com")], None),
    ("start_day", "office", "Start my work day", ["start my work day", "kaam shuru karte hai", "office mode on",
                                                  "work setup kholo"],
     [s("web.open", url="https://mail.google.com"), s("web.open", url="https://calendar.google.com", tab="new"),
      s("apps.launch", name="Visual Studio Code")], None),
    ("chatgpt", "student genz", "Open ChatGPT", ["open chatgpt", "chatgpt kholo"], [s("apps.launch", name="ChatGPT")],
     None),
    ("youtube", "genz", "Open YouTube", ["open youtube", "youtube kholo", "यूट्यूब खोलो"],
     [s("web.open", url="https://www.youtube.com")], None),
    ("maps", "elder office", "Directions", ["show me the way to the railway station", "station ka rasta dikhao"],
     [s("web.search", query="railway station near me", site="maps")], None),

    # -- reminders and timers --
    ("timer10", "student genz", "10 minute timer", ["10 minute ka timer lagao", "set a 10 minute timer",
                                                    "10 min baad bata dena"],
     [s("reminder.set", message="10 minute ho gaye", in_minutes=10)], None),
    ("water", "office student elder", "Drink water reminder", ["remind me to drink water in 30 minutes",
                                                               "30 minute baad paani peene ki yaad dilana"],
     [s("reminder.set", message="Paani pi lo", in_minutes=30)], None),
    ("break", "office", "Break reminder", ["remind me to take a break in an hour", "1 ghante baad break ki yaad dilana"],
     [s("reminder.set", message="Break le lo", in_minutes=60)], None),

    # -- files (practice folder only, so a plan never touches the owner's files on a guess) --
    ("zip_practice", "office", "Zip the practice folder", ["zip the practice folder", "practice folder ki zip banao"],
     [s("files.zip", path=PRACTICE)], None),
    ("list_practice", "office student", "List the practice folder", ["practice folder mein kya hai",
                                                                     "show the practice folder"],
     [s("filesystem.list", path=PRACTICE)], None),

    # -- needs the planner (exam only): context, people, several apps, judgement --
    ("send_ub", "genz", "Message someone", ["UB ko whatsapp pe hi bhejo", "send hi to UB on whatsapp"], None,
     ["message.send"]),
    ("locked_kitkat", "genz", "Locked chat message", ["kitkat ko hello bhejo locked chat mein",
                                                      "send hello to kitkat in locked chats"], None, ["message.send"]),
    ("reply_mom", "elder", "Read a reply", ["mammi ne kya bola", "did mom reply on whatsapp"], None,
     ["message.read_chat"]),
    ("invoice", "office", "Find the latest invoice", ["find the latest invoice pdf and open it",
                                                      "sabse nayi invoice wali pdf kholo"], None,
     ["files.locate", "files.open"]),
    ("mail_draft", "office", "Draft a mail", ["write a mail to my manager that i will be late",
                                              "boss ko mail likho ki main late aaunga"], None, ["email.draft"]),
    ("word_pdf", "office student", "Word to PDF", ["make a word file with my notes and save it as pdf",
                                                   "notes ki word file bana ke pdf kar do"], None,
     ["apps.launch", "desktop.do"]),
    ("summarise_screen", "genz student", "Explain the screen", ["explain what's on my screen", "screen pe kya hai samjhao"],
     None, ["screen.understand"]),
    ("song_play", "genz", "Play a song", ["play afterparty hits on spotify", "spotify pe lowkey chalao"], None,
     ["app.spotify.play_playlist", "spotify.search"]),
    ("game_launch", "genz", "Launch a game", ["launch valorant", "gta chalao"], None, ["games.launch"]),
    ("record_game", "genz creator", "Record gameplay", ["record my game", "game recording on karo"], None,
     ["keyboard.keys"]),
    ("downloads_tidy", "office", "Tidy downloads", ["organise my downloads folder", "downloads saaf karo type ke hisaab se"],
     None, ["files.organize"]),
    ("wallpaper", "genz", "Change wallpaper", ["change my wallpaper", "wallpaper badlo"], None,
     ["desktop.wallpaper_set"]),
    ("headphones", "genz", "Sound to headphones", ["sound headphones pe karo", "switch audio to my earbuds"], None,
     ["audio.set_output"]),
    ("assignment", "student", "Note an assignment", ["add physics assignment due friday", "physics ka assignment add karo friday tak"],
     None, ["mind.add"]),
    ("research", "student", "Look something up", ["what is photosynthesis", "photosynthesis kya hota hai"], None,
     ["web.results"]),
    ("call_mom", "elder", "Call someone", ["mammi ko call karo whatsapp pe", "call mom on whatsapp"], None,
     ["screen.click_risky"]),
]


# Other tools that also do the job right (persona exam 2026-11-10): the exam accepts them too.
ALSO = {"what_open": ["desktop.survey"], "mute": ["keyboard.keys"], "timer10": ["task.schedule"],
        "calendar": ["apps.launch"], "youtube": ["apps.launch"], "game_launch": ["apps.launch"],
        "scientific": ["apps.launch"], "currency": ["apps.launch"], "graphing": ["apps.launch"]}


def lang(text):
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    hinglish = r"\b(?:karo|kar|kya|hai|kholo|mein|batao|dikhao|chalao|lagao|ka|ki|ke|ko|wala|kitna|kitni|bhejo|ne)\b"
    return "hinglish" if re.search(hinglish, text, re.I) else "en"


def main():
    rows = []
    for wid, personas, title, sayings, steps, expect in W:
        for i, say in enumerate(sayings):
            row = {"id": f"{wid}-{i}", "workflow": wid, "personas": personas.split(), "lang": lang(say), "say": say,
                   "title": title,
                   "expect": sorted(set(expect or {st["tool"] for st in steps}) | set(ALSO.get(wid, [])))}
            if steps:
                row["steps"] = steps
            rows.append(row)
    keys = {}
    from_here = __import__("sys")
    from_here.path.insert(0, str(ROOT))
    from chutku.task_table import key
    for row in rows:   # one sentence, one plan: a duplicate key would make the lookup depend on the order
        other = keys.setdefault(key(row["say"]), row["id"])
        if other != row["id"]:
            raise SystemExit(f"duplicate sentence: {row['id']} and {other}")
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    per = {}
    for row in rows:
        for persona in row["personas"]:
            per[persona] = per.get(persona, 0) + 1
    print(f"{len(rows)} rows, {sum(1 for r in rows if r.get('steps'))} with a ready plan, {len(W)} workflows; "
          f"per persona {per}; langs {sorted({r['lang'] for r in rows})}")


if __name__ == "__main__":
    main()
