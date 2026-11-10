# Code map

One line per module, taken from each module's own docstring. Read this first, then open only the files you need.
Regenerate with `scripts/codemap.py` after adding or removing a module (`tests/test_codemap.py` checks it).

## How a request flows

1. Text or voice reaches `dashboard.py` (web app), `cli.py` or `voice/`.
2. `quick_intents.QuickPlanner` / `quick_proposal` try the instant router (no model).
3. Otherwise `agent_loop.AgentSession` plans with `cloud_planner` (cloud-first) or `LocalAgentPlanner`.
4. Every step goes through `runtime.Runtime.run` -> `policy/kernel.PolicyKernel.authorize` -> the tool -> its verifier
   -> `core/event_log` and the hash-chained action log.
5. Tools are registered in `app.create_runtime`; each lives in `tools/` (or `apps/` for app actions from the atlas).

Safety rules are in `docs/SECURITY.md`; the owner-facing phrases are in `docs/OWNER_GUIDE.md`.

## `chutku/`

- `__init__.py`: Chutku local agent runtime.
- `agent_execution.py`: Server-held execution state for reviewed general language-model plans.
- `agent_loop.py`: Observe -> plan -> authorize -> act -> verify -> replan loop for free-form goals.
- `alias.py`: Type chutku.localhost in any browser to open Chutku (owner 2026-11-08: "if someone types chutku in the browser's address bar, the…
- `app.py`: create_runtime: builds the Runtime and registers every tool.
- `approval_memory.py`: WA1 ask-once memory (owner 2026-11-08: "once a step worked for the same exact request, it no longer asks").
- `autostart.py`: Start Chutku when the owner signs in to Windows, so Ctrl+Alt+Space works right away.
- `background_desk.py`: Background Desk (App Mastery 2, owner 2026-11-10): Chutku works in apps BEHIND the owner's window while he keeps working ("it must not…
- `backup.py`: Backup and restore of Chutku's memory (H25, from Hermes `backup` / `import`).
- `blueprints.py`: H23 blueprints (Hermes /blueprint): ready-made automations with a few slots.
- `board.py`: H15 task board (Hermes kanban): the owner's to-dos and Chutku's background research, in data/board.db.
- `brain.py`: Local language planners: review before execution, never execution authority.
- `brain_errors.py`: H9: one name for why a brain call failed, so the fallback and the owner's message agree (Hermes error_classifier).
- `brain_service.py`: Persistent, integrity-checked local model service for the agent loop.
- `browser_intent.py`: Web requests that name a browser, plus the voice model's ways of saying them (owner session 2026-10-04):
- `busy.py`: H18 busy mode (Hermes /queue, /steer, /btw): what a new message means while a task is already running.
- `chat.py`: run_chat, reply: the typed chat loop.
- `cli.py`: main: the chutku command line (every subcommand).
- `cloud_planner.py`: Gemini as a secondary agent planner (owner decision 2026-09-30).
- `coder.py`: Project coder: asks a language model (Gemini when enabled, else the local model) to write a whole small project, and to repair it from…
- `control_intent.py`: Controlling Chutku in plain words (English / Hinglish): stop, pause, undo, repeat, help, "are you there".
- `daily_intent.py`: Everyday Hinglish the owner actually says (found by a 45-phrase real-life sweep on 2026-10-04: 21 missed).
- `dashboard.py`: DashboardServer/DashboardHandler: the local web app on 127.0.0.1, speech queue, voice timings.
- `doctor.py`: Read-only foundation health check.
- `drive_index.py`: Deep drive index (Phase 6 X5, 2026-11-05): the names of the owner's files on every fixed drive, so "D drive mein resume.pdf kahan hai"…
- `elevate.py`: WA2 elevation broker (owner 2026-11-08: admin tasks through Windows' own UAC prompt; Chutku itself never elevated).
- `evidence.py`: Bounded local evidence reader; does not execute benchmarks during page loads.
- `evolve.py`: Evolve (master plan Y2, and the owner-profile part of Y4): Chutku studies her own week and proposes improvements.
- `evolve_apply.py`: Evolve, applying an approved idea (master plan Y2), in its own process: ``python -m chutku.evolve_apply <base> <id>``.
- `experience.py`: Learning from experience: plans that fully succeeded are kept as worked examples, and the most similar ones are shown to the planner for…
- `file_intent.py`: Instant file commands that name full paths (the local model fumbled these in the 2026-10-04 benchmark: it listed recent files and then…
- `for_each.py`: H14 (Hermes execute_code, without running code): one planned step that repeats a tool for every item of a list.
- `gemini.py`: Gemini client (off until the owner stores a key and grants cloud.gemini).
- `goals.py`: Standing goals (H24, from Hermes `/goal`): a goal stays across conversations and is checked without a model.
- `gpu.py`: Pick the real graphics card for the local models.
- `guard.py`: Independent Windows supervisor for the dashboard and owned subprocesses.
- `health.py`: PC health watch: battery, disk space and memory pressure, with rate-limited Windows toasts.
- `help_page.py`: The in-app Help (2026-11-08 launch review: /help showed raw Markdown).
- `history_index.py`: Fast search over everything the owner and Chutku said (Phase 3b H4): "pichhle hafte DBMS ke baare mein kya baat hui".
- `hud.py`: Chutku HUD: a native, frameless, always-on-top panel that appears on Ctrl+Alt+Space or the wake phrase.
- `icon.py`: Chutku's brand mark (2026-11-08 redesign): a warm orange rounded square with a white "c" and a dot in its opening, like a speech mark.
- `identity.py`: Who this assistant is, chosen once at install (owner, 2026-11-06: "everyone names their own AI").
- `input_intent.py`: Instant keyboard/mouse phrases (English and Hinglish).
- `insights.py`: Weekly insights (Phase 3b H7, Hermes /insights): "is hafte kya kiya" / "weekly report".
- `know_me.py`: What Chutku knows about how the owner uses this PC (owner, 2026-11-01: "she must learn from what I do and play regularly...
- `learning.py`: Chutku learns from the owner over time, locally and without any model calls (owner, 2026-10-04: "learn with time, find new ways,…
- `learning_inbox.py`: What Chutku learns, with the owner's OK (Hermes background review + skills, done Chutku's way, 2026-11-07).
- `local_vision.py`: Local eyes: a vision model on this PC (Qwen3-VL-4B through the pinned llama.cpp runtime), so seeing the screen and pictures works…
- `memory_index.py`: Meaning-based memory search (master plan S12): multilingual-e5-small, int8 ONNX, on the CPU, fully local.
- `message_intent.py`: Understand "send a message" requests instantly, in the owner's words or the voice model's rewrite.
- `mind.py`: The owner's personal memory ("mind"): people with their nicknames, facts about the owner, and lists.
- `mind_intent.py`: Instant phrases for the owner's personal memory (chutku/mind.py), English and Hinglish.
- `models.py`: W5: optional offline packs, downloaded with progress and resume, kept only when their pinned hash matches.
- `nightshift.py`: Night Shift (master plan S20): Chutku improves while the PC idles.
- `notes.py`: A small to-do / notes list: "note: buy milk", "show my list", "mark 2 done".
- `online.py`: Is the internet (Google's Gemini endpoint) reachable right now?
- `orchestration.py`: Reviewed cross-tool plans with manifest binding and declared reverse recovery.
- `pause.py`: Background pause (Phase 3b H2): hold every job Chutku starts by herself, while the owner's own requests still work.
- `persona.py`: Who Chutku is (owner, 2026-10-05): female, and her name is छुटकू ("Chhutku"), not चुटकू.
- `planning.py`: The deterministic brain boundary, independent of any language model.
- `plans.py`: Bounded, reviewed deterministic plans over a deliberately small tool set.
- `presence.py`: Chutku's presence window (W4, 2026-10-29): the "Chutku Assistant" window in the corner of the screen.
- `presentation.py`: present: turns tool results into the owner-facing text.
- `profiles.py`: Model-aware settings (owner, 2026-10-05): "when we use Gemini online keep it as it is; when it's Qwen, focus on speed; going back to…
- `providers.py`: Free cloud model providers for the cloud-first brain (W2, owner decision 2026-10-29: "free cloud first").
- `quick_intents.py`: Tier-0/1 router for common everyday requests (English and Romanized Hinglish).
- `recall.py`: What Chutku remembers about the owner and past conversations, as one small, topic-relevant slice.
- `references.py`: @-references in typed chat (Phase 3b H6, from hermes-agent's context references, MIT, Nous Research).
- `reflex.py`: Reflex Compiler (master plan S17): Chutku turns requests the model planned well into instant skills.
- `remind.py`: Run by Windows Task Scheduler at a reminder's time: notify, speak, mark as fired.
- `research.py`: H15 research workers (Hermes delegate_task): a child task that may only use the public web.
- `restart.py`: WA6: restart Chutku without leaving it paused.
- `rewind.py`: Causal Rewind (master plan S18): one undo for everything Chutku did in a time window or a task.
- `routines.py`: Named routines ("work mode", "focus mode"): up to four everyday commands run together.
- `runtime.py`: Runtime.run: validate → policy → execute → verify → log, for every tool call; app lanes.
- `scan.py`: Content scan for anything Chutku saves and later reads back into her prompt (Phase 3b H3).
- `scheduled.py`: Scheduled tasks: "30 min baad X karna", "har 15 min X karna", "raat 12 baje X karna".
- `second_opinion.py`: Second opinion (H22, from Hermes `/review` and `/moa`): "pakka?" re-checks the last answer against public sources.
- `setup_wizard.py`: First-run setup (O4 2026-11-06; assistant name and phone app account added the same day for publishing): `python -m chutku.cli setup`,…
- `skill_import.py`: X17 (2026-11-06): learn an ability from a public GitHub project with one command ("github.com/x/y se skill seekho").
- `skill_runner.py`: Runs one approved Chutku skill (chutku/skills.py): ``python -I -B -X utf8 skill_runner.py <skill folder>``.
- `skills.py`: Self-written skills (master plan X15 + X16): small Python abilities Chutku writes, tests and, once the owner approves them, offers as…
- `streaming.py`: Speak the first words of an answer while the rest is still being written (master plan S11).
- `suggest.py`: Suggestions, not just orders (owner, 2026-10-04): a card on the dashboard's Today page, and at most one Windows popup per hour, never…
- `system_journal.py`: WA2 hardening 2: every system change journals what it replaced (data/system_journal.jsonl), so "undo last change" / "wo wapas karo" can…
- `task_table.py`: The task table (owner 2026-11-10: "synthetic workflows of all possible tasks a user can give, all types of personalities ...
- `timeline.py`: Episodic timeline (master plan S21): "wo PDF jo kal shaam khola tha".
- `today.py`: The dashboard's "Today" panel: a fast, read-only snapshot of the owner's day.
- `translit.py`: Devanagari -> Roman letters, so Hindi the voice service writes in Hindi script ("हाँ", "पिता श्री", "भेज दो") matches the owner's…
- `tray.py`: Notification-area (tray) icon: open the dashboard, pause/resume actions, emergency stop.
- `updates.py`: Updates for installed copies (owner 2026-11-08: "publish an update to existing users, like a pop up").
- `vision.py`: Screen vision: capture the monitor the user is working on, ask the local vision model (Qwen3-VL; Gemini as the backup) what is on it and…
- `workflows.py`: project_plan, run_project: the fixed project recipe.

## `chutku/apps/`

- `__init__.py`: App Mastery (docs/APP_MASTERY_PLAN.md): per-app atlases, a step runner with built-in checks, and the Action Lab.
- `atlas.py`: App atlases (App Mastery A1): what Chutku knows about one app, as checked-in JSON (chutku/apps/atlas/<app>.json).
- `extras.py`: Small read-only app tools that return data (App Mastery A5+).
- `howto.py`: app.howto (App Mastery A3): "Spotify mein shuffle kaise karte hain?" answered from the app's feature map.
- `known.py`: Names the owner's apps proved to have (F6, 2026-10-29): a playlist, artist or album Chutku once played with a passing check is…
- `lab.py`: Action Lab (App Mastery A2): prove each app action on this PC before Chutku trusts it.
- `phrases.py`: Instant routing of app phrases (App Mastery A3): "After Party playlist chalao" -> app.spotify.play_playlist.
- `runner.py`: Run one atlas action (App Mastery A1): its fixed steps, then its check, through a Driver.
- `teach.py`: Teach mode (App Mastery A15): the owner shows a task once in one app window; Chutku saves it as a routine.
- `tools.py`: Atlas actions as Chutku tools (App Mastery A1): every action of every valid atlas becomes `app.<app>.<id>`.

## `chutku/core/`

- `__init__.py`: Core task and audit primitives.
- `action_control.py`: Persistent cooperative pause, accessible independently of the action lock.
- `action_log.py`: Append-only, hash-chained log of everything Chutku did or was refused.
- `approvals.py`: Ephemeral, single-use approvals bound to a server-owned exact task.
- `capability_grants.py`: Durable, exact capability grants for non-filesystem PC authority.
- `elevation.py`: Detect whether Chutku runs with an elevated (administrator) token.
- `event_log.py`: EventLog: the SQLite event trace.
- `execution_lock.py`: ExecutionLock, append_lock: one action at a time; locked log appends.
- `hashcache.py`: Pinned-hash checks for multi-gigabyte model files, without re-reading them on every start.
- `jsonstore.py`: Small JSON files the owner's settings live in (preferences, reminders, routines).
- `launch.py`: Start the owner's apps so they outlive Chutku.
- `ledger.py`: Earned Autonomy (master plan S16): every step's expected result vs what was observed, and a calibrated trust score.
- `log.py`: One local log file for problems Chutku recovers from (data/logs/chutku.log, 5 x 2 MB, rotated).
- `memory.py`: MemoryStore: saved notes and memory.
- `operation_journal.py`: OperationJournal: what was changed, so it can be undone.
- `paths.py`: Data/model folders, protected zones, system_damage (paths that are always refused).
- `preferences.py`: Small validated owner preferences (hands-free autonomy level, wake phrase opt-in, live conversation mode).
- `progress.py`: Progress heartbeat and cancellation for long tool actions (e.g.
- `recycle_bin.py`: Send files and folders to the real Windows Recycle Bin and restore exactly what Chutku sent.
- `resource_grants.py`: Durable, runtime-owned resource grants for filesystem capabilities.
- `task.py`: Task, TaskState: one request's state.

## `chutku/gateway/`

- `__init__.py`: Outbound-only remote channels (H16 Telegram).
- `telegram.py`: H16 Telegram remote control (Hermes gateway + DM pairing), a second remote path next to the phone app.

## `chutku/intents/`

- `__init__.py`: Shared vocabulary for the instant (no-model) request parsers.
- `lexicon.py`: One Hinglish vocabulary for every instant parser (master plan S13).
- `tone.py`: How much may Chutku decide by herself for this one request?

## `chutku/policy/`

- `__init__.py`: Authorization rules isolated from planners and tools.
- `kernel.py`: PolicyKernel.authorize: allow / confirm / deny for every step; autonomy modes.
- `never_rules.py`: The owner's "never" rules (Phase 3b H1): things Chutku must never touch, checked before every other policy rule.

## `chutku/practice/`

- `__init__.py`: WA4 rewarded practice (owner 2026-11-08: "very rigorous training").

## `chutku/relay/`

- `__init__.py`: Account relay: one ID/password links an installed assistant and its phone app (see server.py and client.py).
- `__main__.py`: python -m chutku.relay: runs the relay server.
- `client.py`: The laptop's side of the account relay (chutku/relay/server.py).
- `e2e.py`: W6: end-to-end encryption between the phone app and the laptop, through the account relay.
- `server.py`: The account relay (owner, 2026-11-06): one server that every installed assistant and its phone app reach.

## `chutku/remote/`

- `__init__.py`: Remote access from the owner's phone (W6 = HERMES_PLAN P1-P9, owner order 2026-10-29: "full control from my phone if the PC is online").
- `audio.py`: The laptop's sound for the phone remote (owner 2026-11-08, "there is no audio, only video").
- `auth.py`: Phone pairing, credentials, PIN, sessions and approval nonces (W6 / HERMES_PLAN P1).
- `boot.py`: Reach this laptop after a restart (owner 2026-11-08: one click for every install, not only the owner's checkout).
- `border.py`: The red frame round the laptop screen while the phone controls it (W6 / P5 rule 3): anyone at the laptop sees that remote control is live.
- `control.py`: Direct control from the phone (W6 / HERMES_PLAN P5-P7).
- `files_browse.py`: Browse the laptop's files from the phone (owner 2026-11-07: "I won't remember paths; let me browse my PC's files, with filters like…
- `manager.py`: The laptop side of phone access (W6): turn it on or off, make a pairing code (and QR), arm or disarm control, remove a phone.
- `server.py`: The phone server (W6 / HERMES_PLAN P1-P9): a thin, phone-only API on 127.0.0.1:<port>, published to the owner's tailnet by `tailscale…
- `tailscale.py`: The owner's tailnet is the only way in (W6 / HERMES_PLAN P1).
- `targets.py`: What is on the laptop screen near a point, for the phone remote (owner 2026-11-08): smart tap, the magnetic pointer and the…
- `tools.py`: Phone access by voice or chat at the laptop (W6): "phone connect karo", "phone pair karo", "remote band karo", "phone hatao", "phone…

## `chutku/router/`

- `__init__.py`: Deterministic command routing before any future LLM fallback.
- `catalog.py`: CommandCatalog, RoutedCommand: fixed typed commands.

## `chutku/tools/`

- `__init__.py`: Explicit deterministic tool implementations.
- `action_log_tools.py`: log.recent ("what did you do today?") and log.undo <id> over the hash-chained action log.
- `apps_extra.py`: Messaging (WhatsApp / Telegram Desktop) and games (Steam / Epic), Mark-LIV parity.
- `assistant.py`: register_assistant_tools: capability list, visible windows, limits.
- `audio_output.py`: List playback devices and switch the default one ("switch audio to headphones").
- `browser.py`: Bounded Playwright automation using fresh profiles and semantic locators.
- `builder.py`: code.build_project: turn "build me a calculator app" into a real, checked project.
- `builtin.py`: register_builtin_tools: time, system info, audio devices, GPU and other basics.
- `clipboard.py`: Capability-gated, bounded Windows text clipboard access.
- `desktop.py`: Background desktop control through agent-desktop (vercel-labs, Apache-2.0): desktop.look, desktop.act, desktop.act_risky, desktop.do and…
- `desktop_controls.py`: Desktop controls with Mark-LIV parity: shortcuts, typing, volume, brightness, lock, performance, wallpaper and largest files.
- `documents.py`: Documents and screen text (Mark's file_processor / screen vision, done locally), confirmed Python script runs (code_helper 'run'), and…
- `everyday.py`: Everyday desktop actions: installed apps, files, web, windows and media.
- `files_plus.py`: Everyday file helpers: zip, unzip (safe), recent files, disk space.
- `filesystem_extended.py`: Verified file inventory, search, copy and move inside one explicit grant.
- `finance.py`: Stock quotes (X9): Yahoo Finance's public, keyless endpoints, read with the standard library only.
- `free_input.py`: General keyboard and mouse for Chutku (owner request 2026-10-04): any shortcut, and clicks on anything visible.
- `history_tools.py`: history.search (Phase 3b H4): find past conversation turns by topic, in milliseconds, without a model.
- `image_vision.py`: image.describe: describe a picture file, or answer a question about it: the local vision model first (PNG/JPG, offline), Gemini vision…
- `internet.py`: Read-only internet information: weather, news, web results, page text, YouTube.
- `know_me_tools.py`: Tools on top of chutku/know_me.py (2026-11-01): play a show from the owner's own library and VLC history, and say what Chutku knows…
- `ledger_tools.py`: Earned-autonomy tools (master plan S16): "reliability batao" and the owner-only relax switch; and the learned instant skills (S17):…
- `mail.py`: Email (X8), draft first: email.draft opens a ready draft in the default mail app and sends nothing; the owner presses Send there.
- `mind_tools.py`: Tools over the owner's personal memory (chutku/mind.py): people, facts about the owner, and lists.
- `net_check.py`: Internet troubleshooting in plain words: net.check ("is my internet working?") and net.ping.
- `never_tools.py`: The owner's "never" rules (Phase 3b H1): "D:\Exams ko kabhi mat chhoona" / "never touch D:\Exams".
- `power_controls.py`: Delayed Windows power scheduling with exact phrases and explicit cancellation.
- `processes.py`: Bounded Windows process observation with no shell-derived user input.
- `registry.py`: Tool, ToolRegistry, Risk, ToolResult: the tool contract and its manifest.
- `reminders.py`: Reminders that survive restarts: Windows Task Scheduler runs chutku/remind.py at the set time, which shows a Windows notification and…
- `schedule_tools.py`: Scheduled tasks: "30 min baad X", "har 15 min X", "raat 12 baje X" (see chutku/scheduled.py).
- `screen.py`: Capability-gated Windows display inventory and verified local PNG capture.
- `screen_vision.py`: See the screen and act on it: screen.understand (local vision model first, Gemini as the backup), screen.click, screen.click_risky,…
- `signed_in_browser.py`: The owner's signed-in browser (Z6) through agent-browser (vercel-labs, Apache-2.0): browser.look, browser.act, browser.act_risky, and…
- `speech.py`: register_speech: speaking through Windows SAPI.
- `system_controls.py`: Bounded, separately capability-gated Windows audio and network controls.
- `system_tools.py`: WA2 (Chutku 1.2): system tools.
- `timeline_tools.py`: Episodic timeline tools (master plan S21): "wo PDF jo kal shaam khola tha", and the owner-only on/off switch.
- `uia.py`: Bounded, read-only Windows UI Automation inspection for exact app windows.
- `uia_actions.py`: Exact-target UI Automation actions with action-specific postconditions.
- `visible.py`: Act on what is already on the screen (owner, 2026-10-08): "After Party playlist screen pe hai, use play karo".
- `voice_lock_tools.py`: Owner Voice Lock switches (master plan S19): "voice lock on/off" (typed by the owner only) and its status.
- `windows_apps.py`: WindowsDesktop, register_windows_apps: open/focus/close app windows, verified.
- `windows_settings.py`: Reversible, capability-gated Windows user settings.

## `chutku/voice/`

- `__init__.py`: Local voice capabilities, introduced only after device-level verification.
- `approval.py`: Hands-free approvals: Chutku asks a pending step out loud and the owner answers "haan" / "nahi".
- `audio_probe.py`: Microphone devices and input level checks.
- `handsfree.py`: Hands-free voice: a global push-to-talk hotkey and an opt-in "Oye Chutku" wake phrase.
- `heard.py`: Only real speech counts: a noise gate for the live conversation, a shared transcript filter, and a local "what I heard" log (owner…
- `live.py`: Conversation mode: a live, interruptible voice conversation with Chutku (Gemini Live, free tier).
- `mic.py`: Mic mute (owner, 2026-10-05): while showing Chutku to friends, their laughs and comments were heard mid-answer and the answer stopped to…
- `plausible.py`: Is a spoken transcript a request at all?
- `recognition.py`: Offline free-form speech input.
- `session.py`: Process-local audio session state, independent from task lifecycle state.
- `speaker.py`: Owner Voice Lock (master plan S19): only the owner's voice gives tasks.
- `tts.py`: Chutku's neural voice (master plan S10 service): Kokoro-82M, voice hf_alpha, chosen by the owner's blind listening test on 2026-10-07…
- `wakeword.py`: Chutku's own "Oye Chutku" detector (2026-10-11): listens to every 80 ms of sound, ~1% CPU, no transcription.
- `whisper_stt.py`: Offline Whisper speech-to-text (faster-whisper, CPU int8) for English/Hindi/Hinglish.
