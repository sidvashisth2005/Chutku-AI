# Chutku Implementation Status

**Last updated:** 2026-11-10
**Source of truth for scope:** [docs/DESIGN.md](docs/DESIGN.md)

This file is the implementation ledger. Update it in the same change as every code, configuration, benchmark, or documentation change. A checked item means it exists and has been verified to the stated degree; it does not imply a broader roadmap phase is complete.

## Current focus

2026-11-10: the master plan is [docs/BEST_ASSISTANT_PLAN.md](docs/BEST_ASSISTANT_PLAN.md): eight promises, the
real-use baseline (Daily 30 at 61%), slices B–H with files, edge cases, tests, live checks and gates. Slice A (the
scoreboard) is done, entry (33). Work the first open tick in its section 15.

2026-09-30: Chutku's main path is now a chat/voice agent. A goal goes through the
deterministic everyday router or the GPU local planner, runs as observe → plan → act →
verify rounds bounded by a per-request autonomy level, and every step still passes
grants, policy and independent verification. Stages 1–4 are accepted on the final source.
Stage 5 still needs the owner's consented live microphone run and 200 human trials.
Owner decisions are in `docs/DESIGN.md` §51.

## Delivered

### 2026-11-12 (42): Open bugs fixed, release 1.2.4
- Owner: "finish everything, all the bugs ... then ship and release".
- Weather: "aaj Delhi ka mausam kaisa hai" asked the geocoder for "aaj Delhi" (Cajana). Time and filler words
  (`quick_intents._WEATHER_FILLER`) are now stripped from both ends of the city, not only when the city is exactly
  one of them. Test: `test_quick_intents` (+2 lines).
- `one_command_check`: the maths case now checks WHICH number the reply calls bigger (`_TWO_BIGGER`, `_CUBE_BIGGER`;
  the old check passed "10 ka cube (1000) bada hai 2 ki power 10 (1024) se"), and the weather case needs "Delhi".
- Release blocker found and fixed: the "Offline brain" pack fetched only Qwen3-4B, so with `active_planner:
  planner_qwen35` a fresh or older install would have had no local brain. `brain_service._candidates` falls back to
  the base model when the active planner is missing or fails its hash; the brain pack now includes `planner_qwen35`
  (about 5.3 GB). Tests: `test_model_select` (+2: missing and tampered planner fall back; the pack brings the active
  planner).
- `test_practice_wa4` read UTF-8 fine-tune rows with the Windows default code page (the bank has Hindi now): reads
  UTF-8. `test_phone_remote_w6` h264: 2 s stream window and a polled close (it failed once under a loaded run).
- `docs/SECURITY.md`: 194 app actions, counting the 10 `chutku/apps/atlas/ui_*.json` atlases from the 2026-11-10 app
  survey (`scripts/make_ui_atlases.py`), now committed (safe navigation actions; instant only after 3 Action Lab
  passes).
- Evidence: `one_command_check --offline` 12/12 with the stricter checks, median 4.9 s ("Delhi: 21.6°C ..."; maths
  "1024 is bigger than 1000"); 0 model servers left. `check_phrases.py` 193/193. Full suite **1850 tests, 582 s,
  OK** (no known failures left).
- Released: commit b38b335 pushed to main; `scripts/release_local.ps1 -Version 1.2.4`: build, installer, silent
  install/uninstall test ok (1.2.4), published https://github.com/sidvashisth2005/Chutku-releases/releases/tag/v1.2.4
  (Chutku-Setup-for-Windows.exe, 315,949,768 bytes, sha256 4e4909df...). v1.2.3 kept (no `-Old`).

### 2026-11-12 (41): The local model plans a several-part request one part at a time; 12/12 offline
- Owner: "keep current specs ... give very segregated and simple info to the current model ... delete unused things".
- `agent_loop.goal_parts` splits a request with the instant router's own splitter (`quick_intents._CHAIN_SPLIT`);
  a piece with no verb joins the one before ("RAM aur CPU kitna use ho raha hai" stays one). Only the local model
  (`profile qwen`) gets `PARTS`, `DO_NOW` and a one-line `PARTS_RULE` in its user message (the cached system prefix
  is unchanged, under its 14,000-character test). After a round whose steps all COMPLETED, `DO_NOW` moves on.
  `_reject_early_finish` (local planner only, in `_checked`): while later parts remain, "done" is rejected and
  retried, and "finish" is cleared, so a session never ends after part 1.
- Evidence: `one_command_check --offline` **12/12** (median 6.5 s, slowest 29.7 s); the multi-step case that failed
  for both models ("onecmd mein report naam ka folder banao, usme todo.txt mein 'buy milk' likho, phir us folder ki
  files batao") now creates `onecmd\report\todo.txt`; 0 model servers left afterwards. `eval_planner` 34/40, median
  3.5 s, 3.47 GB: the one change from 35/40 (`info-hinglish-time` answered without the clock tool) misses the same
  way with all of today's code stashed (the prompt carries the current time); in use the instant router answers it.
- Qwen3.5-9B (owner asked about an "8B": none exists; 9B Q4_K_M 5.68 GB, rev 3885219b, sha256 03b74727... matched):
  ~18-20 s per planner round on the 4 GB GPU vs 3.3 s for the 4B after 17 of 45 tasks; stopped on the owner's word,
  file moved to the Recycle Bin.
- Tests: `PartsTests` (splitting, single requests stay whole, DO_NOW only for the local model, no early finish).
  Full suite 1848 tests, 596 s: only the two failures that predate this work (`test_docs_truth`,
  `test_practice_wa4`).

### 2026-11-12 (40): Owner's choice: Qwen3.5-4B is the offline planner; capped thinking for reasoning questions
- `models/manifest.json`: `"active_planner": "planner_qwen35"` (hash-pinned, existing switch). Back: `"model"`.
- `agent_loop._reject_lost_folders`: a step path above a folder the user typed (not inside or a parent of one) is
  rejected and the planner retries; the live miss "D:\ChutkuScratch\onecmd mein notes.txt banao" ->
  `D:\ChutkuScratch\notes.txt` now writes into `onecmd`.
- Thinking: `brain_service.complete(think=True)` turns it on for one request (`chat_template_kwargs`), with
  `--reasoning-budget 256` on the server; the planner uses it only on the first round of a numeric question with
  nothing to do (`_reasoning_question`) or "dhyan se socho". Measured: maths/logic 5/5 at ~6.5 s vs 1/4 without;
  tool rounds with thinking 4/10 vs 10/10 without, so they stay without.
- `scripts/one_command_check.py` closes its model servers on exit (two from its earlier runs held the GPU for ~50
  min and made a thinking run crash).
- Clean-up (owner: "remove anything unnecessary or old"): to the Recycle Bin: the Bonsai candidates, the obsolete
  `models/qwen35-pending.txt` marker, six helper worktrees under `.claude/worktrees` (all merged into main; one held
  untracked presence-bar/face screenshots) and this evaluation's temp logs; `git worktree prune`; merged branches
  deleted with `git branch -d` (refuses unmerged). Kept: Qwen3-4B (still verified at start-up by `brain.py`/
  `doctor.py` and the rollback), Qwen3-8B (offline backup), `claude/brain-2` (2 unmerged plan commits, also on origin).
- Evidence: `one_command_check --offline` 11/12, median 4.6 s (Qwen3-4B before: 11/12, 6.5 s); the maths case is now
  right in 9.7 s ("1024 is bigger than 1000"), 0 model servers left afterwards; `eval_planner` 35/40, median 3.3 s,
  3.41 GB. Still failing: the multi-step case skips the `report` folder (both models).
- Tests: `LostFolderTests` (the live miss rejected; paths inside, above, elsewhere and with nothing typed pass) and
  `ThinkingTests` (which goals count as reasoning questions, and thinking only on the first round or when asked);
  `test_tool_menu`, `test_agent_loop`, `test_profiles`, `test_model_select` 78 OK. Full suite 1846 tests, 628 s:
  only the two failures that also fail with this work stashed (`test_docs_truth` app-action count from the
  untracked atlas files, `test_practice_wa4` decode error). Details:
  [docs/LOCAL_MODEL_EVAL.md](docs/LOCAL_MODEL_EVAL.md).

### 2026-11-12 (39): Local model evaluation: Bonsai 2 27B vs today's models; no switch
- Full record, settings, hashes and reproduce commands: [docs/LOCAL_MODEL_EVAL.md](docs/LOCAL_MODEL_EVAL.md).
- This PC: i5-12500H, 24 GB RAM (4.4-12 GB free with the owner's apps), RTX 3050 Laptop 4 GB, D: 34.7 GB free at start.
- Bonsai 2 27B PTQ1_0 (rev 839bd570, sha256 53107f53... matched) on the PrismML fork prism-b12128-d7b2896 (zip digests
  matched). CUDA build: ready in 6-7 s, 16 prompt / 3.2 decode tok/s, peak 6.99 GB RAM, ~2.3 GB on the GPU; Vulkan
  and CPU builds slower (2.5-3.5 prompt tok/s).
- `eval_planner` (first rounds): Qwen3-4B 27/40 at 4.7 s median; Qwen3.5-4B 35/40 at 3.0 s, 3.39 GB; Qwen3-8B 32/40
  at 12.9 s, 6.53 GB; Bonsai 9/10 on a 10-task subset (all 4 safety negatives refused) at **33.3 s** median (122 s
  worst). The same subset: Qwen3.5 10/10, Qwen3-8B 5/10, Qwen3-4B 4/10.
- `eval_vision` (new, synthetic screen, 5 questions incl. Hinglish and "below/above X"): Qwen3-VL-4B 5/5 at 0.4-2.2 s,
  3.12 GB; Bonsai + mmproj 5/5 at 17.9-19.7 s, 6.68 GB.
- `one_command_check --offline`: Qwen3-4B **11/12**, median 6.5 s; Qwen3.5-4B 8/12, median 16.6 s (wrote outside
  the scratch folder; the harness denied it). Manifest was set to `planner_qwen35` for that run only and restored
  with `git checkout` (clean afterwards).
- **Decision:** keep Qwen3-4B (+8B) planner and Qwen3-VL-4B eyes. Bonsai is accurate but ~7-11x slower and 2x the
  RAM on a 4 GB GPU; re-test on >= 8 GB VRAM. No product code or model setup changed.
- Tooling: `scripts/eval_planner.py` gains `--exe`, `--ngl`, `--reasoning`, `--only`, start time and peak RAM;
  new `scripts/eval_vision.py`.
- Found, not fixed: the offline "math" check passed a reply saying 1000 > 1024; "aaj Delhi ka mausam" answered for
  "Cajana" (instant router) in both runs, and the weather check only looks for a temperature.
- Candidate files (`models/candidates/` + `vendor/candidates/`, 8.4 GB) moved to the Recycle Bin on the owner's word.
- Tests: full suite 1842 tests, 590 s: the known docs-count failure (`test_docs_truth`, 194 vs 144 app actions, from
  the untracked `ui_*.json` atlas files) plus `test_practice_wa4` (cp1252 decode error) and on a second run a
  flaky `test_phone_remote_w6` h264 check. `test_docs_truth` and `test_practice_wa4` fail the same way with this
  change stashed. `test_codemap`, `test_model_select` and the planner tests pass; both eval scripts parse (`--help`).

### 2026-11-11 (38): Owner's report: offline start failed, "two Chutku" on the hotkey, old UI still there
- **"Two Chutku" / old UI:** `watch_presence` started the old Tk HUD when the presence window had not appeared within
  8 s, while the presence process kept running and showed its window later. The log has it 5 times (2026-11-05..10:
  "did not appear (exit code None); using the HUD"). From then on every hotkey showed both. It also looked only for
  the full window's title, not the bar's. Now (owner: "remove"): either presence window counts, the wait is 30 s,
  a presence that never shows is ended (`taskkill /T`, the venv launcher has a child) and started once more, a second
  failure says "use the tray icon". The old HUD never opens on the real install; the tray's "Show window" no longer
  falls back to it (only a machine without pywebview keeps the old panel).
- **Offline start:** at 10:38 the guard killed the first core 15 s in: one heartbeat, then 5 s quiet while it loaded
  (`guard-last-stop.json`, reason `heartbeat_timeout`). `guard._supervise(startup_grace=)`: for 60 s after a core
  starts (`STARTUP_GRACE`, the real guard only) the start-up limit (20 s) applies even after the first heartbeat; a
  real hang is still caught at that limit.
- **Offline briefing** (the 08:00 job ran at 10:42, offline): weather asked "which city?" and the reminders never
  came. Now the weather tool says "No internet connection" when the network is down (it still asks when online and
  the location is unknown); in a plan of lookups only, a failed lookup no longer stops the others
  (`_after_step(lookups=True)`), and the answer names the part that failed ("Check the weather: not done (No
  internet ...)"). A failed *action* still re-plans as before (negative test).
- **Multi-part answers keep every result** (entry 35 follow-up, live 2026-11-11): the cloud model never sees private
  results (disk space, IP), so its reply said "C drive ki details nahi mili" after both checks passed.
  `quick_intents.worded()` builds the answer from the steps' data whenever every step has a reply builder; used by
  `AgentSession._answer` for model sessions too (research steps have no builder: the model still answers). New
  `filesystem.search` builder. The chain router now splits on commas, re-joins a part that is not a request alone
  ("RAM aur CPU kitna use ho raha hai"), takes the finish flag from each part (lookups get worded) and never cuts a
  chain at 4 steps (a longer one goes to the planner). New phrasings: "RAM/CPU kitna use ho raha hai",
  "downloads ki sabse badi file batao".
- **G2 morning brief:** `suggest.candidates` offers "every day at your usual start: weather, news, reminders?" once 3 of
  the last 14 mornings show use and no briefing is scheduled (the owner's is, at 08:00, so it is not offered).
  Popups wait for a good moment (`suggest.can_disturb`): no running task, Windows accepts notifications
  (`SHQueryUserNotificationState`: no full-screen app, game, presentation or Focus), battery not below 20% unplugged.
- **Not changed, and why:** the offline voice understood poorly because Gemini Live needs the internet and the local
  fallback (Whisper) is set to English (`stt_language: en`), weak for Hinglish: the owner's setting. No voice turns
  were logged today at all (the mic was muted in Windows yesterday; it records normally now: rms 0.0028).
- **Verification:** new `tests/test_one_interface.py` (4), `test_guard.py` +2 (a 1 s quiet start is killed without the
  grace and kept with it; a hang inside the grace is still caught), `test_finish_without_cloud.py` +6 (offline
  briefing, failed action still stops, weather offline, planned multi-part keeps results; it fails with the fix
  patched out), `test_quick_intents` +1, `test_learning` +4. Full suite 1,842: the known docs count and
  `test_weather_uses_saved_city_and_asks_otherwise` (it asserted the old offline question; updated). Live, real path:
  "aaj ki date batao, C drive mein kitni jagah hai aur internet chal raha hai kya" instant 2.6 s with every number
  (C: 15.7 GB free of 254.2, matching `Get-PSDrive`); "RAM aur CPU ... aur kaunse apps khule hain" 9.8 s, CPU 48%, RAM
  75%; "downloads ki sabse badi file batao aur desktop pe kitni files hain" 2.1 s, 5 files and 3 folders (matches
  PowerShell's count of 5 files).

### 2026-11-10 (37): Chutku never types a password (master plan slice F3)
- **Gap:** only teach mode skipped password fields (it does not record them); nothing stopped `keyboard.type_text`
  or an app action from typing into one.
- **Fix:** `desktop_controls.focused_is_password()` asks UI Automation (the phone remote's in-process client,
  `remote.targets._uia`, 1 s cap) whether the focused element is a password box. `keyboard.type_text` and
  `apps.runner.Driver.type` refuse then, with or without an approval click: "Chutku never types passwords: type it
  yourself, then tell me to continue." The owner's own typing from the phone is not blocked. Documented in
  `docs/SECURITY.md` §2, with its limit (an app that hides the type is not detected).
- **Verification:** `tests/test_command_window.py` +2 (refused unapproved and approved, typing goes ahead for an
  ordinary box and when UIA cannot tell, app actions raise `StepFailed` and type nothing). Real probe on this PC:
  `focused_is_password()` -> False for the owner's focused element in 0.15 s. Full suite 1,825: 1 failure, the
  known docs count. **Not yet live:** a real password box check needs a window focused on this PC; the owner was
  typing (idle 0 s), so it waits.

### 2026-11-10 (36): "The playlist just below After Party" (master plan slice F1)
- **Real failure** (2026-11-09): "play the playlist just below After Party on the screen in Spotify" went to the
  planner and was cancelled; the screen tool had no idea of below/above, and the router missed "on the screen in
  Spotify".
- **Fix:** `tools/visible.pick(lines, name, kind)` (used by `screen.act_on_visible` instead of `typed`):
  "just below X", "right under X", "X ke neeche/niche", "above X", "X ke upar" pick the nearest item in the anchor's
  column (x within 60 px), skipping type labels ("Playlist • ..."); when the list shows types, the asked kind wins
  (the next *playlist*, not the song between). Several anchors, no anchor, or nothing in that direction pick nothing
  (the tool's own "not visible; I clicked nothing" reply). A name that only looks relative is still matched as a name.
  The router's "on the screen" pattern accepts "... in Spotify"; both Spotify playlist routes leave a relative name
  to the screen tool (it is a place, never a playlist title).
- **Verification:** `tests/test_visible.py` +4 on the real OCR lines from the owner's Spotify (2026-10-08) and a
  labelled list: below/above in 9 phrasings, labels skipped, kind wins, other column ignored, 3 anchors -> nothing,
  the owner's sentence routes to `screen.act_on_visible {name: "just below After Party", kind: playlist, app:
  spotify, action: play}`; "play After Party playlist from the screen in spotify" still uses the verified playlist
  action. Full suite 1,823: 1 failure, the known docs count. Router snapshot: no other change. Phrases 193/193.
- **Not yet live:** needs Spotify open on the owner's screen and music playing; run when the owner says so.

### 2026-11-10 (35): Verified work is never reported as failed (master plan slice E, first part)
- **Found live** (real request path, spare port, temporary data folder with what setup grants a new user):
  "aaj ka weather, news aur meri reminders batao" ran all 4 steps (time, weather, reminders, news: all COMPLETED),
  then answered "I couldn't work on that: the free AI limit is used up", status **failed**. Cause: web.weather,
  web.news and reminder.list had no instant reply builder, so the wording went to Groq, which was rate-limited.
- **Fixes:**
  - `quick_answers.py`: builders for `web.weather`, `web.news`, `reminder.list`, and (the only other instant-routed
    lookups without one, found by routing every task-table and phrase sentence) `filesystem.largest`, `never.list`.
    `file.extract_text` stays with the model (it summarises a document).
  - `AgentSession._finish(..., worded_by_code=True)` on the instant path: a reply Chutku's own code built from
    verified step data skips the model false-claim guard, so a headline like "Files deleted in a data leak" no
    longer withholds the briefing. Negative test: a model reply "I deleted the old files" with no step is still
    withheld.
  - Listing reminders is one instant family (`_REMINDERS_LIST`): "meri reminders dikhao", "koi reminder hai kya",
    "list my reminders" ... (only the exact "show my reminders" was instant). Setting one still routes to
    `reminder.set`; "delete my reminders" is not a list.
- **Verification:** new `tests/test_finish_without_cloud.py` (5 tests), `test_quick_intents` (+1; the guard test has
  samples for the 5 new builders). Full suite 1,819: 1 failure, the known `test_docs_truth` count. Router snapshot:
  only "show my reminders" / "mere reminders dikhao" changed (now worded from the list). `check_phrases.py` 193/193.
  Live (real path): the briefing **done in 7.9 s, 4/4 steps, no cloud call** (time 08:10 PM matched the clock);
  "meri reminders dikhao" done in 4.1 s; "downloads mein sabse badi file kaunsi hai" done in 1.0 s: Chutku-Setup-for-
  Windows.exe 227.3 MB, then a 212.8 MB recording, matching an independent PowerShell listing.
- **Still open in E:** the task card (finish every part of a free-form multi-part request) is not built; the
  briefing case turned out to be a wording failure, not a planning one. "aaj ka weather batao aur meri reminders
  dikhao" failed in the temporary-folder test while Groq was rate-limited; that folder had no `cloud.gemini` grant.
  Correction (checked after the restart): the owner's install has the Gemini key and the grant, so the real planner
  falls back Groq -> Gemini; setup grants `cloud.gemini` whenever a user saves a Gemini key. Since entry (35) the
  sentence is instant anyway (weather + reminder list, no model).

### 2026-11-10 (34): Never lie, never act on noise (master plan slice B)
- **B1, spoken promises:** checked the "unkept promises" the estimate flagged against `data/heard.jsonl`: every one in
  the last 7 days was backed (the Live claim-starts-the-task mechanism works; the time-stamp pairing was wrong).
  So the source now records it exactly:
  - `LiveConversation.tasked_turns`: the owner's turn (n-th "you" entry) for which a task started; `recall.log_voice(...,
    tasked=)` writes `"task": true/false` on each voice row; `dashboard_voice._after_live` passes it.
  - `scripts/scoreboard.unbacked_promises` counts rows with the flag exactly and keeps the estimate only for older rows
    (3-minute grace for a task still running when the conversation ended: live 2026-11-06, 69 s).
  - `_CLAIM` also catches "<action> karti hoon" / "abhi karti hoon" (live 2026-11-07: "abhi set karti hoon" and no
    alarm was set); "yoga karti hoon", "baat karti hoon" stay chat (checked).
- **B2, noise:** `heard.foreign()` (moved from `live.foreign_words`, still importable there) now also catches German,
  French, more Spanish/Portuguese, and Korean/Japanese/Chinese/Cyrillic/Arabic/Thai script when it is most of the line;
  `heard.meaningful()` rejects foreign lines and strips other-script bits before the noise list ("나는, thank you."
  is noise). A real request with a misheard Korean start stays a request. The voice persona says: stay silent on
  other languages and noise.
  - Real check: over 551 distinct voice texts in the logs, 18 are now treated as foreign; all 18 are noise (none was a
    request). Honest limit: Gemini Live hears the audio itself, so it may still answer noise briefly; Chutku no longer
    acts on it, logs it as a turn, or keeps the conversation open for it.
- **B3, question tails:** typed replies have none (1 of 213 "?" endings, a real clarify), so no text filter was added;
  the voice persona now says to end with the result, and the scoreboard counts tails (`TAIL`): baseline 7 days 12,
  60 days 56, target 0.
- **Verification:** tests: `test_live_claims` (+4: turn tracking, "set karti hoon", persona rule for two identities),
  `test_heard` (+2: 14 real foreign lines rejected, 9 Hinglish look-alikes kept), `test_recall` (+1), `test_scoreboard`
  (+2). Full suite 1,812: 1 failure, the known `test_docs_truth` count (the owner's 10 untracked
  `chutku/apps/atlas/ui_*.json`). `check_phrases.py` 193/193. Scoreboard (7 days): B100 343.2, Daily 30 48/78 = 62%,
  promises 2 (both backed per `heard.jsonl`; old rows), tails 12.
- **Not yet live:** the running Chutku was started at 08:43 with the old code; the owner was using the PC (idle 35 s),
  so it was not restarted. The voice checks (a real "VLC kholo" turn logs `"task": true`; a Spanish line gets no
  task and no row) run after the next restart.
- **Slice C deferred, with evidence:** today's instant router sends 33 of the 51 real failures to the right tool with
  the name as said, and the night-shift fixes made after those failures already match the names live (Spotify 9/9
  incl. LowKey/lofi OCR, "Ato mera brave", "Open sport", WhatsApp 5/5). A new resolver would rewrite working matching;
  re-check with a week of new data.

### 2026-11-10 (33): Measure truthfully (plan "best assistant", slice A)
- **Owner's request:** read the whole codebase and say exactly how to make Chutku the best assistant, one that eases
  work and never adds it. The assessment and the slices are in the plan file; the aim in one line: *say it once, in
  any words, and it is done, fully, as fast as by hand, with no questions, and Chutku does the next sensible thing
  before you ask.*
- **What the last 7 days of real use showed** (228 owner turns, 207 by voice): 77 action requests, 30 unfinished
  (20 clarify, 6 failed, 4 cancelled); `mind.json` knows 2 people, so sends ask; names are matched exactly (Loki /
  Lowkey / lofi for one playlist); voice replies promise work with no tool behind them; mishearings in other
  languages get answered.
- **This slice** (`scripts/scoreboard.py`, `tests/test_scoreboard.py`):
  - **Promises with no action** (weight 5): a voice chat line that promises PC work with no task row in that
    conversation. Pairs promises with task rows per conversation, so a backed "VLC khol rahi hoon" is not counted.
    7 days: 2; 60 days: 12.
  - **The Daily 30**: `family(said, tools, status)` sorts each request into one of 27 everyday families (tool name
    first when the request finished; words otherwise, because an unfinished request lists only the steps that ran).
    Over the 51 real failures: music_play 13, whatsapp_open_chat 8, whatsapp_send 5, other 6 (noise transcripts).
    Headline: **7 days 47/77 = 61%**, 60 days 384/448 = 86%, target 99%.
  - **Latency logging was not broken:** `recall.log_session` has written `seconds` since commit `4520390` (01:18
    today); every owner turn in the window predates the 08:43 restart. Nothing to fix; it fills in from the next use.
- **Verification:** `tests.test_scoreboard` 4 tests OK (new: family naming incl. a cancelled play that only ran the
  launch step; a promise counts only when unbacked, "nahi set kar sakti" and offers ending in "?" do not count).
  Real run: `scripts/scoreboard.py` and `--days 60` print the two new sections (numbers above). Negative check:
  the first version mis-filed "read the last message ... on whatsapp" as a send and "play ... playlist" (cancelled
  after the launch) as open_app; both are now test cases.

### 2026-11-10 (32): A smaller codebase for AI agents (no behaviour change)
- **Owner's request:** "shrink it ... none of the features ... affected", because agents lose accuracy on a codebase
  this large.
- **What was measured first:** about 49k source lines, 27k test lines, 18k doc lines. vulture finds almost no dead code
  (3 items at 80% confidence), so the size is real features. The cost to an agent was the docs (this file alone was
  7,052 lines) and six files of 1,200–2,500 lines.
- **Step 1, docs:**
  - this file keeps the newest entries; older ones moved word for word to `docs/archive/STATUS_HISTORY.md`
    (128 + 6,931 lines = all 7,052 plus the pointer);
  - 8 finished plans moved to `docs/archive/` (HERMES, WORLD_CLASS, 4x WEB_CLAUDE_TASKS, TEAM_REVIEW, PROGRESS_LOG),
    links updated;
  - the out-of-date handoff banners in `AGENTS.md` were replaced by a pointer to the code map;
  - new `docs/CODEMAP.md` (`scripts/codemap.py`): one line per module from its docstring. The 22 modules without one
    got a one-line docstring. `tests/test_codemap.py` fails when a module is missing (negative case: removing
    `chat.py` from the map failed with `['chutku/chat.py'] != []`).
- **Step 2, shared helpers: not done.** Only 73 lines are byte-identical copies (`_validate_none`, `_root`, ...);
  sharing them would save ~40 lines and couple unrelated tool modules.
- **Step 3, dead code:** `know_me.brave_history_db` and `icon.PNG_PATH` removed (0 references). The other ~110
  vulture hits are reached by name (HTTP `_post_*` handlers, ctypes fields, library callbacks).
- **Step 4, big files split** (pure moves; every moved name is still importable from the old module):
  - `quick_intents.py` 2,178 -> 1,684: the reply builders (`QUICK_ANSWERS`, `_say_*`) are in `quick_answers.py`;
  - `remote/server.py` 1,234 -> 704: `PhoneHandler` mixes in `PhoneStreams` (`remote/streams.py`), `PhoneControl`
    (`remote/phone_control.py`) and `PhoneFiles` (`remote/phone_files.py`);
  - `dashboard.py` 2,479 -> 1,570: `DashboardServer` mixes in `DashboardVoice`, `DashboardPresence`, `DashboardWork`
    (`dashboard_voice/presence/work.py`); shared helpers are in `dashboard_helpers.py`.
  - How it stayed safe: a move tool (scratchpad, AST) refused any move where the moved code uses a name the tests
    patch, or needs a name that stays behind. The patched names came from the test source and from a suite run that
    logged every real `mock.patch` (264 module attributes); the real list was inside the static one.
  - Kept whole: `agent_loop.py` (the patched safety lists and the injection defence are used throughout; ~150 movable
    lines), `tools/everyday.py` and `tools/apps_extra.py` (most helpers are patched by the Windows/WhatsApp tests).
  - Safety boundaries kept: `voice_enroll` stayed in `dashboard.py` (the voiceprint privacy test names the files
    that may read it); Evolve's protected list now covers `chutku/dashboard*.py` (negative case: without it
    `protected("chutku/dashboard_voice.py")` is False), added to `tests/test_evolve_y2.py` and `docs/SECURITY.md`.
- **Size:** source lines went from 49,327 to 49,582 (+255: re-export lines, docstrings, imports), as expected for
  moves. Docs outside `docs/archive/` went from 18,094 to 9,163 lines; this file from 7,052 to ~150.
- **Verification:** full suite 1,803 tests: 1 failure, `test_docs_truth` (149 app actions in code, 144 in
  `docs/SECURITY.md`); it already failed on `d6a2a0b` before any change. `compileall` clean. Live: the split
  dashboard on a spare port with a temporary data folder served `/` (19,752 bytes), `/api/agent/latest`,
  `/api/presence`, `/api/setup`, `/api/automations` (200), refused a request without the token (403), and answered
  `POST /api/chat` "what time is it" with "It's Tuesday, 10 November 2026, 02:34 PM" (system clock 14:34) in 0.65 s.
  `scripts/check_phrases.py` 193/193. The persona exam's one wrong route ("google calendar kholo" -> web.search) is
  unchanged from before. Instant-router snapshot of 1,816 sentences
  (`chutku/apps/tasks.jsonl`, `scripts/check_phrases.py`, the task bank; times masked) is byte-identical to the
  baseline, and so is the manifest of all 416 registered tools.

### 2026-11-10 (31): Apps learnt by heart, the task table, the persona exam (App Mastery 2, steps 5–8)
- **Owner's requests:**
  - "practice over all the layouts dedicatedly: each button, what it does, how, forward, backward, undo";
  - "synthetic workflows of all possible tasks ... all types of personalities ... in a hash table for lookup";
  - "calculator se aage bhi toh badh".
- **App survey** (`scripts/app_survey.py`, no model):
  - It opens each app behind the owner's window, waits for it to settle (a splash window is replaced, a page fills
    in) and reads every element.
  - It visits each navigation item (tabs, list, tree and option items, after a "Navigation" opener) and records
    what each page adds, then checks that going back returns to the start.
  - `--probe`, **only while the owner is idle**, presses each remaining safe element, records what changed, undoes
    it (toggle again, collapse, the dialog's own Cancel or Close, or Back) and checks that the page came back.
  - RISKY names and a wider do-not-press list (save, print, sign in, Bluetooth, network, play, new, paste...) are
    never pressed.
  - Probing is limited to Calculator, Clock, Paint, Photos, Weather and Snipping Tool. The rest are map-only,
    because they restore or edit the owner's files, make sound, or change the real system.
- **Mapped live on this PC** (`data/apps/<app>/uimap.json`, local), pages each:

  | App | Pages |
  |---|---:|
  | Paint | 21 |
  | Explorer | 19 |
  | Calculator | 18 |
  | Settings | 12 |
  | Clock | 7 |
  | Photos | 7 |
  | Store | 6 |
  | Word | 4 |
  | Excel | 4 |
  | PowerPoint | 4 |
  | Snipping Tool | 3 |
  | Notepad | 3 |

  - **Only the reading lane works:** Weather, To Do, Sticky Notes, OneNote, Outlook and VS Code show UI Automation
    (almost) nothing, so for them Chutku has to read the screen.
  - **Not opened behind the owner's window:** Sound Recorder and Calendar.
- **Found by the survey:**
  - Calculator's navigation ignores UI Automation: the item gets selected, but the mode doesn't change. Its
    pages had no proof of opening, so no `do` actions were made for it. Its documented shortcuts (Alt+1–5) are now
    `chutku/apps/atlas/calculator.json` ("open scientific calculator").
  - Background launches failed for Paint and Explorer: `mspaint.exe` and `explorer.exe` didn't match the app name.
    Ownership now also matches a title ending in the name, or a distinctive word of the name inside the program name.
- **Atlas `do` step and `has_element` check** (`chutku/apps/atlas.py`, `runner.py`):
  - they press an element by name through UI Automation, behind the owner's window;
  - risky names are refused by the validator;
  - `launch: "behind"`;
  - an action made only of these steps runs in its app's own lane (`atlas.background_only`).
- **Map to actions:** `scripts/make_ui_atlases.py` turns each page with proof (an element only that page shows) into
  a safe navigation action with English and Hinglish phrases. These route instantly only after 3 Action Lab passes.
- **Task table** (`chutku/task_table.py`, `chutku/apps/tasks.jsonl` from `scripts/make_task_table.py`):
  - **Content:** 218 sentences from 78 workflows, for the personas genz 103, office 114, student 69, elder 59 and
    creator 16; in English, Hinglish and Hindi script. 183 of them have a ready plan.
  - **Lookup:** one dict lookup on the normalised sentence (`reflex.normalize`).
  - **Order:** it fills the gaps after the hand-written routes, which always win. The exception is a launch of an
    app the sentence never named ("start my work day" used to open Word).
  - An app action in it waits for the lab.
  - **Test:** every plan's tool exists and its arguments pass that tool's own validation.
- **Persona exam (offline)** (`scripts/persona_exam.py`, the instant router):
  - **Of 218 sentences:** 196 planned instantly, 3 answered directly, 19 left to the planner. Routing median 17 ms.
  - **Instant but wrong:** 22, then 1 after the fixes. Per persona: office 106/114 instant and right, genz 92/103,
    student 60/69, elder 56/59.
- **Real misroutes found by the exam and fixed:**
  1. "start my work day" opened **Word**: the fuzzy app match let "work day" be Word. A misheard name has no extra
     words now.
  2. "gmail kholo" / "mera email kholo" opened the **Windows Mail app**; it now opens Gmail.
  3. "awaaz band karo" **closed an app named "awaaz"**; it now mutes.
  - "Open sport" → Spotify and "Ato mera brave" → Brave still work (tests).
- **Left over:** "google calendar kholo" becomes a web search.
- **Tests:** `test_app_survey` (3: the do-not-press list, proof-of-page), `test_task_table` (5), `test_app_atlas`
  +4. Affected suites: 140 OK.
- **Not yet:**
  - the Action Lab on the generated actions and the probe run, both waiting for the owner to be idle;
  - the live persona exam (`--live`, owner away).

### 2026-11-10 (30): WhatsApp Locked chats: Chutku opens them, the owner types his code (20x plan P1 open item)
- **Owner's request:** "Locked chat open krna jo bola usko dhang se search krna brain ka istemaal krke".
- **Flow** (`chutku/tools/apps_extra.py`):
  - When search finds no chat (or the mind marks the person `whatsapp_locked`), Chutku clicks the Locked-chats rail
    icon. Its spot is measured: screen (44, 484) at 125% with the window maximized, 388 logical px below the window's
    top.
  - It then waits up to 60 s, with a toast "Locked chats ka code daal do, main wait kar rahi hoon".
  - **It never types into the code box and never presses its button.** The list counts as unlocked only when no
    code box shows over it.
  - Already inside an unlocked Locked chats list, it looks there first.
- **Finding the chat** (`pick_chat_row`), in this order:
  1. the exact name (spaces and punctuation ignored);
  2. a unique first name;
  3. the one clearly closest name ("kitkatt" finds KitKat);
  4. only then the cloud model, given the visible **names only** (never a message). Its answer counts only when it
     is one of those names.
- **After it is found:** the header is confirmed, the person is remembered as locked (plus the misheard alias), and
  the send is checked as before.
- **Tests** (`tests/test_locked_chats.py`, 12):
  - the safety negatives: any typed key or text fails the test; the code box is closed by Esc only on a timeout or
    a misplaced click; a list still behind the code box isn't taken as unlocked;
  - a cancel stops cleanly; a missing chat is never guessed; the model's answer is checked.
  - WhatsApp suites: 48 OK.
- **Bug found by the tests and fixed:** a model answer that wasn't in the list crashed the pick (`StopIteration`).
- **Not live-verified yet:** it needs the owner present to type the secret code. Dry run:
  `chutku.cli tool message.open_chat` with a locked chat's name.
- **Docs:**
  - `docs/OWNER_GUIDE.md` (WhatsApp chats);
  - the `message.send` description (shortened, so the local model's cached prompt stays under 14,000 characters).

Older entries (2026-09-22 to 2026-11-10 (29)) are in [docs/archive/STATUS_HISTORY.md](docs/archive/STATUS_HISTORY.md).
Read them only when a task needs that history.

## Update protocol

For every change, update **Last updated**, add a row under **Delivered** (or revise the relevant phase row), and record a concrete verification artifact. Never mark a feature complete solely because code was generated.
