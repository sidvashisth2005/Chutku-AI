# Architecture

How the runtime is built. Merged from docs/ARCHITECTURE.md and docs/ARCHITECTURE.md. The newest agent path (chat → router/planner → policy → tools → verification) is summarised in the README.


---

## Part: Architecture

Source of truth: `docs/DESIGN.md`. User direction, 2026-09-26:
foundation first, then brain, permissions/access, local LLM, and finally voice integration.
Mark LIV remains a reference; Chutku remains the runtime. No cloud LLM or paid API.

## Working boundaries

```text
Text CLI / authenticated loopback dashboard
    -> planning.plan_request: deterministic understanding, no side effects
    -> READY typed command / CLARIFYING without tool execution
    -> Runtime: argument validation -> policy -> execution lock -> action
    -> independent observation where provided -> PASS / FAIL / UNKNOWN
    -> durable task trace + operation journal -> presented outcome

Optional pinned local model adapter -> closed command proposal -> explicit review
    -> existing Runtime (never its own execution authority)

Optional offline voice -> exclusive/cancellable audio session -> energy VAD
    -> free-form local Windows dictation -> local LLM typed-tool plan
    -> server-held single-use review -> ordered Runtime execution
    -> separate action-time confirmation for high-risk steps
    -> reviewed microphone provenance
```

The planner is not the LLM. It owns the request/plan interface and emits a stable,
closed intent label separately from the proposed tool and arguments. The LLM is
an optional language adapter. Authorization is outside both. A model-generated
risk or confirmation field cannot grant permission.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `app.py` | Project-relative paths, trusted sandbox, runtime construction |
| `doctor.py` | Read-only prerequisite and SQLite health inspection |
| `planning.py`, `router/catalog.py` | Typed deterministic plan, closed labeled-intent vocabulary, explicit clarification, no implicit model fallback |
| `runtime.py`, `core/task.py` | Validated task lifecycle and verification before completion |
| `policy/kernel.py`, `core/approvals.py` | Runtime risk, provenance denial, exact single-use approvals |
| `core/resource_grants.py` | Durable explicit roots, observe/modify scope, revocation and execution-time recheck |
| `core/capability_grants.py` | Exact non-filesystem PC authority, durable revocation, approval-version binding |
| `core/execution_lock.py` | Serialize cooperating CLI/dashboard actions across processes |
| `core/event_log.py` | Redacted SQLite WAL event history and interrupted-task reconciliation |
| `core/operation_journal.py`, `core/paths.py` | Sandboxed text changes, before/after journal, conflict-aware undo |
| `guard.py` | Separate Windows supervisor, heartbeat/action deadlines, owned process tree termination |
| `brain.py` | Pinned, evaluated local language adapter; never execution or authorization authority |
| `gemini.py`, `ensemble.py` | Consent-gated Gemini advice and fail-closed dual-model reconciliation |
| `tools/processes.py` | Capability-gated process observation and exact approved launch/termination with identity recheck |
| `voice/session.py`, `voice/recognition.py`, `tools/speech.py` | Exclusive audio state, bounded local STT/TTS, cancellation and review-only transcript |
| `dashboard.py`, `web/` | Local presentation and explicit review controls |
| `evidence.py`, `scripts/verify_release.py` | Saved measurements and source-fingerprint freshness |

### Added 2026-10-06 (master plan S1–S21)

| Module | Responsibility |
|---|---|
| `agent_loop.py` | Agent sessions: quick tier → learned skills → exact replay → local/backup planner; untrusted-data wrapping and instruction removal; taint/exposure/suspicious flags; cancel; claim guards |
| `quick_intents.py`, `intents/lexicon.py`, `*_intent.py` | Deterministic Hinglish/English rules with one shared vocabulary, and fixed instant answers |
| `brain_service.py`, `local_vision.py`, `cloud_planner.py`, `profiles.py` | Local llama.cpp services (in-flight count, GPU hand-over, streaming), Gemini/8B backup |
| `core/ledger.py`, `tools/ledger_tools.py` | Earned autonomy: outcome ledger, Wilson lower bound, add-only policy input |
| `reflex.py` | Reflex compiler: learned instant skills with leave-one-out and collision gates, demotion |
| `rewind.py` | Causal rewind: effects with lineage, dependency closure, conflict check, inverse execution |
| `scheduled.py`, `tools/schedule_tools.py` | Scheduled and repeating tasks, run through the normal session path |
| `voice/speaker.py`, `tools/voice_lock_tools.py` | Owner voice lock: WeSpeaker ONNX embedding, enrollment, verdict per voice request |
| `nightshift.py` | Nightly jobs: skills, reliability, plan-only regression replay, maintenance, fine-tune readiness |
| `timeline.py`, `tools/timeline_tools.py` | Opt-in window-title timeline with private masking and time-phrase search |
| `core/log.py`, `core/launch.py`, `core/jsonstore.py`, `core/hashcache.py` | Redacted rotating log, owner-app launches outside the guard job, atomic JSON stores, hash cache |
| `voice/live.py`, `voice/handsfree.py`, `voice/heard.py` | Gemini Live conversation, offline wake listener, local heard log |

## Foundation acceptance scope

- Python 3.11+ and Windows; launch independent of the current shell directory.
- Missing model artifacts do not block deterministic tools.
- Health checks do not start the model or open the microphone.
- Unsupported requests clarify; no generated shell/code or silent fallback.
- Mutations remain inside a dedicated sandbox and use existing policy and verification.
- Unknown verification never becomes success; interrupted tasks are not marked complete.
- Full regression tests and a real CLI/dashboard path accompany changes.
- `Start-Chutku.cmd` starts the independent guard. Direct `chutku.cli dashboard`
  and single CLI commands are intentionally unsupervised development paths.

## Guard limits

The guard assigns the waiting dashboard process to a Windows kill-on-close Job
Object before allowing startup. Descendants inherit membership. Core heartbeat
deadline is five seconds after readiness; startup deadline is twenty seconds;
an HTTP action has a 120-second bound. Ctrl+Alt+F12, Stop-Chutku.cmd, and the
dashboard Stop control request termination. No action is replayed or auto-resumed.

The job does not own existing desktop apps or all Windows-brokered app launches.
It releases Chutku-owned audio by stopping owned processes; it does not globally
mute the microphone. A separate tray stop control remains unimplemented. Files
already written remain journaled for inspection/recovery. A guard crash kills
its job; its stale running marker forces a paused next start.

## Current stage boundary

The foundation, deterministic plan contract, access layer and local language
adapter are accepted by source-bound gates. Voice software and individual real
Windows microphone/STT/TTS probes pass. Free-form dictation and the general
registry-backed local planner are implemented; one observation-only real
model-to-Runtime proof passes. A consented live reviewed full path and
human accent/condition accuracy remain empirical gates and cannot be inferred
from synthetic SAPI speech or a successful microphone-open check.
The local adapter remains review-first and is not promoted to autonomous use.

The expanded goal is broad Windows automation, defined in
`docs/ROADMAP.md`. Stage 6 now publishes a machine-readable manifest
for every registered tool and binds reviewed plans/approvals to its SHA-256.
The current Stage 7 slices add exact process launch/termination, verified file
identity/search, no-overwrite copy/move, conflict-aware undo, recoverable
recycle/restore, and reviewed graceful close for the allowlisted Windows apps.
Stage 8 now has display inventory, local verified PNG capture with undo, bounded
read-only UI Automation inspection, and a clipboard-text slice. UI Automation
actions, general desktop input, browser automation and settings mutation are not
yet implied.

Tool manifests declare bounded arguments, risk, exact non-filesystem capability
or filesystem access, sensitive fields, prerequisites, reversibility, success
predicate and whether an independent verifier exists. Approval and deterministic
multi-step review store the manifest digest; a changed contract invalidates the
review before execution.

UI Automation inspection also reports the exact supported action patterns per
element. This is discovery data only: a later action must still rebind the exact
window and selector, pass policy/review, and prove its own postcondition.


---

## Part: Foundation

Development order agreed on 2026-09-26:

1. Foundation: stable startup, task engine, storage, verification, stop/recovery.
2. Brain: deterministic intent/plan interface, clarification, bounded orchestration.
3. Access and permissions: explicit resource grants, risk escalation, approval UX.
4. Local LLM: measured language adapter over the tested brain/tool vocabulary.
5. Voice: reviewed speech into the same pipeline, then measured conversation/PTT.

## Run the foundation

From this project folder:

```powershell
.\.venv\Scripts\python.exe -m chutku.cli doctor
.\.venv\Scripts\python.exe -m chutku.cli plan "write hello to example.txt"
.\.venv\Scripts\python.exe -m chutku.cli ask "what time is it"
.\.venv\Scripts\python.exe scripts\verify_release.py
```

`plan` never runs the proposed action. `doctor` reports optional model/audio
availability separately from required core health. Keep the existing `.venv`;
its interpreter works here even though its creation metadata names the original
project directory. Use `python -m ...`, not copied package console launchers.
Doctor also requires `pyproject.toml`, `requirements.lock`, and
`THIRD_PARTY_LICENSES.md`; missing dependency/licensing records fail the foundation.

Launch `Start-Chutku.cmd` for the guarded dashboard. If actions are paused after
a stop, inspect Activity/unfinished writes, then click Resume actions. A stop
does not erase completed files or undo an app launch.

## Evidence

The machine-readable checkpoint is `verification/release-report.json`; full test
details are in `verification/release-tests.txt`. Dashboard Verification marks
saved evidence stale when source files change. Reports retain failed hardware
checks. `docs/ARCHITECTURE.md` defines responsibilities; `docs/SECURITY.md` defines limits.

## Not yet complete

General GUI/browser automation, task resumption across arbitrary workflows,
resource-specific grant UI, comprehensive risk escalation, a tray stop control,
multilingual speech measurements, wake word, and large golden-task benchmarks.
The project license also remains an owner decision before public release.

Do not promote the full master plan as complete merely because the foundation
and demonstration pass their narrower tests.
