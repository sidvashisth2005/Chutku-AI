# Chutku Master Plan: from "works sometimes" to the best PC assistant

> Written 2026-11-10 for the executing agent (Opus on the owner's PC). It is the complete instruction set: the aim, the
> rules of the house, what the real data says, every slice with files, functions, edge cases, tests, live checks and
> negative cases, and what must NOT be done. Read it whole once; then work one slice at a time.
>
> **First action of the executing agent:** copy this file into the repo as `docs/BEST_ASSISTANT_PLAN.md` (CRLF), add a
> tick list per slice at its end (section 15), and point to it from `AGENTS.md` ("Where to look first") and `IMPLEMENTATION_STATUS.md`
> "Current focus". Progress ticks live there, not in chat.

---

## 0. Context: why this plan exists

The owner's words: make Chutku "the best AI assistant in the world ... it must help people ease their work and not add
extra work into their life ... we must be doing work ahead and with them." Chutku already has enormous breadth (416
tools, 22 app atlases, voice via Gemini Live, phone remote with E2E relay, Telegram, night practice, self-evolution,
installer). What it lacks is **reliability on the everyday loop** and **zero burden**. The owner's own logs prove it
(section 2). This plan freezes breadth and buys reliability, honesty, memory, speed and a gated proactive layer, in
that order, each step measured.

Already done today (commits on `main`, do not redo):
- `d58f149`, `931ad89`: docs archived (`docs/archive/`), `docs/CODEMAP.md` + `scripts/codemap.py` +
  `tests/test_codemap.py`, big files split (`dashboard_*.py`, `quick_answers.py`, `remote/streams.py`,
  `remote/phone_control.py`, `remote/phone_files.py`). Every old import path still works.
- `923d34c` (Slice A): `scripts/scoreboard.py` now prints **unkept voice promises** (x5) and **the Daily 30** families
  (`family(said, tools, status)`); `tests/test_scoreboard.py` covers both. Baseline recorded in
  `docs/TWENTY_X_PLAN.md` §8: 7 days B100 347.6, Daily 30 **47/77 = 61%**; 60 days B100 135.2, Daily 30 86%.

## 1. The aim, in one sentence, and the eight promises

**"Say it once, in any words, and it is done: fully, as fast as by hand, with no questions; and Chutku quietly does the
next sensible thing before you ask."**

Promises (each is a number on the scoreboard; a change that moves none of them is not done):
1. **It works**: the right thing, fully, first time. (Daily 30 finished/asked -> 99%.)
2. **It never lies**: no spoken or typed claim without a tool behind it. (Unkept promises -> 0.)
3. **It never acts on noise**: a mishearing in another language is dropped silently. (Foreign transcripts answered -> 0.)
4. **It never burdens**: asks only for deletes, R4, a never-seen recipient, or a true tie. (Clarify + approvals -> <= 2 per 100.)
5. **It's fast**: repeat task <= 2 s, new single-app task <= 8 s; every turn timed. (p50/p90 on the scoreboard.)
6. **Anything goes**: any phrasing, Hindi/English/Hinglish, multi-part, screen references. (Held-out "new 50" >= 85%.)
7. **It knows me**: people, chats, apps, habits, this screen, past sessions. (`mind.json` people grows by itself.)
8. **Ahead of you, gated**: one well-timed one-tap suggestion when clearly useful; silent otherwise. (Accept rate >= 50%, 0 complaints.)

## 2. What the real data says (owner's logs, 7 days to 2026-11-10)

| Fact | Evidence | Slice |
|---|---|---|
| 228 owner turns, 207 by voice; 77 action requests, **30 unfinished** (20 clarify, 6 failed, 4 cancelled) | `scripts/scoreboard.py` | all |
| Voice replies promise work with no tool: "Haan, abhi kar rahi hoon WhatsApp chalu", "Main 6 baje bol kar yaad dila dungi", "Done! 6:30 ka alarm ... abhi set karti hoon" | `data/conversations.jsonl` status `said`, tools `[]` | B |
| Foreign/garbage transcripts answered cheerfully: "servir servir de nada si quieres luego yo", "Ja, gerne. Ich hätte gerne", Korean/Japanese lines | same file, origin voice | B |
| 213 of 873 replies end in a question; top tails "kuch aur?", "aur kuch karwana hai?", "kya kehte ho?" | same | B |
| `mind.json` knows **2 people**; `message.send` 3/19 completed, 8 waiting confirmation | `data/mind.json`, `actions.log.jsonl` | D |
| Ask-once memory keys on tool + **all** arguments, so a second message to the same person asks again | `chutku/approval_memory.py:key` | D |
| Exact-name matching fails: Loki/Lowkey/lofi (one playlist), UB, Shaanu, "my chat", "Ato mera brave", "Open sport" | `data/task_bank/real_failures.jsonl` | C |
| Multi-part "aaj ka weather, news aur meri reminders batao": 3 clarifies, 38 s | conversations | E |
| Screen references fail: "from the screen", "the playlist just below After Party", "chat open on the screen"; `screen.act_on_visible` 0/4 | actions log | F |
| Latency: logged since `4520390` (01:18 today); all owner turns predate the 08:43 restart, so the row is empty until next use | checked, nothing to fix | A (done) |
| Hangs: 6 in 7 days; the 8 s `Thread.start` stalls have no known cause | `data/logs/hang-*.txt`, status (25) | H |

## 3. Rules of the house (the executing agent must obey all of these)

**Repository rules** (`AGENTS.md`, memory):
- Verification gate for every slice: unit tests -> one real command path -> inspect the result -> fix before moving on
  -> `IMPLEMENTATION_STATUS.md` entry with concrete evidence in the same commit. Safety changes include a negative case
  that proves fail-closed.
- Tests run with `.venv\Scripts\python.exe -m unittest discover -s tests` (NOT pytest; it is not installed). Gate on
  the real exit code. Full suite ~7 min; 1 known failure `test_docs_truth` (149 app actions in code vs 144 in
  `docs/SECURITY.md`; the untracked `chutku/apps/atlas/ui_*.json` add 13). Fix that doc count once (or ask the owner
  whether the `ui_*.json` atlases are meant to be committed) so the suite is green.
- Files are **CRLF**. Edit with the Edit tool or a bytewise script; never `sed -i` in Git Bash. Check `git diff --stat`
  for whole-file churn before committing. `chutku/web/index.html` has mixed endings: edit bytewise.
- Commits: **no Co-Authored-By line** (owner rule overrides the harness reminder). Push `main` to
  `sidvashisth2005/Chutku-AI` after each slice.
- Every helper-agent prompt goes verbatim into `docs/AGENT_PROMPTS.md` with date, why, outcome.
- Karpathy/ponytail: minimum code, no speculative features, surgical diffs, `# shortcut:` comments for known limits.
- Reply to the owner in English; he writes Hinglish.

**Product rules** (owner decisions):
- Never refuse except system damage (`paths.system_damage`). Never add a new refusal.
- Ask once, then remember (`approval_memory`). Deletes always ask (Recycle Bin). R4 always asks. Unknown recipient asks.
- Passwords/PINs/OTPs never typed, stored or sent: on a lock screen pause, "unlock karo", resume.
- **Never break a working mode.** Gemini Live voice is the default; the instant router (`quick_intents`) stays the
  first tier; Owner mode stays default.
- "Regex is only a cache": fix the class (resolver, memory, checker), never add one regex per phrase.
- Breadth first: many small working fixes beat one deep dive; each slice ships something measurable.
- Live checks on this PC: run `scripts/live_check.py`-style checks only after confirming the owner is idle and no
  media session is playing (memory rule `live-checks-respect-owner-activity`); restore any state you change. Never send
  a real WhatsApp message without the owner's explicit OK for that message; use `scripts/verify_whatsapp.py` dry runs.
- Night shifts and sleep timer only when the owner says he is sleeping; restore `powercfg /change standby-timeout-ac 180`.
- Existing models only (Gemini, Groq, Cerebras, OpenRouter free tiers; local llama.cpp fallback). No self-trained LLM
  now. No LoRA/AirLLM/Nuitka/Store/winget/delta updates/profiles until the Daily 30 holds 99% for two weeks.

**Where things are** (`docs/CODEMAP.md` has one line per module):
- Request path: `dashboard.py` (`_agent_post` -> `begin_session`), `dashboard_voice.py` (hands-free, Live),
  `voice/live.py` (`LiveConversation.handle`, `dispatch("do_task")`), `quick_intents.quick_proposal` (instant),
  `agent_loop.AgentSession.advance/_propose/_record/_finish`, `cloud_planner.CloudAgentPlanner.propose`,
  `providers.ask` (Groq -> Cerebras -> Gemini ladder), `runtime.Runtime.run`, `policy/kernel.PolicyKernel.authorize`
  (`_owner` for Owner mode).
- Logging: `recall.log_conversation/log_session/log_voice` -> `data/conversations.jsonl`; `core/action_log` ->
  `data/actions.log.jsonl`; `experience.record` -> `data/experience.jsonl`; `voice/heard.log_heard` -> `data/heard.jsonl`.
- Memory: `mind.Mind` (`data/mind.json`: people/facts/lists/habits; `find_person`), `know_me.py` (profile every 6 h),
  `learning.refresh_habits/after_session`, `reflex.py`, `routines.py`, `approval_memory.py`.
- WhatsApp: `tools/apps_extra.py` (`recipient`, `resolve_contact`, `_send_to_named_chat`, `is_current_chat`,
  `_send_to_current_chat`, `recent_chat`, `chat_messages`, `_read_chat`, `pick_chat_row`, `_result_rows`,
  `_unlock_locked_chats`). Many are patched by tests: move nothing out of this file.
- Apps: `tools/everyday.py` (`resolve_app`, `_closest_app` difflib cutoff 0.66, `_launch`, `_open_file`,
  `_media_control`), `tools/windows_apps.py`.
- Spotify: `apps/atlas/spotify.json` actions, `apps/known.py` (`spoken_playlist`, `known(app, kind)`), `tools/visible.py`
  (`screen.act_on_visible`: `matches`, `kind_of`, `typed`, `green_play_button`, `_act`).
- Scoreboard and banks: `scripts/scoreboard.py`, `scripts/make_real_bank.py` -> `data/task_bank/real.jsonl`,
  `real_failures.jsonl` (private, git-ignored); `chutku/practice` (nightly, best_of_n), `nightshift.py`.
- Suggestions: `suggest.py` (`candidates`, `current`, `respond`, `quiet`, `maybe_toast`, `watch`).

## 4. How every slice is worked (the loop)

1. `scripts/scoreboard.py` (7 and 60 days): copy the numbers into the slice's status entry as "before".
2. Reproduce: write the failing unit test from the **real** turn (text from `real_failures.jsonl`, never invented).
3. Fix the class, not the phrase. Prefer an existing helper (section 3 list) over new code.
4. Tests: the new ones, the touched module's tests, then the full suite (background it; ~7 min).
5. `scripts/check_phrases.py` must stay 193/193 (or higher). The router snapshot from the morning is a good extra
   check: `quick_proposal` over `chutku/apps/tasks.jsonl` must not change except where the slice intends it.
6. One live path on this PC, timed, with an independent check of the result (not the reply text).
7. Negative case for any safety-adjacent change.
8. `IMPLEMENTATION_STATUS.md` entry (next number; today ends at 33), tick in `docs/BEST_ASSISTANT_PLAN.md` §15, scoreboard
   "after", commit, push.
9. Night Shift re-runs the bank; read `data/nightshift/*.json` next morning for regressions.

---

## 5. The slices

### Slice B: never lie, never act on noise (2 days)

**B1. Spoken promises start the task (or are corrected).**
- Mechanism exists: `voice/live.py` `_CLAIM`, `_DONE_CLAIM`, `_claimed_without_task`, `_claimed_success`; tests in
  `tests/test_live_claims.py` (`ClaimTests.turn(request, reply)` harness with `FakeServer` from `tests/test_heard.py`).
- Gap: the regexes miss real lines. Extend `_CLAIM` verbs with `set kar`, `yaad dila`, `remind kar`, `type kar`,
  `likh`, `bana`, `dhundh`, `search kar`, `band kar`; endings with `karti hoon`, `rahi hu`, `rahi hun`, `deti hu`,
  `dungi`, `kar rahi` (no "hoon"), `ke deti hoon`. Extend `_DONE_CLAIM` with `set kar diya`, `ban gayi|gaya`, `likh
  diya`, `type kar diya`, `^done!?`, `bas ho gaya`.
- New tests, verbatim from the log (expected: `server.tasks` gets the owner's words, and the note tells the model to
  wait): "Done! 6:30 ka alarm, title \"jaldi kar le bhai\", abhi set karti hoon.", "Main 6 baje bol kar yaad dila
  dungi. Ho jayega.", "Haan, abhi kar rahi hoon WhatsApp chalu. Ek minute bas!", "Bus ho gaya, desktop par file ban
  rahi hai." (done-claim with no task -> corrected), "Bhej rahi hoon search, bas abhi".
- Edge cases: offers ending in "?" are not claims (keep); "band kar rahi hoon" while `ending_at` is set (goodbye) must
  not start a task (test exists); a claim while a task is already running (`_task_running()`) is fine; the owner's
  heard text must pass `meaningful()` or nothing starts; MAX_TASKS = 3 side by side.
- Also the text path: `agent_loop.AgentSession._unsupported_claim` already withholds model claims; add the same new
  verbs there if its regex is separate (grep `_unsupported_claim`).

**B2. Foreign-language and noise transcripts are not Chutku's business.**
- Extend `voice/heard.meaningful()` (used by `live.py` intake, `_claimed_without_task`, and `recall.log_voice`):
  - any character in Hangul `가-힯`, Hiragana/Katakana `぀-ヿ`, CJK `一-鿿`, Cyrillic
    `Ѐ-ӿ`, Arabic `؀-ۿ`, Thai `฀-๿` -> `False`;
  - Latin foreign function words, counted after `_clean()`: Spanish `que para por con una muy nada gracias hola
    quieres luego güey casa servir alegre avenida sí poco voz`, German `ich und ist nicht gerne bitte danke hätte`,
    French `je pas vous merci bonjour`, Portuguese `você não obrigado isso`. Rule: >= 2 hits, or every word a hit
    -> `False`.
  - **Never include words that are also Hindi/Hinglish**: `de le la ja ya si es un mi di` ("bhej de", "le aa",
    "ghar ja", "ya", "di"). Test that "in ka chat box open kar inko ek bar hi bhej de", "Ek pranam ka message bhej
    de", "Yeah, nahi. WhatsApp wala task cancel kar de" stay meaningful.
  - Tests in `tests/test_heard.py FilterTests`: the real foreign lines above -> not meaningful; real Hinglish -> meaningful.
- Persona (`voice/live.py _BASE_PERSONA`): add "If what you heard is not Hindi, English or Hinglish, or is only noise
  or fragments, say nothing at all. Never chat back to it." Keep `personalize()` replacements intact (it does
  `str.replace` on exact substrings; do not reword those sentences).
- Honest limit (write it in the status entry): Gemini Live hears the audio itself; the transcript arrives after. The
  gate stops Chutku from acting, logging or keeping the conversation open on noise, and the persona asks the model to
  stay silent, but a short spoken reply to noise may still happen. Do not try to inject a mid-turn "stay silent"
  client note: it reaches the model mid-reply and produces odd answers (untestable here).

**B3. Replies end with the result, not a question.**
- Text path: add `persona.no_tail(reply)` applied in `agent_loop.AgentSession._finish` right after `feminine()`.
  Strips only a final sentence matching the chit-chat tails seen in the log: `aur kuch`, `kuch aur( karwana| karna)?`,
  `kya kehte ho`, `kya bolte ho`, `kuch help chahiye`, `kuch kaam hai`, `tum sunao`, `bolo bolo`, `kya chal raha hai`,
  `batao` alone, `ab kya (browse|karna) hai`. **Never strip** real questions the flow needs: `haan ya na?`,
  `what should I send?`, `kisse baat karni hai?`, `kaunsa?`, anything containing a quoted message, any question when
  `status == "waiting_confirmation"` or `clarify`. Tests in `tests/test_persona.py` with both lists.
- Voice path: persona line "End with the result or the answer. Do not add 'aur kuch?', 'kuch aur karwana hai?', 'kya
  kehte ho?'. Ask only when you need the answer to continue (an approval: 'haan ya na?'; a missing message text)."
- Measure: scoreboard already counts replies; add a `question_tails` count (status `done`/`said` replies ending "?"
  that match the tail list) to `score()` so the drop is visible. Expect 7-day count to fall toward 0 for text.

**B4. Live checks.** With the owner idle: start a Live conversation via the dashboard (or `scripts/live_replay.py`),
say "VLC khol do" -> the task row exists (`actions.log.jsonl` `apps.launch`) and the reply has no tail. Play a 5 s
Spanish TTS clip at the mic (or feed a fake transcript through `LiveConversation.handle(owner("Que sí, güey."))` in a
script) -> `heard.jsonl` logs it ignored, no task, `conversations.jsonl` gets no `said` row for it.

**B5. Scoreboard gate:** unkept promises 0 on the next 7 days of real use; foreign lines answered 0; question tails
on text replies 0.

---

### Slice C: one resolver for names (3 days)

**Goal:** Chutku hears names the way people say them. One scorer for apps, chats, playlists/songs/artists, files.

**C1. `chutku/resolve.py` (new, ~120 lines, pure functions, no I/O):**
- `score(said, candidate) -> float` combining: `difflib.SequenceMatcher` ratio on normalised text; first-word and
  prefix match; **Hinglish/STT normalisation** before comparing: `w<->v`, `ee<->i`, `oo<->u`, `o<->au`, `a<->aa`,
  `ph<->f`, `z<->j`, `ck<->k`, `q<->k`, doubled letters collapsed, `the/my/mera/meri/wala/wali/playlist/chat/app`
  filler removed (reuse `apps/known._FILLER` and `mind.norm` where possible); phonetic key (simple Soundex-like for
  Roman letters) equality adds a bonus; **chosen-before** bonus from a small history (`data/resolve_history.json`:
  said -> chosen, last 500).
- `best(said, candidates, *, min_score=0.62, tie=0.06) -> ("one", name) | ("tie", [a, b]) | ("none", [])`.
  A tie is when the top two are within `tie`. Only a tie may ask; "one" acts and the reply names the choice ("Lowkey
  nahi, 'Lo-fi Beats' chala rahi hoon").
- `remember(said, chosen, base)` after a verified success.
- Unit tests from the failures bank: ("Loki", ["Lo-fi Beats", "After Party", "Liked Songs"]) -> Lo-fi Beats;
  "Lowkey", "lofi" -> same; ("UB", ["UB (Uday Bhaiya)", "Pankaj Dubey", "MyJio"]) -> UB...; ("Shaanu", ["Shanu
  Sharma", "Shahnawaz"]) -> Shanu; ("Ato mera brave", installed apps) -> Brave; ("Open sport", apps) -> Spotify;
  ("vs code", ["Visual Studio Code"]) -> VS Code; ("Arijitt", artists) -> Arijit Singh; and ties: ("Rahul",
  ["Rahul Verma", "Rahul Jain"]) -> tie. Negative: ("random nonsense", [...]) -> none.

**C2. Wire it in (small call-site edits, no logic moves):**
- Apps: `tools/everyday._closest_app` -> use `resolve.best`; keep the signature. Also strip location words before
  matching ("in brave", "active", "current", "wala") for `apps.quit` / `windows.manage` (the P1 fix exists for some;
  check `_manage`).
- WhatsApp: `tools/apps_extra.pick_chat_row` already asks the brain for a row; call `resolve.best` first over the
  visible rows and the Saved people (`mind.default().load()["people"]`), fall back to the brain only on a tie or none.
  `resolve_contact` / `recipient`: when `find_person` is None, try `resolve.best(to, [p["name"], aliases...])` before
  giving up. Keep the "(You)" own-number rule and the Locked-chats flow untouched.
- Spotify: `apps/known.spoken_playlist` returns None unless exact; add a second pass `resolve.best(rest,
  known("spotify","playlist"))` and return `("one", name)`; the caller then plays it and says the name. In
  `tools/visible.matches` use `score` so "After Party" vs "Afterparty Hits" picks right.
- Files: `tools/everyday._open_file` / `files.find`: candidates from `know_me.recent_files()` + the drive index
  (`drive_index.py`) by basename before saying "does not exist".
- Reply rule when the chosen name differs from what was said: the reply names it ("'Lofi' nahi mila, 'Lo-fi Beats'
  chala di"). If the owner says "galat"/"nahi woh nahi" next turn, `remember` the negative (never pick that again for
  that said-text) and ask the tie question once.

**C3. Edge cases:** Devanagari input (`translit.roman` first); numbers in names ("Loki 2"); emojis in chat names
(strip for scoring, keep for display); duplicates in the WhatsApp list (groups vs people: prefer person unless "group"
said); very short said ("UB", 2 letters): require exact prefix/initials match, never fuzzy; own chat ("my chat", "(You)")
handled before the resolver; a name that is also an app word ("Spotify" the person vs the app) decided by the tool.

**C4. Live:** with Spotify open, "play lowkey playlist on spotify" -> the Lo-fi playlist plays (title check via
`app.spotify` lab check); "Ato mera brave open kar" -> Brave window; WhatsApp dry run `scripts/verify_whatsapp.py`
with a near-miss name shows the right row highlighted, nothing sent.

**C5. Gate:** the 13 `music_play` and 8 `whatsapp_open_chat` failures in `real_failures.jsonl` pass in plan mode
(`scripts/persona_exam.py` / `practice.nightly` on the bank); `check_phrases.py` unchanged.

---

### Slice D: remember people and answers; stop asking (3 days)

**D1. People learn themselves.**
- Every time Chutku reads the WhatsApp chat list (`_result_rows`, `recent_chat`, `_read_chat`, `pick_chat_row`),
  write the visible chat names into `mind.json` people as `{"name", "whatsapp", "seen": <ts>, "source": "whatsapp"}`
  via `mind.Mind._change` (dedupe by `norm`; never overwrite a person the owner saved by hand; keep <= 500; names
  only, never message text; nothing from Locked chats unless the owner opened them).
- After a `message.send` the owner approved, mark that person `approved_send: <ts>`.
- `know_me.refresh` (6-hourly) also reads the WhatsApp Desktop local DB? **No**: it is encrypted; skip. Only the screen.
- Tests: fake rows -> people added once; owner-saved person untouched; Locked rows excluded.

**D2. "Unknown recipient" means never seen.**
- Find where the kernel's `owner_question` for sends is produced (grep `unknown recipient` in `tools/apps_extra.py`
  / `tools/messaging*.py` / `dashboard.py`): a recipient present in `mind.json` people (any source) is known. A phone
  number typed by the owner is known. Keep asking for a name Chutku has never seen anywhere.
- Negative test: a brand-new name still asks; a name seen in the chat list does not.

**D3. Ask once per person, not per message.**
- `approval_memory.key(step)` hashes tool + all arguments. Add a per-tool argument filter: for `message.send`
  (and `telegram.send`, `email.send`) the key uses only `to` (not `text`); for `apps.install` only the app; for
  `filesystem.*` the full path. Keep `eligible()` as is (never for deletes, R4, tainted, remote origins).
- Tests: two sends to the same person with different texts -> second runs without asking; different person asks;
  tainted session asks; phone origin for laptop-only stays laptop.

**D4. "Approval mat maangna" means it.**
- `busy.add_note` already records owner notes on a running session; `kernel.TRUSTED` exists for "bina puche kar do".
  Wire: when a note or the request matches `bina puche|approval mat|don't ask|without asking`, set the session's
  trust (`trusted=True` in `_owner`) for R1-R2 steps **of that session only**; never for deletes/R4/unknown recipient.
  Live persona already tells the model to end the goal with "without asking"; make sure `begin_session` honours it.
- Test from the log: "अभी बोला था अप्रूवल मत मांगना" after a pending `message.send` to a known person -> approved;
  to an unknown person -> still asks; a delete -> still asks.

**D5. Resolve instead of asking (the clarify list).**
- Audit all 20 clarifies of the week (they are in `real_failures.jsonl`); each gets a default: missing city ->
  `preferences`/location (exists), missing time -> next sensible slot, missing app -> resolver, missing chat ->
  current/last chat (`is_current_chat`, `recent_chat`), "alarm" -> `reminder.set` with a spoken alarm (no Clock app
  excuse), "open skills page in brave" -> `web.search` in Brave (never "tell me the exact URL").
- Rule in `AGENT_SYSTEM` / `cloud_view`: "Never ask the owner for something you can look up or default; ask one short
  question only for a true tie." Add the tie phrasing: one line, two options.

**D6. Live + gate:** with the owner present (he must approve any real send), one real message to a known person
without a card; a second message to the same person without a card; a never-seen name asks. Scoreboard: approvals +
clarifies <= 2 per 100 over the next week; `mind.json` people >= 20 after one WhatsApp session.

---

### Slice E: finish every part (3 days)

**E1. Task card before planning (Brain 2 §4.1).**
- In `cloud_planner.CloudAgentPlanner.propose` (or a new `understand(goal, context)` in `agent_loop_prompts.py`
  called from `AgentSession._propose` when `is_multipart_goal(goal)` or the instant router returns None): one cheap
  Groq call (`providers.ask`, 6 s timeout, JSON schema) returns `{"parts": [{"ask": str, "tool_hint": str|null,
  "target": {...}}], "unknown": [], "confidence": "high|low"}`. Store on the session (`session.card`), show it as the
  non-blocking one-liner in `declared_plan` ("Weather -> News -> Reminders").
- Fallback: if the call fails or times out, plan as today (never block on the card).
- **Every part must PASS**: in `_finish`/`_reject_false_done`, a session with a card is `done` only when each part has
  at least one COMPLETED step whose tool matches the part's hint or whose output names the target; otherwise status
  `partial` with a reply that says exactly which part did not happen ("Weather aur news ho gaya; reminders list nahi
  mil payi"). `partial` counts as failed on the scoreboard (add to `FAILED`).
- Use `steps.for_each` and the parallel lanes (`runtime.lane`, `dashboard_work._parallel`) when parts are independent
  (weather + news + reminders at once).
- Tests: "aaj ka weather, news aur meri reminders batao" -> 3 parts, 0 questions, three tools, `done`; one tool
  failing -> `partial` reply naming it; a single-part goal gets no card call (fake transport asserts 0 calls);
  injected text in a part (`_InstructionLines`) is still defanged (card parts are untrusted data when tainted).
- Edge cases: parts that depend on each other ("open X then send Y") keep order; "and" inside quoted message text
  is not a split (reuse `_SPLIT` and `_QUOTED` from `quick_intents`); Devanagari conjunctions "aur/phir/uske baad";
  more than 6 parts -> still one card, run in order, no cap below 6.
- Live: the sentence above through `/api/chat` in < 8 s with three results; the negative: unplug the network
  (or fake weather failure) -> `partial` with the honest line.

---

### Slice F: the screen is context (1 week)

**F1. Relative selectors in `tools/visible.py`:** parse "just below X / X ke neeche / above / next to / first / last /
second" into `{anchor, relation, ordinal}`; find the anchor with `resolve.score` over OCR/UIA lines, pick the
neighbour by geometry (`rect` y/x), act on it. Quoted names ("\"(U)\"") are matched literally. Tests with synthetic
line lists; no vision model needed.

**F2. Vision fallback spike (GPU):** evaluate OmniParser vs UI-TARS-1.5-2B on 30 screenshots of WhatsApp/Spotify
lists where UIA sees nothing; measure accuracy and seconds; keep the better one only if >= 85% and <= 1.5 s, behind a
flag; otherwise record the numbers and stop. Record the prompt in `docs/AGENT_PROMPTS.md` if an agent is used.

**F3. Locks:** on a password/PIN/OTP field or a lock screen (UIA `IsPassword`, titles "Locked chats", Windows lock),
pause the session (`status: "waiting_owner"`), say "unlock kar do, main continue karti hoon", resume from the same
step when the field is gone. Negative test: `keyboard.type_text` into an `IsPassword` element is refused even when the
owner's message contains the digits (never type passwords). WhatsApp Locked chats flow already waits; reuse it.

**F4. Gate:** `screen.act_on_visible` >= 90% on a 20-case screen bank; the 4 "from the screen" failures pass.

---

### Slice G: ahead of you, gated (1 week; only after B-E hold for a week)

**G1. Habit suggestions.** `learning.refresh_habits` (min 3 days) + `know_me.frequent_apps` produce candidates in
`suggest.candidates`: "Roz subah 9 baje WhatsApp aur Spotify kholte ho; ek tap mein dono?" -> accept creates a
`routines.save_taught` routine and a `task.schedule`. **Rules:** one suggestion per category per day; `suggest.quiet`
hours; accept/ignore via `suggest.respond`; three ignores silence the category for 30 days; never during a running
task or a voice conversation; never on battery < 20%; never while a game/full-screen app is in front.

**G2. Morning brief at the owner's usual wake time** (from `know_me` first-app-of-day): weather, today's reminders
(`reminder.list`), unread count (`message.unread_count`) -> HUD line and Telegram if paired. Opt-out phrase
"morning brief band" (reflex). Dry-run flag for tests.

**G3. The sensible extra inside a task** (no asking, reversible only): after `message.send` keep the chat open;
after `apps.launch` from voice, focus it unless the owner is typing (`background_desk` focus guard); when a long
message is read, read the first line aloud, then "poora padhun?" is NOT asked, it offers via the HUD.

**G4. Gate:** accept rate >= 50% over two weeks; 0 "chup/stop suggesting" complaints; B100 does not rise.

---

### Slice H: speed and no hangs (ongoing from the first week)

- **Replay cache with per-step checks:** `experience.record/similar`, `agent_loop._replay` (only exact one-round
  repeats today). Allow multi-round replays only when every saved step has a verifier that PASSed and no step used a
  looked-up value from an earlier step; a failing replayed step falls back to the planner (never re-tries blindly).
  Mark the known-bad lesson ("turn on bluetooth" -> `app.spotify.next`) as a test.
- **Provider failover on quota:** `providers.ladder` + `cool_down` exist; make sure a 429 on Groq falls to Cerebras
  within 1 s, and the owner's reply never contains a raw quota error (plain line: "cloud busy, local se kar rahi hoon").
- **Start the app while planning:** when the card's first part is an `apps.launch` with a resolved app, start it in a
  lane immediately.
- **Hangs:** the 8 s `Thread.start` stalls (status 25): capture `hang-*.txt` with thread names; move
  `learning.refresh_habits` and `everyday.describe` (image) off the HTTP loop with hard timeouts; test that a stuck
  worker never blocks `/api/presence`.
- **Gate:** p50 <= 2 s repeat tasks, new single-app <= 8 s, 0 hangs for 7 days.

---

## 6. What NOT to do (until the Daily 30 holds 99% for two weeks)

- No new tools, atlases, dashboard tabs, phone features, Telegram features.
- No LoRA, AirLLM, Nuitka, Store/winget, delta updates, user profiles, new voices.
- No regex-per-phrase in `quick_intents.py` (a new phrase goes to the resolver or the card; `quick_intents` may get a
  phrase only after it is proven live and only as a cache).
- No moving functions out of `tools/apps_extra.py`, `tools/everyday.py`, `agent_loop.py` (tests patch them by module).
- No weakening of: taint rules, laptop-only list, system-damage list, deletes-ask, R4-ask, password rule, Evolve's
  protected files (`evolve_apply.PROTECTED_*`; `chutku/dashboard*.py` is covered, add `chutku/resolve.py` if it
  becomes safety-relevant).
- No real WhatsApp send, email, install or power action in a live check without the owner's explicit OK for that action.
- No work that does not move a number in section 1.

## 7. Order and time

| Week | Slices | Exit gate |
|---|---|---|
| 1 | B, C | unkept promises 0; music_play and whatsapp_open_chat failures pass in plan mode; live checks done |
| 2 | D, E | asks <= 2/100; multi-part sentence done in < 8 s; `mind.json` people >= 20 |
| 3-4 | F, H | screen bank >= 90%; p50 repeat <= 2 s; 0 hangs 7 days |
| 5 | G | accept >= 50%, 0 complaints |
| then | release 1.3 via `scripts/release_local.ps1` only if B100 fell and Daily 30 did not regress | |

## 8. Verification summary (per slice, all required)

- Unit tests from real turns; module tests; full suite green (fix `test_docs_truth` count first).
- `scripts/check_phrases.py` >= 193/193; router snapshot unchanged except intended.
- One timed live path on this PC with an independent check; owner idle and no media first.
- A negative case for anything near safety (password never typed, unknown still asks, delete still asks, damage refused).
- `scripts/scoreboard.py` before/after in the status entry; Daily 30 and B100 trend in `docs/TWENTY_X_PLAN.md` §8.
- Status entry + commit (no co-author) + push after every slice.

---

## 10. Session-start checklist (every working session, before any code)

1. `git status` and `git log --oneline -5`: know what the last session left (uncommitted work is finished or stashed
   with a note in the status file, never silently discarded). The untracked `chutku/apps/atlas/ui_*.json` are the
   owner's: leave them unless he says to commit them.
2. Read `docs/BEST_ASSISTANT_PLAN.md` §15 ticks and the newest `IMPLEMENTATION_STATUS.md` entry; pick the first open
   tick in order (B before C, never G before B-E hold).
3. `scripts/scoreboard.py` (7 and 60 days): the "before" numbers for this session.
4. Is Chutku running? `tasklist /fi "imagename eq pythonw.exe"` and `data/dashboard-session.json`. The running core
   loads code at start: a code change is live only after `Stop-Chutku.cmd` / `Start-Chutku.cmd`. Restart only when
   the owner is not mid-conversation (HUD idle, no `data/last-task.json` running, `background_desk.idle_seconds()` >
   60). Never restart during a night shift of the owner's own practice.
5. Owner reminders: tell the owner, once per session, anything still open in memory `reminder-1-2-future` (publish
   1.2.4, sleep timer, first-time-ask decision) and ask nothing else.
6. Check `data/nightshift/` for last night's report: a regression there is the first bug of the day.

## 11. Cross-cutting edge cases (apply in every slice)

**Language and script**
- Voice transcripts arrive in Devanagari, Roman Hinglish, English or mixed in one sentence ("प्रणाम लिख दे और send").
  Always `translit.roman()` before matching; `translit.has_devanagari()` decides reply script only.
- Hinglish verbs are inflected: `kar/karo/kardo/kar de/kar do/karna/karke`; `khol/kholo/khol de`; `bhej/bhejo/bhej
  de/bhejna`. Match stems, never one form.
- Names are spelt as heard: doubled letters (Arijitt), v/w (Vashisth/Washisth), ee/i. The resolver (Slice C) owns this;
  no other module adds its own spelling tricks.
- Times: "6 baje", "6:30 pm", "saadhe chhe", "dhai", "pauna", "subah/shaam/raat" (AM/PM from the word), "10 min baad",
  "kal", "parso", "har roz". `learning.resolve_day/parse_event` and the reminder parser exist; extend there only.
- English-only assistants (identity `ASSISTANT_LANGUAGE=english`): every persona change goes through `personalize()`;
  test both identities (`tests/test_persona.py` pattern).

**Conversation state**
- A Live conversation may run 1 + MAX_PARALLEL tasks; "aur haan ..." steers the running one (`busy.add_note`),
  "pehle ye" jumps the queue, "baad mein" queues. New code must not break `busy.route`.
- The owner interrupts mid-reply (`interrupted`): playback stops; a task already started keeps running.
- "stop/ruko/cancel" during a running task: `stop_task`; after it, nothing is replayed automatically (owner rule).
- A late "haan" after the approval card expired re-arms the same step on a fresh card (status 25); keep that.
- Origins: `text`, `voice`, `phone`, `telegram`, `script` (synthetic: scoreboard ignores). Laptop-only steps asked
  from phone/Telegram wait for the laptop card; never relax `remote.server.laptop_only`.
- Tainted sessions (after web/chat/screen/file text): R2+ asks, R1 start/remember tools ask; the owner's own words
  (whole words >= 4 chars) are exempt. New tools that read outside text must be added to `agent_loop.TAINTING_TOOLS`
  / `PRIVATE_TOOLS` (a test fails if a name is not a real tool).

**PC and apps**
- UWP/Store apps show a splash window first; `everyday._await_new_window` and `_launch` already wait and retry once;
  background launches use `background_desk` (typing pause 0.7 s, focus guard, never fight the owner's own switch).
- Multi-monitor and DPI: all screen work takes rects from `tools/visible._rect/_screen_rect`; never hard-code pixels.
- WhatsApp Desktop has no usable UIA for the chat list: OCR + geometry (`_result_rows`, `chat_messages`); the green
  highlight means exact match; Ctrl+F is broken (memory `whatsapp-ui-facts`); Locked chats need the owner's code,
  typed by him only.
- Spotify: verified actions in `apps/atlas/spotify.json` plus `apps/lab` runs; the play button is found by colour
  (`green_play_button`, 24 ms). An unverified atlas action goes to the planner, never instant.
- Browser: Brave is the default; `web.open` into the everyday profile; the signed-in `browser.*` tools use the
  dedicated profile and are PRIVATE + TAINTING.
- Offline or quota: `providers.ladder` falls through Groq -> Cerebras -> Gemini -> local; `settings.offline_mode`
  turns cloud off. Every slice that adds a model call must work (slower) with `transport=None` fakes and with the
  ladder empty (plain honest reply, no traceback in the owner's text).
- Sleep/resume: the awake clock (`dashboard.awake_clock`) means a laptop sleep is not a hang; do not add timers that
  count wall-clock across sleep.
- Scheduled tasks (`task.schedule`) and reminders fire later with origin `scheduled`: a remembered approval is never
  reused for R4 there; a reminder that speaks uses `voice.speak`, never a message tool (`message_for_person` guard).

**Data and privacy**
- `conversations.jsonl`, `mind.json`, `experience.jsonl`, `know_me.json`, `resolve_history.json` (new) are local
  only and never enter a cloud prompt except through `cloud_view` (goal, catalog, step summaries, memory slice).
  Nothing from `data/` is committed (git-ignored); tests use `tempfile` bases and never read the owner's data
  (`practice.load_bank()` without `real=` must return nothing private: a test checks this).
- Message text is redacted in the event trace; keep `[REDACTED]` in any new log line that carries owner text.

## 12. How tests are written in this repo

- `unittest` only; `tests/` is flat; discovery with `-s tests`. Imports of sibling test modules use `tests.name`.
- Fakes: `tests/agent_fakes.py` (`FakeRuntime(ask={...})`, `ScriptedPlanner`, `continue_with(*steps, finish, reply)`,
  `real_registry()`), `tests/test_heard.py` (`FakeServer`, `chunk(level)`), `tests/test_live_claims.py`
  (`ClaimTests.turn`). Patch module attributes (`patch.object(module, "name")`): that is why functions must stay in
  their modules.
- No network, no real devices, no real WhatsApp/Spotify: a test that needs a window uses the `ChutkuFormFixture`
  pattern or OCR line lists; a test that needs a model uses `transport=` fakes returning JSON.
- Every real failure becomes a test with the owner's exact sentence (copy from `data/task_bank/real_failures.jsonl`
  into the test as a literal; the bank file itself is private and never imported by tests).
- Safety tests are protected from Evolve (`evolve_apply.PROTECTED_PATTERNS`): a new safety test file gets added there.
- A docs-truth test (`tests/test_docs_truth.py`) pins tool counts and the R3/R4 list in `docs/SECURITY.md`: any new
  tool or risk change updates the doc in the same commit.

## 13. Slice E-H: the same depth as B-D

**E (finish every part), extra detail**
- Where: `agent_loop.is_multipart_goal` decides today (>= 10 words, two action/lookup verbs). The card call is made
  only then, or when `quick_proposal` returns None and the goal has a conjunction (`quick_intents._SPLIT`).
- Card schema (strict, `providers.ask` with a JSON schema): `parts[]` of `{ask, tool_hint, target}`; `tool_hint` must
  be a registered tool name or null (validate against `runtime.registry`; drop unknown hints, never trust them).
- The finish checker lives next to `_reject_false_done`: a `done` proposal with an unmet part raises the same
  `ValueError` style ("part 2 'news' has no completed step; continue"), so the planner is driven to finish, and after
  `limits` are hit the status is `partial` with the honest line. Add `partial` to `recall` statuses and the
  scoreboard's `FAILED`.
- `declared_plan` shows the card as one line; the HUD and the phone read `declared_plan` already.
- Negative: a part whose only "evidence" is model text ("I checked the news") is unmet (no COMPLETED step).
- Live: three sentences through `/api/chat` with `X-Chutku-Synthetic: 1` (so the scoreboard ignores them):
  "aaj ka weather, news aur meri reminders batao", "spotify kholo aur after party chalao aur volume 30 karo",
  "downloads ki sabse badi file batao aur usko desktop pe copy karo" (asks once for the copy: file change).

**F (screen), extra detail**
- Selector grammar: `<anchor> ke (neeche|upar|baaju|right|left)`, `just (below|above|next to) <anchor>`, `(first|
  last|second|teesra|pehla|aakhri)`, `<anchor> wali`. Anchor found by `resolve.score` over line texts; neighbour by
  rect centre distance in the stated direction; ordinal over lines of the same `kind_of`.
- Quoted anchors are literal (`"(U)"`, `"Me (U)"`); unquoted use the resolver.
- When nothing visible matches: say so in one line and offer the search route only if the request did not say
  "from the screen" (owner: never search when he said it is on the screen).
- Lock handling status name: `waiting_owner`; the HUD shows "unlock kar do"; `/api/agent/session` exposes it; the
  phone shows the same; resume happens on the next `desktop.look`/`screen.understand` that no longer sees the
  password field. Timeout 10 minutes -> `cancelled` with a plain line.
- Negative tests: `keyboard.type_text` into `IsPassword` refused; OTP-like 4-8 digit strings in a message to type
  into a password field refused; the Locked-chats code is never in `arguments`.

**G (ahead of you), extra detail**
- Candidate sources: `learning.refresh_habits` (same request >= 3 days), `know_me.frequent_apps` + first-app-of-day,
  `reminder.list` due today, `health.readings` (exists). Each candidate: `{id, category, text, accept_action,
  evidence}`; `accept_action` is a normal goal run through `begin_session` (origin `suggestion`), so policy applies.
- Delivery: HUD line + toast (`health._TOAST` pattern) with Accept / Not now; voice only when a Live conversation is
  already open and idle; Telegram for the morning brief only.
- Memory of answers: `suggest.respond` stores accept/ignore; `candidates` filters: ignored x3 -> 30 days silence;
  accepted -> becomes a routine, suggestion retired.
- Never: during `status in (running, waiting_confirmation)`, during a Live conversation turn, in `quiet` hours,
  on battery < 20% (`health.battery`), when a full-screen app is in front, more than one per category per day, more
  than three per day in total.
- Tests: candidate gating table (each never-rule), accept creates the routine, ignore x3 silences, dry-run brief.
- Live: one real morning brief at the owner's usual time with his OK; one habit suggestion accepted -> routine runs
  next day (check `data/routines.json` and the action log).

**H (speed, hangs), extra detail**
- Per-tier latency report: `scripts/scoreboard.py` gains p50/p90 per `planners` tier (quick / replay / cloud:* /
  local) once real timed turns exist; the first week's job is to get 100+ timed owner turns.
- Replay widening (P3 note in TWENTY_X_PLAN): only rows where every step `verified == PASS`, no step argument came
  from an earlier step's output (`_fill`/`{item}` markers absent), and the goal normalises equal (`experience.
  normal_goal`). On any step FAIL the replay stops and the planner continues from there with the steps so far.
- Known-bad lessons: a test asserts "turn on bluetooth" never replays to `app.spotify.next`; `experience.update_rows`
  marks bad rows; Night Shift re-verifies rows older than 30 days.
- Hangs: add thread names to every `threading.Thread(...)` Chutku starts (grep `Thread(`), so `hang-*.txt` names the
  stuck one; `refresh_habits`, `recall.hidden_turns`, `everyday.describe` run on the worker pool with a 20 s cap;
  `/api/presence` and `/api/agent/latest` never touch disk or models (already) and get a test with a blocked worker.
- Failover: a 429/5xx from Groq must `cool_down` and fall to the next rung inside 1 s (fake transport test); the
  owner's reply never contains a provider error string (assert on `reply`).

## 14. What to tell the owner, and when

- At session start: the open reminders (section 10.5), in one short list, then start work.
- Before any live check that makes sound, moves windows or sends anything: one line asking if now is fine, unless the
  owner already said he is away or the idle check passes and the action is silent and reversible.
- After each slice: the scoreboard before/after, what was proven live, what was NOT (honest limits), the next tick.
- Never a "should I proceed?" between ticks of the same slice; proceed. Ask only for owner decisions: real sends,
  deletes, installs, power, publishing a release, committing his untracked files, changing his preferences.

---

## 15. Progress ticks (the executing agent updates these)

- [x] B1 claims (exact per-turn task flag; 'karti hoon' claims) - 2026-11-10 (34)
- [x] B2 noise gate (heard.foreign; 18/551 real lines dropped, all noise) - (34)
- [x] B3 question tails (voice persona rule; scoreboard TAIL baseline 12/7d) - (34)
- [ ] B4 live: waits for a Chutku restart while the owner is away
- [ ] B5 gate
- [ ] C1 resolve.py: DEFERRED 2026-11-10 (34): routing + live name fixes already cover the bank; re-check with new data
- [ ] C2 wiring
- [ ] C3 edge cases
- [ ] C4 live
- [ ] C5 gate
- [ ] D1 people learn: OWNER DECISION (auto-known names skip the first ask)
- [x] D2 place words in `to` ('KitKat from the screen', 'chat in Locked chats') - (35)
- [x] D3 ask once per person: already done (_remember_chat after a verified send)
- [x] D4 approval mat maangna: already handled by approval.decide DONT_ASK (checked 2026-11-10)
- [ ] D5 resolve not ask
- [ ] D6 live + gate
- [x] E0 verified work never reported as failed: local reply builders, worded_by_code, reminder list - (35)
- [ ] E1 task card + finish checker
- [ ] E live
- [x] F1 selectors (visible.pick below/above, router) - (36); live check waits for Spotify on screen
- [ ] F2 vision spike
- [x] F3a never type a password (focused_is_password) - (37); live password-box check pending
- [ ] F3b lock screen pause/resume
- [ ] F4 gate
- [ ] G1 habits
- [ ] G2 morning brief
- [ ] G3 sensible extra
- [ ] G4 gate
- [ ] H replay
- [ ] H failover
- [ ] H start while planning
- [ ] H hangs
- [ ] H gate
