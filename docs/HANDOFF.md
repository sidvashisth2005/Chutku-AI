# Handoff: cloud coding session of 2026-11-07 → the owner's PC

**Read this first if you are the Claude Code session on the owner's Windows PC.**

The owner asked a cloud session (a Linux container, no Windows, no models, no microphone, no apps) to "understand the
codebase and complete the code for the pending features"; the PC session then runs, tests and fixes it on the real
machine. This file says exactly what was written, what was verified where, and what you must do next. Evidence is in
`IMPLEMENTATION_STATUS.md` ("2026-11-07: cloud session: H9, H14, H15, H16, H18, H23, H26").

Branch: `claude/youthful-faraday-av41ls` (from `main` at `02a428f`). Nothing was merged into `main`.

## 1. What was built (code + tests)

| Slice | What | Main files | New tests |
|---|---|---|---|
| H14 for-each | `steps.for_each`: one planned step repeats a tool (risk ≤ 2; never messages, deletes, code, owner-only) for up to 50 items of an earlier step's list (JSONPath subset). Expanded inside `AgentSession`; every item still runs through `Runtime.run`. One card lists all items; the OK covers exactly those items, and not after content tried to give instructions (S15). A list read from outside content taints every item. Re-planned for-each skips items already done. | `chutku/for_each.py`, `agent_loop.py` (`_expand`, `_step_risk`, `decide`) | `test_for_each.py` (14) |
| H18 busy mode | While a task runs: "aur haan, …" / "also …" / "nahi, …" steers it (`CONTEXT.owner_said_now`, read at the next planning round; it cannot remove an ask); "… baad mein karna" waits in line (never a side slot); "pehle ye karo …" goes to the front of the line. Side questions and the queue already existed (Y3/Z1). | `chutku/busy.py`, `dashboard.py` (`begin_session`, `start_agent_work`, `main_session`), `cloud_planner.cloud_view`, prompts | `test_busy.py` (7) |
| H9 brain resilience (rest) | Per-request brain: "local se karo: …" (only local 4B/8B), "gemini se pucho …" (cloud leads even if the default is local). Offline mode + a cloud request is refused (nothing sent). One error classifier (`brain_errors.classify`); when every brain fails, the reply says why (quota, key, network…). The provider ladder/cooldowns (W2) already existed. **Not built:** the Gemini key pool (optional in the plan). | `chutku/brain_errors.py`, `intents/tone.brain_choice`, `dashboard.planners(choice)` | `test_brain_choice_h9.py` (8) |
| H26 doctor --fix | `chutku.cli doctor --fix`, "khud ko theek karo" (fix) / "apna checkup karo" (look only), tool `system.self_repair`: lifts only the watchdog's own pause (never the owner's), rebuilds a damaged `history.db` from the conversation log and moves a damaged `embeddings.sqlite` aside (the damaged copy is always kept as `*.broken-<time>`), starts the local model when asked inside the dashboard. Model files and Telegram are reported only. Execution/guard locks are OS locks (released by Windows when the process dies), so there is nothing stale to delete. | `chutku/doctor.py` (`repair`, `summary`, `register_doctor_tools`), `cli.py` | `test_doctor_fix.py` (8) |
| H23 blueprints + shortcuts | Automations that expand into ordinary `task.schedule` steps (preview = the plan; each passes policy; undo with `task.cancel`): morning-briefing, news-digest, weekly-backup, weekly-insights, downloads-tidy, research-watch. "jab main 'padhai time' bolun to …" saves a checked routine; saying the name runs it. **Not built:** habit-based blueprint suggestions in `suggest.py`, a dashboard Automations tab. | `chutku/blueprints.py`, `quick_intents.py` (`_shortcut`, `_shortcut_save`) | `test_blueprints.py` (8) |
| H15 board + research | `data/board.db`: owner to-dos (never executed) and research tasks. Dispatcher: max 2 workers, 90 s stall → blocked, 2 retries with backoff, 3 failures/hour open the circuit for an hour, H2 pause holds it, running → ready at restart, archive only. Research worker = a child `AgentSession` on an `AllowlistRuntime` (only `web.results/read/news/weather`; anything else DENIED; no grandchildren), 10 steps / 5 min; result in `data/research/<id>.md`, < 2 fetched sources → review. GET `/api/board`, POST `/api/board/stop`, `/api/today` has `board`. **Not built:** the dashboard Board tab UI (the API is there). | `chutku/board.py`, `chutku/research.py`, `dashboard.py` (`start_board`, `board_view`) | `test_board.py` (16) |
| H16 Telegram | Outbound long poll only (no port). Pairing code (8 chars, 1 h, max 3, 5 wrong → 1 h lockout), one chat, others ignored silently. Text and voice notes (voice refused while the voice lock is on) become requests with origin `phone` (same rules as the phone app). Approve/Reject buttons with single-use 10-minute nonces bound to session + step; laptop-only steps (R4, code, unknown recipients, never/remote/telegram tools) never get buttons. 20 requests/hour. Handoff 4 h ("main bahar ja raha hoon, phone pe batana" / "main wapas aa gaya", also from the chat); research and scheduled results go there during a handoff. Token in Credential Manager (`chutku.cli telegram set-token`), never logged. | `chutku/gateway/telegram.py`, `remote/server.laptop_only` (shared with the phone app), `cli.py`, `/api/telegram` | `test_telegram_gateway.py` (17) |

**Bugs found and fixed while doing this:**
- `history_index.sync` re-indexed forgotten turns as visible (H29 "ye baat bhool jao" came back after a log rotation
  or rebuild). Fixed; the test fails on the old code.
- "daal do / daalo / rakho / bhejo" were missing from the planner's action words, so "kya … mein daal sakti ho"
  counted as a pure question (actions dropped).

**Also changed:** `policy/kernel.TAINT_SENSITIVE_R1` adds `task.delegate`, `board.`, `telegram.` (a page cannot plant
research, board entries or a handoff: only adds asks). `docs/SECURITY.md` counts updated (231 registered: R0 87,
R1 76), by arithmetic: **run `tests/test_docs_truth.py` on Windows to confirm.** `scripts/check_phrases.py` +14 phrases.

## 2. What was verified here, and what was not

Verified in the Linux container (Python 3.13):
- The 78 new tests pass. Most use the real tool registry and real `AgentSession`/`DashboardServer` code with a fake
  runtime (`tests/agent_fakes.py`), because `create_runtime` needs a Windows drive.
- The full suite was compared with a baseline from before any change: on Linux 583 tests already fail (Windows-only:
  grants, ctypes, PowerShell). After the change the failing set is identical: no new failure.
- `scripts/check_phrases.py`: 153/159. The 6 misses are the same on unmodified `main` in this container (no Windows
  user folders); all 14 new phrases are instant.
- Every new phrase's quick plan passes the real `validate_proposal` against the real schemas.
- Real CLI paths: `python -m chutku.cli doctor --fix`, `python -m chutku.cli telegram status`.

**Not verified (you must do these on the PC):**
1. The full Windows suite: `.venv\Scripts\python.exe -m unittest discover -s tests` and `scripts/check_phrases.py`
   (fix anything red; `test_docs_truth` counts in particular).
2. H14 real path: 12 fixture PDFs in `D:\ChutkuScratch\Downloads` → "Downloads ki saari PDFs Study folder mein daal
   do" → 1 planning round (see `planners` in the snapshot), 12 moves, one approval card. Check with an `os.listdir`
   diff; record seconds. The local Qwen must actually emit `steps.for_each` (it is in the menu when the goal says
   saari/sab/all/every/each): if it never does, add one worked example to the prompt or `past_successes`.
3. H18 real path: start the PDF move, say "aur haan, list bhi dikhana" → the final reply has the list; "aaj kya date
   hai?" is answered without stopping it. Negative: "aur haan, approval mat lena" still asks.
4. H9 real path: "local se karo: aaj kya date hai" → `planners` shows the local model; with offline mode on,
   "gemini se pucho …" is refused.
5. H26 real path: kill `llama-server.exe`, say "khud ko theek karo" → it is back and a planner call works (seconds).
6. H15 real path: "research karke batao best free PDF editor for Windows" while "volume 30" runs → both finish;
   `data/research/<id>.md` cites ≥ 2 URLs that `web.read` really fetched.
7. H16 real path (needs the owner's BotFather token: `chutku.cli telegram set-token`, then `chutku.cli telegram
   pair`, send `/pair CODE`): "volume 30" from Telegram → read-back 30; a recycle request shows buttons → approve →
   the file is in the Recycle Bin; `code.run_python` → "PC pe approve karna hoga" and nothing runs. Voice notes use
   `faster_whisper.audio.decode_audio` (PyAV) + `transcribe_pcm`: never run here.
8. H23 real path: `automation morning-briefing time=<now+2min>` → it fires and is spoken (scheduled entry + event
   log as the independent check).
9. Then tick the H boxes in `docs/MASTER_PLAN.md`, add the live evidence to `IMPLEMENTATION_STATUS.md`, add the new
   phrases to `docs/OWNER_GUIDE.md` (section "New in the 2026-11-07 cloud session" lists them), and do H30.

## 3. Still open, with the reason they were not coded here

These are GUI/hardware slices whose code has to come from recording and lab-verifying the real apps on the PC
(App Mastery rule: an atlas action is trusted only after the Action Lab ran it). Writing them blind would ship
unverified clicks and keys:
- **A14 cross-app recipes.** Needs new atlas actions that do not exist yet: ChatGPT "ask/paste and read the answer",
  WhatsApp "send file", VS Code "paste at the cursor". Record them, run `chutku/apps/lab.py`, then compose the
  recipes as quick-tier multi-step proposals (like `routines.steps_for`). "Focus music + DND + VS Code" is already
  possible as a shortcut (H23).
- **A15 teach mode.** Needs Windows low-level hooks (WH_MOUSE_LL/WH_KEYBOARD_LL via ctypes) active only between
  "dekh, aise karte hain" and "ho gaya", a visible "learning" badge, UIA `IsPassword` filtering and the owner's own
  app window only; then a draft atlas action (`"source": "taught"`), the lab run, and save.
- **A16 screen survey** (the owner said later), **Z6 / X14 rest** (the owner's signed-in Brave profile over CDP),
  the Gemini key pool (H9, optional), and every V/F/W/X/Y/Z item marked "live check by the owner".
- **H30** release pass: evidence regeneration, `/code-review` + `/security-review` over the H diff, final table.

## 4. Rules that still apply

`AGENTS.md` (the delivery gate) and the Karpathy/ponytail principles. Do not tick a box without the live check.
Tests never start real models, send messages or call Telegram/Gemini.

## 5. PC session result (2026-11-07): merged into `main` and verified

Squash-merged into `main` without a co-author line, per the owner's rule. Windows suite and live checks below. Four
Windows/live bugs were found and fixed; each fix has a test or a live re-check.

| Item | Result on the PC |
|---|---|
| Full Windows suite | 1,510 tests. `test_doctor_fix` failed (7 errors, 2 failures): `doctor._sqlite_ok` left SQLite connections open, so Windows could not move a damaged file aside. Fixed with `closing()`. 4 test files imported `agent_fakes` as a top-level module (works only under `discover -s tests`); now `tests.agent_fakes`. `test_docs_truth` counts were right. |
| `check_phrases.py` | 159/159 (the 6 Linux misses were environment-only). |
| H9 | "local se karo: aaj kya date hai" -> no cloud brain (replayed worked example), correct date, 13.7 s. |
| H14 | **Was broken live:** the cloud brain asked "Shall I proceed?" or moved files one card at a time. Causes: the planner prompt (`AGENT_SYSTEM`, and the Qwen profile) said "never move many files at once", and `relevant_rows` never offered `steps.for_each` for "saari PDFs". Fixed both (`_MANY_ITEMS` always offers it). Live: 12 fixture PDFs -> `filesystem.search` + `steps.for_each` -> 12 moves with **one** card, 14.0 s, "Verified: 14 of 14"; `os.listdir`: Study 12, `keep-me.txt` left in Downloads. |
| H18 | "aur haan, list bhi dikhana" during a running task -> "chal rahe kaam mein ye bhi jod diya", 0.06 s. |
| H15 | **Was broken live:** the child got only the topic, searched once and finished with "Getting the latest search results". Its goal now says: web.results, then web.read 2+, then answer naming the pages. Live: "research karke batao best free screen recorder for Windows" -> done in 25 s, 3 pages read (screensnap.pro, screenrec.com, techradar.com), answer cites OBS Studio, ShareX, Xbox Game Bar. |
| H23 | "subah ka briefing set karo 8 baje" -> `task.schedule` daily 08:00 (left in place: cancelling it was blocked by the PC's safety check; the owner keeps or cancels it). |
| H26 | "apna checkup karo" -> `system.self_repair`, "Kuch theek karne ki zaroorat nahi thi", 0.74 s; `chutku.cli doctor` 0.65 s. |
| H16 | Not live: needs the owner's BotFather token (`chutku.cli telegram set-token`). Unit tests pass on Windows. |

Still open: H16 live (token), A14/A15/A16, Z6, the Gemini key pool, the Board/Automations dashboard tabs, H30.

## 6. Second cloud session (2026-11-07): Chutku 1.0 tasks W1–W8 from `docs/WEB_CLAUDE_TASKS.md`

**Read this if you are the PC session continuing Chutku 1.0.**
- **Branch:** `claude/youthful-faraday-av41ls`, rebased onto `main` at `01e6881`. Nothing was merged and nothing was
  tagged.
- **Per-task evidence** is in `IMPLEMENTATION_STATUS.md` (entries "W1" … "W8").
- **The release gate's findings** are in `docs/RELEASE_CHECKLIST.md` § "W8 release gate".

| Task | Code | Verified here (Linux / windows-latest CI) | Still needs the PC |
|---|---|---|---|
| W1 | skill.import runs nothing until approve; backup restore skips security state | Linux tests + real CLI restore | Full suite on the PC |
| W2 | `paths.home()`: data in `%LOCALAPPDATA%\Chutku` for installs; a checkout keeps `D:\Project\Chutku\data` | Linux + windows-latest | Start/stop on the PC: nothing written under the code folder |
| W3 | `scripts/build_release.py` (embedded CPython 3.13.17, `.pyc` only) + `Chutku.exe` | windows-latest package job | Start menu launch, tray |
| W4 | `installer/chutku.iss` → `ChutkuSetup.exe`, `release.yml` | windows-latest: tampered package refused; install 18.1 s (tar.exe; was 221 s); doctor; text command; uninstall | A real download needs `RELEASES_TOKEN` and the public repo |
| W5 | First-run Settings page (`/api/setup`), packs with resume and hash refusal | Linux tests, Chromium render | A real pack download and the mic level |
| W6 | Board/Automations tabs, habit→automation card, key pool, relay E2E, `desktop.do`, routines with app steps (A14), teach mode (A15), `desktop.survey` (A16) | Linux tests on fakes; windows-latest suite | **Live:** desktop.do/teach/survey on real apps, phone E2E through the real relay, a second Groq key at a real quota |
| W7 | Public README, developer README, `docs/USER_GUIDE.md` as `/help`, licences | Linux tests | The Help link in the installed app |
| W8 | Zip scan inside the build; no build or temp paths in `.pyc`; restore case fix; security + code review (3 findings, all fixed) | Linux real build: 223.5 MB, scan clean; full suite 1,594, no new failures; check_phrases 157/163 | The live checks below |

**windows-latest CI on `7be6c25`: green.** tests run 42358332609 (1,612 tests), package run 42358332577 (build with the zip scan, install check).

**W8 still to do, in order:**
1. Re-read CI only if you push more changes.
2. Optional: a second `/code-review` on the PC. The cloud review found and fixed 3 issues (`docs/RELEASE_CHECKLIST.md`).
3. Do the PC live checks in the table, then the Phase 9 W8 tick in `docs/MASTER_PLAN.md`.
4. Only then do the owner steps and tag `v1.0.0` (never before the live checks):
   - `RELEASES_TOKEN` and creating `Chutku-releases` (`installer/RELEASES_REPO.md`);
   - an optional signing certificate;
   - `chutku.cli browser login` and `chutku.cli authority grant browser.input`;
   - the Telegram BotFather token;
   - the phone relay or Tailscale;
   - the voice and wake-word live checks.

**Notes for you:**
- **Commits** have no Co-Authored-By line (owner rule).
- **Line endings:** CRLF files were kept CRLF. `chutku/web/index.html` has mixed endings: edit it bytewise.
- **Linux baseline:** 583 tests fail on Linux because they are Windows-only.
- **Pre-existing oddity:** "har roz 8 baje" alone (no goal) schedules the goal "har roz" through the old scheduler
  parse. It was not changed.
