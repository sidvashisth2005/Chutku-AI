# Prompts given to helper agents

Every prompt I (Claude) have written for a helper agent in this project, word for word, with why it was used and what came of it. **From now on, every new helper-agent prompt is added here when it is used.**

How the work is split:
- Most work is done directly in the main session: reading code, editing, running tests, checking the live Chutku.
- A **helper agent** ("sub-agent") is a separate Claude run with its own context. It does one bounded job and reports back. Here they were used for:
  - wide read-only searches across many files;
  - the three-way audit that produced `docs/MASTER_PLAN.md`;
  - the release reviews.
- Their reports are model output. Their findings were checked in the code before anything was changed.
- A **skill** is a packaged procedure built into Claude Code (here `/code-review` and `/security-review`). It brings its own instructions, so only my input to it is recorded.

| # | Date | Session | Kind | Purpose |
|---|---|---|---|---|
| 1 | 2026-10-04 | `a31db4e2` | agent (Explore) | Investigate random noise being taken as commands |
| 2 | 2026-10-04 | `a31db4e2` | agent (Explore) | Map memory, chat history and learning |
| 3 | 2026-10-05 | `679cd5ba` | agent (Explore) | Full audit, part 1 of 3: the brain and planning stack |
| 4 | 2026-10-05 | `679cd5ba` | agent (Explore) | Full audit, part 2 of 3: the safety kernel and tools |
| 5 | 2026-10-05 | `679cd5ba` | agent (Explore) | Full audit, part 3 of 3: voice, UI, vision, packaging and tests |
| 6 | 2026-10-06 | `679cd5ba` | skill `/code-review` | Code review of everything built since S0 (built-in /code-review skill) |
| 7 | 2026-10-06 | `679cd5ba` | skill `/security-review` | Security review of everything built since S0 (built-in /security-review skill) |
| 8 | 2026-10-06 | `679cd5ba` | agent (general-purpose) | Security review: find exploitable issues |
| 9 | 2026-10-29 | `42e77248` | agent (Explore) | Audit 2026-10-29, part 1 of 3: architecture and request flow |
| 10 | 2026-10-29 | `42e77248` | agent (Explore) | Audit 2026-10-29, part 2 of 3: real-session failures from the logs |
| 11 | 2026-10-29 | `42e77248` | agent (Explore) | Audit 2026-10-29, part 3 of 3: plans, status and test health |

## 1. Investigate random noise being taken as commands

- **When:** 2026-10-04 15:25:02 UTC, session `a31db4e2`
- **Kind:** Agent, type `Explore`; short description "Explore voice noise pipeline"
- **Why it was used:** 2026-10-04. You said Chutku "listens to random noises, picks something up and processes it". Before changing the voice code I needed a map of every way microphone audio becomes a command, with the exact thresholds.
- **What came of it:** Read-only search. Its map led to the wake-listener fixes: noise floor, minimum voiced audio, wake-phrase confidence, and the local heard log `data/heard.jsonl` that shows what Chutku heard and why it ignored it.

**Prompt / input, word for word:**

````text
Project: D:\Project\Chutku (Python Windows voice assistant). The owner reports Chutku "listens to many random noises that aren't there, randomly picks something up, then stops and processes it". I need to understand every path where microphone audio becomes a command, and where noise could be mistaken for speech. Read-only exploration; do not modify anything.

Investigate (medium-thorough):
1. chutku/voice/handsfree.py (WakeListener, wake phrase "Oye Chutku", hotkey path), chutku/voice/whisper_stt.py (transcribe_pcm, Whisper settings: model, language, no_speech / log-prob thresholds, VAD filter, prompt), chutku/voice/recognition.py (LEVEL, listen_command, energy thresholds), chutku/voice/live.py (Gemini Live conversation: how mic audio is streamed, any VAD / realtimeInputConfig / automaticActivityDetection settings, how transcripts become do_task calls, heard_since_question, IDLE_END_SECONDS), chutku/dashboard.py (handsfree_request, start_live, _after_live, _approve_by_voice, _listen_once).
2. For each path report: how speech start/end is detected (energy threshold numbers, silence durations), what gates whether a transcript is accepted (min length, confidence, wake-word matching logic incl. fuzzy matching), known Whisper hallucination handling (e.g. "Thank you.", "you", subtitles text) if any, and what happens with the result (direct command? Live model call?).
3. Whether transcripts / heard text are logged anywhere persistently (files under data/, event log types) so we could audit what was heard.
4. Existing tests for these (tests/test_handsfree.py, tests/test_wake*, tests/test_live*, etc.) and any benchmark scripts (scripts/benchmark_wake.py, scripts/benchmark_stt.py) with their findings.

Report concrete file paths, function names, line numbers, and the exact threshold values/config, plus your assessment of the most likely causes of false triggers and false transcripts.
````

## 2. Map memory, chat history and learning

- **When:** 2026-10-04 15:25:10 UTC, session `a31db4e2`
- **Kind:** Agent, type `Explore`; short description "Explore memory and learning surfaces"
- **Why it was used:** 2026-10-04. You asked Chutku to remember your details and past chats, learn over time, make suggestions and show a "mind map". I needed to know what already existed before building more.
- **What came of it:** Read-only search. It led to the conversation memory (`recall.py`), the mind map tab, suggestions (`suggest.py`) and learning from rephrased requests (`learning.py`).

**Prompt / input, word for word:**

````text
Project: D:\Project\Chutku (Python Windows assistant "Chutku", dashboard in chutku/dashboard.py + chutku/web/index.html + app.js, voice conversation in chutku/voice/live.py using Gemini Live, local LLM planner in chutku/agent_loop.py + chutku/brain_service.py, Gemini cloud planner in chutku/cloud_planner.py). The owner wants Chutku to: remember their details and ALL previous chats' context, learn over time, propose suggestions proactively, and show a "mind map" of what it knows about them. Read-only exploration; do not modify anything.

Map what exists today (medium-thorough):
1. Personal memory: chutku/mind.py (data/mind.json people/facts/lists), chutku/tools/mind_tools.py, chutku/mind_intent.py, chutku/core/memory.py (MemoryStore, data/memory.db, memory.remember/search), chutku/notes.py. How are these fed to planners and to the live voice model? (search default_context, _user_facts, memory_facts, user_facts, past_successes).
2. Learning: chutku/experience.py (data/experience.jsonl, record/similar), any other learning/feedback loops.
3. Conversation history: is any chat/voice conversation persisted (dashboard chat sessions, AgentSessionStore, live transcript, data/last-task.json, event log chutku/core/event_log.py data/chutku.db)? Is previous context re-supplied to the planner or Live model in later sessions? What does LiveConversation send at session start (system instruction, PERSONA, memory)?
4. Proactive features: chutku/health.py (watch, notify toasts), Today panel (/api/today in dashboard.py), briefing, routines (chutku/routines.py), reminders. Any suggestion mechanism?
5. Dashboard UI structure: tabs/sections in chutku/web/index.html and app.js (e.g. Memory tab), how a new panel/tab would be added, API endpoint patterns (_agent_post, GET handlers), CSP constraints.
6. Size/limits: how big is context passed to the local model (CONTEXT_TOKENS in brain_service), Gemini usage/quota handling (data/gemini-quota.json).

Report concrete file paths, function names, line numbers, data formats, and gaps relative to the owner's goals.
````

## 3. Full audit, part 1 of 3: the brain and planning stack

- **When:** 2026-10-05 20:14:18 UTC, session `679cd5ba`
- **Kind:** Agent, type `Explore`; short description "Audit brain/planning/agent stack"
- **Why it was used:** 2026-10-05/06, the start of the master-plan session. You asked for a complete audit of the codebase (flaws, upgrades, new ideas). The code was too large to read in one pass, so three read-only agents audited three areas in parallel.
- **What came of it:** Its findings became the planner and agent-loop items of `docs/MASTER_PLAN.md`: S5 agent-loop correctness, S6 model services, S7 phrase routing, S13 one shared vocabulary.

**Prompt / input, word for word:**

````text
Very thorough exploration of a Windows "Jarvis"-style voice assistant called Chutku at D:\Project\Chutku (Python, ~22.5K lines in chutku/). Read-only. Focus area: the BRAIN / PLANNING / AGENT stack. Files: chutku/brain.py, chutku/brain_service.py, chutku/agent_loop.py, chutku/agent_execution.py, chutku/cloud_planner.py, chutku/gemini.py, chutku/quick_intents.py, chutku/*_intent.py (browser_intent, control_intent, daily_intent, file_intent, input_intent, message_intent, mind_intent), chutku/ensemble.py, chutku/orchestration.py, chutku/planning.py, chutku/plans.py, chutku/learning.py, chutku/recall.py, chutku/experience.py, chutku/suggest.py, chutku/mind.py, chutku/persona.py, chutku/translit.py, chutku/router/catalog.py, chutku/gpu.py, chutku/coder.py, chutku/workflows.py, chutku/routines.py, chutku/runtime.py, chutku/chat.py, chutku/online.py.

I need, with file:line citations:
1. How a user utterance flows end-to-end: input -> intent matching (quick tier) -> local LLM planner (llama.cpp server, Qwen3 GGUF in models/) -> cloud fallback (Gemini) -> tool execution -> reply. Name the key functions/classes at each hop.
2. How the LLM is prompted (prompt construction, grammar/JSON constraints, tool catalog size, few-shot experience reuse, caching of prefix), model selection and timeouts.
3. CONCRETE FLAWS: bugs, race conditions, unbounded growth (jsonl files read fully each turn?), blocking calls on hot paths, duplicated logic across the many *_intent.py modules and quick_intents.py (regex sprawl), brittle regexes, exception swallowing (bare except / except Exception: pass), places where model output is trusted without validation, prompt-injection exposure (web/screen/file text flowing into planner prompts), thread-safety, latency hotspots (re-reading files, re-loading models, re-building catalog per request), hard-coded paths, dead code. Quote the specific lines.
4. What "learning"/"memory"/"recall"/"experience" actually does today (retrieval method: keyword? embeddings?).
5. Any TODO/FIXME/XXX comments.
Report as a structured list. Be specific and factual; don't speculate without saying so. Target ~1500-2500 words.
````

## 4. Full audit, part 2 of 3: the safety kernel and tools

- **When:** 2026-10-05 20:14:29 UTC, session `679cd5ba`
- **Kind:** Agent, type `Explore`; short description "Audit safety kernel and tools"
- **Why it was used:** Same audit. This agent covered authorization, protected zones, taint and the security of every tool.
- **What came of it:** Its findings became S1 (running code always asks), S2 (taint and identity), S3 (network, paths and the action log fail closed), S4 (guard, logs, true safety docs) and part of S15.

**Prompt / input, word for word:**

````text
Very thorough exploration of a Windows "Jarvis"-style voice assistant called Chutku at D:\Project\Chutku (Python). Read-only. Focus area: SAFETY KERNEL, RUNTIME and TOOLS. Files: chutku/policy/kernel.py, chutku/core/*.py (action_control, action_log, approvals, capability_grants, elevation, event_log, execution_lock, memory, operation_journal, paths, preferences, progress, recycle_bin, resource_grants, task), chutku/guard.py, chutku/runtime.py, chutku/tools/registry.py, chutku/tools/builtin.py and every other chutku/tools/*.py (apps_extra, assistant, audio_output, browser, builder, clipboard, desktop_controls, documents, everyday, files_plus, filesystem_extended, free_input, image_vision, internet, mind_tools, net_check, power_controls, processes, reminders, screen, screen_vision, speech, system_controls, uia, uia_actions, windows_apps, windows_settings). Also docs/SECURITY.md for the intended model.

Context from project memory: autonomy modes (review / auto_safe <=R1 / auto_edits <=R2 / OWNER mode which is default and only asks for file modifications, deletions, R4, unknown message recipients, tainted steps). Risk levels R0-R4. Protected zones: Windows, Program Files, ProgramData, AppData, Chutku's own runtime must never be altered. Known open holes noted earlier: process.launch and code.run_python may bypass protected zones; a command guard and a Python audit-hook guard were parked.

I need, with file:line citations:
1. How a tool call is authorized: risk classification, autonomy mode check, capability/resource grants, path guard, elevation guard, approvals, journaling/undo. Is the kernel the single choke point, or can tools be invoked around it?
2. CONCRETE SECURITY FLAWS: fail-open paths, TOCTOU in path checks (symlinks/junctions/8.3 short names/UNC/\\?\ prefixes/case/trailing dots), shell=True or string-built commands (PowerShell/cmd injection), subprocess with untrusted args, code execution tools (code.run_python, scripts) and whether they escape protected zones, "taint" tracking (does content from web/screen/clipboard/files mark later steps as tainted?), dashboard/HTTP auth (CSRF, localhost binding, token), secrets storage (Gemini API key - where/how stored), logs containing sensitive data, message.send to unknown recipients enforcement.
3. Reliability flaws: exception swallowing, missing timeouts on subprocess/HTTP, unbounded logs/db growth, lock files that can go stale (data/execution.lock, guard.lock, guard.running), sqlite usage across threads.
4. Tool inventory: count tools, their risk levels, which are OS-specific hacks (OCR clicking coordinates, hard-coded pixel positions like WhatsApp x≈558).
5. Any TODO/FIXME.
Report as a structured list, quote specific lines. Be factual. Target ~1500-2500 words.
````

## 5. Full audit, part 3 of 3: voice, UI, vision, packaging and tests

- **When:** 2026-10-05 20:14:38 UTC, session `679cd5ba`
- **Kind:** Agent, type `Explore`; short description "Audit voice, UI, tests infra"
- **Why it was used:** Same audit. This agent covered the voice pipeline, dashboard, HUD, vision, packaging and the test and evidence setup.
- **What came of it:** Its findings became S8 (voice fixes), S9 (logging, efficiency, packaging), S10 (neural voice test), S11 (streaming and live page updates).

**Prompt / input, word for word:**

````text
Very thorough exploration of a Windows "Jarvis"-style voice assistant called Chutku at D:\Project\Chutku (Python). Read-only. Focus area: VOICE, UI SURFACES, VISION, PACKAGING and TEST/VERIFICATION INFRA. Files: chutku/voice/*.py (approval, audio_probe, handsfree, heard, live, mic, recognition, session, whisper_stt), chutku/dashboard.py, chutku/web/(index.html, app.js, style.css), chutku/hud.py, chutku/tray.py, chutku/vision.py, chutku/local_vision.py, chutku/tools/screen_vision.py, chutku/tools/image_vision.py, chutku/app.py, chutku/cli.py, chutku/doctor.py, chutku/health.py, chutku/today.py, chutku/autostart.py, chutku/presentation.py, chutku/profiles.py, chutku/evidence.py, chutku/notes.py, chutku/remind.py, Start-Chutku.cmd, Stop-Chutku.cmd, Open-Chutku.cmd, pyproject.toml, requirements.lock, models/manifest.json, tests/ (structure, how they are run, how many, mocking approach), scripts/ (verify_*.py, live_check.py, benchmark_*), benchmarks/, verification/ (what evidence json looks like), .gitignore.

I need, with file:line citations:
1. Voice pipeline: wake word detection method (what library? keyword spotting or STT-and-regex?), VAD, STT (faster-whisper small int8 on CPU, Windows dictation fallback), TTS (what engine/voice?), barge-in/interruption support, latency path, "Gemini Live" usage (chutku/voice/live.py) — what it sends to the cloud.
2. Dashboard: web server framework, port, binding (127.0.0.1?), auth/session token, CSRF, websocket/polling, what the UI shows. HUD/tray implementation (tkinter? pystray?).
3. Vision: OCR engine (Windows OCR?), Qwen3-VL local usage, screenshots sent to Gemini?
4. CONCRETE FLAWS: blocking UI threads, polling loops with sleeps, busy waits, no streaming of LLM output to TTS, missing error handling, hard-coded paths/ports, things that won't work on another PC (portability), packaging gaps (no installer, no git repo, models not versioned), dependency pinning, tests that touch the real system, flaky time-based tests, evidence JSON that goes stale.
5. Test infra: number of test files/tests, how run (unittest), coverage gaps — which chutku modules have NO corresponding test file.
6. Any TODO/FIXME.
Report as a structured list, quote specific lines. Be factual. Target ~1500-2500 words.
````

## 6. Code review of everything built since S0 (built-in /code-review skill)

- **When:** 2026-10-06 17:13:08 UTC, session `679cd5ba`
- **Kind:** Built-in skill `/code-review`
- **Why it was used:** 2026-10-06, release slice S22. The plan requires a review of the whole diff since the S0 baseline before release. This is Claude Code's built-in code-review skill: it runs as its own review agent with built-in instructions. My only input was the review level and the commit range (shown below), so there is no prompt text of mine to record.
- **What came of it:** It found 10 real problems, all fixed with regression tests in `tests/test_review_fixes_s22.py`. Examples: "undo the last task" only undid its last step; a voice approval accepted a transcript without real speech; an old clip of your voice could vouch for someone else's request; "earned autonomy relax" covered a whole folder tree.

**Prompt / input, word for word:**

````text
(skill input) high 11e59eb..HEAD
````

## 7. Security review of everything built since S0 (built-in /security-review skill)

- **When:** 2026-10-06 17:38:03 UTC, session `679cd5ba`
- **Kind:** Built-in skill `/security-review`
- **Why it was used:** Also S22. This built-in skill gives its own instructions (find issues with one agent, then double-check each one). The text below is the scope I gave it.
- **What came of it:** It launched entry 8 below.

**Prompt / input, word for word:**

````text
(skill input) Review 11e59eb..HEAD plus the uncommitted working tree in D:\Project\Chutku (a local Windows assistant). Focus on the new code: chutku/rewind.py, chutku/scheduled.py, chutku/nightshift.py, chutku/timeline.py, chutku/reflex.py, chutku/voice/speaker.py, chutku/core/ledger.py, the dashboard endpoints added (/api/reflexes, /api/voice/enroll, /api/nightshift), chutku/policy/kernel.py, chutku/runtime.py, chutku/agent_loop.py. Report only concrete, exploitable issues.
````

## 8. Security review: find exploitable issues

- **When:** 2026-10-06 17:38:20 UTC, session `679cd5ba`
- **Kind:** Agent, type `general-purpose`; short description "Identify security vulnerabilities"
- **Why it was used:** Part of the security review in entry 7. The skill told me to hand the search to a separate agent with the threat model and exclusions spelled out. I wrote this prompt with the project's real threat model from `docs/SECURITY.md` and the specific attack paths worth checking.
- **What came of it:** It found no high-confidence vulnerabilities, and listed what it checked and why each area holds. It also gave four lower-confidence notes (a bystander's spoken "haan" can approve the owner's own request, and three minor rewind/ledger edges), recorded in IMPLEMENTATION_STATUS.md.

**Prompt / input, word for word:**

````text
You are a senior security engineer doing a focused security review of a local Windows assistant ("Chutku") at D:\Project\Chutku (Python). Review the changes in `git diff 11e59eb..HEAD` plus the uncommitted working tree (`git diff`), with focus on NEW code: chutku/rewind.py, chutku/scheduled.py, chutku/nightshift.py, chutku/timeline.py, chutku/reflex.py, chutku/voice/speaker.py, chutku/core/ledger.py, chutku/tools/schedule_tools.py, chutku/tools/timeline_tools.py, chutku/tools/voice_lock_tools.py, chutku/tools/ledger_tools.py, the dashboard endpoints added in chutku/dashboard.py (/api/reflexes, /api/voice/enroll, /api/nightshift, /api/preferences changes), chutku/policy/kernel.py, chutku/runtime.py, chutku/agent_loop.py, chutku/quick_intents.py, chutku/cli.py (nightshift _ask_running_chutku). Do NOT write or modify any files.

Threat model (from docs/SECURITY.md): same-user Windows assistant, NOT an isolation boundary against other same-user programs. Its job: keep its own actions authorized (PolicyKernel; autonomy modes review/auto_safe/auto_edits/owner; user_only tools can never be chosen by the agent/delegated provenance), verified, logged, reversible; refuse to be steered by content it reads (web pages, chat messages, files, window titles — "tainted"/"suspicious" sessions must ask before acting). The dashboard binds 127.0.0.1 with a per-launch token and Origin checks. Relevant attacker: content Chutku reads (web page/message/file/window title/OCR) trying to make Chutku act without the owner's click, or another person's voice near the mic when the voice lock is on. Same-user local malware is out of scope.

OBJECTIVE: identify HIGH-CONFIDENCE security vulnerabilities newly added with real exploitation potential (authorization bypass, injection-driven unauthorized action, privilege/policy bypass e.g. a tainted session scheduling or rewinding things without approval, user_only bypass, path traversal outside grants/protected zones in rewind/undo, command injection in PowerShell calls such as the NightShift task install or SAPI, XSS in the dashboard web UI (chutku/web/app.js renders new data: skills phrases/examples, timeline, voice lock lines — check whether it uses textContent vs innerHTML), data exposure of window titles/voiceprint to Gemini/cloud). Exclusions: DoS, resource exhaustion, rate limiting, secrets on disk, theoretical races, outdated libs, test-only files, log spoofing, regex DoS/injection, docs, lack of audit logs, user content in AI prompts.

Methodology: 1) understand existing patterns (PolicyKernel, Runtime.authorize/run, step_question, TAINT_SENSITIVE_R1, TAINTING_TOOLS/PRIVATE_TOOLS, user_only, approvals binding). 2) compare new code against them. 3) trace data flows from untrusted inputs to sensitive operations. Examples worth checking concretely: Can a tainted/suspicious agent session reach rewind.run, task.schedule, reflex compile, settings.* without CONFIRM? Does a scheduled task replay run with fewer checks than the original order (e.g. loses taint)? Can the reflex compiler learn a skill from a tainted session's goal and later execute it unasked? Do rewind inverses escape protected zones or grant roots (e.g. _root_of derived from journal records)? Does /api/nightshift or /api/voice/enroll lack token/origin checks? Does the cli _ask_running_chutku leak the token? Does the timeline search output reach the Gemini cloud planner?

Output: markdown list of findings, each with file:line, severity (HIGH/MEDIUM), category, description, concrete exploit scenario, recommendation, and your confidence 1-10. Only include findings you're >80% confident are exploitable. If none, say so explicitly.
````

## 9. Audit 2026-10-29, part 1 of 3: architecture and request flow

- **When:** 2026-10-29, session `42e77248`
- **Kind:** Agent, type `Explore`; short description "Map architecture and request flow"
- **Why it was used:** 2026-10-29. You said "this AI isn't working properly" and asked for a check of the complete codebase. I had already found that actions were paused and the wake word had never fired. I needed the exact path of a request (wake, hotkey, typed) and the pause/heartbeat behaviour, with file:line references.
- **What came of it:** It mapped every hop, from `serve()` through `begin_session`, `AgentSession`, `Runtime` and `SpeechQueue`. It confirmed the following:
  - a guard stop pauses actions until a typed resume;
  - the marker always says "by the user";
  - paused voice requests get no spoken reply;
  - `WAKE_PROMPT` is echoed back by Whisper (44 exact echoes);
  - none of the 5,071 ignored lines resembles "Chutku".
  These became plan items F1 and F2 in Phase 4 (`docs/WORLD_CLASS_PLAN.md`).

**Prompt / input, word for word:**

````text
Repo: D:\Project\Chutku — "Chutku", a local Windows voice/desktop AI assistant (Python, llama.cpp Qwen3-4B local brain, optional Gemini, faster-whisper STT, Kokoro TTS, dashboard, policy kernel). Thoroughness: very thorough, but read-only.

I need a concise architecture map so I can plan fixes. Report:
1. The end-to-end path of ONE request from (a) voice wake word, (b) the Ctrl+Alt+Space hotkey, (c) typed dashboard chat → to the planner → tool execution → reply/TTS. Name the exact modules/functions at each hop (e.g. chutku/voice/*, chutku/runtime.py, chutku/agent_loop.py, chutku/quick_intents.py, chutku/router/*, chutku/core/*, chutku/brain_service.py, chutku/dashboard.py).
2. Which processes/services run live (guard, core, brain llama-server, voice service, dashboard, tray, HUD) and how they're started (Start-Chutku.cmd, scheduled task \Chutku\Chutku, chutku/cli.py). What is the heartbeat and what does 'heartbeat_timeout' do — data/guard-last-stop.json shows reason heartbeat_timeout on 2026-10-28 and data/actions.paused says "Actions paused by the user. Resume explicitly." Find who writes actions.paused and what happens to requests while paused (do they silently fail?).
3. The wake word path: how is 'Oye Chutku' detected (Whisper transcribe-everything vs a wake detector), where is the 'confidence' / 'level' in data/heard.jsonl computed, what the thresholds are, and what the "wake detector (gated, off until it passes)" from the last commit is. Note: data/heard.jsonl has 5071 entries since 2026-10-23, ALL with decision 'ignored', and one heard text is literally "kholo, chalao, batao, open, search, time." — find whether that is an initial_prompt for Whisper being hallucinated back.
4. Size map: list the largest modules by line count (top 25) and the number of tools registered (find the tool registry/catalog and count tools).
Keep the report under ~900 words with file:line references.
````

## 10. Audit 2026-10-29, part 2 of 3: real-session failures from the logs

- **When:** 2026-10-29, session `42e77248`
- **Kind:** Agent, type `Explore`; short description "Mine real-session failures from logs"
- **Why it was used:** The same audit. Your real sessions, not the test runs, show what fails. I needed numbers and examples from `data/` without reading 700 KB of logs into the main session.
- **What came of it:** It found that real voice use peaked on 10-06 and stopped after 10-24. Its failure taxonomy:
  - the talk mode claimed things it hadn't done (Bluetooth, Spotify);
  - STT mishearing (19 foreign-language turns, hotkey failed 13 of 31);
  - Spotify "After Party": 0 of 15;
  - wrong tools or refusals;
  - pause and heartbeat stops.
  Latency: local model median 14.7 s and p90 58 s by voice; Gemini median 85 s by voice. It also found 25 frustration turns. Night Shift replay "passes" on only 2 goals. These became plan items F4–F7 and W2.

**Prompt / input, word for word:**

````text
Repo: D:\Project\Chutku — "Chutku", a local Windows voice assistant. The owner says "this AI isn't working properly". Read-only investigation of the REAL usage logs to find what actually fails. Thoroughness: very thorough.

Files (in D:\Project\Chutku\data): conversations.jsonl (154 KB), actions.log.jsonl (400 KB), experience.jsonl, feedback.jsonl, last-task.json, scheduled.json, reflexes.json, suggestions.json, logs/chutku.log, nightshift/ (folder), and chutku.db / ledger.db (SQLite — you may query with python's sqlite3 read-only via `python -c` using uri 'file:...?mode=ro', list tables first). Use python one-liners to aggregate; don't dump whole files.

Report:
1. Timeline: date range of real owner requests; requests per day for the last 3 weeks; when usage dropped off.
2. The owner's last ~60 real requests (goal text, path: instant/quick vs model/planner vs Gemini, status, elapsed seconds, reply). Show them compactly.
3. Failure taxonomy: group failures/wrong answers/timeouts/refusals/'I can't'/approval asks/hallucinated success into categories with counts and 2-3 concrete examples each (quote the goal + what Chutku did). Look especially for: slow model responses (>15 s), planner picking the wrong tool, claims of success that didn't happen, Hindi/Hinglish misunderstanding, app actions failing (Spotify/WhatsApp/Brave/YouTube), approvals that annoyed the owner, pause/heartbeat problems.
4. Latency stats: median/p90 time for instant vs model-planned requests.
5. Errors/tracebacks in logs/chutku.log and the nightshift folder (latest nightshift report contents and whether regression replay passes).
6. Anything that suggests the owner gave up (repeated rephrasings, angry/frustrated messages, 'stop', 'kuch nahi hota', etc.).
Keep the report under ~1000 words, concrete, with numbers.
````

## 11. Audit 2026-10-29, part 3 of 3: plans, status and test health

- **When:** 2026-10-29, session `42e77248`
- **Kind:** Agent, type `Explore`; short description "Audit plans, status and test health"
- **Why it was used:** The same audit. Before proposing upgrades I needed to know:
  - which planned slices are done or open;
  - what the ledger records as broken or parked;
  - which flagship features are actually switched on;
  - the state of the test suite and the dashboard.
- **What came of it:** It reported:
  - A0–A6 and H1–H8 are done; A7 is next; P1–P4 were skipped.
  - The latest full run was 1,111 tests OK (10-12).
  - Voice Lock was never enrolled, and Timeline is off.
  - Several docs have stale counts.
  - The dashboard is plain (93-line HTML, 101-line CSS, 0-byte icon).
  This shaped the "wow" options I put to you and Phase W4.

**Prompt / input, word for word:**

````text
Repo: D:\Project\Chutku — "Chutku", a local Windows voice assistant (Python). Read-only audit of the project's planning/status docs and feature inventory. Thoroughness: medium-to-thorough.

Read: IMPLEMENTATION_STATUS.md (latest ~300 lines, it's a ledger), docs/MASTER_PLAN.md, docs/HERMES_PLAN.md, docs/APP_MASTERY_PLAN.md, docs/MARK_PARITY.md, docs/OWNER_GUIDE.md (skim), README.md, docs/ROADMAP.md.

Report:
1. For HERMES_PLAN (H1–H30) and APP_MASTERY_PLAN (A0–A16): which slices are ticked done vs not done; what's the next unticked slice; what is parked and why.
2. Open problems / known-broken items / 'unverified' / 'parked' / 'owner-only' items explicitly recorded in IMPLEMENTATION_STATUS.md and docs (list them with one line each).
3. The current user-facing feature inventory as a compact grouped list (voice, apps, files, web, messaging, memory, scheduling, dashboard, coding, vision, etc.), marking which are verified live vs unit-tested only.
4. What 'wow'/flagship features exist already (Reflex Compiler, Earned Autonomy, Causal Rewind, Voice Lock, Night Shift, Timeline, etc.) and whether they are actually enabled in data/preferences.json (handsfree_mode owner, timeline false, voice_lock false...).
5. Test suite shape: number of test files in tests/, any tests marked skip/expectedFailure, and the most recent recorded full-suite result in IMPLEMENTATION_STATUS (count, pass/fail, date).
6. The dashboard UI: what tech it uses (chutku/dashboard.py, chutku/web/*) and what it looks like (pages/panels), roughly how polished.
Keep the report under ~1000 words.
````
