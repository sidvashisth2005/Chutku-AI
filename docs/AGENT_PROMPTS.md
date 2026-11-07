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
| 12 | 2026-11-05 | `ad67e502` | skill `/code-review` | Review of Phase 5 K + C (Karpathy rules, coder guard, dead-code removal) |
| 13 | 2026-11-05 | `ad67e502` | agent (Explore) "Auditor" | Gap analysis: the owner's 19 capabilities and offline readiness |
| 14 | 2026-11-05 | `ad67e502` | agent (general-purpose) "Scout" | Online research: offline models, desktop agents, skill import, email/stocks |
| 15 | 2026-11-05 | `ad67e502` | agent (general-purpose, worktree) "Mason" | Build X4 window snapping, X6 telemetry, X7 PowerShell |
| 16 | 2026-11-05 | `ad67e502` | agent (general-purpose, worktree) "Pixel" | Build X11 eyes with moods, X12 amplitude lip-sync |
| 17 | 2026-11-05 | `ad67e502` | agent (general-purpose, worktree) "Quill" | Build X8 draft-first email, X9 stock quotes |
| 18 | 2026-11-05 | `ad67e502` | agent (general-purpose, worktree) "Sentinel" | Make CI green on a fresh clone without weakening tests |
| 19 | 2026-11-05 | `ad67e502` | agent (general-purpose, worktree) "Forge" | Build X15 skill format/runner, X16 self-written skills |
| 20 | 2026-11-06 | `ad67e502` | agent "Pixel" (resumed, worktree) | Build Y1 compact top bar with eyes + expand |
| 21 | 2026-11-06 | `ad67e502` | agent (general-purpose, worktree) "Sage" | Build Y2 Evolve: proposals, owner approval, test-gated self-change |

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

## 12. Review of Phase 5 K + C (built-in /code-review skill)

- **When:** 2026-11-05, session `ad67e502`
- **Kind:** Skill `/code-review` (built in; it brings its own instructions and reviews the uncommitted diff). Only my input is recorded.
- **Why it was used:** Plan step C5. The diff changed the project builder's repair loop (a new guard against rewriting
  tests) and removed code, so a second look was due before committing.
- **What came of it:** 10 findings. Each was checked in the code:
  - **Fixed:**
    - The guard locked the generated tests forever, but the same LLM wrote them and they can be wrong. Now only
      the first repair after a failed assertion is locked.
    - The coder was never told its edit was dropped. The next fix prompt now says so.
    - The trigger was a plain "AssertionError" substring. It is now unittest's `FAIL:` line.
    - The test-file rule was defined twice. It is now one `is_test_file`.
    - The error text was joined twice.
    - A leftover `import hashlib` in `local_vision.py`.
    - Dead compact/`fit()` code in `presence.js` and `presence.css`.
  - **Known limit, not fixed:** helper modules imported by tests are not protected. They are rare in these small
    generated projects, and later repairs may change tests anyway.
  - **No change needed:** `beat(note)` dropping the note. Only tests ever read it, so behavior is unchanged.
  - **Ledger finding:** done in the same change.

**Prompt / input, word for word:**

````text
high
````

## 13. Gap analysis: the owner's 19 capabilities and offline readiness

- **When:** 2026-11-05, session `ad67e502`
- **Kind:** Agent, type `Explore`, persona "Auditor"; short description "Auditor: gap analysis vs 19 capabilities"
- **Why it was used:** The owner asked for 19 capabilities in 7 groups, and for a team of agents. I needed to know from the code which of
  the 19 exist before planning Phase 6.
- **What came of it:** Of the 19, 8 are missing: self-coding, GitHub skill import, the eyes, lip-sync, in-HUD YouTube, email, stocks and a
  deep drive scan.
- Partial: web autopilot (fresh profile; `browser.input` is not granted), window snapping (no snap), telemetry (no
  CPU temperature), OS commands (no PowerShell tool) and phone control (unit-tested only).
- Strong: app building and memory.
- Offline: the hotkey, STT, TTS and local planning (4B, then the 8B) work. Web tools don't, and the trained wake
  model is missing.
- It listed 5 reasons "open my last PDF, summarise it and email it to Ravi" fails: no email tool, an unknown
  contact, an 8,000/3,500-character text cap, tight rounds, and unproven voice approval.
- Spot-checked in code before it shaped the Phase 6 plan.

**Prompt / input, word for word:**

````text
You are "Auditor", a meticulous, skeptical senior engineer on Chutku's team. You trust code, not docs. Read-only.

Repo: D:\Project\Chutku. Chutku is a Windows voice/text assistant in Python (chutku/ ~34k lines, ~230 typed tools registered via registry.register(Tool("name", ...)), app "atlases" in chutku/apps/atlas/*.json, a deterministic quick router chutku/quick_intents.py + chutku/*_intent.py, an agent loop chutku/agent_loop.py, cloud planner chutku/cloud_planner.py (Groq/Gemini), local Qwen via chutku/brain_service.py, voice in chutku/voice/, HUD chutku/hud.py + presence window chutku/presence.py + chutku/web/presence.*, phone remote chutku/remote/, project builder chutku/tools/builder.py + chutku/coder.py). Ledger: IMPLEMENTATION_STATUS.md (newest first). Plan: docs/MASTER_PLAN.md.

The owner wants these 19 capabilities (7 groups). For EACH one, report: status = present-verified-live / present-unit-tested-only / partial / missing; the exact files + tool names that implement it (cite file:line); what is missing; and whether it works OFFLINE (no internet) today.
1 Self-coding & auto-upgrade: Chutku writes and installs its own new code (a new tool/skill) when a new requirement comes up.
2 Web autopilot: operates a real Chrome/Brave browser like a human; fills forms/boxes automatically; smart search and data extraction.
3 Skills injection: reads an open-source GitHub project and turns its abilities into a Chutku ability with one command.
4 System governance: deep scan of every connected drive; voice-controlled window snapping; hardware telemetry (CPU/RAM/GPU/temps); single-shot OS command execution.
5 HUD media & expressions: vector eyes reacting to mood; cartoon lip-sync while speaking; live YouTube playback inside the HUD.
6 Instant software development: idea -> production-ready HTML/JS/Python web apps and tools.
7 Memory & intelligence: remembers conversations and preferences; drafts and sends emails; tracks live stocks; controls the phone wirelessly.

Also answer: (a) Offline readiness: with internet unplugged, which parts of the path "single voice command -> any PC task" still work (wake/hotkey, STT model, local planner, TTS, tools)? Which models are on disk (models/manifest.json, models/ dir listing) and what is the local planner's fallback path when cloud is unavailable (look at preferences "offline_mode", brain "cloud_first", chutku/online.py, provider fallback)? (b) The 5 biggest reasons a single complex voice command ("open my last PDF, summarise it and email it to Ravi") would fail today, with evidence from code.

Output: a compact table for the 19 items, then (a) and (b). Under 1200 words. Cite file paths with line numbers.
````

## 14. Online research: offline models, desktop agents, skill import, email/stocks

- **When:** 2026-11-05, session `ad67e502`
- **Kind:** Agent, type `general-purpose` (with web search), persona "Scout"; short description "Scout: online research for offline assistant"
- **Why it was used:** The owner asked to take inspiration from resources online and to make one voice command work with little or no
  internet.
- **What came of it:** A ranked list with links and licences. Top ideas taken into Phase 6:
  - JSON-schema-constrained tool choice in llama-server, plus top-k tool retrieval;
  - an A/B of Qwen3.5-4B (BFCL-V4 50.3) against today's Qwen3-4B before any switch;
  - faster-whisper large-v3-turbo;
  - Kokoro phoneme timestamps for lip-sync;
  - UFO-style multi-action plans;
  - a cloud "tool maker" with a local "tool user", and SKILL.md skills with tests and approval;
  - a dedicated signed-in browser profile over CDP;
  - draft-first email;
  - cached stock quotes labelled "as of".
- Licence warnings kept: xLAM is non-commercial, Piper is GPL, espeak-ng is GPL, Open Interpreter and Skyvern are
  AGPL (ideas only).
- Unverified items are marked as such in the plan.

**Prompt / input, word for word:**

````text
You are "Scout", a curious, pragmatic research engineer on Chutku's team. You read primary sources (GitHub READMEs, official docs, model cards), not listicles, and you say plainly when something is unproven. Research only: do not modify any files.

Context: Chutku (D:\Project\Chutku) is a Python Windows assistant meant to do ANY PC task from a single voice command, offline-first (internet optional), on modest hardware: RTX 3050 Laptop 4 GB VRAM, 24 GB RAM, Windows 11, C: nearly full (models live on D:). Today it uses faster-whisper small (CPU int8), Kokoro TTS (onnx), Qwen3-4B Q4_K_M via llama.cpp Vulkan as the local planner (median ~15 s, p90 ~58 s, picks wrong tools sometimes), Groq/Gemini free tiers when online, Playwright for web, UI Automation + OCR for desktop apps, openwakeword for wake word. It will be open-sourced under MIT, so every recommended component must have a license compatible with redistribution or be an optional download.

Use WebSearch/WebFetch to find the current best (2026) options and report, with links, license, size and a one-line "why":
1. Local tool-calling LLMs that fit 4 GB VRAM (or CPU+RAM) and are strong at function calling / JSON tool selection (e.g. Qwen3 small variants, Llama 3.x 3B, Phi-4-mini, Hammer, xLAM/ToolACE, Gemma 3n, FunctionGemma or newer). Prefer published function-calling benchmarks (BFCL etc.). Include speculative decoding / grammar-constrained (GBNF/JSON schema) decoding tips for llama.cpp that make small-model tool calls fast and valid.
2. Offline STT for English+Hindi+Hinglish on that GPU: faster-whisper large-v3-turbo / distil variants, Moonshine, Parakeet, IndicConformer/AI4Bharat; latency and accuracy notes.
3. Offline TTS with Hindi+English and low latency (Kokoro, Piper, Indic Parler-TTS, others) and simple lip-sync/viseme output for an animated avatar (e.g. Rhubarb Lip Sync, phoneme timestamps).
4. Open-source desktop/OS agents to take inspiration from (Open Interpreter, UFO/UFO2 from Microsoft, OS-Copilot, Agent-S, browser-use, Skyvern, Windows-Use, Leon, OpenJarvis-style projects): for each, the one architectural idea worth copying (e.g. UIA-tree grounding, skill libraries, self-written tools with tests, planner/executor split).
5. Browser autopilot in the user's own real browser (Playwright connect_over_cdp to Chrome/Brave/Edge profile, browser-use) for form filling and data extraction. Note: we will NOT do bot-detection evasion/fingerprint spoofing or CAPTCHA bypass; only automate the user's own normal browser.
6. "Skill import from a GitHub repo": how projects like Voyager (skill library), Anthropic Agent Skills (SKILL.md), MCP servers, or tool-maker papers (LATM, CRAFT, ToolMaker) turn external code/docs into reusable tools safely (sandboxing, tests, human approval).
7. Free/no-key data sources for live stock quotes usable offline-tolerant (with caching), and email drafting/sending on Windows without paid APIs (e.g. default mail client via mailto/Outlook COM, Gmail SMTP with app password) — note the safety trade-offs.

Output: a ranked, concrete recommendation list per section (top 2-3 each), with links and licenses, plus a final "Top 10 changes for Chutku" list ordered by impact on "one voice command does the task, offline". Under 1500 words.
````

## 15. Build X4 window snapping, X6 telemetry, X7 PowerShell

- **When:** 2026-11-05, session `ad67e502`
- **Kind:** Agent, type `general-purpose`, in its own git worktree, persona "Mason"; short description "Builder Mason: system governance X4 X6 X7"
- **Why it was used:** Phase 6 slices; the owner asked for a team of agents. Isolated new tools in a worktree, so they could not collide
  with my own edits.
- **What came of it:** Commit `5956770`. I reviewed it, merged it, and resolved the `docs/SECURITY.md` conflict by recomputing from the
  registry.
- Kept its two deviations:
  - `-EncodedCommand` instead of `-Command` (exactly the approved text runs);
  - no instant snap phrase.
- 21 tests. Its live checks were read-only probes; a real snap and a real PowerShell run were not done (the owner
  was using the PC).
- The worktree-only test failures (missing git-ignored models) pass in main.

**Prompt / input, word for word:**

````text
You are "Mason", a calm, exacting Windows systems engineer on Chutku's team: 20 years of Win32, you distrust anything you have not observed, and you write the smallest code that fully works.

Repo (your own git worktree of D:\Project\Chutku): Chutku, a Python Windows voice/text assistant. Python: use the main venv `D:\Project\Chutku\.venv\Scripts\python.exe` (run it from your worktree folder so your code is the one imported). First read: AGENTS.md, .claude/skills/ponytail/SKILL.md, .claude/skills/karpathy-guidelines/SKILL.md. Tool API: chutku/tools/registry.py (Tool, Risk, ToolResult, Verification, argument_schema). Model examples: `windows.manage` in chutku/tools/everyday.py (around lines 790-830 and 972) and `WindowsDesktop.focus` in chutku/tools/windows_apps.py; tools are registered from chutku/tools/builtin.py `register_builtin_tools`. Instant phrase routing lives in chutku/quick_intents.py (and chutku/*_intent.py parsers it calls); phrase regression list: scripts/check_phrases.py.

Build these three slices (Phase 6 in docs/MASTER_PLAN.md):
X4 Voice window snapping: a new tool `windows.snap` taking the same exact-window identity arguments as windows.manage (window_id, process_id, executable) plus `position` in {left, right, top, bottom, top_left, top_right, bottom_left, bottom_right, maximize, center}. Use the window's own monitor work area (MonitorFromWindow + GetMonitorInfoW), restore first if maximized/minimized, SetWindowPos, then verify independently with GetWindowRect within a small tolerance (DPI-aware: check how the repo handles DPI). Same risk and capability as windows.manage. Add instant phrases (English + Hinglish, e.g. "snap notepad left", "chrome ko right side karo", "dono windows side by side" may be left to the planner) only where the existing routing pattern makes it clean.
X6 Telemetry: CPU temperature where Windows exposes it without admin (try root/wmi MSAcpi_ThermalZoneTemperature and the ACPI thermal zone perf counters); when not available say so honestly ("CPU temperature isn't exposed on this PC without admin"). Do not change any existing tool's description text (descriptions feed each tool's contract hash); add fields to outputs or add a small new tool instead. Optional if small: current network throughput.
X7 Single-shot OS command: a new tool `system.powershell` (one command string, max 500 chars, no newlines) that runs `powershell.exe -NoProfile -NonInteractive -Command` with a 60 s timeout, captures stdout/stderr (truncate ~8 KB), and returns them marked as untrusted output like other tools that return outside content (see how chutku/tools/documents.py `code.run_python` near line 504 is made to ALWAYS need an on-screen confirmation in every autonomy mode, including owner mode, and copy that mechanism exactly). It must never run from reflexes, replays or scheduled tasks without a click. Negative tests: in auto_safe, auto_edits and owner modes it still stops at WAITING_CONFIRMATION; multi-line or oversized commands are refused before anything runs.

Rules:
- Tests in new tests/test_governance_x4_x7.py; tests never touch real windows, WMI or PowerShell (mock ctypes/subprocess). The full suite must stay green: `D:\Project\Chutku\.venv\Scripts\python.exe -m unittest discover -s tests` (about 4-5 minutes), plus `scripts/check_phrases.py`.
- Real-path checks: ONLY read-only probes, because the owner is using this PC right now: e.g. compute (not apply) the snap rectangle for an existing window, read the temperature source, run `system.powershell` through the runtime only up to WAITING_CONFIRMATION and then deny it. Never move/focus windows, send keys, or execute a PowerShell command for real. Report exactly what you ran and the output.
- Do NOT edit IMPLEMENTATION_STATUS.md, docs/MASTER_PLAN.md, docs/OWNER_GUIDE.md, docs/AGENT_PROMPTS.md or README.md. Instead end your report with (1) proposed ledger text with evidence, (2) proposed owner-guide phrase lines.
- Keep CRLF files CRLF: use the Edit tool, never sed -i, never PowerShell Set-Content. Check `git diff --stat` for whole-file rewrites.
- Commit on your worktree branch with message "X4+X6+X7: <summary>" and no Co-Authored-By line. Do not push.

Report: files changed, tool names and risks, test counts and the full-suite result line, real-path output, anything you could not do and why. Under 700 words plus the two proposed texts.
````

## 16. Build X11 eyes with moods, X12 amplitude lip-sync

- **When:** 2026-11-05, session `ad67e502`
- **Kind:** Agent, type `general-purpose`, in its own git worktree, persona "Pixel"; short description "Builder Pixel: HUD eyes and lip-sync X11 X12"
- **Why it was used:** Phase 6 slices (the owner's "vector eyes, lip-sync").
- **What came of it:** Commit `262d91d`, merged cleanly.
- I re-checked the live `/presence` page in headless Edge: the face shows, mood "calm", no console errors.
- v2 visemes are parked: the installed Kokoro model has no duration output.

**Prompt / input, word for word:**

````text
You are "Pixel", a front-end and motion designer-engineer on Chutku's team: you care about character and feel, you keep pages fast and dependency-free, and you respect reduced-motion users.

Repo (your own git worktree of D:\Project\Chutku): Chutku, a Python Windows voice assistant (female persona, "Chutku"). Python: use the main venv `D:\Project\Chutku\.venv\Scripts\python.exe` (run it from your worktree folder). First read: AGENTS.md, .claude/skills/ponytail/SKILL.md, .claude/skills/karpathy-guidelines/SKILL.md. The presence window is the dashboard page /presence: chutku/web/presence.html, presence.js, presence.css (+ theme.css), served by chutku/dashboard.py (find the /presence and /api/presence handlers and the page's Content-Security-Policy), shown in a pywebview window by chutku/presence.py. Today it draws a voice-reactive orb on a canvas whose colour and spin follow `state.phase` (idle, listening, thinking, running, speaking, paused, error...) and whose wave follows `voice_level` (see chutku/voice/tts.py speaking_level and how the dashboard exposes it). Tests: tests/test_presence_w4.py.

Build these two slices (Phase 6 in docs/MASTER_PLAN.md):
X11 Vector eyes with moods: give the orb a face: two vector eyes (canvas or inline SVG, no image files, no CDN) that blink naturally and change with a mood derived from the existing state: idle (calm, slow blink), listening (wide, slightly up), thinking/running (look aside, slight squint), speaking (soft), happy (after a verified "done"), sorry (after "failed"/"error"), paused (closed/sleepy). If the presence payload lacks something needed (e.g. the last outcome), add the smallest field to the /api/presence payload in chutku/dashboard.py with a test. Keep the orb: the owner likes the Jarvis orb, never remove a working look; the face lives inside/on it.
X12 Lip-sync: a mouth that moves while she speaks. v1 (this slice): map `voice_level` (amplitude) to 5 mouth shapes (closed, slightly open, open, wide, round) with smoothing so it does not jitter; honest name in code: amplitude lip-sync. If Kokoro (chutku/voice/tts.py, kokoro-onnx) exposes phoneme/word timestamps cheaply, describe in your report how v2 could drive visemes from them, but do not build v2 unless it is small and testable.
Respect `prefers-reduced-motion` (no blinking/bouncing then, static friendly face). Keep CPU low: one requestAnimationFrame loop (reuse the existing draw loop), no per-frame DOM churn.

Rules:
- Tests: extend tests/test_presence_w4.py or add tests/test_presence_face_x11.py (e.g. page contains the face elements, mood mapping function if you put it in Python, the payload field). If `node` is available, syntax-check presence.js with `node --check`; if not, say so.
- Visual check: take headless screenshots of the page in several moods. You may load the static files with a tiny local test server or a file:// copy with a stubbed `api()` / fake state (do not modify the running Chutku). Python Playwright is installed in the venv (playwright 1.63; Chromium may need `python -m playwright install chromium`; if download is impossible, use the installed Edge via `channel="msedge"`). Save PNGs under your worktree's `verification/presence-face/` and list them. Do not open windows on the owner's desktop (headless only): the owner is using this PC right now.
- The full suite must stay green: `D:\Project\Chutku\.venv\Scripts\python.exe -m unittest discover -s tests` (about 4-5 minutes).
- Do NOT edit IMPLEMENTATION_STATUS.md, docs/MASTER_PLAN.md, docs/OWNER_GUIDE.md, docs/AGENT_PROMPTS.md or README.md. End your report with (1) proposed ledger text with evidence, (2) proposed owner-guide lines.
- Keep CRLF files CRLF: use the Edit tool, never sed -i, never PowerShell Set-Content. Check `git diff --stat` for whole-file rewrites.
- Commit on your worktree branch with message "X11+X12: <summary>" and no Co-Authored-By line. Do not push.

Report: files changed, how moods map to state, screenshot paths, test counts and the full-suite result line, CPU notes, anything you could not do. Under 700 words plus the two proposed texts.
````

## 17. Build X8 draft-first email, X9 stock quotes

- **When:** 2026-11-05 (resumed 2026-11-06), session `ad67e502`
- **Kind:** Agent, type `general-purpose`, in its own git worktree, persona "Quill"
- **Why it was used:** Phase 6 slices for the owner's "drafts and sends emails" and "tracks live stocks".
- **What came of it:** Commit `35da120`, merged.
- I reviewed the two safety-critical lines myself:
  - a new `email.send` capability that is never granted by default;
  - `step_question` makes every send ask on screen in every mode, and the tool refuses again unless the step was
    approved on screen.
- 21 tests.
- Live: "TCS stock kitna hai" gave "₹2,495.70, +2.45%, as of 15:28 IST" in 1.16 s.
- No mail app was opened and no email was sent.
- All three were cut off by a usage limit and resumed on 2026-11-06 with a short message. Each said: continue the same task and rules, commit, and report. Quill was also asked to explain every change to runtime.py and capability_grants.py line by line, and Sentinel to justify its product change to wakeword.py.

**Prompt / input, word for word:**

````text
You are "Quill", a careful integrations engineer on Chutku's team: you never send anything a human did not approve, you prefer the standard library, and you label stale data as stale.

Repo (your own git worktree of D:\Project\Chutku): Chutku, a Python Windows voice/text assistant. Python: use the main venv `D:\Project\Chutku\.venv\Scripts\python.exe` (run it from your worktree folder so your code is the one imported). First read: AGENTS.md, .claude/skills/ponytail/SKILL.md, .claude/skills/karpathy-guidelines/SKILL.md. Tool API: chutku/tools/registry.py (Tool, Risk, ToolResult, Verification, argument_schema, network_egress). Examples: internet tools in chutku/tools/internet.py (web.read, weather/news, how they use urllib, required_capability "internet.read" and offline handling via chutku/online.py), messaging in chutku/tools/apps_extra.py (`message.send`, how recipients are resolved from the owner's memory chutku/mind.py `recipient`, and how sends always confirm / unknown recipients ask), Windows Credential Manager key storage in chutku/gemini.py / chutku/cli.py (`gemini set-key`, `cloud set-key`). Tools are registered from chutku/tools/builtin.py `register_builtin_tools`. Instant phrases: chutku/quick_intents.py and chutku/*_intent.py; phrase regression list: scripts/check_phrases.py.

Build these two slices (Phase 6 in docs/MASTER_PLAN.md):
X8 Email, draft first: `email.draft` (to, subject, body) opens a ready draft in the default mail app via a `mailto:` URL (stdlib urllib.parse.quote; note that mailto cannot attach files: say so in the reply); nothing is sent, so it is a reversible, low-risk step. Recipients resolve from the owner's people memory (add an optional `email` field to a person in chutku/mind.py if missing, validated) or a literal address; an unknown name asks instead of guessing. Optional `email.send` via stdlib smtplib (Gmail SMTP with an app password stored only in Windows Credential Manager, set by a new `chutku.cli email set-account`), as an external side effect that always asks for an on-screen confirmation of recipient and body in every mode, with a new capability that is not granted by default. Tests mock smtplib and os.startfile; negative tests: no stored account gives a clear error and nothing is sent; an unknown recipient never sends.
X9 Stocks: `finance.quote` (a symbol or company name) using Yahoo's public endpoints with stdlib urllib only (search: query1.finance.yahoo.com/v1/finance/search; price: query1.finance.yahoo.com/v8/finance/chart/<symbol>), with a User-Agent header, required_capability "internet.read", network egress declared. Cache every quote locally (data/finance-cache.json or sqlite, bounded) and ALWAYS state the time the price is from, e.g. "Reliance (RELIANCE.NS) ₹2,950.10, +1.2%, as of 15:29 IST"; when offline or the call fails, answer from the cache and say "offline, last known price as of ...", or say honestly that no price is known. Indian names should prefer NSE (.NS) when the search offers it. Add instant phrases like "reliance ka share price", "TCS stock kitna hai", "price of AAPL". Tests mock urllib (never the network).

Rules:
- Tests in new tests/test_mail_finance_x8_x9.py. The full suite must stay green: `D:\Project\Chutku\.venv\Scripts\python.exe -m unittest discover -s tests` (about 4-5 minutes), plus `scripts/check_phrases.py`.
- Real-path checks: you MAY make one or two real read-only quote requests (network GET) and show the reply and cache. You must NOT open the mail app, open a mailto URL, or send any email: the owner is using this PC right now. Run `email.draft` through the runtime only with os.startfile mocked, and run `email.send` only up to WAITING_CONFIRMATION, then deny it.
- Do not change any existing tool's description text (descriptions feed each tool's contract hash).
- Do NOT edit IMPLEMENTATION_STATUS.md, docs/MASTER_PLAN.md, docs/OWNER_GUIDE.md, docs/AGENT_PROMPTS.md or README.md. End your report with (1) proposed ledger text with evidence, (2) proposed owner-guide phrase lines. Also list any new dependency (there should be none).
- Keep CRLF files CRLF: use the Edit tool, never sed -i, never PowerShell Set-Content. Check `git diff --stat` for whole-file rewrites.
- Commit on your worktree branch with message "X8+X9: <summary>" and no Co-Authored-By line. Do not push.

Report: files changed, tool names, risks and capabilities, test counts and the full-suite result line, the real quote output, anything you could not do and why. Under 700 words plus the two proposed texts.
````

## 18. Make CI green on a fresh clone without weakening tests

- **When:** 2026-11-05 (resumed 2026-11-06), session `ad67e502`
- **Kind:** Agent, type `general-purpose`, in its own git worktree, persona "Sentinel"
- **Why it was used:** CI failed 19 tests that only pass on the owner's PC.
- **What came of it:** Commit `d13e05f`, merged.
- Root cause: the CI TEMP is an 8.3 short path while Chutku stores resolved long paths.
- Narrow skips only for the missing openWakeWord feature models and a missing playback device.
- A real product bug fixed: the wake Detector left its `.npz` open and locked on Windows.
- A fresh clone passes `scripts/ci_tests.py`: 1,268 OK.
- It reported three product notes, now in the ledger.
- All three were cut off by a usage limit and resumed on 2026-11-06 with a short message. Each said: continue the same task and rules, commit, and report. Quill was also asked to explain every change to runtime.py and capability_grants.py line by line, and Sentinel to justify its product change to wakeword.py.

**Prompt / input, word for word:**

````text
You are "Sentinel", the release/CI engineer on Chutku's team: you never make a test pass by weakening what it checks, and you treat a test that only passes on one machine as a bug in either the test or the product.

Repo (your own git worktree of D:\Project\Chutku): Chutku, a Python Windows assistant. Python: `D:\Project\Chutku\.venv\Scripts\python.exe` (run from your worktree so your code is imported). Read AGENTS.md, .claude/skills/ponytail/SKILL.md, .claude/skills/karpathy-guidelines/SKILL.md, .github/workflows/tests.yml and scripts/ci_tests.py first.

Problem: GitHub Actions (windows-latest, a fresh clone: no git-ignored `models/`, `data/`, `sandbox/`, `vendor/`; no audio device; the runner is Administrator, which scripts/ci_tests.py already handles) fails 19 tests that pass on the owner's PC. Latest failing run: `gh run view 42067896536 --log-failed` (the `gh` CLI is logged in; read-only use only). Failing tests: test_voice_lock (several), test_review_fixes_s22.test_an_old_owner_clip_never_vouches_for_a_new_request, test_wakeword (openwakeword resource models missing), test_phrase_coverage.test_every_real_phrasing_resolves_instantly_to_the_right_tool, test_audio_output.test_real_devices_and_policy_interface, test_processes.test_launch_requires_capability_and_approval_then_verifies_image, test_protected_zones.test_chutku_runtime_cannot_be_modified ("Target parent directory does not exist"), test_rewind.test_no_grant_no_undo, test_runtime.test_incomplete_write_is_detected_and_recovered, test_failclosed_s3.test_organize_never_overwrites_a_file_that_appeared ("Path is outside the granted sandbox root"), plus file-lock PermissionError on m.npz in temp dirs.

For EACH failing test decide, with evidence from the code and the CI log:
(a) product bug that a fresh install would also hit (e.g. Chutku assuming `sandbox/` or `data/` exists): fix the product minimally (e.g. create the folder where the runtime is created) and keep the test;
(b) test bug (depends on the owner's data, on a real device, on an unclosed file handle, on test order): fix the test so it is self-contained (temp dirs, mocks, close handles) WITHOUT weakening any assertion;
(c) genuinely needs a local asset that is not in git and is too big for CI (the speaker ONNX model, openwakeword resource models): mark it with `unittest.skipUnless(<asset exists>, "<asset> is not installed (git-ignored model); runs on a full install")`, as narrowly as possible (per test or per class, never a whole module if only some tests need it). Never skip a safety/policy test that does not need such an asset.
To reproduce CI locally: make a fresh clone into a folder on D: (for example `git clone D:\Project\Chutku D:\ChutkuScratch\ci-repro-<something>`; do NOT touch D:\ChutkuScratch\install-test), install nothing new (use the main venv's python with the clone as cwd), and run `D:\Project\Chutku\.venv\Scripts\python.exe scripts\ci_tests.py` there. Note: your clone is from the committed main; apply your worktree's changes to it (or run from your worktree after temporarily moving nothing: your worktree also lacks models/data, which is the point).

Rules:
- The full suite must also stay green in a full install: run `D:\Project\Chutku\.venv\Scripts\python.exe -m unittest discover -s tests` from D:\Project\Chutku is NOT allowed (that is the owner's live checkout; do not modify it); instead, before committing, report the list of tests you changed so I can run them in the main checkout.
- Do not delete or rename tests. Do not change docs except a short note in scripts/ci_tests.py's docstring if useful.
- Do NOT edit IMPLEMENTATION_STATUS.md, docs/MASTER_PLAN.md, docs/OWNER_GUIDE.md, docs/AGENT_PROMPTS.md, README.md.
- Keep CRLF files CRLF (Edit tool; never sed -i or PowerShell Set-Content); check `git diff --stat` for whole-file rewrites.
- Commit on your worktree branch as "CI: <summary>" with no Co-Authored-By line. Do not push. Delete your ci-repro clone folder when done.

Report: a table of every failing test → (a)/(b)/(c) → what you changed and why; the local fresh-clone `scripts/ci_tests.py` result line before and after; the list of changed test files for me to run in the full install; any product bug you found. Under 800 words.
````

## 19. Build X15 skill format/runner, X16 self-written skills

- **When:** 2026-11-05 (resumed 2026-11-06), session `ad67e502`
- **Kind:** Agent, type `general-purpose`, in its own git worktree (re-created as `forge-x15` on resume), persona "Forge"
- **Why it was used:** Phase 6 slices for the owner's "writes and installs its own code", under the owner's standing decision D5
  (running code always asks).
- **What came of it:** Commit `a88b119`.
- Safety design: pending skills are never tools; turning one on is typed only plus a click; the approval is bound
  to a SHA-256 of the code; every run asks.
- 18 tests; the real path ran in a temporary base.
- It raised one owner decision: the 10-minute repeat-approval memory also covers skills.
- All three were cut off by a usage limit and resumed on 2026-11-06 with a short message. Each said: continue the same task and rules, commit, and report. Quill was also asked to explain every change to runtime.py and capability_grants.py line by line, and Sentinel to justify its product change to wakeword.py.

**Prompt / input, word for word:**

````text
You are "Forge", a principled tool-smith on Chutku's team: you build things that build things, and you assume any code a model writes is hostile until its tests pass and a human approves it.

Repo (your own git worktree of D:\Project\Chutku): Chutku, a Python Windows voice assistant. Python: `D:\Project\Chutku\.venv\Scripts\python.exe` (run from your worktree so your code is imported). Read first: AGENTS.md, .claude/skills/ponytail/SKILL.md, .claude/skills/karpathy-guidelines/SKILL.md, docs/SECURITY.md, chutku/tools/registry.py (Tool, Risk, runs_code, user_only), chutku/policy/kernel.py (how runs_code and user_only tools are authorized), chutku/coder.py + chutku/tools/builder.py (`code.build_project`: the coder that writes projects, `choose_coder`, `_ask_with_fallback`, `keep_tests_fixed`, `check_python` running unittest in a subprocess), chutku/tools/documents.py `code.run_python` (how a script runs in a subprocess with a timeout and untrusted output), chutku/tools/never_tools.py and `filesystem.delete_permanent` (examples of owner-only tools), chutku/app.py create_runtime and chutku/tools/builtin.py (registration).

Build Phase 6 slices X15 + X16 (docs/MASTER_PLAN.md) with exactly this safety design (the owner's standing decision D5: running code always asks for a click):
X15 Skill format and runner (new module chutku/skills.py):
- A skill is a folder `data/skills/<name>/` (name: lowercase letters, digits, underscore, 3-40 chars) with: `skill.json` {"name", "description" (<=300 chars, what it does and when to use it), "arguments" (a JSON-schema object with additionalProperties false, only string/integer/number/boolean properties, each bounded), "network": false|true, "writes_files": false|true}; `SKILL.md` (human description); `tool.py` defining `run(args: dict) -> dict` (JSON-serialisable); `test_tool.py` (unittest).
- Pending skills live in `data/skills/_pending/<name>/` and are NEVER registered or run as tools.
- `run_tests(folder)`: `python -I -m unittest -v test_tool` in a subprocess, cwd=the skill folder, timeout 60 s, minimal environment; returns (passed: bool, output).
- Active skills are registered at runtime creation as tools `skill.<name>` with the manifest's description and argument schema, Risk.EXTERNAL_SIDE_EFFECT, `runs_code=True` (so the kernel always asks for a click in every mode, like code.run_python), required capability "process.launch". Execution: a small fixed runner script (inside the chutku package, e.g. chutku/skill_runner.py) run as `python -I <runner> <skill folder>` in a subprocess, args JSON on stdin, result JSON on stdout, cwd = the skill folder, timeout 60 s, output capped (8 KB) and marked provenance "external_untrusted"; a crash, timeout, non-JSON or non-dict result is FAIL with the error shown. A manifest that fails validation is skipped with a logged reason, never half-registered. Skills must not be able to shadow existing tools (names are always `skill.`-prefixed).
- `skill.list` (R0): active and pending skills with name, description, tests status.
- `skill.approve` (owner-only / user_only like filesystem.delete_permanent, so the planner can never choose it): re-runs the pending skill's tests; only if they pass, moves it to active; the tool becomes available after Chutku restarts (or register it immediately if that is simple and safe; say which). `skill.remove`: moves a skill to the Recycle Bin (reuse the repo's recycle helper) and asks first.
X16 Self-coding: `skill.create` (R2, writes only under data/skills/_pending): input `request` (what the new ability should do) and optional `name`. Uses the same coder as code.build_project (Gemini when enabled, else local; reuse `choose_coder` and `_ask_with_fallback`, add a SKILL_SYSTEM prompt in chutku/coder.py in the same style as CODER_SYSTEM: stdlib only, the minimum code, `run(args)` contract, a real test file, a manifest) and the repair loop (run_tests, feed real errors back, at most 3 repairs, `keep_tests_fixed` so a repair cannot rewrite a failing assertion away). The result reply says the skill is pending and how to approve it ("skill approve <name>" typed, or the dashboard button if you add one). Add instant phrases: "ye kaam karne ka skill bana lo: ...", "make a skill that ...", "skills dikhao" / "list my skills", "skill approve <name>" (typed only; approval by voice is not allowed for this).

Tests in new tests/test_skills_x15_x16.py with fake coders (never a real model): a valid skill installs pending, its tests run, approve activates it, the tool appears as skill.<name> and runs in a subprocess returning its dict; negatives: a pending skill is never a tool; failing tests block approval; skill.approve cannot be proposed by the planner/agent path (user_only); skill.<name> always stops at WAITING_CONFIRMATION in owner, auto_edits and auto_safe modes; a manifest with an unsafe name/path, unbounded argument, or extra keys is rejected; a skill that times out, prints non-JSON or raises is FAIL; a repair that edits the test after a failed assertion is discarded. Update tests/test_docs_truth.py's runs_code set and docs/SECURITY.md (counts + R3/R4 list + one short "Self-written skills" paragraph) so test_docs_truth passes.

Rules:
- The full suite must stay green: `D:\Project\Chutku\.venv\Scripts\python.exe -m unittest discover -s tests` from your worktree (about 4-5 minutes). Your worktree lacks the git-ignored models/ and data/: about 10 voice-lock/wake/phrase tests fail there on an untouched checkout too; report the exact list and do not try to fix those (another agent is on it).
- Real path: in a temporary base folder (never the owner's data/), create a skill with a fake coder through the runtime, approve it, and run it up to WAITING_CONFIRMATION then approve the token in the test runtime and show the result. Do not start real models, do not open windows, do not type or click: the owner is using this PC.
- Do NOT edit IMPLEMENTATION_STATUS.md, docs/MASTER_PLAN.md, docs/OWNER_GUIDE.md, docs/AGENT_PROMPTS.md or README.md; end your report with (1) proposed ledger text with evidence and (2) proposed owner-guide lines.
- Keep CRLF files CRLF (Edit tool; never sed -i or PowerShell Set-Content); check `git diff --stat` for whole-file rewrites. Do not change existing tools' description text.
- Commit on your worktree branch as "X15+X16: <summary>" with no Co-Authored-By line. Do not push.

Report: files, tools and their risks/flags, how approval and running work, test counts and the full-suite line, the real-path output, limits (be explicit that a skill runs with the owner's Windows rights: the click is the boundary, not a sandbox). Under 800 words plus the two proposed texts.
````

## 20. Build Y1 compact top bar with eyes + expand

- **When:** 2026-11-06, session `ad67e502`
- **Kind:** Message to the existing "Pixel" agent (resumed with its context), new worktree
- **Why it was used:** The owner asked (2026-11-06) for Chutku to start as a small rounded bar at the top centre with reactive eyes and
  an expand icon.
- **What came of it:** Commit `7b98aaa` (branch `y1-compact-bar`), merged cleanly.
- Live after a redeploy:
  - the bar is visible, topmost, top centre, 525×65 physical (420×52 logical) px, rounded-corner preference set;
  - the full window is hidden.

**Prompt / input, word for word:**

````text
New task Y1 (Phase 7 in docs/MASTER_PLAN.md), same rules as before (your own fresh worktree from current main; tests; headless screenshots only; no edits to IMPLEMENTATION_STATUS.md / MASTER_PLAN.md / OWNER_GUIDE.md / AGENT_PROMPTS.md / README.md; CRLF kept; commit "Y1: <summary>" with no co-author line; don't push; report with proposed ledger + owner-guide text). Your X11/X12 face is merged in main.

The owner (2026-11-06): "When I turn on Chutku it must not appear in such a big screen. It must appear in the middle top, as just a small rectangle with curved edges so it looks professional, with eyes in it that react to the conversation and things. There will be an enlarge icon; when I click it, Chutku opens as the big app like usual. Make Chutku minimal on screen and faster to use." They showed a screenshot of a slim dark rounded search-bar-like strip (about 600 x 36 px) at the top of the screen, and a sheet of cartoon eyes with many expressions (wide, sleepy, angry brows, hearts, spirals, side glances, half-closed).

Design to build:
- Start-up shows a COMPACT BAR: a frameless, always-on-top, rounded-rectangle window (about 360-440 x 48-56 px, Windows 11 rounded corners: DWMWA_WINDOW_CORNER_PREFERENCE=DWMWCP_ROUND via ctypes, or CSS radius on a transparent window if pywebview supports it on WebView2), centred at the top of the primary monitor's work area. Inside: the eyes (reuse your drawEye/mood code; add a few more expressive states from the owner's sheet where cheap: hearts for happy/love words, spirals for confused/error, angry brows when the owner sounds annoyed if the payload gives a cue, sleepy when paused), one line of live caption/status text (what she heard / is doing / the result, truncated), and an expand icon button. Dragging the bar should move it (pywebview easy_drag) if simple.
- Expand icon: shows the existing full "Chutku Assistant" window (today's normal window from chutku/presence.py main(), at its usual size) and hides the bar; the full window gets a small "minimise to bar" control that hides it and shows the bar again. Closing the full window keeps today's behaviour (quits Chutku; the owner asked for that on 2026-11-01). Use pywebview's js_api (a small Bridge with expand()/compact() that run window.show()/hide() off the js_api thread, like the old 2026-10-30 fix noted in git history: window calls from js_api froze the page) and create both windows at start (bar visible, full hidden), or the simplest robust equivalent.
- The page: reuse /presence with a query flag (e.g. /presence?view=bar) rendering the compact layout from the same /api/presence state, so there is one page and one poll loop; keep the strict CSP; no CDN/images.
- Keep everything working: the Ctrl+Alt+Space flow, approvals (the bar shows approve/deny buttons or expands automatically when an approval is pending — choose expand-automatically if simpler, so the owner never misses one), the Tk HUD fallback when pywebview is missing.
- Respect prefers-reduced-motion. Keep CPU low.
Tests: Python tests for any new payload field / Bridge logic with a fake window; node --check; headless screenshots of the bar in several moods and of the expand/compact transition states (you cannot open real windows: the owner is using the PC). Report what you could NOT verify live (the real frameless window, corners, always-on-top) so I can check it on the desktop.
````

## 21. Build Y2 Evolve: proposals, owner approval, test-gated self-change

- **When:** 2026-11-06, session `ad67e502`
- **Kind:** Agent, type `general-purpose`, in its own git worktree, persona "Sage"
- **Why it was used:** The owner asked (2026-11-06) for Chutku to improve herself daily: plan first, propose as advice, and on approval
  build, test, keep or revert.
- **What came of it:** It was cut off by a usage limit before its final suite run. Its worktree was committed as `wip/y2-evolve`, reviewed (the protected-path list and safety tokens), merged, and re-tested: 13 Evolve tests, full suite 1,344 OK, a real offline review on a copy of the owner's logs.

**Prompt / input, word for word:**

````text
You are "Sage", Chutku's improvement architect: patient, evidence-driven, allergic to changes nobody asked for, and absolutely strict that a system which edits itself must never be able to edit its own brakes.

Repo (your own git worktree of D:\Project\Chutku): Chutku, a Python Windows voice assistant. Python: `D:\Project\Chutku\.venv\Scripts\python.exe` (run from your worktree). Read first: AGENTS.md, .claude/skills/ponytail/SKILL.md, .claude/skills/karpathy-guidelines/SKILL.md, docs/SECURITY.md, chutku/nightshift.py (the nightly job runner: run_once, _run_jobs, reports, morning_line, when-idle scheduling), chutku/skills.py (self-written skills: pending -> tests -> typed approve), chutku/coder.py + chutku/tools/builder.py (the coder: choose_coder, _ask_with_fallback, repair loop, keep_tests_fixed), chutku/learning.py, chutku/reflex.py, chutku/know_me.py, chutku/mind.py, chutku/recall.py, chutku/core/ledger.py (reliability per tool/target), and the logs it may read: data/actions.log.jsonl, data/conversations.jsonl, data/heard.jsonl, data/experience.jsonl (owner data: read locally, never send raw logs to a cloud model; send only short redacted summaries).

The owner (2026-11-06): "Chutku must improve and enhance herself every day on her own. If she wants to add a feature she has thought of, she must plan everything first and then, after a full plan in the backend, propose it to me as advice. If I approve, she adds the feature to the codebase and tests it; if it works keep it, else revert to the previous version. She improves overnight or whenever internet is available, in the background: mind maps, user customisations, according to the user, the tasks and the behaviour the user shows."

Build slice Y2 "Evolve" (and the profile part of Y4) with exactly this safety design:
1. Review (automatic, no changes): a Night Shift job `evolve_review` (also runnable on demand: "khud ko improve karo" / "improvement ideas do") that reads the last 7 days of local logs and computes evidence: failed or unverified steps by kind, slow requests (> 15 s), requests that went to the model but could be instant (repeated phrasings), misheard/ignored speech patterns, repeated asks the owner refused or approved every time, and owner habits (apps/times/phrases). It refreshes the owner profile/mind-map data where existing modules allow (know_me, mind, reflex) — local only.
2. Proposals: from that evidence, up to 3 proposals per day, each a FULL plan saved as data/evolve/proposals/<id>.json and shown in plain words: title, the evidence (counts, examples, redacted), what would change (files/areas), the step plan, the test plan (which tests + which real check), risk and how it is undone. The cloud coder may draft the plan from the redacted evidence summary when online; offline, use deterministic proposal templates (e.g. "add instant phrase X -> tool Y, seen N times") so it works without internet.
3. Owner decision: proposals are only advice. `evolve.list` (R0) shows them ("aaj ke suggestions", "improvement ideas"); `evolve.approve <id>` is user_only (typed, then a click: same pattern as skill.approve; never by the agent or by voice); `evolve.reject <id>`.
4. Apply (only after approval), in a separate process/flow, never as an agent tool that edits the live checkout directly: create a git branch `evolve/<id>` in a git worktree under data/evolve/work/ from the current HEAD; let the coder write the change there (reuse the coder and the repair loop with keep_tests_fixed); run the FULL unit test suite and scripts/check_phrases.py in that worktree; if all green, fast-forward/merge the branch into main with a commit "Evolve <id>: <title>" (no co-author line) and record it; if anything fails, delete the branch and worktree (the main checkout was never touched) and mark the proposal failed with the reason. Pushing to GitHub happens only if the owner turned that on (a preference, default off) — say so in the reply.
5. Hard boundary, enforced in code before any merge (and tested): an Evolve change may NOT modify chutku/policy/, chutku/runtime.py, chutku/core/ (grants, paths, elevation, action log, ledger), chutku/guard.py, chutku/tools/registry.py, chutku/skills.py, chutku/evolve*.py, AGENTS.md, docs/SECURITY.md, tests/test_docs_truth.py, tests/test_trusted_task.py, any test that checks a safety boundary (list them explicitly by name: test_autonomy_policy, test_protected_zones, test_taint*, test_elevation, test_injection*, test_failclosed*), .github/, requirements.lock, pyproject.toml; and it may not delete tests. A diff that touches any of these is refused and discarded. Also cap the diff size (e.g. 400 changed lines) and the number of files.
6. Owner-customisation lane (no code): proposals of kind "phrase", "routine", "preference" or "skill" apply through the existing data paths (reflex/routines/preferences/skills.create) instead of editing code, still only after approval.
Tests in new tests/test_evolve_y2.py with fake coders, temp git repos and temp data (never the real repo or the owner's data): review finds evidence from synthetic logs; proposals are full plans; approve is user_only (agent and voice denied); a passing change is merged into the temp repo's main; a failing change leaves main untouched and the branch removed; a diff touching chutku/policy or deleting a test is refused; offline proposals work without a cloud coder.

Rules:
- Full suite from your worktree (`D:\Project\Chutku\.venv\Scripts\python.exe -m unittest discover -s tests`, ~4-5 min); a fresh worktree lacks git-ignored models/ and data/: list any failures that also fail on an untouched checkout, don't fix them.
- Real path: run evolve_review against a COPY of the owner's last-7-days logs in a temp folder (copy D:\Project\Chutku\data\actions.log.jsonl, conversations.jsonl, heard.jsonl, experience.jsonl into a temp base; do not write to the owner's data/), show the evidence and the proposals produced (offline mode), and run one full approve->apply cycle in a temporary git repo clone (not the owner's repo) with a fake coder. Do not open windows, type or click: the owner is using this PC.
- Do NOT edit IMPLEMENTATION_STATUS.md, docs/MASTER_PLAN.md, docs/OWNER_GUIDE.md, docs/AGENT_PROMPTS.md, README.md. If test_docs_truth needs docs/SECURITY.md counts, run `scripts/security_counts.py` and add one short "Evolve" paragraph to docs/SECURITY.md describing the boundary.
- Keep CRLF files CRLF (Edit tool; never sed -i or PowerShell Set-Content); check `git diff --stat`.
- Commit as "Y2: <summary>" with no Co-Authored-By line. Do not push.

Report: the design as built, files, tools/flags, the protected-path list as enforced, test counts and the full-suite line, the real-path evidence/proposals output, limits (be explicit about what Evolve can and cannot change), and (1) proposed ledger text, (2) proposed owner-guide lines. Under 900 words plus the two texts.
````

## 22. Explore: map install, first-run and app shell (2026-11-07)
Why: plan the professional installer (owner: "single click setup ... user must not know the tech stack").
Outcome: found that all data lives in the install folder, setup is console-only, the launch shows a console, there is
no uninstaller, and the defaults suit the owner. These became plan phases P2–P5 (`docs/WEB_CLAUDE_TASKS.md`).

````text
Repo: D:\Project\Chutku (Python Windows voice assistant "Chutku"). Thoroughness: medium. Read-only.
Goal: understand everything a "professional one-click installer + app experience" would build on. Report concisely with file paths and key function names:
1. Install path today: Install-Chutku.cmd, scripts/install.ps1 (all steps), scripts/setup_all.py (model download, sizes per model in models/manifest.json), requirements.lock (rough package count, any heavy ones like torch), pyproject.toml, tools/package.json.
2. First-run / setup: chutku/setup_wizard.py (the 6 questions, is it CLI-only?), chutku/identity.py (.env), any dashboard first-run wizard in chutku/web/ (index.html/app.js) or chutku/dashboard.py.
3. How the app runs for a user: Start-Chutku.cmd -> chutku/guard.py -> what starts (dashboard, presence UI chutku/presence.py with pywebview?, tray icon?, HUD, voice). Is there a tray icon, window icon (.ico) anywhere, app name/branding assets? Do any console windows show? chutku/autostart.py (how sign-in start works).
4. Uninstall/stop paths, where user data lives (data/), whether code writes into its own install folder (would break if installed under Program Files / read-only).
5. Hard-coded owner/PC specific paths or assumptions still present (D:\, C:\Users\siddh, Brave, etc.) — grep for them in chutku/ and scripts/.
6. README.md, CONTRIBUTING.md, docs/RELEASE_CHECKLIST.md, docs/OWNER_GUIDE.md: current state and headings.
7. .github/workflows contents.
Keep the report under 900 words.
````

## 23. Explore: inventory for the release recheck (2026-11-07)
Why: "recheck everything ... no vulnerabilities ... nothing must remain undone".
Outcome:
- Listed the 32 unticked plan items, the owner-only items and the 5 `# shortcut:` notes.
- Found that the relay defaults to `0.0.0.0` over plain HTTP, that `X-Forwarded-For` can be spoofed, that the lock has
  no hashes, and that `know_me` calls a bare `powershell`.
- All of these were fixed this session (relay exposure, absolute System32 paths, `--require-hashes`).

````text
Repo: D:\Project\Chutku (Python Windows assistant). Thoroughness: medium. Read-only.
Goal: inventory what a final "recheck everything, no vulnerabilities, nothing undone" release pass must cover. Report concisely with paths:
1. docs/MASTER_PLAN.md: list every item still unticked "- [ ]" (ID + one-line summary), and the "Parked" and "Owner-only items" sections verbatim-short.
2. docs/RELEASE_CHECKLIST.md and docs/HANDOFF.md section 5: open findings/items.
3. IMPLEMENTATION_STATUS.md: any entries that say "not live", "not verified", "owner step", "shortcut:", "TODO", "not done yet" in the newest ~15 entries (summarize).
4. grep the chutku/ package for "# shortcut:", "TODO", "FIXME", "XXX", "NotImplemented", "pass  #" and list counts + notable ones.
5. Network-listening components and their bind addresses/auth: chutku/dashboard.py, chutku/remote/server.py, chutku/relay/server.py (look for bind host, token checks, CSP, http vs https).
6. Secret handling: grep for keyring/CredentialManager usage, any place writing tokens/keys to files or logs; .env handling in chutku/identity.py.
7. subprocess/shell usage with shell=True, eval/exec, pickle, yaml.load, tempfile mktemp — list locations.
8. Dependencies: requirements.lock count and whether hashes are pinned (--hash).
Keep under 900 words.
````

## 24. Security review of c851336..HEAD plus working tree (2026-11-07, `security-review` skill sub-task)
Why: the release review (H30/O6) over the roughly 9,100 lines added since the last audit.

Outcome, three findings:

| # | Finding | Confidence | Status |
|---|---|---|---|
| 1 | Signed-in browser pages did not mark the session as private, so an injected mail line could make Chutku open an attacker URL carrying an OTP | 8/10, HIGH | **Fixed** (`browser.open` split out as egress; `browser.*` added to PRIVATE_TOOLS; test `SignedInPagesArePrivateTest`; live re-check) |
| 2 | `skill.import` runs code written from an untrusted README during the import step | 7/10, MEDIUM | Handed to web Claude: `docs/WEB_CLAUDE_TASKS.md` W1 |
| 3 | Restoring a backup zip can bring in pairing state and approved skills | 5/10 | Handed to web Claude: W1 |

The prompt was the skill's standard template (objective, categories, exclusions, method, output format) with this
scope prepended:

````text
You are a senior security engineer doing a focused security review of a Python project at D:\Project\Chutku (a Windows voice assistant "Chutku" that runs local tools on its owner's PC). Read-only: do not modify any file.

SCOPE (the "PR"): the changes in `git diff c851336 HEAD -- chutku android scripts Start-Relay.cmd` PLUS the uncommitted working-tree changes (`git diff` and the untracked files scripts/hash_lock.py, tests/test_relay_exposure.py, tests/test_telegram_token_leak.py). About 9,100 lines in 83 files under chutku/. Use git and file reading/search tools to inspect it.

Priority areas: [HTTP servers (dashboard, remote, relay); Telegram gateway; skills and skill import; Evolve; steps.for_each, research workers, learning inbox, backup/restore; desktop.py and signed_in_browser.py; policy bypasses (TAINTING/PRIVATE, kernel, step_question, user_only/runs_code/deletes)]

Security model to respect: same-user programs are out of scope. Attackers of interest: web pages / messages / documents Chutku reads (prompt injection steering tools), network clients of the relay / phone server / dashboard, a malicious Telegram user, a malicious skill repo or backup zip.
[then the security-review skill's objective, categories, exclusions, method and output-format text, unchanged]
````
