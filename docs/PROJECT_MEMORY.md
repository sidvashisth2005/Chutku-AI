# Project memory

Development decisions and lessons for future sessions.


---

## Part: Memory

Updated: 2026-09-30.

## 2026-09-30 checkpoint (supersedes older notes below where they conflict)

- Goal restated by the owner: a practical "Jarvis" for this PC: chat or voice goal →
  Chutku declares steps → executes → verifies. Owner decisions are recorded in
  `docs/DESIGN.md` §51 (autonomy selector, C:/D: access with protected
  zones, Gemini as secondary planner, Whisper STT, GPU brain).
- Main path is now `chutku/agent_loop.py` (observe→plan→act→verify loop) driven from the
  dashboard chat (`/api/chat`, `/api/agent/*`, `/api/voice/ask`). First tier:
  `chutku/quick_intents.py`. Model: persistent Vulkan llama-server (`chutku/brain_service.py`).
  Legacy `brain.plan`/`plans.py`/project recipe remain because stage gates and the 302-case
  benchmark depend on them; they are not the user path.
- Small-model failure modes seen and guarded deterministically: invented placeholders
  (`[newest_pdf_file]`), unrequested actions on questions, false "done" wording (verified
  tally appended), redundant re-check steps (prompt rule), wandering on destructive
  requests (prompt refusal + protected zones).
- Evidence must be regenerated after the LAST code edit: `source_digest` covers
  chutku/, tests/, scripts/ and benchmarks/, so editing any script stales every gate.
- C: drive is ~98% full; keep models/caches on D:.

- Latest owner-directed sequence: foundation first, deterministic brain second,
  then access/permissions, then local LLM, then voice integration. Preserve old
  experiments but do not let them bypass the stage gates. See docs/ARCHITECTURE.md and
  docs/ARCHITECTURE.md; docs/ROADMAP.md records the superseding order.
- Foundation checkpoint: doctor, typed request planning/clarification, guarded
  launcher and independent stop, task-bound approvals and visible evidence.
  126 automated tests and 21 core smoke checks pass. Hardware focus remains
  OS-dependent; an initial 42/43 desktop check report is preserved.
- Actual model development/regression suites passed 10/10 and 7/7 after prompt
  clarification; these are small tuned sets, not general accuracy measurements.
  Real dashboard proposal/review/execution and stop were exercised. Keep model
  experimental; general Hindi/Hinglish speech is still unverified.
- Start-Chutku.cmd now runs chutku.guard. Direct chutku.cli dashboard is unguarded.
  Stop remains paused across restart until explicit resume. Existing/brokered
  desktop apps may survive; completed effects are not automatically undone.
- Verification source of truth: verification/release-report.json and its listed
  artifacts. Read the newest 2026-09-26 ledger entry before historical notes below.
- Final desktop retest is 41/43: both foreground-focus requests refused by Windows.
  All remaining hardware checks passed; aggregate report intentionally remains false.

## Historical notes (2026-09-25; newer checkpoint above supersedes status)

- Respond to the owner in English, including when they speak Hindi/Hinglish.
- Goal: useful local Windows automation with independently authorized, observed,
  auditable outcomes. Preserve the master plan's zero-paid-API/no-cloud-LLM constraint.
- User reconfirmed local-only operation in this session. A Gemini API key exists
  as a possible future backup; do not load it, enable cloud calls or transmit data
  without a later explicit integration request.
- Preserve Chutku as the foundation. Mark LIV is a reference, not a replacement runtime.
- Reference study and attribution: `docs/reference/MARK_NOTES.md`.
- Presentable slice implemented: local dashboard, explicit searchable memory, registered
  capability inventory, visible-window inspection, previewed project recipe,
  durable step history and conflict-aware text undo.
- Current verification: 104 automated tests; all 26 tools exercised. Latest live smoke had two Windows foreground-focus refusals; all other checks passed.
  See `verification/archive/VERIFICATION_REPORT.md` and `IMPLEMENTATION_STATUS.md`.
- Current extension: allowlisted app control, cross-process locking, cooperative action pause, local Zira output, free-form offline English dictation, and reviewed general local-LLM typed-tool plans.
- Owner heard Zira through speakers and accepts it temporarily; replace with a more realistic local voice later.
- Ordered implementation plan: docs/ROADMAP.md. Local Qwen3 4B model evaluation is in progress; task-bound R3+ approvals and independent guard still remain.
- Do not claim general conversational STT, dependable autonomous LLM reasoning, general GUI control, learned workflows,
  scheduling or durable general rollback until separately implemented and tested.
- Source code alone is insufficient evidence. Follow AGENTS.md, run regression
  tests, a real command path, and negative safety cases; update the ledger.
- Mark's source license states CC BY-NC 4.0. No source/assets/configuration are copied.
- This file is repository-local development memory. User notes saved by the
  application are separate, visible, locally stored data and not policy instructions.
