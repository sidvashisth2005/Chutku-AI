# Chutku design (master source of truth)

Formerly `docs/DESIGN.md`. Product vision, safety principles and owner decisions (§51).


---

## Part: Master context

**Status:** Final updated context  
**Supersedes:** `Chutku_Context_v2.md` as the working source of truth  
**Purpose:** Persistent context for future planning, implementation, research, testing, and documentation of Chutku.

---

# 1. Project Identity

**Project:** Chutku  
**Wake phrase:** “Oye Chutku”  
**Voice:** Female, local TTS  
**Platform:** Windows 11 Home Single Language  
**Deployment:** Local-first; local inference and data; network access only through explicit browser/download tools  
**Cloud LLM:** No  
**Paid APIs:** No  
**Budget:** ₹0  
**Development model:** AI-assisted engineering  
**Primary objective:** Build a résumé-quality, privacy-first, voice-controlled local Windows AI agent capable of interacting with and automating a Windows PC safely, reliably, and verifiably.

Chutku is not merely a chatbot with speech recognition.

> **Chutku is a zero-cost, privacy-first Windows agent runtime that turns natural-language voice or text commands into policy-checked, verified, undoable actions on constrained local hardware — and measures its own reliability.**

Primary defensible research/engineering claim:

> **A local Windows computer-use agent whose actions are policy-gated, verified against real UI/file-system state, and evaluated with reproducible benchmarks on constrained hardware.**

---

# 2. The Central Engineering Principle

> **Chutku should never be more autonomous than it is capable of verifying safely.**

Core loop:

```text
OBSERVE
   ↓
UNDERSTAND
   ↓
PLAN
   ↓
AUTHORIZE
   ↓
ACT
   ↓
VERIFY
   ↓
RECOVER / COMPLETE
```

The assistant must never report success merely because a tool returned without an exception.

---

# 3. Core Design Principles

## 3.1 Local by default

User data, voice, memory, documents, screenshots, workflows, logs, and model inference remain local whenever technically possible.

No dependency should silently upload private information.

## 3.2 Deterministic where possible

Do not use an LLM when a deterministic operation can reliably perform the task.

Example:

```text
“Mute the computer”
```

should preferably use a deterministic Windows audio-control tool rather than:

```text
voice → LLM → arbitrary GUI clicking
```

## 3.3 Agentic only where useful

Use the LLM for:

- natural-language understanding
- interpretation
- ambiguity resolution
- planning
- workflow generation
- recovery strategy
- explanation

## 3.4 Never assume success

Execution ≠ success.

Every important operation needs an explicit verification condition.

## 3.5 Least privilege

The LLM proposes actions.

The policy kernel decides whether the proposed actions are allowed.

Deterministic tools execute them.

The LLM never receives unrestricted OS authority.

## 3.6 Measure first

Architecture and model choices should be based on measurements from the actual Dell G15 rather than assumptions.

## 3.7 AI-assisted development, human-validated engineering

Chutku is being built **with AI assistance**, not by manually implementing every component line by line.

AI may accelerate:

- research
- implementation
- boilerplate
- debugging
- test generation
- benchmark scripts
- documentation
- refactoring
- log analysis
- dataset preparation
- schema/prompt design
- iteration

However, AI-generated implementation does **not** count as validated capability.

The project owner must validate:

- real hardware performance
- actual Windows behavior
- safety boundaries
- benchmark results
- failure recovery
- verification correctness
- whether a feature is genuinely implemented
- whether résumé/research claims are supported by evidence

> **AI accelerates implementation; empirical testing establishes truth.**

The project should optimize for how much one person can **understand, validate, maintain, and defend** with AI assistance — not for how much code AI can generate.

---

# 4. Hardware and Environment

| Component | Specification |
|---|---|
| Laptop | Dell G15 5520 |
| CPU | Intel Core i5-12540H |
| RAM | 24 GB |
| GPU | NVIDIA RTX 3050 Laptop GPU |
| VRAM | 4 GB |
| Storage | 512 GB SSD |
| OS | Windows 11 Home Single Language |
| Budget | ₹0 |

## Hardware implications

The 4 GB VRAM is the primary AI-resource constraint.

Do not design around large models permanently residing in VRAM.

Use:

- quantized models
- CPU inference
- GPU acceleration where useful
- CPU/GPU hybrid inference
- lazy loading
- model unloading
- model routing
- context management
- resource-aware selection

24 GB RAM provides useful headroom, but Windows, browser applications, and AI models must coexist.

Windows 11 Home Single Language means:

- **Windows Sandbox should not be assumed available**
- Hyper-V should not be assumed available
- any future sandbox strategy must be verified against the exact system configuration

Generated-code execution is **not part of v1**.

---

# 5. Resource and Storage Philosophy

Chutku should eventually track:

- RAM usage
- GPU utilization
- VRAM usage
- CPU usage
- model disk usage
- cache size
- loaded model
- inference mode
- model feasibility

The 512 GB SSD requires storage discipline.

Potential layout:

```text
Chutku/
    models/
    datasets/
    cache/
    logs/
    memory/
    benchmarks/
    recordings/
    workflows/
    temporary/
```

Never automatically delete potentially important user data.

Cleanup must be explicit, safe, and reversible where possible.

---

# 6. High-Level Architecture

```text
MICROPHONE / TEXT
        ↓
VAD / PTT / WAKE WORD
        ↓
       STT
        ↓
    ROUTER
        ↓
COMMAND / CATALOG / EMBEDDING / LLM
        ↓
     PLANNER
        ↓
   POLICY KERNEL
        ↓
ALLOW / CONFIRM / DENY
        ↓
   TOOL EXECUTOR
        ↓
WINDOWS / BROWSER / FILES / APPS
        ↓
     OBSERVER
        ↓
    VERIFIER
        ↓
RECOVER / COMPLETE / FAIL
        ↓
 EVENT LOG + MEMORY
        ↓
      TTS / TEXT
```

The runtime should eventually be multi-process:

```text
chutku-core
chutku-audio
chutku-llm
chutku-guard
```

A separate guard process provides the kill-switch/heartbeat boundary.

---

# 7. Four-Brain Conceptual Model

This remains a conceptual model rather than a requirement for four separate processes.

### Reflex brain
Deterministic tools and rules.

### Language brain
Local LLM for language understanding/planning.

### Perception brain
UIA, OCR, screenshots, browser state, and later vision if measurements justify it.

### Memory brain
Tasks, events, preferences, workflows, failures, and retrieval.

---

# 8. State Machines

Do not mix real-time audio states with task execution states.

## Audio/session state

```text
IDLE
→ LISTENING
→ TRANSCRIBING
→ RESPONSE
→ IDLE
```

## Task state

```text
RECEIVED
→ UNDERSTANDING
→ PLANNING
→ AUTHORIZING
→ EXECUTING
→ VERIFYING
→ COMPLETED
```

Failure:

```text
FAILED
→ RECOVERING
→ VERIFYING
→ COMPLETED / FAILED
```

Other states include:

```text
WAITING_CONFIRMATION
CLARIFYING
PAUSED
DENIED
TIMED_OUT
CANCELLED
```

Use ULIDs internally rather than sequential task IDs.

Example human-readable prefix:

```text
CHUTKU-01H...
```

---

# 9. LLM Strategy

Do **not** train a main LLM from scratch.

Do **not** fine-tune initially.

Use a small local pretrained model with structured outputs/tool calling.

Expected v1 role:

> **LLM parser/planner over a closed typed-tool vocabulary.**

Not:

> unrestricted general computer-use agent.

Small quantized local models are expected to be better at converting commands into structured actions than at open-ended GUI planning.

Candidate runtimes include:

- llama.cpp
- Ollama

Exact runtime/model selection is an empirical Phase 0 decision.

---

# 10. Four-Tier Router

The router should prefer the least expensive reliable method.

```text
Tier 0 — deterministic command matching
Tier 1 — catalog / grammar matching
Tier 2 — embeddings / semantic matching
Tier 3 — local LLM
```

The router should have explicit thresholds and fail-closed behavior.

Do not use verbal LLM confidence such as “I am 95% sure” as a safety mechanism.

Confidence and authorization are different concepts.

---

# 11. Tool Architecture

LLM:

```text
proposes typed tool call
```

Runtime:

```text
schema validation
→ policy validation
→ permission validation
→ precondition check
→ execution
→ observation
→ verification
```

## Required tool metadata

- name
- input schema
- output schema
- base risk
- risk escalators
- preconditions
- execute
- verify
- timeout
- error taxonomy

Optional:

- rollback
- idempotency
- retry policy
- capability requirements

### Critical rule

**The LLM must never supply the authoritative risk level.**

If the LLM emits a risk field, it is ignored.

The **policy kernel computes risk** from:

- tool identity
- arguments
- target/resource
- context
- permission state
- reversibility
- operation class

---

# 12. Policy and Risk

Risk levels:

```text
R0 — observation
R1 — low-risk/reversible
R2 — user-data modification
R3 — external side effect
R4 — destructive/privileged
R5 — dangerous/disabled
```

Typical authorization:

- R0: automatic
- R1: automatic where safe
- R2: policy-checked
- R3+: normally on-screen user confirmation
- R4: strong confirmation / restricted
- R5: deny

Voice-only confirmation is **not sufficient for R3+**.

---

# 13. Filesystem Safety

Windows path handling must account for:

- canonical paths
- allowlisted roots
- `..`
- junctions
- symlinks/reparse points
- UNC paths
- 8.3 paths
- case-insensitivity
- alternate data streams
- TOCTOU issues

File deletion should use the Recycle Bin where practical.

Bulk operations require explicit thresholds and policy checks.

The initial sandbox should be a dedicated user-created test directory.

---

# 14. Operation Journal / Undo

For R2+ file operations, use a SQLite WAL-backed operation journal.

Record before and after acting:

```text
task_id
operation
source
destination
prechecks
result
```

This enables:

- undo
- crash recovery
- audit
- incomplete-operation detection

On restart:

> “I found an unfinished file operation. Do you want me to complete or roll it back?”

Undo is therefore an actual mechanism, not merely a voice-command promise.

---

# 15. Verification

Verification is a first-class tool capability.

Possible outcomes:

```text
PASS
FAIL
UNKNOWN
```

`UNKNOWN` must never be converted into success.

Examples:

### Open application
Verify:

- expected top-level window exists
- visible
- responsive
- UIA accessible where expected
- within timeout

A process existing is not enough.

### File operation
Verify:

- source/destination state
- size
- hash where cheap

### Volume/mute
Read back actual audio state.

### Browser search
Prefer deterministic URL launch when possible and verify:

- browser window
- title
- URL/omnibox state

---

# 16. Windows Automation Hierarchy

Preferred order:

```text
1. Native API/application API
2. Windows UI Automation
3. Browser DOM / Playwright
4. OCR / accessibility tree
5. Vision model
6. Coordinate mouse/keyboard fallback
```

Semantic automation is preferred over pixel clicking.

### UIA realities

Account for:

- Windows launcher stubs
- foreground-lock behavior
- UIPI
- UAC secure desktop
- lock screen
- DPI scaling
- multi-monitor setups
- Chromium/Electron accessibility limitations

Probe application capabilities rather than assuming UIA works universally.

App capability states:

```text
SUPPORTED
PARTIALLY_SUPPORTED
VISUAL_FALLBACK
UNSUPPORTED
REQUIRES_USER
```

---

# 17. Browser Strategy

Apply Principle 2 to browser tasks.

If a task can be solved by deterministic URL launch, do not unnecessarily use Playwright.

Example:

```text
open browser
→ launch search URL
→ verify title/URL
```

Playwright is deferred for:

- dedicated automation profiles
- local test websites
- tasks that actually require DOM interaction

Do not design around controlling the user's normal Chrome instance via assumptions about remote debugging.

---

# 18. Voice Architecture

Target:

```text
Microphone
→ VAD
→ PTT or wake detector
→ STT
→ router
→ planner
→ policy
→ tools
→ verification
→ TTS
```

Development order:

```text
Text CLI
→ Push-to-talk voice
→ Custom wake word
```

PTT remains a permanent fallback.

### Audio safety

Threats include:

- media replaying “Oye Chutku”
- TTS triggering itself
- video/audio saying “yes” during confirmation
- microphone capturing Chutku's own voice
- wake-word activation during speech

Use:

- half-duplex behavior
- wake suppression during TTS
- no voice-only R3+ confirmation
- explicit on-screen confirmation
- separate kill switch

---

# 19. Language Requirement

Language choice is an explicit Phase 0 decision.

Candidate scope:

```text
English
Hinglish
Hindi
```

Do not assume the language/model choice before measuring.

Evaluate:

- English
- Indian-accented English
- Hinglish
- Hindi if included
- Roman Hindi vs Devanagari behavior where relevant

---

# 20. STT

Candidate STT technologies should be benchmarked locally.

Measure:

- WER
- command-level accuracy
- decode latency
- CPU
- RAM
- VRAM
- noise robustness
- fan/thermal behavior

Create an own-voice speech set.

---

# 21. TTS

Benchmark:

- Windows/SAPI voices
- Kokoro
- Piper/current maintained distribution as appropriate

Check:

- voice quality
- latency
- pronunciation of “Chutku”
- English/Hinglish/Hindi requirements
- memory footprint
- licensing

Do not assume an old Piper repository or model license remains current.

---

# 22. Wake Word

Wake word:

> **“Oye Chutku”**

Wake word is not authentication.

Evaluate:

- false accepts/hour
- false rejects
- latency
- noise robustness
- distance
- speakers
- pronunciation variants
- media injection
- real recordings

Do not list “Oye Chutku” itself as a negative example.

Wake word development is timeboxed.

If targets are not met, PTT remains the reliable fallback.

---

# 23. Prompt Injection / Untrusted Content

Webpages, PDFs, emails, documents, files, and application content are **untrusted data**.

They are not authorities.

Prompt injection defense must be a mechanism, not merely a system prompt.

Use:

- taint tracking
- quarantined reader pattern
- provenance
- memory quarantine
- on-screen confirmation for tainted R2+ actions
- injection regression suite

Target:

```text
≥50 injection cases
0 unauthorized R2+ actions
```

A tainted plan attempting R2+ should require explicit on-screen confirmation with origin information or be denied.

---

# 24. Audio and Kill-Switch Safety

A voice “stop” command cannot be the only emergency control.

Use:

```text
guard process
+
global hotkey
+
tray Stop control
```

The guard must remain able to:

- stop/kill tool execution
- mute/disable microphone
- terminate a hung core
- respond even when the LLM is frozen

The kill switch must be tested while the core is deliberately hung.

---

# 25. Secrets and Sensitive Data

Do not put secrets into ordinary memory/RAG.

Use Windows Credential Manager / DPAPI-backed mechanisms where appropriate.

Screenshots, OCR, clipboard, and logs may contain passwords.

Therefore:

- skip password UI fields where possible
- block sensitive windows from capture
- avoid screenshot persistence by default
- define log retention
- minimize sensitive context passed to models

---

# 26. Memory

Initial persistence:

**SQLite**

Store:

- tasks
- events
- memories
- workflows
- failures
- tool metadata
- benchmark data

Memory provenance:

```text
user_stated
tool_observed
inferred
external_untrusted
```

Also store:

- confidence
- timestamp
- TTL

Temporary session state should expire.

Do not automatically convert inferred information into permanent fact.

Vector search is optional and must be justified by measured need.

---

# 27. Workflow Learning

Do **not** passively record the user's keyboard/mouse activity.

That creates keylogger-like privacy/security problems and can capture passwords.

Instead:

```text
Chutku executes successful verified tool sequence
→ repeated similar sequence detected
→ Chutku proposes workflow
→ user approves
→ generalized workflow stored
```

Example:

```text
project_directory
```

instead of:

```text
C:\Users\...\specific-project
```

Every workflow must pass through the policy kernel again when executed.

---

# 28. Failure Learning

Failure categories:

```text
STT_ERROR
INTENT_ERROR
PLANNING_ERROR
TOOL_ERROR
PERCEPTION_ERROR
VERIFICATION_ERROR
PERMISSION_ERROR
ENVIRONMENT_ERROR
TIMEOUT
MODEL_ERROR
SCHEMA_ERROR
```

Store:

- task ID
- intended action
- actual action
- observation
- error
- recovery
- result
- model
- tool
- application

Important failures should become regression tests.

Do not allow the LLM to silently modify production code based on failures.

---

# 29. Recovery

Recovery must be:

- bounded
- error-aware
- deterministic where possible
- verifiable

Examples:

```text
Tool timeout
→ classify
→ retry only if retryable
→ verify
```

```text
UI changed
→ re-perceive
→ retry boundedly
→ verify
→ ask user
```

```text
Permission denied
→ stop
→ explain
→ request user action
```

Never perform unlimited autonomous retries.

---

# 30. Observability and Audit

The event log is a core architectural component.

Log:

- task ID
- timestamp
- transcript
- intent
- plan
- authorization
- tool calls
- observations
- verification
- errors
- recovery
- final result
- model
- latency

Avoid unnecessary sensitive data.

The event log should eventually support:

- audit
- debugging
- metrics
- deterministic runtime trace replay

Trace replay means replaying recorded runtime events/model outputs/tool observations against the runtime logic. It does **not** mean literally replaying nondeterministic GUI actions.

---

# 31. Graceful Degradation

Examples:

```text
LLM unavailable
→ deterministic commands continue
```

```text
Vision unavailable
→ UIA/OCR
```

```text
TTS unavailable
→ text
```

```text
Wake detector unavailable
→ PTT
```

```text
Memory DB unavailable
→ temporary safe session context
```

```text
Thermal pressure
→ lighter model / smaller context / text-only mode
```

---

# 32. Network Policy

“Fully local” means:

> local inference and local data, with network access only through explicit browser/download tools.

No hidden telemetry.

No cloud LLM.

No arbitrary network access for tools.

A full network gateway is deferred; use a simpler explicit egress policy for v1.

---

# 33. Licensing

Track:

```text
THIRD_PARTY_LICENSES.md
```

For every distributed dependency/model record:

- component
- version
- source
- license
- model-card/source link
- checksum where appropriate
- date checked

Do not advertise:

> “100% open source”

unless every distributed component satisfies the relevant definition.

Safer description:

> “Built with locally deployed open-source and openly available AI components, subject to their licenses.”

Licenses must be re-verified when final dependencies/models are pinned.

---

# 34. Evaluation and Benchmarking

Benchmarks begin early, not at the end.

## Datasets

Target:

- ≥300 labeled command utterances
- ≥200 recorded speech commands
- ≥50 prompt-injection cases
- 30 golden tasks

Speech conditions:

- quiet
- fan noise
- music/TV
- 0.5 m
- 1 m
- 2 m
- multiple speakers where possible

## Golden tasks

Include:

- normal tasks
- ambiguous tasks
- permission failures
- missing targets
- renamed files
- app crashes
- path traversal attempts
- dangerous delete requests

Run important tasks repeatedly.

Use Wilson confidence intervals where appropriate.

For zero observed failures, remember that very small samples cannot prove an extremely low failure rate; safety-critical metrics need larger samples.

---

# 35. Core Metrics

Measure:

- task success rate
- step success rate
- planning accuracy
- tool-selection accuracy
- verification accuracy
- recovery rate
- false-action rate
- false-success rate
- human intervention rate
- latency
- CPU
- RAM
- VRAM
- catastrophic errors

### Important definitions

**Task success:** final state matches the specification, checked by the benchmark harness.

**False success:** Chutku reports success while the actual state is wrong.

**Catastrophic error:** data loss or an out-of-policy action.

Target:

```text
Catastrophic errors = 0
```

for release-quality safety testing.

---

# 36. Proposed Initial Targets

These are **provisional** and must be adjusted after Phase 0 measurements.

| Area | Initial target |
|---|---|
| Wake word | ≤1 false accept / 8 h mixed use |
| Wake recall | ≥90% quiet @1 m |
| Wake noisy recall | ≥75% moderate TV/music |
| Wake latency | ≤300 ms after phrase |
| Wake idle CPU | ≤5% |
| STT | ≥95% command accuracy quiet |
| STT noisy | ≥85% |
| STT latency | ≤1 s for ≤4 s utterances |
| Structured LLM output | 100% syntactically valid with constrained decoding |
| Router semantic validity | ≥95% on 300 commands |
| R2+ unauthorized actions | 0 |
| Golden deterministic tasks | ≥95% |
| LLM-planned golden tasks | ≥80% |
| Recovery | ≥70% transient failures without user intervention |
| Catastrophic error | 0 |

These are engineering targets, not claims of current performance.

---

# 37. Phase 0 — Empirical Spikes

Phase 0 exists specifically to stop analysis paralysis.

Each spike is a small throwaway experiment producing numbers.

## S0 — Environment

Determine:

- exact Windows edition/build
- Python version
- GPU driver
- power mode
- available storage
- virtualization-related capabilities

Current known OS:

> **Windows 11 Home Single Language**

## S1 — STT

Test:

```text
microphone
→ VAD
→ local STT
```

Use English/Hinglish commands initially and Hindi if selected.

Measure:

- WER
- command accuracy
- latency
- CPU
- RAM
- VRAM
- Roman/Devanagari behavior

## S2 — LLM

Test:

- 3–4B Q4
- 7–8B Q4 where feasible

Measure:

- tokens/sec
- prefill time
- VRAM
- RAM
- thermal behavior
- structured JSON reliability
- semantic accuracy

Use a 1–2K token tool prompt.

## S3 — TTS

Compare:

- Windows/SAPI
- Kokoro
- current maintained Piper distribution

Measure quality, latency, pronunciation, resource usage, and licensing.

## S4 — UIA

Test:

- Windows Notepad
- Chrome
- VS Code

Also test:

- deterministic URL search
- window/title verification

## S5 — Wake Word

Timebox custom wake-word experimentation.

Measure false accepts and feasibility.

Output:

```text
GO
NO-GO
EXPERIMENTAL
```

---

# 38. Roadmap

The previous v2 estimate of 20–28 weeks assumed 10–15 hours/week and was explicitly an assumption.

**Do not treat that schedule as locked.**

Because development is AI-assisted, implementation can be accelerated substantially.

The correct schedule should be recalculated from:

1. actual available hours/week
2. Phase 0 measurements
3. AI-assisted implementation velocity
4. number of iterations required by testing

Do not compress safety/verification merely to shorten calendar time.

## Phase 1 — Core spine, text-first

Build:

- repository
- `uv` environment
- model manifest
- license tracking
- event bus
- SQLite event log
- task FSM
- tool registry
- policy kernel v0
- operation journal
- ~10 deterministic tools
- verification
- CLI
- guard process
- first golden tasks

## Phase 2 — Push-to-talk voice

Build:

- audio process
- PTT
- VAD
- STT
- router
- TTS
- half-duplex
- mic indicator
- transcript/response UX
- device-change handling

## Phase 3 — Brain + safety hardening

Build:

- local LLM interface
- constrained decoding
- tiered routing
- semantic validation
- confirmation UX
- taint tracking
- quarantined reader
- injection suite

## Phase 4 — Wake word

Timeboxed custom wake detector.

PTT remains fallback.

## Phase 5 — Perception

Build:

- UIA adapters
- app capability probing
- Windows OCR
- screenshot handling
- Playwright dedicated profile
- local test website

Do not add a VLM unless UIA/OCR failure measurements show that it materially solves a problem.

## Phase 6 — Reliability

Build:

- recovery engine
- timeouts
- bounded retries
- crash recovery
- undo
- trace replay
- chaos testing
- failure → regression workflow

## Phase 7 — Memory and workflows

Build:

- persistent memory
- provenance
- session context
- follow-ups
- file search
- trace-derived workflows
- workflow policy re-checking

## Phase 8 — Benchmark and showcase

Produce:

- benchmark results
- confidence intervals
- ablations
- baseline comparisons
- README
- architecture diagram
- threat model
- technical report
- demo mode
- résumé claims supported by actual results

---

# 39. Vertical Slice Strategy

Do not build isolated subsystems for months.

A better progression is:

```text
Text
→ deterministic tool
→ policy
→ verification
→ logging
→ recovery
→ voice
→ LLM
→ perception
→ memory
```

Every slice should become more capable without removing the earlier safety guarantees.

---

# 40. AI-Assisted Development Workflow

For each meaningful feature:

```text
1. Define the measurable requirement
2. Ask AI to research/design implementation
3. Ask AI to implement a small change
4. Generate tests with AI
5. Run locally
6. Inspect failures
7. Feed real evidence back to AI
8. Fix
9. Benchmark
10. Record result
11. Only then mark capability implemented
```

For risky components:

```text
AI proposal
→ human review
→ implementation
→ adversarial tests
→ measurement
→ acceptance
```

AI should not be treated as the authority for whether its own generated system is safe.

---

# 41. Definition of Done

### Tier A — Every component

- implementation
- unit tests
- structured logging
- short documentation

### Tier B — Policy/executor/R2+ components

Tier A plus:

- security checklist
- sandbox/test-root testing
- regression tests
- chaos case

### Tier C — Metrics-bearing components

Tier A plus:

- benchmark
- versioned result
- comparison against target

---

# 42. Repository Structure

Create folders when needed rather than scaffolding everything immediately.

```text
chutku/
  README.md
  LICENSE
  docs/SECURITY.md
  docs/SECURITY.md
  docs/ARCHITECTURE.md
  THIRD_PARTY_LICENSES.md
  pyproject.toml
  uv.lock
  models.manifest.json

  chutku/
    core/
    policy/
    tools/
    voice/
    llm/
    perception/
    memory/
    workflows/
    eval/
    guard/

  adapters/
  tests/
  docs/
  scripts/
```

Deferred/de-emphasized from the old structure:

- plugins
- dashboard
- passive learning
- generated-code execution
- VLM
- full network gateway

---

# 43. What Is Explicitly Cut/Deferred

## Deferred

- plugin system
- dashboard
- full network gateway
- VLM
- generated-code execution
- paper until benchmarks exist
- speaker verification unless later justified
- advanced vector database
- unrestricted shell
- general autonomous multi-app loops

## Cut

- passive keyboard/mouse workflow recording
- reinforcement-learning-style claims
- “AI controls everything” positioning

---

# 44. Competitive/Research Positioning

Do not claim novelty for commodity components such as:

- wake-word → STT → TTS plumbing
- generic UI automation
- generic computer-use agents

The project’s stronger technical story is:

- policy-gated execution
- computed risk
- verification against actual Windows state
- taint-aware prompt-injection defense
- operation journal / undo
- bounded recovery
- reproducible benchmarks
- ablations
- constrained local hardware evaluation

Research question:

> **How reliable can a locally deployed Windows agent be when operating under a 4 GB VRAM constraint, when every consequential action is policy-gated and independently verified?**

---

# 45. Résumé Honesty Rule

Only claim features after they:

1. ship
2. are tested
3. are benchmarked where applicable
4. have evidence

Do not claim:

- RAG
- multimodal AI
- workflow learning
- persistent memory
- wake word
- reinforcement learning

until those capabilities actually exist and have been measured.

Do not claim “fully open source” without verifying all relevant component licenses.

---

# 46. Failure Matrix

| Failure | Detection | Recovery | Fallback |
|---|---|---|---|
| Wake miss | no activation | repeat | PTT |
| False wake/media injection | activation without intent | ignore/timeout | on-screen confirmation |
| TTS self-trigger | wake during speech | suppress | — |
| STT failure | empty/poor result | one retry | text |
| Wrong intent | ambiguity | clarify | stop |
| Wrong plan | semantic validation | replan once | ask user |
| Tool failure | exception/error class | bounded retry if safe | alternate tool |
| UI changed | verification fail/unknown | re-perceive | ask user |
| Permission denied | OS/integrity error | stop/explain | user action |
| App crash | window/process failure | bounded relaunch | ask user |
| Interrupted file operation | journal entry incomplete | offer rollback/complete | manual |
| Tainted R2+ plan | taint flag | on-screen confirmation or deny | deny |
| Core hung | heartbeat failure | guard terminates tools/mutes mic | hotkey |
| Thermal throttling | latency/temperature drift | lighter model/context | text-only |
| Vision unavailable | model failure | UIA/OCR | ask user |
| Verification unknown | no evidence | report inability to verify | stop |

---

# 47. Pre-Coding Gate

Only these are required before Phase 1:

- [x] Hardware profile recorded
- [x] Windows edition recorded: Windows 11 Home Single Language
- [ ] Exact Windows build recorded
- [ ] Python environment recorded
- [ ] GPU driver recorded
- [ ] Language requirement decided
- [ ] Granted roots defined
- [ ] Test/sandbox folder created
- [ ] Risk levels and confirmation rules written
- [ ] Threat model v0 written
- [ ] Repository + environment created
- [ ] License choice made
- [ ] Phase 0 spikes completed or actively running

Everything else should be a phase-specific exit criterion.

---

# 48. Current Open Decisions

| Decision | Resolution |
|---|---|
| OS edition | **Windows 11 Home Single Language — resolved** |
| Languages | English / Hinglish / Hindi — user decision + S1 |
| STT runtime/model | S1 |
| TTS | S3 |
| LLM runtime/model/quant | S2 |
| Wake engine | S5 |
| OCR | Phase 5 |
| Vector strategy | Phase 7 based on measured need |
| Future sandbox | Post-v1, edition-dependent |
| Project license | Before first public commit |
| UI/dashboard | Post-v1 |
| Exact hours/week | **Still open** |

---

# 49. Current Project State

The project has moved beyond the original “write another giant design document” loop.

The current priority is:

> **Empirical Phase 0 → measurable decisions → small vertical implementation slices.**

The master plan must remain the source of truth.

Whenever planning forward:

1. Refer to this document.
2. Preserve existing locked decisions.
3. Identify any proposed change explicitly.
4. Do not silently replace architecture decisions.
5. Prefer measurements over assumptions.
6. Do not prematurely expand scope.
7. Keep safety and verification from the first real tool onward.
8. Use AI assistance aggressively for implementation and iteration.
9. Keep human validation as the authority for actual system behavior.

---

# 50. Final Project Definition

> **Chutku is a zero-cost, privacy-first, locally deployed Windows agent that turns voice or text commands into policy-checked, verified, undoable actions — using deterministic tools first, a small local language model only where language understanding is needed, and explicit evidence of outcome — while measuring its own reliability under the constraints of a Dell G15 5520 with an Intel i5-12540H, 24 GB RAM, RTX 3050 4 GB VRAM, 512 GB SSD, and Windows 11 Home Single Language.**

Defining engineering principle:

> **Never be more autonomous than it can safely verify.**

Defining process principle:

> **Measure first; build vertical slices; ship safety with the first tool.**

Defining development principle:

> **Use AI to accelerate engineering, but use real measurements and human validation to establish truth.**

Defining product philosophy:

> **Build a reliable agent, not merely an impressive demo.**

Defining voice identity:

> **“Oye Chutku” — female local voice assistant.**

---

# 51. Owner-Directed Changes (2026-09-30)

These explicitly supersede the listed earlier decisions; everything else stands.

| Area | Earlier decision | Owner decision 2026-09-30 | Safeguard kept |
|---|---|---|---|
| Autonomy | Every LLM plan reviewed before execution | Per-request selector: Review / Auto-safe (≤R1) / Auto-edits (≤R2 with runtime undo) | Policy kernel computes risk; R3+ always on-screen; taint + network egress forces confirmation; R5 denied |
| File access | Explicit folder grants, whole drives refused | Whole local drives C:\ and D:\ may be granted | Code-owned protected zones (Windows, Program Files, ProgramData, AppData, drive-root system files, Chutku runtime) are observe-only; canonical/8.3/junction checks |
| Cloud LLM | No cloud LLM | Gemini allowed as a secondary planner when the local model cannot decide | Off until `cloud.gemini` is granted and a key is stored in Credential Manager; only goal, tool catalog and redacted step names are sent; output passes the same validation and policy |
| STT | Windows dictation (en-US) | Offline faster-whisper-small (CPU int8), Hinglish-biased, Romanized output | Integrity-pinned model; audio in memory only; Windows dictation fallback |
| LLM runtime | CPU llama.cpp, cold start per request | Persistent llama.cpp Vulkan server on the RTX 3050 with idle unload | Whole runtime directory hash-pinned; loopback + API key; CPU fallback |
| Routing | Deterministic catalog, then reviewed LLM plan | Deterministic everyday-intent router first, then observe→plan→act→verify loop | Router output is an ordinary proposal: same validation, policy and verification |

## 51.1 Owner-directed changes (2026-10-01)

The owner has no objection to Gemini or other online models. The local model stays first for speed, cost and
privacy; Gemini covers what it cannot do. The owner also wants long tasks automated end to end, e.g. "build me
a calculator app" should be written, opened in VS Code, run and fixed.

| Area | Earlier (2026-09-30) | Owner decision 2026-10-01 | Safeguard kept |
|---|---|---|---|
| Gemini role | Backup planner only | Also writes code for `code.build_project` and plans long goals first (60 steps / 1 h budget) | Still off until `cloud.gemini` is granted and a key is stored; every step passes the same validation, policy and verification |
| What Gemini sees | Goal, catalog, redacted step names | Adds public results from an allowlist (web, system status, file names, build results) | File contents, clipboard, screen text, memory and messages are never sent; sensitive arguments stay redacted |
| Building software | Out of scope (4B model quality) | `code.build_project` (R3): new folder only, VS Code, compile + project tests + launch checks, up to 3 repairs from real errors | Never overwrites an existing folder; protected zones refused; stripped environment and time limits for generated code; success only when checks pass |

## 51.2 Owner-directed changes (2026-10-01, later)

| Area | Before | Owner decision | Safeguard kept |
|---|---|---|---|
| Screen | Local OCR text only | Screenshots may go to Gemini (free models) so Chutku can see the screen and act on it | Gemini off without `cloud.gemini`; HUD excluded from capture; clicks only on fresh element ids; consequential clicks (Gemini label or local OCR) are R3 |
| Priority | Safety first, then automation | Automation is the priority; hands-free level set to Auto: incl. file edits; network after public web content no longer needs a click | R3 still on-screen (HUD Approve); edits after untrusted content still confirm; egress after private reads still confirms; existing documents protected unless named |
| Billing | - | No paid API; free models only, even if slower | Daily-quota memory, lite models for planning and vision, local fallback |
| Activation | Ctrl+Alt+Space with the server running | Always available from sign-in; wake phrases "Oye Chutku" and "Chutku sun" | Per-user logon task, never elevated; the wake listener is deaf while Chutku speaks |
