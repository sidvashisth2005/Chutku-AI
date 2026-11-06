# Chutku — Owner's Guide

Everything you need to use, control and look after Chutku. Last updated 2026-11-05 (find any file on any drive, window snapping, PowerShell with a click, CPU temperature and network speed, Chutku's face).

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
| Pause or resume actions | The **Pause actions** button at the top of the dashboard, typing "pause chutku" / "resume" in chat, pressing **Ctrl+Alt+Space** and saying "resume" / "chalu ho jao", or `python -m chutku.cli control pause` and `control resume`. |
| Is it OK? | `.venv\Scripts\python.exe -m chutku.cli doctor`. It should say `"ready": true`. |

**Important (changed 2026-10-29):** if Chutku hangs or crashes, the guard restarts her by itself (up to 3 times in half an hour). The pause the guard set is lifted by itself once the restarted Chutku has run fine for 30 seconds, and she says so ("Main atak gayi thi, isliye khud restart hui…", naming the task that was cut off). That task is **never** run again by itself: ask again if you still want it. **Your own pause** (Pause button, tray, "pause chutku") and the **emergency stop** (Ctrl+Alt+F12, Stop Chutku) are never lifted by themselves. Resume them with the dashboard or tray button, by typing "resume", or with **Ctrl+Alt+Space** then saying "resume". A wake phrase ("Oye Chutku") cannot lift a pause, because anyone in the room can say it. If her loop gets stuck, a hang report with every thread is saved in `data\logs\hang-*.txt`.

All commands are run from `D:\Project\Chutku` using `.venv\Scripts\python.exe -m chutku.cli …`.

---

**The Ctrl+Alt+Space panel:**
- **Move** it by dragging its top bar (where "C H U T K U" is).
- **Resize** it with **－ / ＋** at the top right, or drag the **◢** grip in the bottom-right corner. The text shrinks with it.
- **Click any other app** and the panel goes behind that app; it stays open in the background. Press Ctrl+Alt+Space to bring it back to the front.
- **✕** hides it.
- Its size and position are remembered.

**Give several orders and walk away:** while one task runs, new orders (typed in the dashboard or the panel, or spoken with the wake phrase) wait in line, marked **queued**, and start by themselves one after another. Up to 10 can wait. Stop on a queued task removes it from the line. When a run of two or more tasks is over, a Windows notification lists them (✓ done / ✗ not done). Voice answers are spoken as each task finishes.


### What changed on 2026-10-29/30 (after "this AI isn't working properly")

- **Brain: free cloud first.** When the internet works, free cloud models plan your requests: Groq and Cerebras if you stored a key, then Gemini (already set up). Your PC's own model takes over offline, or when they all fail. Instant phrases never wait for any model.
  - Say **"cloud brain off"** to use only the local model; **"cloud brain on"** turns it back on.
  - For the fastest answers, get a free Groq key at https://console.groq.com/keys, then run `python -m chutku.cli cloud set-key groq` (the key is hidden while you type it).
  - `python -m chutku.cli cloud status` shows which keys exist; `cloud test` asks the cloud "2+2" and times the answer.
  - The cloud sees the same things Gemini always saw: your request, tool names and public results. Never file contents, clipboard, chats or typed text.
- **Gemini Live talk mode is now opt-in.** It sometimes said "ho gaya" when nothing had happened. Ctrl+Alt+Space now listens with Chutku's own voice loop.
  - Say **"conversation mode on"** / **"live mode on"** for Gemini Live; **"conversation mode off"** turns it off.
  - If Live says "done" while the task failed or never ran, Chutku makes it correct itself straight away.
- **Faster, more natural talking (W3).** She notices when you stop talking sooner (about 0.6 s instead of 0.9 s) and ignores fans, music and clicks. After answering she keeps listening for 8 seconds, so just keep talking. **Press Ctrl+Alt+Space while she talks to cut her off** and speak. A slow answer starts with "Ek second." Every spoken answer's wait time is saved in `dataoice-timings.jsonl`.
- **Chutku's presence orb (W4).** A glowing orb sits in the bottom-right corner. It listens (blue), thinks or works (purple, spinning), speaks (it moves with her voice), needs your OK (yellow) or is paused (red). When something happens it grows into a panel showing what you said, what she is doing step by step (✓ = checked and verified) and Approve/Cancel buttons. **Click the orb to talk.** After 6 quiet seconds it shrinks back. Turn it off with `presence_overlay: false` in `data\preferences.json`. It needs `pywebview` (installed by Chutku); without it the old panel is used. The dashboard is now dark and follows the same colours, and there is an "Open presence orb" button in the sidebar.
- **Screen copilot (W5).** Ask about whatever you are looking at: "ye kya hai", "is error ko fix karo", "screen dekh ke batao …", "explain this error", "is page ka summary do". Or press **Ctrl+Alt+S**, then ask your question (or say nothing to hear what is on screen and what needs fixing). She looks only at the window in front, answers in a few seconds (Gemini first, her own vision model offline), and never looks at apps on your private list.
- **Your phone (W6).** Install Tailscale on the laptop and phone (same account). Say "phone connect karo", then "phone pair karo" and open the link/code on the phone and choose a PIN. From the phone: chat, hold-to-talk, approve (PIN), watch the screen (PIN), files, clipboard, tap a spot and ask. Direct control only after "phone control on karo" at the laptop; a red border shows; Ctrl+Alt+Shift+P stops it. "remote band karo" turns it off, "phone hatao" removes phones.
- **She knows your shows, apps and sites (2026-11-01).** "baki chalao" (continues where VLC stopped), "baki ka next episode", "play baki episode 25", "bleach chalao"; "open github" / "vercel kholo" open your usual sites; "mere shows" and "mere baare mein kya pata hai" tell you what she knows. Built from your video folders, VLC history, Windows app counts and Brave history, refreshed every 6 hours, local only. Timeline (window titles, 14 days) is on too; turn off with "timeline off".
- **She tells you when she didn't hear you.** "Sorry, theek se sunai nahi diya…" instead of only a beep.
- **Misheard noise is read back, not run.** If what she heard has no request in it ("Watch out brother."), she says "Maine suna: '…'. Kya yahi karna hai?" and does nothing. Typed text is never checked like this.
- **Commands she used to drop are heard again.** Until now "Spotify kholo", "Open Notepad", "Next song", "Pause the music" and "Volume kam karo" spoken after Ctrl+Alt+Space came back as silence. A filter meant for Whisper's echoes threw them away.
- **"hindi bhi samjho"** lets speech recognition pick Hindi or English for each command; **"sirf english suno"** goes back to English only (the default; Hinglish comes out translated).
- **Room talk is not stored any more.** The wake listener used to write every overheard sentence to `data\heard.jsonl` (5,071 lines in 6 days). Now only wakes and your commands are written; other speech is only counted (`data\heard-counts.json`). **"heard debug on"** stores everything for 24 hours if you want to see what it hears; **"heard debug off"** stops it.
- **Every wake beeps and shows the panel**, so a false wake can never go unnoticed.
- **Spotify:**
  - "spotify ka gaana band karo" / "Spotify open karke gana band karo" now **pause the song** (before, they closed Spotify);
  - after a playlist has played once, "after party bajao", "play after party", "Spotify pe After Party chalao" and "Mera Spotify open kar aur after party playlist chala" play **that playlist** at once, never a search.
- **Habits and suggestions come from you only.** Chutku's own test scripts no longer count as your habits (the "2 to the power 10" question at 2 AM was a test). The nightly replay says "too few real requests" instead of "ok" when you barely used her that week.

### Chutku's voice (Kokoro, since 2026-10-07)

You picked the new neural voice in the blind listening test (10 of 10 times over the old Windows voice), so it is now Chutku's voice for everything she says on this PC: spoken answers, reminders and confirmations.
- She speaks sentence by sentence. The first words come about a third of a second after the answer is ready, and long answers are no longer cut at 200 characters.
- **"ruko" / "stop"** stops her mid-sentence.
- If the voice files are missing or the voice fails, the old Windows voice says it instead, so she is never silent.
- To go back to the old Windows voice, run `.venv\Scripts\python.exe -c "from chutku.core.preferences import Preferences; from chutku.app import PROJECT_ROOT; Preferences(PROJECT_ROOT).update({'voice_engine': 'sapi'})"`. Use `'kokoro'` to switch back.
- In a live conversation (Gemini Live), Google's own voice still speaks; Kokoro is the voice for everything Chutku says herself.
- Later, Chutku's voice can become your own recorded voice: see `docs/VOICE_RECORDING_GUIDE.md`.

### Voice conversation fixes (2026-10-06)
- **A quick "हां"** is no longer lost. If Chutku answers before your words are written down, she waits up to 2 seconds for them.
- **One request is started once,** even if it is heard twice within 2 seconds.
- **Words that come out in Spanish** ("Sí, un poco") are treated as misheard and start nothing. Say it again.
- **Her replies no longer repeat** or run into each other in the conversation log.
- **Names come from your memory.** She writes your saved people's names exactly as saved ("remember AK is my mammi"); no names are built into the code.

### Voice lock: only your voice gives tasks (since 2026-10-06, off until you set it up)

1. **Enroll once.** Use the dashboard's **Voice lock** tab: read the 8 highlighted lines, then press **Finish enrollment**. Or run `.venv\Scripts\python.exe -m chutku.cli voice enroll` in a terminal. Do it somewhere quiet, in your normal voice.
2. **Turn it on.** Type **"voice lock on"** in the chat (typed only: no voice and no agent can switch it), or use the button on the Voice lock tab. **"voice lock off"** turns it off again.

What changes when it's on:
- When a voice request doesn't sound like you (a friend, the TV, a video), Chutku still answers questions. Anything that changes something waits for a click on screen, and that request can't be approved by saying "haan".
- Your requests work as before. The check takes about 0.1 second.
- Your voiceprint (`data\voiceprint.npy`) never leaves this PC. `chutku.cli voice forget` deletes it and turns the lock off.
- **It learns your voice over time:**
  - Every request it clearly recognises as you moves your voiceprint 3% towards how you sound today, so a new mic or a slightly different voice keeps working.
  - If it ever doesn't recognise you (a cold, a noisy room), the Voice lock tab shows **"That was me"** for 15 minutes; one click teaches it that recording (15%).
  - A clearly different voice is never learned, even after a mistaken click. Your original enrollment is kept, and no update may move the voiceprint too far from it.
  - The Voice lock tab shows how many times it has learned.
- **Honest limit:** a recording of your voice can pass. This keeps other people and the TV out; it is not a password.
- **Calibrating:** `chutku.cli voice record` saves your 8 lines as clips. Then `scripts\calibrate_voice_lock.py --owner D:\ChutkuScratch\voicelock\owner` measures how well your voice is told apart and suggests a threshold.

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
- **A kind of step that keeps failing** (earned autonomy, since 2026-10-06). Chutku checks every step that changes something, and counts how often it really worked for that app, site, folder or contact. After at least 2 recent failures with a low success rate, that kind of step asks first, in every level: *"This has worked 0 of the last 5 times (app:…); confirm it."* Ask **"reliability batao"** / **"tum kitni reliable ho"**, or open the **Reliability** tab, to see the numbers.
  - **"earned autonomy relax on"** (only you can say it; off by default): file changes that can be undone and have worked 20 times in a row on the same folder stop asking. Deletes, and anything after Chutku read outside text, still ask. **"earned autonomy relax off"** turns it back off.

Everything is still logged ("what did you do today"), the Stop / Pause buttons still work, and Windows system folders are never touched.

**Approving by voice:** Answer in Hindi or English, Chutku understands both (हाँ, हम्म, जी, ठीक है, भेज दो, haan, hnn, yes, ok...). Any "no / nahi / नहीं / ruko / cancel" cancels; "hmm" in the middle of a long sentence is not taken as a yes. when you started the request by voice (hotkey, wake phrase or conversation), Chutku says what it is about to do, for example *"Send 'hi' to Ak on WhatsApp? Haan ya na?"*, and listens.
- **"haan" / "yes" / "hnn" / "bhej do" / "kar do"** approves.
- **"nahi" / "no" / "ruko" / "cancel"** cancels.
- A yes counts only if it is short and has no no-word in it, so background talk can't approve anything.
- If it doesn't hear a clear answer twice, it leaves the Approve button on screen.

In the other three levels, deleting, sending messages, closing apps, power, installing, running code and building apps always ask.

The hands-free (voice) level is set separately, in the dashboard's Hands-free row. It is now **Owner: no approvals**.

---

## 3. Things you can say

**New on 2026-11-06: learn from GitHub**
- "github.com/owner/project se skill seekho" or "import skills from https://github.com/owner/project" (asks first). Chutku downloads the project (nothing from it is run) and notes its licence.
  - If it has SKILL.md files, they become procedures she reads when a task fits.
  - Otherwise she writes a small skill from its README, which waits for "skill approve <name>".

**New on 2026-11-06: Chutku improves herself (Evolve)**
- Every night (Night Shift), Chutku studies the last 7 days: failures, slow or misheard requests, questions you always answer the same way, and your habits. She refreshes what she knows about you and writes at most 3 improvement ideas, each with a full plan: the evidence, what would change, the steps, the tests, the risk, and how it is undone. Nothing changes by itself.
- "khud ko improve karo" / "improvement ideas do" runs that review now. "aaj ke suggestions" / "improvement ideas dikhao" lists them.
- To accept one, **type** "evolve approve <id>", then click. Small ideas (a new phrase, routine, preference or skill) apply through the normal settings. A code idea is written on a separate git branch, the **full** test suite runs, and it is merged only if everything passes; otherwise it is thrown away and main is untouched. "evolve reject <id>" drops an idea.
- She can never change her own safety code: policy, permissions, the guard, the runtime, Evolve itself, or the safety tests. Pushing to GitHub after a merge is off unless you turn on the `evolve_push` preference.

**New on 2026-11-06: Chutku starts small**
- The bar is **hidden** until you want it: **Ctrl+Alt+C** shows it, Ctrl+Alt+C again hides it. While she listens or works (Ctrl+Alt+Space) it appears by itself and goes away about 6 seconds after she is done, unless you pinned it with Ctrl+Alt+C. It shows what you say ("You: ...") and what she says ("Chutku: ...") live. Drag it anywhere; it remembers where you left it.
- Click the expand icon at the right end of the bar to open the full window. The "to bar" icon at the top right of the full window shrinks it back.
- When she needs your OK, the full window opens by itself with Approve and Cancel, so an approval never hides.
- Her eyes react: hearts when you thank her, spirals when she has to ask you something, angry brows when you sound annoyed, happy ^ ^ after a verified task, sad after a failure, closed when paused.
- Closing either window quits Chutku, as before.
- While a task runs you can still ask questions ("D drive mein kitni jagah hai?"): she answers at once. A new order waits until the running one finishes.

**New on 2026-11-06: give the order and go for a coffee**
- Add **"bina puche kar do"**, "approval mat maangna", "main abhi approve kar raha hoon", "without asking" or "main coffee break pe ja raha hoon" to a request. That one task then runs **without asking for basic steps**: file changes Chutku can undo, Recycle-Bin deletes, closing apps and so on. It still asks for the **very risky** ones: power or killing programs, running code or PowerShell, messages or emails to people not in its memory, anything after a web page or message tried to give orders, and changes built from text it read online. System folders stay off limits.
- In the middle of a task, answering an approval with "haan, aur baar baar mat pucho" approves that step **and** stops asking for basic steps for the rest of that task.
- Add "dhyan se" / "carefully" / "puch ke karna" and that task asks before every change instead.
- Voice approvals are fixed: "हां", "यस", "yes bol to diya" and "approval mat maangna" all count as yes. A no word ("nahi", "mat bhejo", "ruko") still cancels. After an unclear answer, your next answer is judged by itself.

**New on 2026-11-05**
- "D drive mein resume kahan hai" / "where is my electricity bill" / "find invoice march": instant search of every file name on your fixed drives (the drive index; names only, never contents; system and code folders skipped). Night Shift refreshes it daily; "saari drives index karo" rebuilds it now. It matches file names, not folder names.
- "snap notepad left" / "chrome ko right side karo" / "VS Code ko top right corner mein rakho" / "notepad ko center karo" *(model)*: snaps that window to a half or a quarter of its own screen. "dono windows side by side karo" does two snaps.
- "laptop garam hai kya" / "cpu temperature kitna hai" / "laptop lag kar raha hai": CPU, RAM, GPU with temperature, and network speed. If Windows does not expose the CPU temperature without admin rights, Chutku says so.
- "powershell mein ye command chalao: Get-Date" *(model)*: runs **one** single-line PowerShell command (up to 500 characters, 60 s). It **always** shows a confirm button, in every mode including owner mode, and Chutku never chooses it by herself unless you say powershell, command or terminal.
- **Chutku's face:** the orb has eyes and a mouth. She looks calm when idle, wide-eyed while listening, glances aside while thinking, smiles (^ ^) after a task she has verified, looks sorry when something failed, and closes her eyes when paused. Her mouth follows how loud her voice is (not the exact words). If Windows "Animation effects" is off, the face stays still.


Everything below is **instant**: matched by rules and done within about a second, without the AI model. The exceptions are marked *(model)*: those, and anything you phrase differently, are planned by the local model, or by Gemini for code and long tasks. English, Hindi and Hinglish all work.

**Controlling Chutku** (works typed, in the panel, or by voice)
- "stop" / "ruko" / "cancel" / "bas": stops the running task **and** everything waiting in line, at once. (With nothing running, "stop" pauses your music.)
- "pause actions" / "sab rok do": stops everything and pauses Chutku until you resume (button, typed "resume", or Ctrl+Alt+Space then "resume" / "chalu ho jao").
- While paused she still answers when you call her and says why she is paused ("Aapne mujhe pause kiya hua hai"). After Ctrl+Alt+Space she listens for "resume" only; anything else is not run.
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
- Read replies: "Pita Shri ne kya bola?" / "did mammi reply?" / "AK ka last message kya hai" / "what did Pita Shri say". Chutku opens the chat, reads the latest messages from the screen (locally) and tells you who said what. Photos, stickers and voice notes can't be read. If WhatsApp on the PC says "Syncing paused", Chutku tells you; open WhatsApp on your phone so recent messages appear.
- If WhatsApp on the PC is logged out (QR-code screen), Chutku says so straight away: link it again from your phone (WhatsApp > Linked devices > Link a device).

**Messages** (always asks before sending)
- "send hi to AK on whatsapp" / "AK ko whatsapp pe hi bhejo" / "message AK on whatsapp saying hi there"
- Chutku searches your chats and opens only a chat whose name is *exactly* what you said (it uses WhatsApp's own green highlight, so short names like "Ak" work). If no chat or several chats match, it sends nothing and tells you the closest names.
- Fastest: save a number once with "remember contact_ub = +91…", and messages to AK skip the search.

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
- Teach people: "AK is my gf" / "AK meri gf hai" / "remember Sharma Sir is my DL wale sir" / "mammi ka number +91 98765 43210 hai"
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

### Timeline: "wo PDF jo kal shaam khola tha" (since 2026-10-06, off until you turn it on)

- **"timeline on"** (typed only) starts it. Every 5 seconds Chutku notes which app and window title is in front, and only when that changes.
  - **Window titles only:** no screenshots, no contents, no keystrokes.
  - Kept for 14 days.
  - Private windows (InPrivate / Incognito, password managers) are stored as "[private]". Add your own, for example a banking app, with the preference `timeline_private` (a list of app names such as `mybank.exe`).
- Ask: **"wo PDF jo kal shaam khola tha"**, **"abhi kaunsa PDF khola tha"**, **"wo invoice jo maine aaj subah dekha tha"**, **"which pdf did I open yesterday evening"**, **"what was I looking at this morning"**. Files Chutku opened for you are included too.
- **"timeline off"** stops it **and deletes everything it stored**.

### Night Shift: Chutku improves while you sleep (since 2026-10-06)

Once a day, Chutku does her homework. From **4:00 am**, she waits until the PC has had **no keyboard or mouse use for 30 minutes** while plugged in, then starts. There is no fixed time: if you use the PC until 4:15 and then go to sleep, she starts at about 4:45. If that doesn't happen until later in the day, she starts then. On battery she waits, and she runs at most once a day. The PC is kept awake only while she works (about 10–15 minutes).
- She learns new instant skills from the day's requests.
- She checks which kinds of actions keep failing.
- She **re-plans every request from the last 7 days without doing anything**, and compares the plan with what worked before.
- She tidies old logs and checks that the action log is intact.

The **Today** card then shows a line like *"Raat ko: 1 naye skills, 4 badle hue plans, 3 ab fail, 16 same."*

- Run it by hand: `.venv\Scripts\python.exe -m chutku.cli nightshift run`. While Chutku is running, the work happens inside her, so only one model uses the graphics card.
- **Scheduled tasks tell you the result (since 2026-10-09):** when a scheduled task finishes, a notification shows its answer. Add "sirf nayi" / "only new" ("har subah news batao, sirf nayi", "har ghante inbox folder ki files batao, sirf nayi") and she compares with the last result and stays quiet when nothing changed. If a task keeps failing the same way, you are told once a day, not every run.
- **Act on what is already on the screen (since 2026-10-08):** "playlist screen pr hi h after party ki play it", "after party playlist screen pe hai play karo", "screen pe Settings dikh raha hai usko kholo", "play After Party from the screen". She brings the app to the front, reads its window, and acts on the item whose text is exactly what you said (spacing counts: "After Party" is not "Afterparty") **and** whose type matches what you said (a playlist, not a song with the same name; in Spotify's search results she opens the "Playlists" filter to find it). She never searches. If it isn't there as you described, or two items look the same, she clicks nothing and tells you. For "play" she presses that page's own play button (never the player bar at the bottom) and checks that what starts is one of its tracks; if something else starts, she pauses it at once. Saying "search mat karna" or "screen pe hai" also stops any search in the request.
- **Weekly report (since 2026-10-07):** "is hafte kya kiya", "weekly report", "hafte ki report", "what did you do this week", "insights". The last 7 days against the 7 before: your requests (voice/typed), how many were answered instantly vs by a model (and how many by Gemini), the most used actions, how many actions worked, failed or were refused, how often she asked you and you approved, and new learned skills. ("aaj kya kiya" still lists today's actions.)
- **Attach things in typed chat with @ (since 2026-10-07):** `@file:D:\notes\a.txt ka summary do`, `@file:"D:\My Notes\a.txt":10-25` (only those lines), `@folder:D:\Study mein kya hai`, `@url:https://example.com padho`, `@clip ka translation karo` (clipboard text). Up to 3 per message. She reads them first (through her normal tools, so protected folders and your "never" rules still apply) and answers from them; long text is cut at 6000 characters and she says so. Password, key and login files (`.env`, `.ssh`, `id_rsa`, `.kdbx`, `.pem`, browser "Login Data"/"Cookies") are never attached. Attached text counts as outside content: anything it would lead to that changes something waits for your click. Typed chat only, not voice.
- **Search past chats (since 2026-10-07):** "gulabi top wali baat dhoondo", "what did I say about DBMS", "pichhle hafte DBMS ke baare mein kya baat hui" (last 7 days), "kal mammi ke baare mein kya baat hui" (since yesterday), "search my chats for night report", or in Hindi script "मम्मी के बारे में क्या बात हुई". She answers in under a second with the date, what you said and what she said (up to 3, all your words first, any word if nothing has them all). Hindi script and Roman letters find each other. "what did we talk about yesterday" (no topic) still gives the day's summary.
- **Ask her (since 2026-10-07):** "night report", "night shift report", "raat ko kya kiya", "kal raat kya kiya", "what did you do last night", or in Hindi script "नाइट शिफ्ट रिपोर्ट". She answers instantly from the saved report: when it ran, new skills, how many of your past requests she re-checked (same / changed / now failing), what keeps failing, and fine-tune progress. The voice conversation also knows last night's result, so it no longer guesses.
- `chutku.cli nightshift report` prints the last report. The full report is in `data\nightshift\report-YYYYMMDD.json`, including which requests are planned differently now.
- The task is `\Chutku\NightShift` in Task Scheduler; `chutku.cli nightshift install` sets it up again.
- When there are 300 verified requests, she also writes `data\nightshift\lora-ready.json`. That means enough data for the planned weekly fine-tune, which still needs your yes the first time.

### App actions and the Action Lab (since 2026-10-09)

Chutku now has a fixed recipe for each thing she can do in an app (`chutku/apps/atlas/<app>.json`). Spotify is first: open, pause, resume, next, previous, shuffle, repeat, volume, search, Home, your playlists (Your Library), Liked Songs, queue, **play one of your playlists by its exact name**, play Liked Songs, new playlist, quit.
- Every recipe ends with its own check, for example: the song that started must be on the page she opened, or she pauses it.
- **Action Lab:** she tries each harmless recipe 3 times on your PC. Only then does it count as *verified*. Run it yourself:
  - `.venv\Scripts\python.exe -m chutku.cli apps lab spotify`;
  - only one action: add `--action play_playlist`;
  - to see the counts: `… apps list`.
- The lab never sends, deletes or quits anything. It adds things to your apps only with `--changes`. If your music was paused before, it pauses it again afterwards.
- Spotify on 2026-10-09: 26 of 28 verified (new playlist and quit are never run by the lab). Typical times: about 1 s for play, pause or volume; about 2.5 s to open a page; about 6 s to play a named playlist.

- **Say it, and a verified action runs at once** (since 2026-10-09), with no model and no approval:
  - "After Party wali playlist chalao" / "play my After Party playlist" / "spotify pe After Party playlist chalao";
  - "play liked songs" / "liked songs chalao";
  - "spotify pause karo" / "spotify roko" / "spotify wapas chalao";
  - "spotify pe agla gaana" / "spotify next" / "spotify previous";
  - "spotify mein lofi beats dhoondo" / "search lofi on spotify";
  - "meri playlists dikhao" / "liked songs kholo" / "spotify queue dikhao" / "spotify home";
  - "spotify shuffle" / "spotify repeat" / "spotify ki awaaz badhao".
  - "spotify pe Arijit Singh ke gaane chalao" / "play songs by Arijit Singh on spotify" (artists saved in your library);
  - "Gal Sun album chalao" / "play my Gal Sun album" (albums and singles in your library);
  - "spotify made for you" / "new releases dikhao" / "mere artists dikhao" / "mere albums dikhao";
  - "spotify back" / "spotify pe thoda peeche karo" / "spotify pe thoda aage karo" (5 seconds).

  "gaana roko" / "agla gaana" without "Spotify" still control whatever is playing (YouTube too). If the playlist name isn't in your library exactly as you said it, she clicks nothing and tells you; she does not go hunting.
- **Ask how to do something in an app:** "spotify mein shuffle kaise karte hain", "how do I mute a chat in whatsapp", "vs code mein terminal kaise kholte hain". She answers from her notes on that app (Spotify, WhatsApp, Brave/YouTube, VS Code, Settings, ChatGPT, Discord, VLC, Telegram, File Explorer, Notepad) and says whether she can do it herself.

- **WhatsApp** (since 2026-10-09):
  - "whatsapp pe kitne unread messages hain" (she reads the "Unread" number; nothing is opened, so nothing is marked read);
  - "whatsapp unread dikhao" / "whatsapp favourites dikhao" / "whatsapp saare chats dikhao";
  - "whatsapp new chat" / "whatsapp search kholo" / "whatsapp profile kholo" / "whatsapp panel band karo".

  Sending and reading messages work as before ("AK ko bolo …", "AK ka last message padho").
- **Brave and YouTube** (since 2026-10-09):
  - "brave history kholo" / "brave downloads kholo" / "bookmarks dikhao" / "brave new tab";
  - "page bada karo" / "page chhota karo" / "page normal size karo";
  - on a YouTube tab: "video aage karo" / "video peeche karo" (10 s), "youtube captions on karo", "theatre mode on karo", "video full screen karo", "youtube speed badhao" / "speed kam karo", "agla video chalao".

  YouTube keys go only to a YouTube tab; on any other page she says so and presses nothing.

- **When an app action fails, she stops and tells you why.** She does not try other things on her own (since 2026-10-09: once, after "close the panel" failed, she closed WhatsApp instead).

### Undo everything at once (Causal Rewind, since 2026-10-06)

- **"pichhle 10 minute ka sab wapas karo"** / "undo everything from the last 10 minutes", **"aaj jo kiya sab wapas karo"** / "undo everything today", **"last task undo karo"** / "undo the last task".
  - One approval card lists exactly what will be undone, newest first.
  - Changes undone: files written, copied, moved or recycled; folders tidied; empty folders made; volume, brightness and theme; reminders and scheduled tasks.
  - Later changes that build on one of these are undone too, first. For example, a file Chutku wrote and later moved goes back in the right order.
- **Your own edits are never overwritten.** If you changed a file or a setting after Chutku did, it is shown as "kept as you changed it" and left alone, together with anything that depends on it.
- **Cannot be undone, and listed as such:** messages, web searches, typing and power actions. **Apps Chutku opened stay open**, because closing them could lose your work.
- **"pichhle 15 min ka kya kya wapas ho sakta hai"** shows the list without changing anything.
- "undo that" / "wapas karo" still undoes just the last single change.

### Tasks for later: once, at a time, or again and again (since 2026-10-06)

Give the order once. Chutku saves it, keeps talking and working normally, does the task by herself when the time comes, then goes back to normal.

| Say | What happens |
|---|---|
| "30 min baad AK ko hi bhej dena" / "send hi to AK in 2 hours" | once, after that long |
| "raat 12 baje Rahul ko happy birthday bhejna" / "at 9 pm send good night to mammi" / "kal subah 8 baje news sunao" | once, at that time |
| "har 15 min weather batao" / "har ghante paani peene ka bolo" / "check my internet every 30 minutes" | again and again until you cancel |
| "scheduled tasks dikhao" / "what's scheduled" | the list, with each task's id |
| "scheduled tasks band karo" / "cancel scheduled task 3fa2c1" | cancels all of them, or that one |

- **Times:** "12 baje" with a birthday or wish means midnight; otherwise it means the next 12 o'clock. Bare 1–6 means evening, like everywhere else. Chutku always says back the exact time, so correct her if it's wrong.
- **Same rules as when you said it.** The task runs later in the same autonomy level you used when giving the order. So in Owner mode, changing files, deleting and messaging someone new still ask, and the approval waits on screen. A web page or message can't plant a task: scheduling after Chutku read outside text asks first.
- **Busy or paused:** if Chutku is busy at that moment, the task waits in line and runs right after. While actions are paused, nothing runs.
- **Missed tasks:** a task that was due while Chutku was off runs once when she starts, if it is less than 6 hours late. A repeating task never runs several times to catch up.
- **Notifications:** a Windows notification "Chutku: scheduled task" shows when one starts.
- **Typing into another app on a timer** (for example "continue" into the Claude chat in VS Code) is **not reliable yet**. Chutku has to find the window and the right box each time, and if the focus is wrong the text lands somewhere else. For Claude specifically, use Claude Code's own `/loop 15m continue`.

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
- **Reliability tab:** for each action and target (an app, site, folder or contact), how many times it ran, how many really worked, and the cautious success estimate. Each step in a task also shows a small chip like "12/13 ✓". When trust is low, the spoken reply starts with "Shayad ho gaya, ek baar check kar lo".
- **Skills I learned tab** (since 2026-10-06): when you ask the same kind of thing twice in different words (for example "tell me whether VLC exists on this laptop", then "… Steam …") and the model's plan worked both times, Chutku learns that shape. Next time ("… Spotify …") she does it instantly, without the model. Ask **"tumne kya seekha"** / **"what did you learn"** to hear the list.
  - Each skill has a **Switch off / Switch on** button. A skill also switches itself off after one failure, when you say **"galat kiya"** about a request it handled, or when one of its steps keeps failing.
  - Learned skills never send messages, delete, change files, run code, or click/type on screen.
  - The Today card shows **"Instant answers this week: X% (last week Y%)"**.
  - From a terminal: `python -m chutku.cli reflex list|compile|enable <id>|disable <id>`.

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
- **Saved text is checked (since 2026-10-07).** Before Chutku saves something she will read back later (a fact, a person's note, a "remember x = y" note, a to-do, a scheduled task), she refuses text with hidden characters (invisible ones like zero-width spaces that a copied web page can carry), and for facts and people also text that reads like an order to the assistant ("ignore previous instructions…"). Your own to-dos and scheduled tasks may of course be orders. Hindi words that need a joiner are fine. A to-do you already have open is not added twice. "what do you remember about me" ends with a meter: "Yaad: 368/600 characters (61%)" — how much of your memory fits in one request to the local model; above 100% only the most relevant parts go with each request.
- **Pause her background work (since 2026-10-07).** Say or type "background kaam roko" / "pause background work": scheduled tasks and the Night Shift wait (a task that comes due stays waiting; nothing is lost), while everything you ask yourself still works. "is background paused?" / "background paused hai?" tells you. To start them again, **type** "resume background work" / "background kaam shuru karo" (by voice it is refused on purpose). This is different from "pause everything", which stops every action, yours too. The pause is the file `data\background.paused`; even an empty or damaged file counts as paused.
- **Your own "never" rules (since 2026-10-07).** Type "D:\Exams ko kabhi mat chhoona" or "never touch D:\Exams", and nothing Chutku does may read or change that folder or anything in it, in any mode. Even your own approval click can't override a rule; remove the rule first. Other kinds: "never use tool message.send" (a tool or pattern like `web.*`), and "never run a command containing <words>" (a script or program containing those words is refused). "never rules" / "mere never rules dikhao" lists them with their ids. "remove never rule <id>" / "never rule <id> hatao" removes one, and that always asks first. Only you can add or remove rules; the agent can't. If the rules file `data\never_rules.json` gets damaged, Chutku refuses every change until it is fixed.
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
| Free cloud brain (fastest) | Free key from https://console.groq.com/keys, then `python -m chutku.cli cloud set-key groq`. Check with `cloud status` and `cloud test`. |

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
| `data\actions.paused` | Exists while actions are paused. It records who paused (you, the guard, or an unclean start) and why. |
| `data\guard-last-stop.json` | Why Chutku last stopped. |
| `IMPLEMENTATION_STATUS.md` | Detailed record of everything built and how it was verified. |
| `docs\MARK_PARITY.md` | Comparison with Mark LIV. |
| `D:\ChutkuScratch` | Test folders and screenshots from development. Safe to delete. |

---

## 9. When something goes wrong

| Symptom | Fix |
|---|---|
| "I'm paused, so I didn't do that" / "Actions are paused" | The message says who paused and when. A pause after a hang lifts itself within about a minute. Your own pause or the emergency stop needs **Resume actions** (dashboard or tray), a typed "resume", or Ctrl+Alt+Space then "resume". |
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

- "meri last pdf kholo", "latest video kholo", "last photo dikhao", "open my recent ppt": opens the newest file of that kind you opened.
