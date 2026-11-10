# Chutku: fix what's broken, then make it world-class (plan, 2026-10-29)

## Context
The owner says Chutku "isn't working properly" and has "no wow factor". An audit of the code plus the real
logs (data/heard.jsonl, conversations.jsonl, actions.log.jsonl, nightshift reports) shows the owner effectively
**gave up on 2026-10-24**. The code is large and well tested (about 31k lines, about 230 tools, 1,111 unit tests
green on 10-12). But the live experience fails at the very first step (being heard and staying on), then at
being honest and fast. This plan fixes those first, then adds four flagship upgrades the owner picked today.

## Diagnosis: why it "doesn't work" (ranked, with evidence)
1. **Dead since 10-26: actions are paused.** `data/actions.paused` exists. Any watchdog stop (guard
   `heartbeat_timeout`, or `action_deadline` at 120 s) pauses forever until a *typed* resume
   (`chutku/guard.py:197`, `core/action_control.py:25`). The marker always says "paused by the user",
   even when the guard wrote it. Voice requests made while paused get **no spoken reply**
   (`dashboard.py:245` skips `speak_result`).
2. **The wake word never fires.** 5,071 utterances since 10-23 were all ignored, and not one contained
   "Chutku". `WAKE_PROMPT` (`voice/handsfree.py:24`) doesn't mention Chutku; Whisper is forced to English and
   echoes the prompt back (44 exact echoes). The trained detector failed its gate (recall 0.44, 68 false
   wakes/h). Meanwhile every overheard household sentence is transcribed and logged (a privacy problem).
3. **STT mishears.** Hotkey listening failed 13 of 31 times, and 19 turns came back as Spanish, Japanese or
   Korean. Misheard text ("Watch out brother.", "Basic presentation.") still ran 45–58 s model plans that
   opened files.
4. **Talk mode lies.** 216 unverified Gemini Live turns: "Bluetooth band ho gaya" (it wasn't), "play pe
   click kar diya" (the app was closed). It also "switches itself on" (6 complaints on 10-11/12).
5. **Spotify, the owner's top goal:** "After Party" playlist, 15 tries, 0 verified plays. 7 of the 8
   "keeps failing" tool kinds in Night Shift are Spotify.
6. **The brain is slow and wrong.** Local Qwen3-4B: median 14.7 s, p90 58 s by voice. Gemini by voice:
   median 85 s. It picks wrong tools ("close vs code" ×4, "start work mode" refused).
7. **Self-checks are blind.** Night Shift replay "passes" on 2 goals, both mishearings. `mind.json` habits
   and suggestion toasts are built from automated test traffic (for example "2^10 vs 10 cubed at 2 AM").
   The toast PowerShell times out after 30 s (`health.py:128`).
8. **No visual identity.** The dashboard is 93 lines of HTML and 101 of CSS, the HUD is a basic Tk window,
   and `chutku.ico` is 0 bytes.

## Owner decisions (2026-10-29)
- **Wow focus:** Jarvis presence UI, real-time conversation, screen copilot, phone remote with **full control
  from the phone whenever the PC is online** (this unlocks HERMES_PLAN P5–P9 as well as P1–P4).
- **Brain:** **free cloud first** (Gemini Flash/Flash-Lite, Groq, rotating on quota), with local Qwen as the
  offline fallback.
- **Wake:** **both**: a proper wake engine, with the hotkey as the primary trigger until the engine passes its gate.

## Rules that still apply to every slice
AGENTS.md gate (tests + a real path + a negative case + an `IMPLEMENTATION_STATUS.md` entry with evidence);
timings **and** an independent correctness check (`scripts/live_check.py`); `docs/OWNER_GUIDE.md` updated for
every phrase or control; every helper-agent prompt goes in `docs/AGENT_PROMPTS.md`; commit `<ID>: summary` with
**no co-author line**, then push `main`; keep CRLF files CRLF (Edit tool, no `sed -i`); tests never start real
models. Slices go into `docs/MASTER_PLAN.md` as a new **Phase 4 (W0–W6)** with tick boxes.

---

## Phase W0: Housekeeping (first, small)
- Update memory:
  - new `owner-decisions-2026-10-29.md` (the 3 decisions above, plus the diagnosis summary);
  - refresh `master-plan.md` (last commit 5515954 on 10-12; A0–A6 and H1–H8 done; next was A7; now W-phase first);
  - fix `MEMORY.md` index lines.
- Log this session's 3 Explore-agent prompts verbatim in `docs/AGENT_PROMPTS.md`.
- Add Phase 4 to MASTER_PLAN. Fix stale counts in README / OWNER_GUIDE / the ledger header (230 tools, 1,111 tests).
- `Untitled-6.txt` (120 bytes of blank lines, untracked) is left alone. Deletes are asked: I'll mention it, not remove it.

## Phase W1: Make it work again (fixes; each item is its own small slice)
**F1. Pause that heals itself, and that speaks.** `core/action_control.py`, `guard.py`, `dashboard.py`
- The pause marker records `{source: owner|guard|startup, reason, at}`. The message names the real cause.
- **Watchdog pauses** (heartbeat/startup/action_deadline) auto-clear once the restarted core is healthy for
  30 s. The interrupted task is marked failed and **never re-run**. Chutku says: "Main atak gayi thi, restart
  ho gayi; '<task>' beech mein ruka tha". **Owner pauses stay manual**, but a spoken "Chutku resume" now works
  for the owner by hotkey (it is only a resume, not new work).
- Heartbeat moves from `service_actions` (HTTP poll loop) to its own thread. On 2 missed beats,
  `faulthandler` dumps all stacks to `data/logs/hang-*.txt`, so the real cause of the 10-28 hang is captured.
  Long tools (screen.understand) get a per-tool deadline instead of the global 120 s kill.
- A voice request while paused always gets a spoken reply. The HUD and tray show a red "Paused: reason" state.
- Tests: a guard stop leaves the pause auto-clearing, while an owner pause does not; the interrupted task is
  not replayed; the spoken paused reply. Negative: an owner pause survives restart.

**F2. Wake word that works (stage 1: fix the Whisper path today).** `voice/handsfree.py`, `voice/whisper_stt.py`, `voice/heard.py`
- Bias the prompt toward the name ("Oye Chutku, Chutku sun"). Reject prompt echoes by word overlap, not
  only exact substrings. Language is chosen from {en, hi} only. Re-benchmark with
  `scripts/benchmark_noise.py` / `scripts/record_wake.py` clips.
- **Privacy:** ignored speech is no longer stored by default. `heard.jsonl` keeps wakes, commands and counts;
  full ambient logging becomes a 24 h debug toggle. The existing 5,071 lines are kept unless the owner says to delete.
- The HUD/tray "listening" glow plus a chime on every wake, so a false wake is always visible ("switches
  itself on").

**F3. Wake engine (stage 2).** `voice/wakeword.py`, `scripts/train_wake.py`
- An openWakeWord-style detector: its frozen ONNX mel and embedding models (Apache-2.0), plus a small
  "Oye Chutku" head trained on **thousands of synthetic Kokoro clips** (all voices, speed and pitch, with
  room-noise augmentation) plus the owner's 29 clips. Negatives: 1–2 h of consented room recording
  (local only) and public noise sets.
- Two stages: the detector fires, then Whisper checks that 1.5 s clip with the name prompt.
- Same gate as today (owner recall ≥ 0.9, ≤ 1 false wake/h on the stream test). It is installed only if it
  passes, otherwise it stays parked and the hotkey stays primary.

**F4. Hear correctly and refuse nonsense.** `voice/recognition.py`, `agent_loop.py`
- Command STT: language restricted to en/hi (Hindi is turned into Roman script by `translit.roman`). Once
  W2 moves the brain to the cloud, use local **large-v3-turbo on the GPU**, which is freed from Qwen.
- **Plausibility gate:** a low-confidence or non-command transcript ("Watch out brother.") gets "Maine suna
  '…' — yahi karna hai?" instead of a 58 s plan. Retire the Windows dictation fallback (0 of 10).

**F5. Never claim what didn't happen.** `voice/live.py`, `dashboard.py`
- Gemini Live becomes opt-in ("baat karte hain" mode), not the default for the hotkey. The default hotkey path
  becomes W3's local pipeline.
- In Live mode, the outcome of a task is spoken **by Chutku's verified status line** (in Kokoro), never by the
  Live model. Extend `_claimed_without_task` to any "ho gaya/kar diya" said with no verified step.

**F6. Spotify that actually plays.** `apps/atlases` (spotify), `apps/runner.py`, `tools/everyday.py`
- pause/next/previous/volume use **global media keys** (no UI needed), verified through the window title / media status.
- "Play <playlist>": find the playlist's `spotify:` URI once from the library UI, cache it in `mind.json`,
  then open the URI and press play. Verify that the window title changed to a track.
- The real path is the owner's actual sentence: "Spotify pe After Party chalao", 5 of 5 times by voice.

**F7. Honest self-checks.** `mind.py`, `suggest.py`, `nightshift.py`, `health.py`
- Every request carries `origin` (owner voice/text vs test/script/nightshift). Habits, suggestions,
  experience and replay use **owner traffic only**. Purge the test-made habits (a reversible edit, logged).
- Night Shift replay with fewer than 10 owner goals reports "not enough real use", not ok.
- Toasts go async with a 5 s timeout, so a stuck PowerShell never blocks.

## Phase W2: Cloud-first brain (free)
`cloud_planner.py` → new `chutku/providers/` (`gemini.py` existing, `groq.py` and `openai_compat.py` new)
- `CloudAgentPlanner` generalises `GeminiAgentPlanner`. It reuses `cloud_view` (the privacy filter: private
  results withheld), `cloud_schema`, `validate_proposal` and the Credential Manager key storage
  (`stored_key`/`store_key`, given one name per provider).
- **Provider ladder:**
  1. Groq (fast, free: Llama-3.3-70B / Qwen3-32B / GPT-OSS-120B), JSON mode;
  2. Gemini Flash then Flash-Lite;
  3. local Qwen3-4B (offline or all quotas exhausted), then the 8B.
  Per-provider quota/cooldown file like `gemini-quota.json`. A health ping decides "online".
- `dashboard.planners()` order flipped: cloud first when `cloud.*` is granted and online. Quick intents and
  reflexes still go before any model (instant stays instant).
- **Tool retrieval:** send core tools plus the top-k tools matched to the goal (reuse the `qwen_prompt`
  matching), not all 230.
- **Streaming answers** for chat replies, so speech starts on the first sentence.
- CLI: `chutku.cli cloud set-key groq|gemini`, `cloud status`. Policy kernel, grants and approvals are unchanged.
- Gate: `scripts/eval_planner.py` ≥ 36 of 40 (local was 29). Median plan time ≤ 2 s. The owner's real failed
  goals ("close vs code", "start work mode", the VS Code "continue" task) are replayed and fixed.
  Negative: private file text never appears in the outgoing payload (captured transport).

## Phase W3: Real-time conversation (local voice loop)
`voice/` new `conversation.py`. Reuses `SpeechQueue` (`dashboard.py:56`), Kokoro (`voice/tts.py`), `Segmenter`.
- Hotkey or wake → listen with Silero-VAD end-of-speech (about 300 ms tail) → GPU Whisper turbo → instant
  intents or the cloud brain (streaming) → Kokoro speaks **sentence by sentence**.
- **Follow-up window:** 8 s after she speaks, no wake word needed.
- **Barge-in:** "ruko / stop / Chutku" or the hotkey while she is talking cuts the TTS within 200 ms. A
  speech-energy barge-in is used only if Windows communications-mode echo cancellation works on this mic (measured).
- Short "hmm / ek sec" filler if the brain takes more than 1.2 s.
- Targets (measured from end of speech to first audio): instant ≤ 1.2 s, cloud ≤ 2.5 s. Correctness is
  checked with `live_check.py`.

## Phase W4: Jarvis presence UI
- **Presence overlay** (replaces the Tk HUD, `hud.py`): a frameless, transparent, always-on-top WebView2 window
  (`pywebview`, a new dependency) with an animated, voice-reactive orb (canvas/WebGL).
  - States: idle, listening, thinking, acting, speaking, paused, phone-connected.
  - Live captions (what the owner said, what Chutku says).
  - A **task step timeline** with ✓ verified, ✗ failed and approval cards (click to approve).
  - Fed by the existing SSE stream; mic and TTS levels pushed about 20×/s.
- **Dashboard redesign** (`chutku/web/*`, vanilla JS, no build step, libraries vendored offline):
  - a dark "command center": the Today panel, live vitals, the task timeline, a memory/mind view, skills,
    reliability charts and voice;
  - responsive, so it is also the phone UI's base;
  - a real `.ico`/PWA icon.
- Checked with the `webapp-testing` skill (Playwright screenshots, light/dark) plus an a11y pass.

## Phase W5: Screen copilot
`tools/screen_vision.py`, `vision.py`, `local_vision.py`, `tools/visible.py` (reuse `act_on_visible`)
- **Ctrl+Alt+S** or "ye kya hai / screen dekh / ye error fix karo / is page ka summary".
  1. Capture the active window or a dragged region.
  2. Downscale to 1280 px.
  3. Gemini Flash vision (free) answers in ≤ 5 s; local Qwen3-VL is the offline fallback.
  4. Windows in `timeline_private` and password fields are masked before upload.
- "Click/scroll/open that": grounding via OCR boxes plus UIA (existing `act_on_visible`), still policy-gated.
  "Fix this error": the explanation plus a fix copied to the clipboard, or an edit proposal for a VS Code file
  (a file change, so it asks).
- Fixes the 5 min 39 s `screen.understand` case with a hard 20 s budget.

## Phase W6: Phone remote with full control (HERMES_PLAN P1–P9, build as specified there)
- **P1** Tailscale HTTPS + QR pairing + PIN (Funnel forbidden). **P2** PWA: chat, live progress, approvals.
  **P3** phone push-to-talk plus spoken replies. **P4** live screen view plus keep-awake.
- **P5–P9** (now in the build order, per the owner's "full control" request): tap/pointer, keyboard (Hindi
  too), gestures, clipboard and files. All P5–P9 control rules hold: armed only at the laptop, step-up PIN, a
  red border, the laptop always wins, `Ctrl+Alt+Shift+P` kill, no secure-desktop input.
- The W4 dashboard styles are reused for the PWA.
- **Owner input needed:** install Tailscale on the laptop and phone (same account), and pick a PIN.

## Later ideas (not in this plan's build order; offered after W6)
- Proactive morning briefing by voice (weather, reminders, WhatsApp unread, Night Shift report).
- Teach-by-demonstration ("dekh, aise karte hain" records a new app action).
- Resume App Mastery A7–A16 (VS Code, Explorer, …) on the cloud brain.
- Weekly LoRA (255 of 300 turns).

## Order
W0 → W1 (F1, F2, F4, F5 first: they bring Chutku back; then F6, F7, F3) → W2 → W3 → W4 → W5 → W6.
The F3 wake engine runs alongside, since training is long. Each slice is committed and pushed.

## Verification (end-to-end)
- Full suite: `.venv\Scripts\python.exe -m unittest discover -s tests` green after every slice. `scripts/check_phrases.py` all instant.
- Live redeploy: `Stop-Chutku.cmd` → `Start-ScheduledTask \Chutku\Chutku` → check that the
  `dashboard-session.json` date is fresh → `chutku.cli control resume`.
- `scripts/live_check.py`: seconds plus an independent PASS/WRONG for each case.
- A **real-goal replay set** built from the owner's own failed sentences (After Party, close VS Code, start
  work mode, Bluetooth off, "Spotify ka gaana band karo", WhatsApp to Pita Shri) must pass by voice. The
  results and timings go in `IMPLEMENTATION_STATUS.md`.
- Safety negatives each slice: an owner pause is never auto-cleared; private text never leaves for the cloud;
  phone approvals need the PIN; R4/`runs_code` can't be approved from the phone; Funnel → the remote server stops.
