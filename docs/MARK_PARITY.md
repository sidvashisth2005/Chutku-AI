# Mark LIV parity tracker

Goal (owner, 2026-09-30): Chutku must do everything Mark LIV (`D:\Project\Mark-LIV-main`) can do, and more.
Mark is CC BY-NC 4.0: it is studied as a reference, and every capability here is Chutku's own implementation
on Chutku's safety core (grants, policy, confirmation, verification, undo). Mark relies on the Gemini cloud
for conversation, search and vision; Chutku does these locally where possible.

Status: ✅ done and verified on this PC · ⏳ not yet · ⛔ deliberately different (reason given)

| Mark capability | Chutku equivalent | Status |
|---|---|---|
| Open any app (`open_app`) | `apps.launch` (any Start-menu app) | ✅ |
| Close any app (`close_app`) | `apps.quit` by name (confirmed; never closes Chutku's own page) | ✅ |
| Chained commands ("open X and then Y") | deterministic chains of up to 3 everyday intents, "it" = the app just named | ✅ |
| Files: list/create/delete/move/copy/rename/read/write/find/info (`file_controller`) | `filesystem.*` on C:/D: with protected zones and undo | ✅ |
| Largest files, disk usage | `filesystem.largest`, `system.environment` (all drives) | ✅ |
| Web search / open URL (`browser_control` go_to/search) | `web.search` (+ flights, amazon, flipkart, images), `web.open` | ✅ |
| Web answers: news / research / price / compare (`web_search`) | `web.news` (Google News RSS), `web.results` (DuckDuckGo/Bing), `web.read` → local answer | ✅ |
| Weather (`weather_report`) | `web.weather` (Open-Meteo, no key; uses saved `city`) | ✅ |
| YouTube play (`youtube_video`) | `youtube.play` (top result, verified playing via media session) | ✅ |
| Volume up/down/mute/set | `audio.volume` (read-back) | ✅ |
| Brightness up/down/set | `display.brightness` (read-back, undo hint) | ✅ |
| Window: minimize/maximize/close/switch/snap/show desktop | `windows.manage`, `windows.close`, `keyboard.shortcut` | ✅ |
| Browser tabs: new/close/next/prev, back/forward, zoom, refresh, find | `keyboard.shortcut` / `keyboard.edit` to the window you were using | ✅ |
| Copy/paste/cut/undo/redo/select all/save, Enter/Escape | `keyboard.shortcut`, `keyboard.edit`, `keyboard.press_enter` (confirmed) | ✅ |
| Type text on screen (`computer_control` type) | `keyboard.type_text` (any language; verified by save-and-read-back) | ✅ |
| Lock screen | `system.lock` | ✅ (unit-tested; not run live to avoid locking you out) |
| Screenshot | `screen.capture` | ✅ |
| Dark mode | `settings.theme_set` / restore | ✅ |
| WiFi toggle | `network.adapter_set` (confirmed) | ✅ |
| Shutdown / restart | `power.schedule` (confirmed, cancellable) | ✅ |
| Open Settings / Explorer / Task Manager / Run | `apps.launch` + `keyboard.shortcut` (windows_settings, file_explorer, task_manager, run_dialog) | ✅ |
| Hardware monitor: CPU/RAM/GPU/temperature | `system.performance` (+ battery, top memory users) | ✅ |
| Desktop wallpaper | `desktop.wallpaper_status` / `desktop.wallpaper_set` | ✅ |
| Desktop organize / clean | `files.organize` (confirmed) + `files.organize_undo` (skips files changed since) | ✅ |
| Reminders (Task Scheduler) | `reminder.set/list/cancel` (toast + spoken, survives restarts) | ✅ |
| Timers | "set a timer for 5 minutes" → reminder | ✅ |
| Morning briefing | "good morning" → time, weather, reminders, headlines | ✅ |
| File processor: PDF/Word/Excel/CSV/image text | `file.extract_text` (pypdf, OOXML, CSV, Windows OCR; image-only slides via OCR) | ✅ |
| Screen understanding (Gemini vision) | `screen.understand` (Gemini: describe, answer, clickable elements) + local OCR `screen.read_text` + `uia.inspect` | ✅ |
| Clipboard intelligence (translate/summarize/explain) | `clipboard.read_text` → local answer | ✅ |
| Code helper: write / explain / run | agent writes files; `code.run_python` (confirmed, 60 s, output returned) | ✅ |
| Send message: WhatsApp / Telegram | `message.send` (confirmed; delivery checked by reading the chat) | ✅ (unit-tested; no real message sent in testing) |
| Game library (Steam/Epic) | `games.list`, `games.launch`, `games.downloads` | ✅ |
| Flight finder | `web.search` site=flights (Google Flights) | ✅ |
| Persistent memory, recall | `memory.*`; saved notes are given to the planner as `user_facts` | ✅ |
| Undo | journaled files, organise undo, volume/theme/brightness/wallpaper restore, reminder cancel | ✅ |
| Real confirmation the model can't forge | runtime approvals, R3+ on screen | ✅ |
| Wake word | "Oye Chutku" (local Whisper, opt-in) | ✅ |
| Push-to-talk (global) | Ctrl+Alt+Space | ✅ |
| Self-echo guard | listener deaf while speaking + mic echo cancellation | ✅ |
| Hybrid voice + text input | chat + 🎙 + hotkey | ✅ |
| Multi-step agent mode | observe→plan→act→verify loop | ✅ |
| Small talk / general questions | planner answers directly without tools | ✅ |
| Auto-start on boot | `chutku.cli autostart on/off/status` | ✅ (available; left off until you choose) |
| Game install/update scheduling (Steam/Epic) | `games.install` opens Steam's install window by game name; `games.downloads` opens the download page; timed downloads use Steam's own download restrictions | ✅ (Epic install: library page only) |
| Audio device picker | `audio.outputs` / `audio.set_output` ("switch audio to headphones"); Core Audio + IPolicyConfig via ctypes, read back, previous device returned | ✅ |
| Holographic avatar, lip-sync, themes | — | ⛔ cosmetic; web UI instead (can revisit) |
| Remote phone dashboard (LAN + QR) | — | ⛔ for now: exposes PC control to the network; needs pairing + TLS design first |
| Drop-in Python plugins | — | ⛔ for now: loads arbitrary code; registry tools instead |
| Dev agent (build whole projects via Gemini) | `code.build_project`: writes a new project, opens VS Code, compiles, runs its tests, launches it, repairs from real errors (Gemini Pro when enabled, else local) | ✅ (verified with the local coder; layout quality needs Gemini) |
| Image description (what's in a photo) | `image.describe` via Gemini vision (needs cloud.gemini; image sent to Google) | ✅ |

## Beyond Mark

Works offline (Mark needs the Gemini cloud for everything) · every action verified against real state ·
per-request autonomy levels · protected system zones · journaled undo with conflict detection · guard process
with emergency stop · audit trail per step · prompt-injection taint rule · SSRF-safe web reading · image-only
slide decks read via OCR · message delivery checked by reading the chat · golden-task benchmark with real checks.

## Beyond Mark (2026-10-06, master plan)

| Capability | Chutku | Status |
|---|---|---|
| Owner mode with fixed, owner-chosen asks; code execution always asks | `policy/kernel.py` | ✅ |
| Earned autonomy (steps that keep failing ask first; reliability per action) | `core/ledger.py` | ✅ |
| Learns its own instant skills from verified model plans | `reflex.py` | ✅ |
| One undo for everything in a time window / task, never over the owner's edits | `rewind.py` | ✅ |
| Scheduled and repeating tasks beside normal work | `scheduled.py` | ✅ |
| Only the owner's voice can make changes (opt-in) | `voice/speaker.py` | ✅ (owner enrollment pending) |
| Nightly self-check: re-plans the week's requests without running them | `nightshift.py` | ✅ |
| "Which PDF did I open yesterday evening" (opt-in, titles only) | `timeline.py` | ✅ |
| Prompt-injection lines removed before the model sees read content | `agent_loop._observation` | ✅ |

## Beyond Mark (2026-10-02)

| Capability | Chutku | Status |
|---|---|---|
| Today home screen (weather, drives, reminders, recent work, activity) | `chutku/today.py` | ✅ |
| Routines ("start work mode") | `chutku/routines.py` | ✅ |
| Health alerts (battery, disk, memory) as Windows notifications | `chutku/health.py` | ✅ |
| Free-up-space report | `storage.cleanup_report` | ✅ |
| Tray icon (open, pause/resume, emergency stop) | `chutku/tray.py` | ✅ |
| Tamper-evident action log + undo by number | `log.recent`, `log.undo` | ✅ |
| Real Recycle Bin delete/restore for files and folders | `filesystem.recycle` | ✅ |
| To-do list with Today tile | `note.add` / `note.list` / `note.done` | ✅ |
| Install a Steam game by name | `games.install` (store search + Steam's own install window) | ✅ (scheduling: Steam's download restrictions) |
| Find personal files by name / open folders and drives | `files.find`, `files.open` phrases | ✅ |
| Interrupted-task Retry after a crash | dashboard banner | ✅ |
