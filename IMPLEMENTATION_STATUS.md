# Chutku Implementation Status

**Last updated:** 2026-11-10
**Source of truth for scope:** [docs/DESIGN.md](docs/DESIGN.md)

This file is the implementation ledger. Update it in the same change as every code, configuration, benchmark, or documentation change. A checked item means it exists and has been verified to the stated degree; it does not imply a broader roadmap phase is complete.

## Current focus

2026-09-30: Chutku's main path is now a chat/voice agent. A goal goes through the
deterministic everyday router or the GPU local planner, runs as observe → plan → act →
verify rounds bounded by a per-request autonomy level, and every step still passes
grants, policy and independent verification. Stages 1–4 are accepted on the final source.
Stage 5 still needs the owner's consented live microphone run and 200 human trials.
Owner decisions are in `docs/DESIGN.md` §51.

## Delivered

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
- **Verification:** full suite 1,803 tests: 1 failure, `test_docs_truth` (149 app actions in code, 144 in
  `docs/SECURITY.md`); it already failed on `d6a2a0b` before any change. Instant-router snapshot of 1,816 sentences
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
