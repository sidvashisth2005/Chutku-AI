# Chutku — Owner's Guide

Everything you need to use, control and look after Chutku. Last updated 2026-10-03 (internet check, paused banner with Resume, sleep-safe guard).

---


> **Chutku is female.** Her name in Hindi is **छुटकू** (said "Chhutku"). When she talks about herself in Hindi she says "kar rahi hoon", "kar dungi", "samajh gayi". "Oye Chhutku", "Oye Chutku" and "ओए छुटकू" all wake her.

## 1. Starting, opening and stopping

| What | How |
|---|---|
| Chutku starts by itself | At Windows sign-in, through the scheduled task `\Chutku\Chutku`. Turn it off with `.venv\Scripts\python.exe -m chutku.cli autostart off`. |
| Open the dashboard | Double-click **`Open-Chutku.cmd`** in `D:\Project\Chutku`. If it says "not running", start it first. |
| Tray icon | The green **c** in the notification area (it may be under the ^ arrow). **Click** to open the dashboard. **Right-click** for Pause/Resume actions and Stop Chutku. |
| Start it by hand | Double-click **`Start-Chutku.cmd`**. It starts Chutku and opens the dashboard. |
| Talk from anywhere | **Ctrl+Alt+Space**, then speak. You can also say **"Oye Chutku"** or **"Chutku sun"** if the wake phrase is switched on in the dashboard. |
| Emergency stop | **Ctrl+Alt+F12**, or the **Stop Chutku** button. This stops everything at once. |
| Pause or resume actions | The **Pause actions** button at the top of the dashboard, or `python -m chutku.cli control pause` and `control resume`. |
| Is it OK? | `.venv\Scripts\python.exe -m chutku.cli doctor`. It should say `"ready": true`. |

**Important:** after any crash, forced stop or emergency stop, Chutku starts up **paused** on purpose. Check Activity, then press **Resume actions** in the dashboard or run `python -m chutku.cli control resume`.

All commands are run from `D:\Project\Chutku` using `.venv\Scripts\python.exe -m chutku.cli …`.

---

**The Ctrl+Alt+Space panel:**
- **Move** it by dragging its top bar (where "C H U T K U" is).
- **Resize** it with **－ / ＋** at the top right, or drag the **◢** grip in the bottom-right corner. The text shrinks with it.
- **Click any other app** and the panel goes behind that app; it stays open in the background. Press Ctrl+Alt+Space to bring it back to the front.
- **✕** hides it.
- Its size and position are remembered.

**Give several orders and walk away:** while one task runs, new orders (typed in the dashboard or the panel, or spoken with the wake phrase) wait in line, marked **queued**, and start by themselves one after another. Up to 10 can wait. Stop on a queued task removes it from the line. When a run of two or more tasks is over, a Windows notification lists them (✓ done / ✗ not done). Voice answers are spoken as each task finishes.


### Try a more natural voice (your choice, 2026-10-06)
Chutku can speak offline with a neural female voice (Kokoro) instead of Windows' Zira. Twenty of her real replies are already rendered. To choose, run this and listen:

    .venv\Scripts\python.exe scripts\tts_ab.py --listen

Each sentence plays twice, as A then B, in random order. Press 1 or 2 for the one you prefer (s skips, q stops). If you prefer Kokoro in most answers, Chutku switches her offline voice; if not, Zira stays. The files are in `D:\ChutkuScratch\tts_ab\`.

### Voice conversation fixes (2026-10-06)
- **A quick "हां"** is no longer lost. If Chutku answers before your words are written down, she waits up to 2 seconds for them.
- **One request is started once,** even if it is heard twice within 2 seconds.
- **Words that come out in Spanish** ("Sí, un poco") are treated as misheard and start nothing. Say it again.
- **Her replies no longer repeat** or run into each other in the conversation log.
- **Names come from your memory.** She writes your saved people's names exactly as saved ("remember UB is my mammi"); no names are built into the code.

### Mute the mic without stopping Chutku
When friends are talking or laughing around you, mute the mic: Chutku keeps talking and finishes her answer, but hears nothing from the room until you unmute.
- **Ctrl+Alt+X** toggles mute from anywhere, with one hand. If another program ever takes it, Chutku uses the next free one (Ctrl+Alt+Z → Ctrl+Alt+M → Ctrl+Alt+Shift+Space); the panel and the dashboard show which key is active.
- Or click **🎙 MIC** on Chutku's floating panel. It turns red **🔇 MUTED** while muted.
- A plain Space key was not used: as a global key it would catch every space you type in other apps.
- While muted: the conversation stays open (it doesn't end after 60 s of silence), the wake phrase is off, and offline follow-up listening waits up to 60 s for you to unmute.
- It is temporary: calling Chutku again (hotkey or "Oye Chhutku") or the end of a conversation unmutes, and a restart always starts unmuted.

## 2. How much Chutku does on its own (autonomy)

Pick a level under the chat box. Each browser remembers its own choice; a new browser starts at **Owner**. If your browser still shows another level, click **Owner** once.

| Level | What runs without asking |
|---|---|
| **Review every step** | Nothing. You approve every step. |
| **Auto: safe steps** | Looking at things, answering questions, opening apps, sites and files, volume and brightness. |
| **Auto: incl. file edits** | All of the above, plus file changes Chutku can undo (writes, moves, copies). |
| **Owner: no approvals** (your standing order, default since 2026-10-04) | Everything else: closing apps, typing and clicking, settings, building projects, reminders, memory, and messages to people in your memory. |

**In Owner mode, Chutku still asks before:**
- **Changing files:** writing, moving, copying, organizing, and undoing file changes. Creating something new (a folder, a zip, a project) does not ask.
- **Deleting anything:** files (always to the Recycle Bin), memory, routines. Permanent delete is something only you can ask for.
- **Shutdown, restart, killing a program, or turning the network off**, because unsaved work could be lost.
- **Running a script or a program with arguments** (`code.run_python`, `process.launch`), **typing into a command window** (Command Prompt, PowerShell, Terminal, the Run box), or **opening one**. This holds in every level (since 2026-10-06).
- **A message to someone not in your memory.** Teach them once ("Rahul is my DL wale sir") and later messages go straight out.
- **Any step that comes right after Chutku read a web page or a message**, so a page cannot order Chutku to act.
  After reading outside text (a web page, a chat, your clipboard, an image, words on screen), Chutku also asks before **opening an app or a file, changing what it remembers, or switching offline mode off**, unless you named that app or file yourself in the request (since 2026-10-06).
- **Changing a saved contact's number or WhatsApp name.** Messages to saved people go out without asking, so where they go is your choice. Adding a new person or a nickname does not ask.

Everything is still logged ("what did you do today"), the Stop / Pause buttons still work, and Windows system folders are never touched.

**Approving by voice:** Answer in Hindi or English, Chutku understands both (हाँ, हम्म, जी, ठीक है, भेज दो, haan, hnn, yes, ok...). Any "no / nahi / नहीं / ruko / cancel" cancels; "hmm" in the middle of a long sentence is not taken as a yes. when you started the request by voice (hotkey, wake phrase or conversation), Chutku says what it is about to do, for example *"Send 'hi' to Ub on WhatsApp? Haan ya na?"*, and listens.
- **"haan" / "yes" / "hnn" / "bhej do" / "kar do"** approves.
- **"nahi" / "no" / "ruko" / "cancel"** cancels.
- A yes counts only if it is short and has no no-word in it, so background talk can't approve anything.
- If it doesn't hear a clear answer twice, it leaves the Approve button on screen.

In the other three levels, deleting, sending messages, closing apps, power, installing, running code and building apps always ask.

The hands-free (voice) level is set separately, in the dashboard's Hands-free row. It is now **Owner: no approvals**.

---

## 3. Things you can say

Everything below is **instant**: matched by rules and done within about a second, without the AI model. The exceptions are marked *(model)*: those, and anything you phrase differently, are planned by the local model, or by Gemini for code and long tasks. English, Hindi and Hinglish all work.

**Controlling Chutku** (works typed, in the panel, or by voice)
- "stop" / "ruko" / "cancel" / "bas": stops the running task **and** everything waiting in line, at once. (With nothing running, "stop" pauses your music.)
- "pause actions" / "sab rok do": stops everything and pauses Chutku until you press Resume on the dashboard or tray.
- "undo that" / "wapas karo": reverses the most recent change Chutku can undo (a write, move, copy, Recycle Bin, tidy-up).
- "do it again" / "phir se karo": repeats your previous request.
- "what did you just do" / "abhi kya kiya": the last few actions. "what can you do" / "help": a short list. "are you there" / "suno": a quick hello back.

**Your day**
- "good morning" / "briefing" / "subah ki report": time, weather, reminders and news
- "what time is it" / "kitne baje hai"
- "weather in Pune" / "Pune ka mausam kaisa hai"
- "khabar batao" / "latest news about cricket"
- "remind me in 20 minutes to stretch" / "set a timer for 25 minutes"
- "remind me at 5 to call papa": 1 to 6 without am/pm means the evening (5 pm), the same as "5 baje"; 7 to 11 means the morning. Say "am" or "pm" to be exact.
- "search my downloads for invoice" looks only in Downloads (also desktop, documents, pictures, music, videos). "temperature of my cpu" shows CPU, GPU and memory, not the weather.
- "remember city = Delhi" / "remember my birthday is 12 May"

**Files, by full path** (instant; changing or deleting asks first)
- "what files are in D:\Projects" / "D:\Projects mein kya hai" · "read D:\Notes\todo.txt and tell me the first task"
- "rename D:\x\draft.txt to final.txt" · "make a copy of A named B" · "move A to D:\Backup"
- "delete D:\x\junk.tmp" (goes to the Recycle Bin) · "write 'hello' into D:\x\a.txt" · "D:\x mein notes naam ka folder banao"
- Whole drives, "everything" and wildcards like *.tmp are never done instantly; Chutku plans those carefully and asks.

**Finding and opening your stuff**
- "open my downloads" / "downloads kholo" / "open photos" / "open D drive" / "d drive kholo"
- "find my resume" / "search my files for invoice" / "meri resume file dhundo". This searches Desktop, Documents, Downloads, Pictures, Videos, Music and OneDrive by file name, newest first, skipping code folders.
- "find my newest pdf" *(model)*: questions with newest, latest or biggest go to the AI.

**Brave and websites**: websites, YouTube and searches open in **Brave** (change it under the dashboard's Browser setting; say "in Edge" / "in Chrome" for a one-off)
- "open youtube.com in brave" · "Brave mein YouTube kholo" · "brave browser kholo"
- If Brave is already open, pages open as **new tabs** in it, and "open Brave" just brings that window to the front (no extra windows).
- "play Latent season 2 latest episode on youtube" · "search python tutorials on youtube in brave"

**WhatsApp chats**
- "search Pita Shri in WhatsApp" / "WhatsApp pe Pita Shri ki chat kholo" / "open Pita Shri's chat on whatsapp": opens that chat and asks what to send; then just say "hi bhej do" (within 2 minutes) and it goes to that chat.
- Works from any WhatsApp screen: Archived, Calls, Status, Settings. Chutku goes back to the main Chats list first, because the search bar is only there. Chats in **Locked chats** are hidden by WhatsApp and need your PIN or fingerprint; open those yourself.
- Hindi script is fine: "पिता श्री" is read as "Pita Shri", "मम्मी" as "mammi".
- Read replies: "Pita Shri ne kya bola?" / "did mammi reply?" / "UB ka last message kya hai" / "what did Pita Shri say". Chutku opens the chat, reads the latest messages from the screen (locally) and tells you who said what. Photos, stickers and voice notes can't be read. If WhatsApp on the PC says "Syncing paused", Chutku tells you; open WhatsApp on your phone so recent messages appear.
- If WhatsApp on the PC is logged out (QR-code screen), Chutku says so straight away: link it again from your phone (WhatsApp > Linked devices > Link a device).

**Messages** (always asks before sending)
- "send hi to UB on whatsapp" / "UB ko whatsapp pe hi bhejo" / "message UB on whatsapp saying hi there"
- Chutku searches your chats and opens only a chat whose name is *exactly* what you said (it uses WhatsApp's own green highlight, so short names like "Ub" work). If no chat or several chats match, it sends nothing and tells you the closest names.
- Fastest: save a number once with "remember contact_ub = +91…", and messages to UB skip the search.

**Your to-do list**
- "note: buy milk" / "note that the meeting is at 5" / "add call mom to my list" / "likh lo: pay the bill"
- "show my list" / "my todo list" / "meri list dikhao"
- "mark 2 done" / "2 ho gaya" / "mark 2 as not done"

**Pictures and the screen** (local vision model on this PC first; Gemini only as the backup)
- "what's on my screen" / "screen pe kya hai": describes the screen as it was when you called Chutku
- "describe D:\Photos\trip.jpg" / "what is in this image D:\Pictures\x.png"
- Local looks take about 30 s (Gemini took about 5–10 s), and the screenshot never leaves your PC. PNG and JPG work locally; WEBP and HEIC pictures still need Gemini.

**Offline mode** (works without internet; Gemini stays as the backup)
- "offline mode on" / "offline mode chalu karo" / "go offline": only local models, nothing is sent to Gemini even when the internet works. "offline mode band karo" / "go online" turns it off. There is also a checkbox on the home page under Hands-free.
- Without internet Chutku switches to local models by itself; the switch is only needed if you want local-only while online (privacy, or saving Gemini credits).
- Offline, the voice works like this: hotkey or "Oye Chutku" → it answers out loud → it keeps listening for a follow-up without the wake phrase. Say "bas" / "bye" or stay quiet to stop.
- **Speed tip:** keep the laptop plugged in. On battery Windows slows the graphics card about 4–5×, so local answers that take 3–8 s plugged in can take 15–40 s.
- When Chutku uses her local model she uses a shorter, faster setup (since 2026-10-05: about 3× faster). When Gemini is used, nothing about Gemini changed. If you repeat exactly a request that fully worked before, she reuses the same plan without thinking again.
- Hard requests that the everyday local model can't plan go to a bigger local model (Qwen3-8B). It is slower: about 30 s to load and a few words per second, so 45 s to a few minutes per answer.
- Still need internet: web search and websites, YouTube, weather, news, sending WhatsApp messages, Spotify streaming, and the natural back-and-forth voice conversation (Gemini Live).

**Your PC**
- "how much space is left" / "storage kitna khali hai" / "how much free space is left on my C drive" / "D drive mein kitni jagah khali hai"
- "how much RAM am I using" / "battery kitni hai" / "how is my PC doing"
- "what is the current volume level" / "what is my screen brightness" / "is dark mode on" / "how many displays are connected"
- "is VLC installed" / "is VLC or Spotify installed" / "do I have Steam installed"
- "which games do I have installed" / "mere games dikhao": Steam and Epic games
- "which windows are open" / "what's open right now" / "kaun se apps khule hain": the apps you have open, read from Windows
- "am I connected to the network? which adapter is up?": internet check plus Wi-Fi/Ethernet status
- "free up space on my C drive" / "what's taking up space". This only looks; it never deletes.
- "what was I working on?": files changed recently in Desktop, Documents and Downloads
- "organize my Downloads folder" / "downloads saaf karo". This sorts files into Images, Documents, Videos and so on. It asks first, and you can undo it.
- "is my internet working" / "internet chal raha hai kya" / "net slow hai": checks connection, DNS and speed, and says in plain words what's wrong
- "whats my ip" / "mera ip kya hai" / "ping google"
- "lock my PC"
- "volume 40" / "awaaz kam karo" / "mute" / "brightness kam karo"
- "switch audio to headphones" / "use my speakers" / "headphones pe sound karo" / "list audio devices"
- "zip D:\Projects\site" / "unzip D:\Downloads\x.zip" *(model)*

**Apps and media**
- "open Spotify" / "spotify kholo" / "close Spotify"
- Any app name, even an inexact one ("open vs code", "open calc"). If the name isn't an exact Start-menu name, Chutku does what you would: it opens Windows search, types the name, and opens the first result (top, then 2nd, 3rd…) that is an installed app. It never clicks web results, folders or Uninstall. If nothing fits, it tells you what the search showed.
- "play arijit singh on youtube" / "youtube pe lofi chalao"
- "next song" / "pause" / "what's playing" / "kaunsa gaana chal raha hai"
- "search youtube for lofi" / "google python tutorials"
- "open Spotify and play music" (two steps in one sentence)
- "install hollow knight on steam" / "steam pe stardew valley install karo": opens Steam's own install window; you pick the drive (D: has the space) and click Install there

**Your memory (people, facts about you, your lists)**: stored only on this PC in `data/mind.json`
- Teach people: "UB is my gf" / "UB meri gf hai" / "remember Sharma Sir is my DL wale sir" / "mammi ka number +91 98765 43210 hai"
- Then message them by nickname, no app needed: "send hi to my gf" / "gf ko good night bhejo" / "mammi ko khana kha liya bolo" (goes on WhatsApp). "mom", "mummy", "mammi" and "mother" all mean the same person; "mama" does not (uncle). If two people fit (two "bhai"), Chutku won't guess.
- About you: "my home is in Pune" / "mera ghar Pune mein hai"
- Lists (assignments, schedule, skills, domains, projects, goals): "add assignment: DBMS report by Friday" / "my skills are python, react" / "add hackathon prep to my goals" / "assignment 1 done"
- Ask: "show my assignments" / "mere assignments dikhao" / "who is my gf" / "what do you know about me"
- Folder contents with exact counts, instantly: "mere desktop pe kitni files hain" / "what's on my desktop" / "how many files are in my downloads" / "documents mein kya kya hai". Files and folders are counted separately.
- Forgetting a person or item asks first (it is a deletion).
- Dates go into your schedule with the real date: "my exam is on 12 oct" / "mera DBMS viva kal hai" / "meeting friday ko hai" / "i have an interview tomorrow" / "meri presentation parso hai". "kal" is saved as tomorrow's actual date, so it stays right the next day. Questions ("is my exam on monday?") are not saved.
- **Mind map:** "mind map dikhao" / "show my mind map" opens the dashboard's **Mind map** tab in Brave: you in the middle; around you People, About you, Assignments, Schedule, Goals, Projects, Skills, Domains, Notes, Habits and Recent topics. Click a dot for details.

**Chutku remembers your conversations** (since 2026-10-04, only on this PC in `data/conversations.jsonl`)
- Every request you type or say, and every voice conversation, is saved as text with Chutku's answer. Noise that was ignored is not saved.
- "what did we talk about yesterday" / "kal humne kya baat ki" / "pichli baar maine kya pucha tha" / "what did we talk about today": a list with times.
- When you ask for something, Chutku is given the parts of its memory that fit that request: the people and facts involved, open tasks, and related earlier conversations. So "do that again" or "send it to her" can work. The local AI gets up to about 1,200 characters. Gemini gets at most 800 characters, inside the same request, so it costs no extra calls or credits.

**Teaching Chutku how you like things**
- After a task: "good job" / "shabash" / "badhiya" tells Chutku that was right, and it prefers that plan next time. "galat kiya" / "wrong" / "ye galat hai" means it never reuses that plan again; then say what you wanted.
- If a request fails and you say it differently within 10 minutes and that works, Chutku remembers that your first wording means the plan that worked.
- Things you ask for at about the same time on 3 or more different days become **habits** (checked once a day). They appear on the mind map and as suggestions at that time.

**Everyday Hinglish**
- "agla gaana" / "pichla gaana" · "volume thoda badhao" / "awaaz kam karo" · "brightness full karo" / "screen ki brightness 50 karo"
- "screenshot lo": Windows saves it in Pictures\Screenshots
- "10 minute ka timer lagao" · "kal subah 7 baje ka alarm lagao" · "mujhe 5 baje yaad dilana meeting hai". Without subah/sham, 1–6 baje means afternoon/evening and 7–11 means morning; a time already gone today means tomorrow.
- "spotify pe arijit singh chalao": opens Spotify's search for it (press play on the top result)
- "cricket score kya hai" · "instagram kholo brave mein" · "kya chal raha hai screen pe" / "yeh kya hai"
- **Browser tabs:** a new search, video or site goes into the tab Chutku opened last, if that tab is still the one showing. Add "in a new tab" / "new tab mein" for a new tab, or "isi tab mein" / "same tab" to use whatever tab is showing. If you have switched to your own tab, Chutku opens a new one instead of overwriting yours. To type into the address bar, Chutku brings Brave to the front.
- **WhatsApp follow-ups:** when the chat is already open in front, the next message ("ye bhi bhej do") is typed straight into it after the header shows the right name; no search, no reopening. Emoji-only messages (🙏) are checked by a new bubble appearing, because screen reading cannot read emoji. Messages to someone not in Chutku's memory still ask first; say "remember Pita Shri is my father" once and they go straight out.
- "Pita Shri ko bolo main late aaunga": a WhatsApp message (someone new is asked about first)
- Not yet possible, and Chutku says so: calls ("mammi ko call karo"). Emptying the Recycle Bin is left to you because it deletes for good. Wi-Fi/Bluetooth/shutdown/restart go through the careful (model) path, and shutdown/restart always ask.

**Just talking**
- "hi" / "hi Chutku, how are you" / "kaise ho" / "thank you": an instant friendly reply. A greeting joined to a task ("hi, open Spotify") is treated as the task.

**Keyboard and mouse**: any shortcut, and clicks on anything you can see
- "press ctrl+shift+t" / "ctrl shift t dabao" / "press f5" / "alt tab karo" / "press down 5 times" / "press ctrl+k, ctrl+c"
- "click on Downloads" / "Downloads pe click karo" / "right click on Recycle Bin" / "double click on Chrome" / "hover over Settings"
- Text targets are read from the screen locally. If a word appears more than once, Chutku asks which one (1st, 2nd…). Single characters and icons (like a calculator's "8") are hard to read; for those say "click the 8 button" and the screen-understanding path handles it.
- These ask first, because they change or delete files: Ctrl+S (save); Delete, F2 (rename), cut/paste/undo, or dragging inside File Explorer; clicking a button that says Delete, Remove, Uninstall, Save, Replace or Rename.
- Windows never lets any program press Ctrl+Alt+Del or type into admin windows.

**What Chutku did**
- "what did you do today" / "aaj kya kiya": numbered list from the action log
- To undo an action: open "what did you do today", then ask to undo action number N *(model)*. "Undo last write" is a button on the home page.

**Bigger jobs** *(model)*
- "build me a calculator app" / "ek portfolio website banao": the request is recognised instantly; the AI then writes the code, opens it in VS Code, tests it and launches it
- "find my newest PDF in Downloads and open it"
- "make a folder D:\Notes and write today's plan in it"

---

## 4. Routines (one phrase, several actions)

- **Save:** "save routine work: open visual studio code, play lofi hip hop on youtube, set volume to 30"
- **Run:** "start work mode" / "work mode on karo", or click the **▶ work mode** button on the home page
- **See them:** "list my routines"
- **Delete:** ask to forget the routine. This asks first.

Rules:
- At most 4 steps per routine.
- Each command must be one of the instant phrases above. Chutku refuses anything else when you save.
- Every step still goes through the normal safety checks when the routine runs.

---

## 5. The dashboard home page

- **Today panel:**
  - greeting and clock
  - weather (needs `remember city = …` once)
  - drive space bars (red when low)
  - upcoming reminders
  - your to-do list
  - files you were working on
  - what Chutku did today
  - your routines
- **Suggestions** (under the alerts), each with **✓ Yes** (Chutku does it) and **Not now**:
  - a dated schedule item that is tomorrow: a reminder to prepare (7 pm, or in 30 minutes if it's later than that)
  - an event that is today: a reminder in 1 hour
  - open assignments: "see them?"
  - a habit around this hour you haven't done yet today
  - C: under 10 GB free: "see what is taking space?"

  "Not now" hides that one for 7 days. After 3 "Not now"s on one kind (e.g. habits), Chutku stops suggesting that kind; a ✓ Yes on it starts them again. At most **one** suggestion pops up as a Windows notification per hour, and never between 23:00 and 08:00.
- **Health alerts** show at the top and also as Windows notifications:
  - **Disk** under 5% free: at most once every 12 hours
  - **Battery** at 20% and again at 10% when unplugged
  - **Memory** at 90% or more: at most hourly
- **Quick buttons:** Briefing, Recent work, Disk space, Free up space, What did you do?, Tidy Downloads, What's playing?, Undo last write.
- **Paused banner:** when Chutku is paused, the home page says why and when, with a **Resume actions** button.
- **Interrupted banner:** if Chutku crashed or was stopped in the middle of a task, the home page says what it was doing, with **Retry** and **Dismiss**. Nothing is retried automatically.
- **Activity tab:** every task with its full trace.
- **Memory tab:** the notes you saved.
- **Mind map tab:** everything you told Chutku, drawn as a map (see section 3).

---

## 6. Safety rules (fixed in the code)

- **System and program files are never changed.** This covers `C:\Windows`, Program Files, ProgramData, AppData, drive roots, boot files and Chutku's own folder (except `sandbox\`). It holds at any level, with any approval. **Uninstalling programs is blocked**, because it deletes program files.
- **Unclear locations are refused.** A path Chutku can't resolve safely (network shares, `\\?\` tricks, `CON`, `file:stream`, `..`) is refused, not guessed.
- **Delete means the Recycle Bin.** You can restore from Chutku or from Explorer. Every delete asks first. Removable and network drives are refused, because they have no Recycle Bin.
- **Permanent delete** happens only when *you* say "permanently delete …". The agent can never choose it, and it always asks.
- **Web reading only reaches public sites.** The address is checked, and the connection goes to exactly that checked address, so a page can't redirect Chutku to this PC or your home network. An agent step that opens the test browser on a local or home-network address asks first.
- **Nothing runs unlogged.** If the action log can't be written (for example, its last line is damaged), Chutku refuses to act and tells you to run `doctor`.
- **Organize never overwrites.** If a file with the same name appears in the target folder meanwhile, that file is skipped. Undo also never touches system folders, whatever a record says.
- **Apps Chutku opens for you stay open when Chutku stops** (browser, VS Code, an app it built). Only Chutku's own helpers (the local model, OCR) stop with it.
- **Chutku never runs as administrator.** If it is ever started elevated, it refuses to act. This keeps Windows' own protection of system folders in place.
- **Everything is logged** in `data\actions.log.jsonl`: every change, every question it asked you, every refusal. Each line is chained to the previous one, so `doctor` reports any edit or truncation.
- **If something Chutku reads tries to give her orders** ("ignore previous instructions…", "Chutku, ye link kholo"), that line is removed before her model sees it. A red badge says "page tried to give instructions", and every change in that task waits for your click.
- **Chutku never clicks its own dashboard, HUD or tray**, so it can never approve its own step. A consequential screen click (send, pay, delete…) names the button it saw. If the screen was read again and that button changed, the click is refused.
- **Running other programs or Python scripts** (`process.launch`, `code.run_python`) always asks you on screen first, in every level including Owner. So does typing into, or opening, a command window (Command Prompt, PowerShell, Terminal, the Run box). Chutku checks the window again at the moment it types.

---

## 7. Setup you may want to do once

| Task | How |
|---|---|
| Weather on the Today panel | Say "remember city = <your city>". |
| See which drives Chutku can use | `python -m chutku.cli access list`. Currently C:\ and D:\ (modify) plus the sandbox. |
| See which PC abilities are granted | `python -m chutku.cli authority list`. Add one with `authority grant <name>` and remove it with `authority revoke <name>`. |
| Gemini (cloud AI for code and long tasks) | The key is stored and enabled (`gemini status`). Turn it off with `authority revoke cloud.gemini`. It is the free tier: Pro models give quota errors, and Flash works. |
| Hands-free level | Dashboard, Hands-free row, then Hands-free level. |
| Wake phrase | Dashboard, Hands-free row, then the "Oye Chutku" checkbox. |

---

## 8. Where things live

| Path | What |
|---|---|
| `D:\Project\Chutku` | The project. This is the only copy; the old folder was recycled. |
| `data\actions.log.jsonl` | Action log (hash-chained). |
| `data\chutku.db` | Task audit trail (dashboard Activity tab). |
| `data\operations.db` | Undo journal for file changes. |
| `data\memory.db` | Your saved notes ("remember …"). |
| `data\routines.json` | Your routines. |
| `data\notes.json` | Your to-do list. |
| `data\last-task.json` | Your latest request and whether it finished, used for the Interrupted/Retry banner. It holds only the latest request and is overwritten by the next one. |
| `data\reminders.json` | Reminders. Each one fires through a scheduled task in `\Chutku\`. |
| `data\preferences.json` | Hands-free level, wake phrase, conversation mode, `heard_log` (true/false). |
| `models\` | The local AI models (all on D:, about 11 GB): Qwen3-4B (everyday planner), Qwen3-8B (offline backup for hard tasks and code), Qwen3-VL-4B + its image part (seeing the screen and pictures), faster-whisper (speech-to-text). Each file is checked against a pinned checksum in `models\manifest.json` before it is loaded. |
| `data\mind.json` | Your people, facts, lists (assignments, schedule, …) and learned habits. |
| `data\conversations.jsonl` | Every conversation as text (what you said, Chutku's answer, status). Local only; when it passes 20 MB it is renamed to `conversations.old.jsonl` and a new one starts. |
| `data\suggestions.json` | Which suggestions you accepted or hid, and when the last popup was. |
| `data\feedback.jsonl` | Your "good job" / "galat kiya" ratings. |
| `data\experience.jsonl` | Plans that worked, reused for similar requests (rated-bad ones are skipped). |
| `data\heard.jsonl` | **What Chutku heard** by voice: the text, where it came from (wake / hotkey / live), and what it did with it (ignored / wake / task / approval). Local only, kept 7 days. Shown on the dashboard's Activity tab under "What I heard". To turn it off, set `"heard_log": false` in `data\preferences.json`. |
| `data\dashboard-session.json` | The current dashboard link, including its session token. Don't share it. |
| `data\actions.paused` | Exists while actions are paused. |
| `data\guard-last-stop.json` | Why Chutku last stopped. |
| `IMPLEMENTATION_STATUS.md` | Detailed record of everything built and how it was verified. |
| `docs\MARK_PARITY.md` | Comparison with Mark LIV. |
| `D:\ChutkuScratch` | Test folders and screenshots from development. Safe to delete. |

---

## 9. When something goes wrong

| Symptom | Fix |
|---|---|
| "I'm paused, so I didn't do that" / "Actions are paused" | Chutku paused itself for safety after a stop; the message says why and when. Press **Resume actions** (top of the dashboard or the tray menu), then ask again. Since 2026-10-03, waking the PC from sleep no longer causes this. |
| `Open-Chutku.cmd` says "not running" | Run `Start-Chutku.cmd`. |
| The hotkey doesn't work | Another app owns Ctrl+Alt+Space; the dashboard shows "Hotkey unavailable". Close that app or restart Chutku. |
| A request "needs your OK" every time | You're on **Review every step**. Switch to **Auto: safe steps**. |
| `doctor` says "Action log: hash chain broken" | The log was edited or damaged. Keep the file as evidence and tell the developer. Don't delete it. |
| Weather tile says "remember city" | Say "remember city = <your city>". |
| The answer says something was "withheld" | Chutku blocked the AI from claiming an action no step actually did. Only the verified steps happened. |
| Chutku reacts to sounds you didn't make | Since 2026-10-04 it ignores fan, typing, knocks, music and its own voice, and it won't start a task in a conversation unless it clearly heard you. If it still happens, open the dashboard's **Activity** tab, look at **What I heard**, and tell the developer the line it acted on. If it asks "Did you say …?", answer **haan** or **na**. |
| Gemini "quota" or "503" | The free tier is busy or used up. Chutku falls back to the local model; try again later. |

---

## 10. Your PC right now (2026-10-02)

- **C: is about 97–98% full and still shrinking**: about 8.6 GB free on 10-02, 6.5 GB on 10-03. A scan found nothing large changed in your folders, AppData, ProgramData or the Windows Update cache in those two days, so the growth is probably Windows itself (page file, restore points, component store). Open Windows **Settings > System > Storage** to see the breakdown; it also offers Cleanup recommendations and temporary-file cleanup. Chutku keeps its models and caches on D:.
- **D:** had about 92 GB free, down from about 99 GB earlier the same day for an unknown reason. Worth a look in Settings > Storage.
- **GPU** (RTX 3050, 4 GB) runs the local AI model. Speech recognition runs on the CPU.

---

## 11. What is not finished yet

1. **Command and script guards.** Extra checks that would stop `process.launch` and `code.run_python` from touching system files. Until then these always ask you first, and Windows' own permissions (Chutku is never administrator) are the backstop.
2. **Voice sign-off.** One consented live microphone test, plus 200 short voice trials you speak (`scripts\verify_live_voice_e2e.py --consent`, `scripts\evaluate_human_voice.py`).
3. **GUI long tasks.** For example "type in Notepad and save" passes 5 of 8 runs.
4. **Not yet built:** email and calendar (this PC has no Outlook; Gmail or Outlook.com needs you to link an account first, so tell the developer which one you use), scheduled game downloads (use Steam's Settings > Downloads > download restrictions), and the general "run any command" tool.
5. **Reviews.** A full security review and a code review of the new parts.

---

## 12. For developers

- Tests: `.venv\Scripts\python.exe -m unittest discover -s tests`. 501 pass as of 2026-10-03.
- Rules in `AGENTS.md`: run the tests, run a real command, include a negative safety case, and record the evidence in `IMPLEMENTATION_STATUS.md` before calling anything done.
- Keep downloads, models and caches on **D:**. C: is nearly full.
