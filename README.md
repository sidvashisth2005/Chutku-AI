# Chutku

Chutku is a local-first Windows agent runtime. It routes text or voice commands to typed tools, computes authorization independently of an LLM, verifies outcomes, and records an audit trail.

**Using Chutku day to day? Start with [docs/OWNER_GUIDE.md](docs/OWNER_GUIDE.md)**: how to open, pause and stop it, what to say, routines, safety rules, where files live, and troubleshooting. Open the running dashboard with `Open-Chutku.cmd`.

**How it works now (2026-09-30):** type or speak a goal in the dashboard chat
("open Spotify", "find my newest PDF in Downloads and open it", "youtube pe lofi
chalao", "make D:\Notes and write today's plan"). Chutku then:

1. tries a deterministic router for common intents (apps, web search, media, time);
2. otherwise asks the local Qwen3-4B planner, running on the RTX 3050 through a
   persistent, hash-pinned llama.cpp Vulkan server, which plans a step, observes
   the verified result and replans (bounded to 12 steps / 6 rounds);
3. runs each step through the same validation → grants → policy → execution →
   independent verification path, bounded by the **autonomy level you choose per
   request**: *Review every step*, *Auto: safe steps* (≤R1), or *Auto: incl. file
   edits* (≤R2 with runtime undo). R3+ actions (closing apps, sending, power…) always
   need your on-screen click; system folders are never modified.

160 registered tools (2026-10-06) cover files on all local drives (system areas read-only), any
installed app, default-browser web search/URLs, window and media control, settings,
UI Automation, Playwright, screen capture, clipboard and processes. Voice uses offline
Whisper (English/Hindi/Hinglish, Romanized output). "Build me a calculator app" writes a
real project into `D:\ChutkuProjects`, opens it in VS Code, tests it, fixes its own errors
and leaves the app running. Gemini is optional: after you store a key and grant
`cloud.gemini`, it writes code for project builds and leads long multi-step tasks, and it
is the backup planner when the local model cannot decide. Gemini sees the goal, the tool
list, step summaries and public results (web pages, system status, file names). File
contents, clipboard, screen text and memory stay on the PC.

### New since 2026-10-06 (master plan S0–S22, [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md))

- **Owner mode** is the default autonomy level. It asks only before changing files, deleting, power/kill actions, messages
  to unknown people, and running code or typing into a command window (those two ask in every level).
- **Earned autonomy:** each checked step is counted per app/site/folder/contact; a kind of step that keeps failing
  asks first. "reliability batao", Reliability tab.
- **Learned instant skills:** request shapes the model planned well twice become instant ("tumne kya seekha").
- **Causal Rewind:** "pichhle 10 minute ka sab wapas karo" undoes everything Chutku changed, newest first, never over
  your own later edits.
- **Scheduled tasks:** "30 min baad ...", "har 15 min ...", "raat 12 baje ..." run by themselves beside normal work.
- **Owner Voice Lock** (off until you enroll): another voice can ask, but cannot change anything without a click.
- **Night Shift:** after 4 am, once the PC has been unused for 30 minutes (plugged in), Chutku re-plans the week's requests without running them, learns
  skills and tidies logs; the Today card shows the result.
- **Timeline** (opt-in, titles only): "wo PDF jo kal shaam khola tha".
- Hardening: injection lines removed from read content, taint/identity rules, fail-closed network/paths/logging,
  stop that really stops, streaming answers, structured logs. 231 tools, about 1,130 automated tests (2026-10-29).

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for verified evidence and
limits, and [docs/DESIGN.md](docs/DESIGN.md) for the design.

## Where things are

| Path | What it is |
|---|---|
| `Start-Chutku.cmd` / `Stop-Chutku.cmd` | Start / emergency-stop Chutku |
| `README.md` | This guide |
| `IMPLEMENTATION_STATUS.md` | What is built and how it was verified (newest first) |
| `docs/` | `DESIGN.md` (vision + safety rules), `ARCHITECTURE.md`, `ROADMAP.md`, `SECURITY.md`, `PROJECT_MEMORY.md` |
| `chutku/` | The program (agent loop, policy, tools, voice, web UI) |
| `tests/`, `scripts/`, `benchmarks/` | Automated tests, real-PC verification scripts, benchmark task sets |
| `verification/` | Latest evidence files (`archive/` holds superseded ones) |
| `models/`, `vendor/` | Local AI models and the llama.cpp runtime (hash-pinned) |
| `data/` | Your local databases, grants and preferences |
| `sandbox/` | Chutku's own scratch folder |

## Using Chutku (quick guide)

### Launch

Double-click **Start-Chutku.cmd**. It starts the guarded local server and opens your
browser. Keep the terminal open. **Ctrl+Alt+F12**, the **Stop Chutku** button or
`Stop-Chutku.cmd` stops everything (including the local model); after a stop, inspect
Activity and resume with `.\.venv\Scripts\python.exe -m chutku.cli control resume`.

The local model warms up in the background (about 10 s on first launch). Run in your
normal Windows session, not as Administrator.

### Pick an autonomy level (per request, remembered in this browser)

| Level | Runs by itself | Waits for your click |
|---|---|---|
| Review every step | nothing | every step |
| Auto: safe steps | looking things up, opening apps/files/websites, window and media control | file changes and anything riskier |
| Auto: incl. file edits | the above plus file changes Chutku can undo (write, copy, move, recycle to Chutku's trash) | closing apps, sending, power, deleting without undo, anything after reading untrusted content |

System folders (Windows, Program Files, ProgramData, AppData, drive-root system files)
and Chutku's own folders are never modified in any mode.

### Things to try (type or click 🎙 and speak)

```text
open spotify                      spotify kholo
search youtube for lofi music     youtube pe arijit singh ke gaane chalao
pause the music / next song       gaana roko
what time is it                   abhi kitne baje hain
how much free space do I have?
which windows are open?
find the newest PDF in my Downloads folder and open it
create the folder D:\Notes and write "buy milk" into D:\Notes\todo.txt
close the calculator window       (asks you to confirm)
undo last write

good morning                      (time, weather, reminders, headlines)
weather in Delhi                  Pune ka mausam kaisa hai
latest news about cricket         khabar batao
play arijit singh songs on youtube
remind me in 10 minutes to drink water     set a timer for 5 minutes
remind me tomorrow at 9 am to submit the report
volume up / set volume to 30 / mute        awaaz kam karo
brightness down / set brightness to 40     brightness badhao
how much RAM and GPU am I using?
what is C:\Users\<you>\Downloads\report.pdf about?     (PDF, Word, Excel, PowerPoint, images)
what is written on my screen?
new tab / go back / zoom in / snap left    (sent to the window you were using)
type "hello" and press enter              (Enter asks you to confirm)
organize my Downloads folder              (asks to confirm; undo available)
which games do I have? / launch Rocket League
send a WhatsApp to Ravi saying I'm on my way   (after: remember contact_ravi = +91...)
build me a calculator app         ek snake game banao      (asks to confirm; takes minutes)
make a portfolio website with dark mode
remember city = Delhi             (Chutku uses saved notes when relevant)
```

Each answer shows the declared plan, every step with its verified state, a trace link
and a deterministic tally such as `[Verified: 2 of 2 steps completed.]`. Trust the tally,
not the wording: if a step failed, the tally names it.

The mic listens until you pause (up to 12 s), transcribes offline with Whisper
(English, Hindi and Hinglish, written in Roman script), runs the request and speaks the
answer. Audio is never saved.

### Hands-free

- Chutku starts when you sign in to Windows (`chutku.cli autostart on|off|status`, a normal-rights logon task).
- **Ctrl+Alt+Space** from any app: the **HUD** slides in at the bottom-right and shows:
  - a reactor that follows your voice;
  - what it heard and every step live;
  - **Approve / Deny** for risky steps;
  - the answer with a verified badge;
  - a box to type commands.

  It hides itself about 14 s after finishing.
- Wake phrases: **“Oye Chutku, …”** or **“Chutku sun, …”**. Saying just the phrase opens the mic. It stays deaf while
  Chutku speaks, and uses the separate **Hands-free level** (now *Auto: incl. file edits*).
- **Screen:** the instant you call Chutku, it remembers what was on screen. “ye kya hai?”, “what's on my screen?”,
  “click the first video” and “use the calculator to work out 125 x 48” work with Gemini vision (free models).
  - Consequential buttons (send, delete, pay, submit…) always wait for your click.
  - The HUD is invisible to screenshots.
- Chutku will not type into or save one of your existing documents unless you name it in the request.

### Grants

```powershell
.\.venv\Scripts\python.exe -m chutku.cli access list          # file roots
.\.venv\Scripts\python.exe -m chutku.cli authority list       # PC capabilities
.\.venv\Scripts\python.exe -m chutku.cli authority revoke apps.launch
```

Currently granted on this PC: modify access to `C:\` and `D:\` (system areas read-only),
and apps.launch, browser.navigate, desktop.input, audio.observe/modify, screen/process/
settings/network observe, settings.modify (brightness, wallpaper, theme with confirmation),
clipboard.read, internet.read (weather, news, web answers), reminders.manage and
process.launch (script runs, always confirmed). Not granted: process termination, power,
network changes, clipboard write and Gemini.

**Where to paste your Gemini API key.** Run this in the Chutku folder. Paste the key when
it asks (the input is hidden), then press Enter. The key is kept in Windows Credential Manager
("Chutku/Gemini"), never in a file. Then allow Chutku to use it:

```powershell
.\.venv\Scripts\python.exe -m chutku.cli gemini set-key
.\.venv\Scripts\python.exe -m chutku.cli authority grant cloud.gemini
.\.venv\Scripts\python.exe -m chutku.cli gemini status      # checks the key works
```

With Gemini on:
- Project builds use the best Gemini Pro model your key can use, or `CHUTKU_GEMINI_CODE_MODEL`.
- Long goals (more than ~30 words, or several "then / after that" parts) are planned by Gemini Flash
  first, with a 60-step, 1-hour budget.
- Short everyday commands stay local and instant.
- Remove access with `authority revoke cloud.gemini`.
- A **Gemini app subscription (Google AI Pro) does not cover API keys**. Pro models need billing enabled on the key's
  project (aistudio.google.com → API keys → Set up billing). Without it, Chutku uses the Flash models. If Gemini is
  overloaded or out of quota, it moves to the next model, and in the end falls back to the local model.

### Verify it yourself

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts/verify_agent_chat.py      # real chat goals + negatives
.\.venv\Scripts\python.exe scripts/verify_builder.py         # "build me a calculator app" end to end
.\.venv\Scripts\python.exe scripts/verify_everyday.py        # apps, files, web, windows, media
.\.venv\Scripts\python.exe scripts/verify_voice_agent.py     # Hindi/English audio -> Whisper -> action
.\.venv\Scripts\python.exe scripts/verify_release.py --model --hardware
.\.venv\Scripts\python.exe scripts/check_stages.py --through all
```

### Honest limits

- The 4B local model is good at one- to three-step tasks; long multi-app tasks can wander.
  Bounds (12 steps, 6 planning rounds, 2 failures; 60 steps / 1 hour for long tasks) and the
  tally keep that visible. With Gemini enabled, long tasks and project code go to Gemini.
- Project builds with the local model work for small apps (calculator, to-do list, simple games);
  bigger apps need Gemini. A build is reported as done only if its compile, tests and launch checks pass.
- Voice accuracy is measured on synthetic Windows voices only; your own voice
  (and a consented live voice run plus 200 human trials) is still to be measured.
- The “Oye Chutku” wake phrase is measured on synthetic voices only (16/16 heard, 0/57 false wakes);
  real-room false wakes per hour still need measuring with your voice and TV/music around.
- Web tasks open pages in your default browser; filling forms uses a separate fresh
  Playwright browser, not your logged-in profile.

## Developer reference

### Start the dashboard

Double-click `Start-Chutku.cmd`, or run `.\.venv\Scripts\python.exe -m chutku.guard --open`.
Keep the terminal running. Follow [README.md](README.md) for a five-minute walkthrough and test commands.

Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Development follows foundation →
deterministic brain → permissions → local LLM → voice. Run
`.\.venv\Scripts\python.exe -m chutku.cli doctor` for prerequisite/storage health.
`chutku.cli plan "YOUR COMMAND"` previews understanding without running it.
Ctrl+Alt+F12 or `Stop-Chutku.cmd` stops the guarded dashboard and owned children.
Inspect Activity before resuming. Verification shows saved checks and source freshness.

Reference-study notes are in [docs/reference/MARK_NOTES.md](docs/reference/MARK_NOTES.md).
Persistent development context is in [docs/PROJECT_MEMORY.md](docs/PROJECT_MEMORY.md).
The post-foundation expansion is defined in [docs/ROADMAP.md](docs/ROADMAP.md).

Exact PC authorities are separate from filesystem grants and disabled by default:

```powershell
python -m chutku.cli authority list
python -m chutku.cli authority grant process.observe
python -m chutku.cli run process.status --args '{"pid":4}'
python -m chutku.cli authority revoke process.observe
```

Explicit filesystem grants can now inspect/search and perform no-overwrite,
journaled copy, move/rename, recycle, restore and conflict-aware undo. Clipboard
text has separate `clipboard.read` and `clipboard.write` grants; content is
redacted from audit and is never implicitly sent to a model.

Gemini is an optional secondary planner for the chat agent. It stays off until you
both store a key (kept in Windows Credential Manager) and grant the capability:

```powershell
python -m chutku.cli gemini set-key
python -m chutku.cli authority grant cloud.gemini
python -m chutku.cli gemini status
```

File access: the runtime sandbox plus any folder or whole drive you grant, e.g.
`python -m chutku.cli access grant "D:\\" --permission modify`. Windows, Program Files,
ProgramData, AppData, drive-root system files and Chutku's own folders stay read-only.

### Run the current slice

Python 3.11+ is required.

Activate the project-local environment for audio features:

```powershell
.\.venv\Scripts\Activate.ps1
```

For a fresh environment, install the pinned runtime dependency set:

```powershell
python -m pip install -r requirements.lock
```

```powershell
python -m chutku.cli tools
python -m chutku.cli run system.get_time
python -m chutku.cli run filesystem.list --args '{"path":"."}'
python -m chutku.cli run filesystem.create_directory --args '{"path":"reports"}'
python -m chutku.cli run filesystem.write_text --args '{"path":"reports/note.txt","content":"hello"}'
python -m chutku.cli run filesystem.undo_last_write --args '{}'
python -m chutku.cli run filesystem.list_incomplete_writes --args '{}'
```

### Natural-language planning

The command center retains its fast deterministic commands. The Local brain panel and voice path use the local Qwen model to produce up to eight exact typed-tool calls after a tool-domain selection pass. The complete plan is held server-side and must be reviewed. High-risk steps pause again for action-time approval; changed tool contracts, invented tools and invalid arguments fail closed.

```powershell
python -m chutku.cli brain "Create a Notes folder, write a checklist, then list the folder"
```

CLI planning is preview-only. Use the authenticated dashboard to review and run a proposal.

Run ordered acceptance gates with:

```powershell
.\.venv\Scripts\python.exe scripts\check_stages.py --through all
```

Stages 1–4 currently pass. Stage 5 also passes its software, authenticated review
boundary and individual real Windows audio checks, but remains red until the
consented live full-path run and human corpus are collected. Collection is
deliberately interactive and saves metadata, not raw audio:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_human_voice.py --group "English" --condition quiet-1m --participant-id english-01 --trials 20 --consent
.\.venv\Scripts\python.exe scripts\evaluate_human_voice.py --group "Indian-accented English" --condition fan-noise --participant-id indian-01 --trials 20 --consent
```

Repeat collection until each accent group has 100 trials and every condition
(`quiet-0.5m`, `quiet-1m`, `quiet-2m`, `fan-noise`, `media-noise`) has at least
20 trials. The checker requires quiet accuracy ≥95%, noisy accuracy ≥85%, each
accent group ≥85%, and zero automatic execution.

One consented live end-to-end path is also required:

```powershell
.\.venv\Scripts\python.exe scripts\verify_live_voice_e2e.py --consent
```

```powershell
python -m chutku.cli ask "what time is it"
python -m chutku.cli ask "system status"
python -m chutku.cli ask "gpu status"
python -m chutku.cli ask "audio devices"
python -m chutku.cli ask "microphone input status"
python -m chutku.cli ask "check microphone level"
python -m chutku.cli ask "check microphone activity"
python -m chutku.cli ask "create folder demo-output"
python -m chutku.cli ask "write Hello from Chutku to demo-output/hello.txt"
python -m chutku.cli ask "read file demo-output/hello.txt"
python -m chutku.cli ask "list files"
python -m chutku.cli ask "undo last write"
python -m chutku.cli history --limit 10
python -m chutku.cli trace CHUTKU-PASTE-A-TASK-ID-HERE
```

Quoted write content is also supported, but it is optional:

```powershell
python -m chutku.cli ask 'write "Hello from Chutku" to demo-output/hello.txt'
```

Unsupported phrasing fails closed with a help message rather than guessing.

### Interactive console

```powershell
python -m chutku.cli chat
```

Type a supported request at the `You:` prompt. Use `help` to see supported commands and `exit` to close the console.

Text reads are limited to UTF-8 files up to 64 KiB inside the sandbox. Their contents are labelled untrusted and are redacted from the ordinary event log.

`check microphone level` opens the default microphone for exactly one second, calculates peak/RMS levels in memory, then discards the raw audio. It creates no recording file.

`check microphone activity` uses a fixed three-second check with 20 ms RMS energy frames. It is an early audio-activity measurement, not speech recognition or a final VAD implementation.

`history` shows task IDs, timestamps, requested tools, and final states. It intentionally does not show command arguments or tool output.

`trace` shows the recorded lifecycle, authorization, and safe/redacted outcome for one task ID from `history`.

Events are stored locally in `data/chutku.db`. The runtime itself owns the granted filesystem root (`sandbox/` by default); tools cannot override it through command arguments.

Every state transition is also written to the event log. This makes it possible to distinguish a failed, denied, waiting-for-confirmation, and completed task from the durable trace instead of relying on a final console message.

All current tools validate their accepted arguments before authorization. `filesystem.create_directory` is restricted to one new directory directly within an existing granted sandbox root and checks its final state before completion.

Text writes are R2 data modifications. Before writing, Chutku records the target's previous state in `data/operations.db` using SQLite WAL. The undo tool restores the previous contents or removes a file that the recorded write created; its result is independently verified.

The regular event log redacts text-write content. The operation journal retains before, planned and verified file content so undo and rollback are possible; do not use this development sandbox for credentials or other secrets.

On restart, unfinished journal entries can be listed. A specific entry can be rolled back with `filesystem.recover_incomplete_write` and its `operation_id` if its current contents match a recorded safe state. Conflicts and older records without the expected write contents require manual review. Completing an interrupted write is not automated.
