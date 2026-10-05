# Roadmap and stage gates

Merged from docs/ROADMAP.md, docs/ROADMAP.md and docs/ROADMAP.md. Current progress lives in IMPLEMENTATION_STATUS.md.


---

## Part: Full-PC automation plan

The five original stages establish a verified safety core; they do not constitute
complete PC automation. This expansion turns that core into a broad Windows agent.
An action counts as supported only when Chutku can target it precisely, authorize
it, execute it, re-observe the result, and report verification honestly.

## Non-negotiable execution protocol

Every computer-changing step follows:

1. Observe the current target and bind its identity.
2. Produce a typed plan from registered capabilities only.
3. Consult local and Gemini planners when Gemini is configured, reachable, and
   the user has explicitly allowed that request text to leave the computer.
4. Require exact consensus or deterministic arbitration; disagreement clarifies.
5. Display material effects and obtain risk-appropriate user approval.
6. Recheck target identity, permission, pause, and approval immediately before use.
7. Execute one bounded step.
8. Re-observe and compare against an explicit success predicate.
9. Journal reversible effects; stop at the first unverified result.

No LLM may click, type, run a process, change a file, or confirm its own action.

## Stage 6 — PC capability and authority foundation

- Add typed grants for desktop input, screen capture, processes, applications,
  browser profiles, network/cloud consultation, clipboard, and OS settings.
- Add capability manifests with argument schemas, risk, prerequisites, verifier,
  reversibility, sensitive fields, and declared resource authority.
- Add task-scoped target snapshots and a durable action/undo journal.
- Add optional Gemini structured planning. Send only the bounded request by
  default; never send screenshots, files, clipboard, memory, or secrets implicitly.
- Acceptance: grant/provenance matrix, model disagreement tests, expired/revoked
  permission tests, and zero execution from either model response alone.

## Stage 7 — Files, processes, and applications

- Explicitly granted filesystem roots: inspect, search, copy, move, rename,
  create, edit, recycle, and restore with conflict-aware verification.
- Enumerate, launch, focus, wait for, and close exact applications/processes.
  Arbitrary command lines remain a separately approved expert capability.
- Acceptance: real Windows scenarios across user-selected folders and apps,
  rollback/conflict tests, process-image verification, and negative target tests.

## Stage 8 — Windows UI, screen, keyboard, mouse, and settings

- Prefer Windows UI Automation elements and accessibility identities.
- Use coordinate input only against a fresh screenshot/display fingerprint with
  visible preview and post-action re-observation.
- Add bounded keyboard, mouse, clipboard, window management, volume, display,
  network, and power controls with separate permissions and risk levels.
- Acceptance: a versioned desktop-task suite across multiple DPI/scaling states,
  interruption tests, wrong-window prevention, and verified final UI state.

## Stage 9 — Browser automation

- Dedicated Playwright profile, exact origin/tab binding, DOM-first selectors,
  downloads constrained to granted roots, and screenshot fallback as untrusted.
- Separate navigation, form entry, authentication, upload/download, messaging,
  purchasing, and publishing permissions. External side effects always require
  final on-screen approval at the destination and a delivery/result check.
- Acceptance: local deterministic test sites plus consented real-site checks;
  prompt injection from pages cannot authorize tools.

## Stage 10 — General planning and reliability

- Expand the closed action vocabulary only after its tools pass prior stages.
- Hierarchical planning, replanning after observations, checkpoints, resumable
  workflows, recovery, and model-independent success predicates.
- Benchmark at least 1,000 versioned requests plus real multi-application tasks,
  destructive-action refusal, cloud outage, model disagreement, screen changes,
  crashes, and emergency stops. Publish per-capability success rates and limits.

## Completion definition

“Complete PC automation” is not claimed as an absolute ability to execute every
possible utterance perfectly. Chutku is up to the requested level when the broad
capability inventory above is implemented, each capability has measured real-PC
evidence, failures stop safely, and the published benchmark meets its recorded
thresholds. Unsupported or unverifiable requests must be identified explicitly.

## Re-baselined execution order — 2026-09-27

The remaining work is executed in this order. A later workstream does not inherit
"complete" status merely because an earlier prototype exists.

### 6A — finish the authority contract

1. Publish a machine-readable manifest for every registered tool: bounded argument
   schema, risk, permission, sensitive fields, prerequisites, reversibility, and
   success predicate.
2. Bind plans and approvals to the manifest version and target observation.
3. Add task-scoped snapshots for windows, displays, browser tabs, and settings.
4. Gate: manifest completeness, tamper/version/revocation tests, model output alone
   causes zero effects, and a real read-only capability inventory succeeds.

### 7A — filesystem breadth

1. Add bounded search, metadata inspection, copy, rename, move, recycle, and
   restore inside explicitly granted roots.
2. Refuse drive-root grants, reparse traversal, hard-link ambiguity, overwrite by
   default, type changes, and source/target identity drift.
3. Journal before/after identities and hashes where practical; provide conflict-
   aware undo for copy/move/rename and restore.
4. Gate: real disposable-folder scenarios plus traversal, collision, concurrent
   modification, revocation, interrupted-operation, and rollback tests.

### 7B — general application lifecycle

1. Enumerate and bind exact executable, PID, window handle, title, and responsiveness.
2. Launch, wait, focus, request graceful close, and separately approve forced
   termination. Never select a target by title alone.
3. Gate: real Notepad plus one traditional Win32 and one packaged Windows app;
   duplicate-window and changed-process negative cases must fail closed.

### 8A — observation and structured UI Automation

Current checkpoint (2026-09-27): 8A-1 display inventory/safe capture and 8A-2
bounded read-only UI Automation inspection pass unit and real Windows checks.
8A-3 is accepted: exact-target invoke/expand/value/select/scroll contracts pass
the real Calculator button path and a disposable WPF menu/text/list/scroll fixture.
Changed identity, missing focus and failed postconditions fail closed. The action
target contract supports exact HWND/PID/executable triples so arbitrary-app support
does not depend on titles. 8A-4 is also accepted for bounded exact-field keyboard
typing and exact-element mouse clicks with semantic postconditions. Arbitrary
coordinate input remains intentionally unavailable. The next execution-order item
is Windows settings, volume, network and power controls. Item 5A now real-verifies
volume observe/change/conflict-aware restore and bounded network observation with
separate grants. Item 5 is accepted for bounded volume, theme, physical-adapter,
and delayed power controls: reversible settings and delayed shutdown cancellation
are real-verified; positive adapter mutation is unit-verified with real identity
refusal because toggling the active connection is intentionally non-routine.
Item 6 now has real-verified Playwright inspection and reviewed semantic workflows
against a disposable local page in installed Edge. Public-site compatibility and
site-specific side effects remain dependent on each site and explicit permissions.
Item 7 real-verifies a server-owned reviewed settings-plus-browser plan, controlled
failure, reverse recovery and replay refusal. Item 8 passes 1,200 deterministic
runtime requests; it is not a substitute for the separate human voice evaluation.

1. Add display inventory and bounded screenshots behind `screen.observe`; screenshots
   remain local unless separately disclosed and approved.
2. Add UI Automation tree inspection with stable runtime/control identities.
3. Add invoke, select, toggle, value entry, and scrolling against a freshly rebound
   element; prefer UIA over coordinates.
4. Gate: versioned Windows fixtures across DPI/scaling states, wrong-window and stale-
   element prevention, interruption, and exact post-action state checks.

Execution slices for 8A are strictly ordered:

1. `8A-1 display`: inventory display device/bounds/primary identity; capture one
   reviewed display to a new PNG inside a modify grant; recheck the display
   fingerprint; verify PNG dimensions/hash; provide conflict-aware undo.
2. `8A-2 inspect`: bind an exact HWND/PID/executable and return a bounded local
   UI Automation tree with stable runtime IDs; user-controlled names remain data.
3. `8A-3 operate`: invoke/select/toggle/value/scroll only by a fresh element
   snapshot plus independent post-action state observation.
4. `8A-4 fallback`: add foreground-bound keyboard/mouse only after 8A-3 passes;
   coordinates additionally bind display layout and a short-lived screenshot.

### 8B — keyboard, mouse, clipboard, and settings

1. Add bounded keyboard/mouse actions only after exact foreground-window binding.
2. Permit coordinate actions only with a fresh display fingerprint, visible preview,
   short expiry, and re-observation.
3. Separate clipboard read/write, audio, display, network, power, and settings grants.
4. Gate: emergency stop during input, focus theft, display-layout change, clipboard
   secrecy, settings rollback, and power-action approval tests.

### 9 — browser

1. Use a dedicated Playwright profile and bind every step to browser, context, tab,
   URL origin, and DOM observation.
2. Implement navigation and reading first; then forms, download/upload, authentication,
   messaging, purchasing, and publishing as separately gated capabilities.
3. Treat all page text, downloads, screenshots, and model suggestions as untrusted.
4. Gate: deterministic local sites, origin/tab swaps, downloads restricted to grants,
   prompt-injection refusal, and consented real-site smoke checks.

### 10 — planner, voice, and reliability closure

1. Expand the brain vocabulary only for accepted manifests; add observation-driven
   replanning, checkpoints, resumability, and bounded recovery.
2. Make text and reviewed voice use the same planner, policy, permissions, verifier,
   journal, pause, and emergency-stop path.
3. Run at least 1,000 versioned requests, multi-app scenarios, model disagreement,
   Gemini outage, UI drift, crashes, timeouts, and destructive-action refusal.
4. Complete one consented live voice-to-action run and 200 consented human trials.
5. Gate: publish per-capability success rates and known limits. The overall goal is
   complete only when Stages 6–10 pass; unsupported requests still fail explicitly.


---

## Part: Stage gates

This plan turns the master requirements in `docs/DESIGN.md` into
ordered delivery gates. A later stage cannot compensate for a failed earlier
stage. `IMPLEMENTATION_STATUS.md` records evidence; it does not replace these
acceptance criteria.

Run the gate checker from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\check_stages.py --through brain
```

Use `--through all` to see every remaining gate. A non-zero result means at least
one requested stage is not accepted. Hardware/model checks are never inferred
from unit tests or old evidence.

## Stage 1 — Foundation

Scope: startup, task lifecycle, tool contracts, storage, sandbox, verification,
audit, operation journal, independent stop/guard, and reproducible evidence.

Acceptance:

- `doctor` reports every required prerequisite and SQLite database healthy.
- Full automated suite passes with zero skips; guard fault injection covers a
  hung core, descendant termination, action deadline, and unclean restart.
- Core tool smoke passes, including traversal, ADS, conflict, recovery, and undo.
- A real CLI request completes; unsupported input clarifies; preview has no effect.
- Release evidence matches the current source digest.

Evidence: `verification/release-report.json`. Status: accepted on 2026-09-27.

## Stage 2 — Deterministic brain

Scope: closed labeled intents, explicit clarification, bounded reviewed plans,
preconditions, conflict detection, final-state verification, and no LLM dependency.

Acceptance:

- Every supported route has one stable intent label and typed tool arguments.
- Unsupported, missing, oversized, and ambiguous requests return `CLARIFYING`
  without an intent, tool execution, or request-content audit leakage.
- One-to-six-step plans validate every step before execution, require review,
  bind the reviewed content, stop on failure, and detect target changes.
- Planner tests and a real disposable multi-step path pass; foundation remains green.

Evidence: `verification/stage-gates.json`. Status: accepted on 2026-09-27.

## Stage 3 — Access and permissions

Scope: runtime-owned resource grants, least privilege, computed risk escalation,
task-bound approvals, cancellation/expiry, and clear approval presentation.

Acceptance:

- Grants are explicit, typed, scoped to a resource/action, durable where intended,
  revocable, and cannot be supplied or widened by request/model arguments.
- Canonical path and Windows alias/reparse/hardlink/ADS boundaries fail closed.
- R0/R1 policy, R2 mutation rules, R3+ on-screen confirmation, tainted provenance,
  approval TTL/single-use/same-task binding, pause, and policy recheck are tested.
- Dashboard and CLI show requested action, resource, computed risk, origin, and
  consequences without exposing secrets; denial never executes a tool.
- At least 50 provenance/injection cases, including microphone transcripts, yield
  zero unauthorized R2+ actions.

Evidence: `verification/stage-access.json`. Status: accepted on 2026-09-27.

## Stage 4 — Local LLM adapter

Scope: a pinned local model/runtime acting only as a language adapter over the
accepted brain contract. It has no execution or authorization authority.

Acceptance:

- Runtime/model source, revision, license, and SHA-256 are pinned and verified.
- Inference is local-only, has no cloud fallback/API-key inheritance, is bounded
  by timeout/context/output size, and can be killed by pause/guard.
- Output is schema-constrained or strictly validated against the closed intent and
  plan vocabulary; invalid, truncated, injected, or mixed unsafe plans clarify.
- At least 300 versioned labeled utterances measure tool/plan semantic accuracy;
  the accepted threshold is recorded, with zero unauthorized execution.
- Plans remain preview-only until explicit review and then re-enter Stage 3 policy.
- Reviewed model steps preserve `inferred` provenance through policy and audit;
  review cannot relabel model output as user-stated instructions.
- Missing model degrades to the deterministic brain without blocking core tools.

Evidence: `verification/stage-llm.json` and
`verification/stage-llm-evaluation.json`. Status: accepted on 2026-09-27.

## Stage 5 — Voice command path

Scope: push-to-talk capture, local STT, transcript review, the same brain/policy
path, verified response, local TTS, half-duplex safety, and device-change handling.

Acceptance:

- Audio/session state is separate from task state; capture is bounded, indicated,
  cancellable, memory-only by default, and releases devices on timeout/stop.
- Transcript is untrusted and review-only; voice alone never confirms R3+.
- Reviewed transcripts use expiring, single-use server-held tokens; browser text
  cannot retarget them and microphone provenance survives policy and audit.
- TTS suppresses listening/self-trigger and failure falls back to visible text.
- Synthetic tests cover silence, noise, low confidence, replay, timeout, pause,
  device failure, and no-auto-execution.
- Human recordings measure at least English and Indian-accented English command
  accuracy and latency. Hinglish/Hindi are claimed only if separately measured.
- The complete microphone → STT → brain → policy → tool → verification → response
  path passes a real Windows run, while the independent stop remains effective.

The human gate is fixed at at least 100 trials per listed accent group and at
least 20 trials in each of quiet 0.5 m/1 m/2 m, fan-noise and media-noise cohorts.
Quiet exact recognition must be at least 95%, noisy at least 85%, each accent
group at least 85%, and voice-triggered execution must remain zero.

Evidence: `verification/stage-voice.json`. Status: software and individual real
Windows audio checks pass; final acceptance is pending one consented live
end-to-end command and the consented human trials (0/200).

## Completion rule

The requested program is complete only when `check_stages.py --through all` exits
zero against fresh source-matched evidence. Software completion must not be used
to invent human-speech accuracy, audible TTS quality, foreground-focus reliability,
or other physical observations.

## Expanded goal — complete-PC automation

The original five gates certify the bounded core and voice path; they do not
certify arbitrary PC automation. The owner's expanded goal continues through
Stages 6–10 in `docs/ROADMAP.md`: exact PC authority, files/processes/
apps, Windows UI and screen control, browser automation, then general planning
and reliability. The original gates remain prerequisites and must be refreshed
after changes, but passing them alone is no longer overall project completion.


---

## Part: Development order

The master requirements remain in `docs/DESIGN.md`. This plan
orders delivery; it does not declare the full vision complete. Every stage needs
automated negative cases, a real Windows path, and evidence in the status ledger.
Detailed entry/exit criteria and the executable gate command are in
`docs/ROADMAP.md`. Later stages cannot be marked accepted while an earlier gate fails.

## Decisions

- English responses. Local inference only; Gemini is a future option, disabled.
- Zira is acceptable for now (the owner heard it through speakers); replace its
  quality later without blocking the command flow.
- Preserve explicit tools, policy, observation, verification, and durable audit.
- Download model/runtime artifacts once; no user data is sent for setup or inference.
- Start with bounded, reviewed plans. General autonomous desktop loops are later.

## Ordered delivery

### User-directed order, 2026-09-26 (supersedes the older sequence below)

1. Consolidate and verify the foundation in `docs/ARCHITECTURE.md` and `docs/ARCHITECTURE.md`.
2. Build the brain as a deterministic intent/plan/clarification layer, independent of an LLM.
3. Extend access and permissions, resource grants, risk escalation and approval UX.
4. Connect/evaluate the local LLM through the established brain interfaces.
5. Connect voice through that same verified path; measure human speech before broader claims.

Existing guard, approval, model and voice work is preserved. Experiments do not
bypass these gates. The older sequence below is retained as historical context.

1. **Foundation consolidation:** verify current app controls and voice output;
   keep records current; persistent action pause independent of the action queue.
   Cooperative pause is an interim boundary, not the independent kill guard.
2. **Voice baseline:** five-second offline English command capture, no saved audio,
   transcript review, explicit execution. Test synthetic audio separately from
   human speech. Evaluate multilingual neural STT before claiming Hinglish support.
3. **Local brain experiment:** portable llama.cpp + official Qwen3 4B Q4 model;
   pin hashes/license, measure actual command-planning accuracy and latency.
   First output is a reviewed plan from existing low-risk command choices.
   No model-generated shell/code, cloud fallback, or automatic execution.
4. **Reliable action loop:** independent heartbeat/kill guard with fault-injection
   tests; task-bound approvals; explicit cancellation and bounded recovery.
5. **Expand reach:** verified UI Automation for selected apps, browser DOM actions,
   file workflows. Add one capability only when its observed completion is reliable.
6. **Conversation:** selected local model, explicitly scoped conversational memory,
   multilingual STT, improved local TTS, measured half-duplex/PTT interaction.
7. **Broader autonomy:** durable workflow resume, scheduling, wake word, perception,
   and reliability benchmarks. Keep foreground ownership and failure recovery visible.

## Evidence gates

- Test success, refusal, timeout, conflicting state, and pause where applicable.
- Model JSON validity is not proof of semantic correctness or authorization.
- Human voice accuracy, p95 latency, RAM/VRAM, thermal behavior, Hindi/Hinglish,
  and autonomous-task success rates require separate measurements.
- Finish one useful vertical slice before expanding the next.
