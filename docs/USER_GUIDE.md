# Chutku: User Guide

How to use, control and look after Chutku. This is the general guide that the app opens as **Help**. Examples are
written the way people actually talk to Chutku, in English, Hindi or Hinglish.

> Chutku is female. Her name in Hindi is छुटकू (said "Chhutku"). You can give her another name in **Settings**.

Chutku is designed and developed by **Siddhant Vashisth**.

---

## 1. Starting, opening and stopping

**Opening Chutku:** Chutku is an app. Press the Windows key, type **Chutku** and press Enter, or double-click the
desktop icon. While Chutku is running you can also type **chutku.localhost** in any browser's address bar. (A single
word like "chutku" is treated as a web search by every browser, so the address needs the ".localhost" part.)

| What | How |
|---|---|
| Start | The **Chutku** shortcut in the Start menu (or on the desktop). If you chose "start when I sign in" during setup, she is already running. |
| Open the window | Click the shortcut again, or the Chutku icon in the tray (near the clock). |
| Talk from anywhere | **Ctrl+Alt+Space**, then speak. With the wake phrase switched on (Settings), say **"Oye Chutku"**. |
| Type | Type in the chat box of the Chutku window. |
| Emergency stop | **Ctrl+Alt+F12**. Everything stops at once and actions stay paused until you click **Resume actions**. |
| Pause / resume | The **Pause** button at the top of the window, or say "pause" / "resume". |
| Quit | Right-click the tray icon, then **Quit Chutku (close everything)**. |
| Restart | Say "chutku restart karo", or the tray icon → **Restart Chutku**, or Settings → About → **Restart Chutku**. She comes back in about 10 seconds, not paused. (Only the emergency stop leaves her paused.) |

If Chutku hangs or crashes, she restarts by herself (up to 3 times in half an hour).

---

## 2. First-run setup and Settings

The first time Chutku opens, a short guided setup fills the window. It takes about two minutes, and Chutku opens
when it is done. Everything can be changed later under **Settings**.

1. **Your free AI key (required).** Click **Get my free key** (it opens Groq), sign in with Google, click **Create
   API Key**, copy the key and paste it in. Chutku checks the key with Groq (or Google) before keeping it, so a wrong
   or half-copied key is caught at once with a plain message; setup cannot be finished without a working key. There
   is no provider to choose: a `gsk_` key is Groq, an `AIza` key is Google Gemini. Keys go to Windows Credential
   Manager, never a file.
2. **A little about you:** your name (optional) and how much Chutku does on her own (Safe is preselected and
   recommended).
3. **Microphone check** (optional): say something and watch the level bar move.

Then Chutku says you are all set and opens. The rest is optional, under **Settings**:

1. **Your name** (optional).
3. **Her name and voice** (optional): Chutku, female, Hinglish, warm. Press **Change** to pick others.
4. **How much she does on her own**: Safe is preselected and recommended (see section 3).
5. **Microphone check** (optional): speak and watch the level bar move.
6. **Your phone** (optional): **Set up my phone** opens the Phone page and connects it for you (section 8).
7. **Websites that need your login** (optional): sign in once in the browser window that opens.
8. **Work without internet** (optional downloads): Voice, Brain and Screen packs. Every file is checked against a
   pinned checksum; a damaged download is deleted and never used, and a stopped download resumes.

---

## 3. How much Chutku does on its own

| Level | What runs without asking |
|---|---|
| **Safe steps** (the default) | Looking at things, answering questions, opening apps, sites and files, volume and brightness. |
| **Safe steps and file edits** | All of the above, plus file changes Chutku can undo (writing, moving, copying). |
| **Full** | Also closing apps, typing and clicking, settings, building projects, reminders, memory, and messages to people you taught her. |

**In every level Chutku still asks before:**
- deleting anything (files always go to the Recycle Bin);
- shutting down, restarting, ending a program, or turning the network off;
- running a script or a program, or typing into a command window (Command Prompt, PowerShell, Terminal, Run);
- sending a message to someone she does not know yet;
- pressing a button that sends, pays, deletes, submits or installs something in an app;
- anything right after she read a web page or a message, so a page can never give her orders.

**Approving by voice:** "haan", "yes", "ok", "kar do" approves; "nahi", "no", "ruko", "cancel" cancels. A yes counts
only when it is short and clear, so background talk cannot approve anything. Without a clear answer the **Approve**
button stays on screen.

---

## 4. Things you can say

The **What can I say?** page in the Chutku window has many more examples you can tap to try.

**Apps and windows**
- "Spotify kholo" / "open notepad" / "VS Code band karo"
- "minimize this" / "window left side pe karo" / "switch to Chrome"
- "Spotify pe lofi chalao" / "next song" / "volume 30 karo"

**Files** (every change can be undone)
- "meri resume file dhundo" / "find invoice march" / "open my downloads"
- "meri last pdf kholo" / "latest photo dikhao"
- "organize my Downloads folder" / "rename draft.txt to final.txt"

**Web**
- "search best free PDF editor" / "aaj ki news" / "weather kaisa hai"
- "YouTube pe cooking video chalao"

**Your PC**
- "kitni jagah bachi hai" / "battery kitni hai" / "brightness 60"
- "screenshot lo" / "bluetooth settings kholo"

**Screen**
- "screen pe kya hai?" / "click the first video"
- "screen survey karo" / "what's open on my screen": a short list of the open windows and what is in them (nothing
  is saved or sent).

**Messages** (sending always asks the first time for each person)
- "Rahul ko WhatsApp pe hi bhejo" / "did Rahul reply?"
- Teach people once: "remember Rahul is my college friend".

**Memory**
- "remember city = Pune" / "mera birthday 12 March hai" / "what do you know about me"
- "forget Rahul's number" (asks first)

**Timers, reminders and automations**
- "30 min baad yaad dilana pani peena" / "har roz 8:00 baje weather batao"
- "kaun si automations hain" / the **Automations** tab

**Tasks and research**
- "ye kaam board pe daal do: DBMS notes banana" / "board dikhao" / the **Board** tab
- "research karke batao best free PDF editor for Windows": she works on it in the background and tells you when
  it is done.

**Coding**
- "build me a snake game": she writes the project, tests it, fixes her own errors and opens it.

**Undo and history**
- "undo" / "pichhle 10 minute ka sab wapas karo" / "what did you do today"

---

## 5. Routines, and teaching Chutku a task

**Routines** run several things from one phrase:
- **Save:** "save routine work: open visual studio code, play lofi on youtube, set volume to 30"
- **Run:** "start work mode" / "work mode on karo", or just say its name.
- **Shortcut style:** "jab main 'padhai time' bolun to volume 30 karo aur music band karo".
- A routine can also press things inside an app by name: `click "Lofi" in Spotify`,
  `toggle "Dark mode" in Settings`, `type "hello" into "Search" in Spotify`.
- **See / delete:** "list my routines" / ask to forget one (asks first).

**Teach mode:** show Chutku a task once and she saves it as a routine.
1. Open the app, then say "sikho dark setup settings mein" or "teach me dark setup in Settings".
2. Do the task yourself in that window: type into fields, tick boxes, open menus.
3. Say **"ho gaya"**. Chutku tells you the steps she saw and saves them under that name.

Notes:
- She watches only that one window, for at most 5 minutes, and never takes screenshots.
- **Password, PIN and OTP fields are never recorded**, not even that you typed in them.
- A plain button click is not seen yet. Add it with a routine step: `click "Save" in Notepad`.
- Buttons that send, pay or delete are never pressed by a routine; those always ask.
- Watch the first replay of a taught task.

---

## 6. The Chutku window

The menu starts simple: **Home**, **What can I say?**, **Activity**, **Phone** and **Settings**. Press **More** to see
every page; Chutku remembers your choice. During your first week, Home shows one "Try saying…" tip. Every error
message has one button for what to do next (**Try again**, **Open Settings** or **Show me how**).

- **What can I say?:** examples you can tap to try, in English, Hinglish and Hindi, with a search box.
- **Command center:** chat, the Today panel (clock, weather, drive space, reminders, to-dos, what Chutku did),
  suggestions with **Yes** and **Not now**, and health alerts (disk, battery, memory).
- **Board:** your tasks and Chutku's research jobs, with **Done**, **Again** and **Archive**.
- **Automations:** ready-made automations (daily briefing, weekly backup ...) and the ones you scheduled, with
  **Cancel**.
- **Activity:** every task with its full trace, and what Chutku heard by voice.
- **Memory** and **Mind map:** what you told Chutku.
- **Reliability:** how often each kind of step really worked.
- **Skills I learned:** request shapes she learned to do instantly; each can be switched off.
- **Phone:** link your phone.
- **Settings:** the setup steps, packs and modes.
- **Help:** this guide.

---

## 7. Safety rules (fixed in the code)

- **Chutku never runs as administrator.** She refuses only what could damage Windows: its own folder, start-up files,
  deleting programs file by file (say "uninstall" instead), turning Defender or the firewall off, formatting a drive.
  An app's own files (Program Files, ProgramData, AppData) ask you the first time.
- **"Yes, always"** on an approval card: once that exact step worked, she does it again without asking. Deletes,
  power and anything right after reading a web page still ask. Settings → "Things you let Chutku do without asking"
  lists them, each with Forget.
- **Delete means the Recycle Bin**, and always asks. Permanent delete happens only when *you* ask for it.
- **Every step is checked independently.** Answers end with a tally like `[Verified: 2 of 2 steps completed.]`, and
  she never claims a step that did not happen.
- **Text she reads cannot give her orders.** Instruction-like lines from pages, files or messages are removed, and
  every change in that task waits for your click.
- **Your own "never" rules:** "never touch D:\Exams" or "D:\Exams ko kabhi mat chhoona" blocks that folder in every
  mode. "never rules" lists them; removing one asks first.
- **Everything is logged** on this PC with a hash chain, so any edit to the log is detected. If the log cannot be
  written, Chutku refuses to act.
- **Keys and passwords** are stored in Windows Credential Manager, never in files or logs.

---

## 8. Privacy and your phone

- Your files, screen text, clipboard and memory stay on this PC.
- With a cloud brain key, the AI service sees your request, notes you told Chutku that relate to it, and names of files and windows; with a Gemini key and no offline Screen pack, screen questions send a screenshot to Google.
- Watching the laptop screen on mobile data uses up to about 1.4 GB an hour (Watch mode up to about 3.6 GB).
- Private browser windows are never recorded.

**Phone app (optional).** On the **Phone** page press **Connect my phone**. It installs Tailscale if needed (press
**Yes** if Windows asks), opens its sign-in page, turns phone access on and shows a code. On the phone: install the
free Tailscale app, sign in with the same account, scan the code and choose a PIN. (People who run their own relay
server can link through it under Settings → Advanced.) Traffic through the relay is **end-to-end encrypted**: the relay forwards only sealed messages and
never sees your password, your requests or the screen. The phone asks for your PIN before approvals, screen view and
control. Some steps (deleting for good, power, running code) can only be approved at the PC.

**Telegram (optional).** On the **Phone** page, the **Telegram** card: open @BotFather in Telegram, send `/newbot`,
pick any name and a username ending in "bot", and paste the token it sends you. Chutku checks the token with
Telegram before keeping it (in Windows Credential Manager) and never shows it again. Then press **Pair my phone** and
scan the code with your phone's camera: Telegram opens your bot, press **Start** and that chat is paired (or send
`/pair CODE` to the bot). Only the paired chat is answered.

**Reach this laptop after a restart (optional).** On the **Phone** page press **Turn on** under "Reach this laptop
after a restart" and click **Yes** when Windows asks (your Windows account must be an administrator; Chutku itself
never runs as one). From then on, after every restart or power cut your Telegram gets "Laptop is ON" with a link
that shows the Windows sign-in screen on your phone: tap the picture, type your password and press Sign in. It needs
the Telegram bot and Tailscale (**Connect my phone**) first, and it turns off Windows Fast Startup so that switching
the laptop on is a real start. **Turn off** removes it again.

---

## 9. Where things live

| Path | What |
|---|---|
| `%LOCALAPPDATA%\Programs\Chutku` | The app. Updating or reinstalling replaces it; your data is not here. |
| `%LOCALAPPDATA%\Chutku\data` | Your data: memory, conversations, routines, settings, the action log. |
| `%LOCALAPPDATA%\Chutku\models` | Downloaded packs (voice, brain, screen). |
| Windows Credential Manager | Keys, the phone link and sign-in tokens (entries named `Chutku/...`). |

"backup bana lo" saves Chutku's memory to a zip in a `ChutkuBackups` folder, keeping the last 4. Restoring a backup never brings back security
settings (phone pairing, approvals, never rules) unless you confirm that separately.

---

## 10. When something goes wrong

| Symptom | Fix |
|---|---|
| "Actions are paused" | The message says who paused and why. Click **Resume actions** or say "resume". A pause after a hang lifts itself within a minute. |
| The hotkey does nothing | Another app owns Ctrl+Alt+Space; the window shows "Hotkey unavailable". Close that app or restart Chutku. |
| Every request asks for approval | You are on a stricter level. Change it in Settings (section 3). |
| "quota" or "busy" from the cloud brain | The free tier is used up for now. Wait a little, or add a key for the other provider (Groq or Gemini) in Settings; Chutku falls back to local models if the Brain pack is installed. |
| She reacts to sounds you did not make | Open **Activity**, then **What I heard**, to see what she acted on. Turn the wake phrase off in Settings if needed. |
| Something seems broken | Say "khud ko theek karo" / "apna checkup karo", or run `Chutku.exe --doctor` from the app folder for a health report. |
| The log "hash chain broken" | The log was edited or damaged. Keep the file; do not delete it. |

**Updates:** Chutku checks for a new version by itself. When one is out, a window shows what is new: click
**Update now** (it downloads, checks the file, installs and opens Chutku again, keeping all your data) or **Later**
(it asks again tomorrow). **Settings → About Chutku → Check for updates** checks at any time.

**Uninstall:** if you turned on "Reach this laptop after a restart", press **Turn off** on the Phone page first
(the uninstaller cannot remove it). Then Windows Settings, then Apps, then Chutku, then Uninstall. It asks whether to
delete your data as well; say no to keep it for a later install.
