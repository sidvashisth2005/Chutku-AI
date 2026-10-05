# Mark LIV reference notes

Merged from docs/reference/MARK_NOTES.md and docs/reference/MARK_NOTES.md. Reference only; no Mark code is used.


---

## Part: Learnings

Study date: 2026-09-24. Reference: `D:/Project/Mark-LIV-main`, supplied local snapshot.
This is persistent project memory, not a claim that the assistant's model weights or
global memory were changed. Read this alongside `docs/PROJECT_MEMORY.md` and
`IMPLEMENTATION_STATUS.md` when continuing development.

## Provenance and approach

Mark LIV identifies FatihMakes as its author. Its LICENSE states CC BY-NC 4.0
and prohibits commercial use. No Mark source files, assets, secrets, certificates,
personal memory, or dependency tree are being copied into Chutku. The implementations
in this slice are written for Chutku's existing interfaces. This notebook records
the behavioral ideas studied and their provenance; it is not a license clearance.

The reference was inspected as source, not certified by running its full assistant.
Descriptions below distinguish observed code from claims in its README.

## Lessons selected for the presentable slice

| Reference | Observation | Chutku decision |
|---|---|---|
| `core/prompt.txt`, `main.py::_describe_tools` | Capabilities should come from the actual registered actions. | Generate a capability inventory from ToolRegistry, with explicit limits. |
| `ui.py`, `main.py::_execute_tool` | Users need visible state, immediate acknowledgement and results. | Local browser dashboard with running state, results, audit history and exact task IDs. |
| `memory/memory_manager.py::search_memory` | Small lexical search is useful without embeddings or another model. | SQLite-backed explicit notes, bounded search, provenance, timestamps and deletion. |
| `memory/memory_manager.py::all_entries_for_ui` | Users should see and remove remembered facts. | Searchable memory panel. No passive capture or inferred permanent facts. |
| `core/confirm.py` | A pending operation should be stored outside model arguments. | Preview tokens bind one workflow to one execution, expire, and cannot be replayed. This is workflow consent, not the final R3+ approval system. |
| `actions/dev_agent.py` | Multi-step work benefits from visible steps and bounded attempts. | Small deterministic project recipe, preflight of every step, stop on failure and linked step traces. No arbitrary generated code execution. |
| `core/undo.py` | Shared undo is essential; memory-only closures disappear on restart. | Keep Chutku's durable journal and reject undo when a newer external edit is detected. |
| `actions/file_controller.py` | Resolved paths and explicit size limits matter. | Reject Windows device names, ADS, absolute/UNC/traversal paths and reparse components; bound reversible text writes. |
| `actions/desktop.py`, `actions/open_app.py` | OS integration should report observed desktop state. | Read visible Windows windows through native APIs; report process IDs, redact titles from audit. App launching remains a later verified slice. |
| `dashboard/server.py` | A dashboard creates an additional permission boundary. | Loopback only, random session token, exact Host/Origin checks, no external assets, bounded JSON requests. No LAN server or firewall changes. |

## Additional details extracted for later phases

| Reference | Useful detail | Future implementation / validation needed |
|---|---|---|
| `core/action_loader.py` | Metadata and handlers share a consistent contract; duplicate names rejected. | Keep explicit registration today; later manifests must validate arguments and declared authority. |
| `core/plugin_loader.py` | Optional skills can fail individually without stopping discovery. | Never equate schema validation with sandboxing: Python imports execute code. Isolate any future untrusted plugin. |
| `core/hotkey.py` | Windows push-to-talk needs press AND release, debounce, stop cleanup and honest scope reporting. | Implement after measuring local STT; verify microphone closes on release, errors and shutdown. |
| `core/audio_devices.py` | Stable device names are more useful than volatile indices; opening a device proves more than enumeration. | Device picker with explicit short probe and fallback; no surprise audio playback/capture. |
| `core/echo.py` | Speaker-output history can help distinguish self-echo; noisy rooms weaken separation. | Measure on this laptop. Never label a heuristic as guaranteed echo cancellation. |
| `core/wake_word.py` | Installation and model-file availability are separate states. | Opt-in local model download; no automatic microphone streaming or silent installation. |
| `main.py` audio queues | Audio callbacks should hand off work; interruptions must flush stale playback. | Bounded queues, cancellation, device disconnect and echo tests before always-on voice. |
| `main.py` reconnect handling | Connection recovery and conversation reset are different events. | Preserve only valid local session state; never replay mutating actions on reconnect. |
| `core/gemini.py` | Centralized model deadlines, concurrency limits and cooldowns avoid scattered retries. | Apply these patterns to a local provider adapter; do not inherit the cloud dependency. |
| `core/llm_client.py` | Local providers need health checks and structured outputs. | Benchmark parser accuracy and RAM/VRAM use. This file is not the active main voice path. |
| `actions/browser_control.py` | Playwright offers structured browser operations and session lifecycle handling. | Dedicated test profile, URL verification and DOM-based actions before coordinate fallback. |
| `actions/computer_control.py` | Clipboard-based typing supports text that synthetic keystrokes may mishandle. | Future explicit clipboard permission, restoration and target-window verification. |
| `actions/screen_processor.py`, main vision dispatch | Screenshots and webcam images need distinct source labels. | Preserve untrusted provenance; camera access explicit; no image treated as an instruction. |
| `actions/background_monitor.py` | Content hashes help suppress repeat alerts. | Opt-in watches, change-only notifications, persisted last-seen state and bounded schedules. |
| `actions/proactive.py` | Context-sensitive assistance can be useful but interruptive. | Quiet hours and explicit user control; no unsolicited actions based on guessed intent. |
| `actions/reminder.py` | OS schedulers can persist reminders beyond application lifetime. | Structured arguments, inspectable ownership, delete/cancel support and real delivery checks. |
| `memory/memory_manager.py` | Retrieval can keep a prompt small without deleting all older facts. | TTL, confidence and source fields before inferred or external memories are introduced. |
| `main.py` session summaries | A short prior-session summary can provide continuity. | Opt-in summarization; never turn model guesses into user-stated facts. |
| `core/avatar.py`, `core/viseme.py`, `ui.py` | Visual state can communicate listening/thinking/speaking. | Use simple honest status indicators now; animated face and lip-sync are deferred. |
| `ui.py` clipboard features | Small contextual actions can provide everyday utility. | Prefer explicit paste/action rather than passive clipboard monitoring. |

## Patterns deliberately not inherited

- Messaging returns a success string after keystrokes without verifying recipient or delivery.
- Coding-agent timeout is treated as non-error; process return codes are not carried through its runner result.
- Ten-entry in-memory undo is not crash recovery; a failed undo is removed from that stack.
- Broad shell/app launching and unconstrained generated programs exceed Chutku's authority model.
- Main conversation uses Gemini Live; no-cloud and no-paid-API constraints remain in force.
- LAN dashboard, automatic firewall changes, bundled certificates and cloud credentials are not imported.
- Marketing feature lists are not evidence of working behavior or benchmarked reliability.

## Extraction complete for this slice

Selected integrations and the implementation boundary are recorded above. Development
now proceeds in Chutku. Remaining ideas are a backlog, not delivered features.
Verification evidence and any scope changes belong in IMPLEMENTATION_STATUS.md.


---

## Part: Reference review

Reviewed `D:\Project\Mark-LIV-main` on 2026-09-27 as design input. No Mark code
was copied into Chutku.

## What Mark uses

- `actions/computer_control.py`: PyAutoGUI for coordinates, typing, hotkeys,
  scrolling, drag, clipboard paste and screenshots. `FAILSAFE` is enabled, but
  successful API return text is generally treated as action success.
- Windows focus uses `WScript.Shell.AppActivate` with a title fragment; it does
  not bind executable/PID/HWND or re-observe foreground ownership.
- `screen_find` sends a screenshot plus natural-language description to Gemini
  and uses returned coordinates without a fresh display/window binding.
- `actions/game_updater.py`: pywinauto UIA descendants by control type, with
  localized text matching and coordinate fallback. This provides useful breadth,
  but clicks are not followed by exact independent postcondition checks.
- `actions/browser_control.py`: persistent Playwright sessions, multi-browser
  executable discovery, semantic locators and interactive fallbacks.

## Adopted ideas

- UIA control-type-first discovery before coordinate fallback.
- Explicit discovery of supported UIA patterns (`invoke`, `value`,
  `selection_item`, `scroll`) so planners cannot request an unsupported action.
- Keep PyAutoGUI-style emergency-corner fail-safe as an additional future input
  abort, while retaining Chutku's independent guard and persistent pause.
- Reuse the Playwright session/executable-discovery concepts in Stage 9, with a
  dedicated profile, exact tab/origin binding and post-navigation verification.

## Boundaries Chutku retains

- Exact capability grant, review token and provenance checks before input.
- Exact executable/PID/HWND and verified foreground ownership; never title-only.
- Unique automation ID/name plus control type, not fuzzy text as authority.
- Action-specific postconditions; an automation API returning normally is not success.
- Screenshots and clipboard contents remain local unless separately disclosed and approved.
- Coordinate fallback remains disabled until structured UIA real-fixture gates pass.
