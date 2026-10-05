# Security and threat model

Merged from docs/SECURITY.md and docs/SECURITY.md.


---

## Part: Security

Chutku is intentionally incomplete. Do not treat the current runtime as suitable for unrestricted automation or sensitive production data.

The initial runtime follows these constraints:

- The policy kernel currently uses trusted registered tool risk metadata; argument-dependent risk escalation is not implemented yet.
- Tools are registered explicitly and unknown tools are denied.
- The filesystem list tool is restricted to the resolved `sandbox/` directory.
- Each task writes an append-only event trail to a local SQLite WAL database.
- Verification failure or uncertainty is never reported as success.

Report vulnerabilities privately to the project owner. Do not include secrets, credentials, or sensitive screenshots in issues or event logs.

## Local dashboard preview

The server binds only to 127.0.0.1, requires a random per-launch API token, and
checks the exact Host and Origin. It serves only the three bundled static files.
Workflow preview tokens expire after two minutes and are consumed before execution.
Workflow previews remain distinct from task approvals. R3+ runtime requests now
use exact server-owned task/argument/root snapshots with expiring single-use
tokens. The HTTP approval endpoint accepts only that token. External-side-effect
tools are not currently registered; those approval paths are tested with fixtures.

Path checks reject existing aliases and ambiguous Windows names, but they are not
OS-level process isolation. A hostile process with access to the same folders can
race path checks or alter local databases. Cooperating CLI/dashboard instances serialize actions with an OS file lock.
This does not prevent unrelated programs from changing files. Use a dedicated sandbox.

Undo compares current contents with the recorded post-write contents. Recovery
requires a recognizable recorded state. Legacy journal entries without expected
contents are refused for automatic recovery. Atomic replacement reduces partial
text writes but is not a guarantee against all power-loss or storage failures.

Saved memory and the operation journal are plaintext. Ordinary audit redaction
does not encrypt storage, securely erase SQLite pages or protect against another
program running as the same Windows user. Plugins are not loaded automatically.

## Voice, pause, and experimental model

Speech and recognition use fixed local scripts, JSON stdin, and installed Windows
engines. Audio is held in memory and discarded; a fixed energy VAD rejects silence
and low-level noise before STT. Recognized phrases are untrusted and never
auto-executed. A separate audio-session state prevents Chutku capture and speech
from overlapping, but cannot silence unrelated applications. Dashboard transcript
review uses an expiring single-use server-held token, refuses retargeting/replay,
and preserves `microphone_untrusted` provenance through runtime authorization.

Action pause is persistent and cooperative. A blocked OS call may outlive a pause.
Start-Chutku.cmd additionally starts a separate Windows guard. It assigns the
waiting core to a kill-on-close Job Object, watches heartbeat/action deadlines,
and owns Ctrl+Alt+F12. Stop-Chutku.cmd and the authenticated Stop control signal
that guard. Direct CLI/dashboard commands do not have this supervision. Existing
or Windows-brokered app processes may remain open; completed effects are not undone.
No tray stop control or global microphone mute is claimed. See docs/SECURITY.md.

Non-user provenance is denied for R2+ actions by the runtime policy. This depends
on trusted adapters preserving provenance; it is not hostile Python-code isolation
or comprehensive semantic injection detection.

The experimental model proposes only up to three fixed commands, with no tools
or ambient file/memory access. The server binds to literal loopback with a random
per-process API key, disables its web UI, uses offline mode, and is stopped after
planning. No remote endpoint, proxy, redirect, or cloud fallback is supported.
Dashboard review tokens are server-owned, single-use and expire after five minutes.
Reviewed model steps retain `inferred` provenance when they re-enter policy;
review does not relabel model output as user-stated. Model correctness still
requires human review; valid JSON does not establish intent.

## Expanded PC authority and Gemini advice

Non-filesystem authority is stored as exact named capabilities. Wildcards are
invalid, no capability is enabled by default, revocation is checked again before
execution, and high-risk approvals bind the capability version. A copied build
running under a normal Windows account receives only that account's OS rights;
it does not bypass Windows security or Chutku's own policy.

Gemini is an optional advisor, not a fallback inside the offline local model.
The adapter uses a fixed Google HTTPS endpoint, structured output, bounded input,
response size and timeout, and an environment-provided API key. Each cloud call
requires explicit consent to send the exact request text. Files, screenshots,
clipboard contents, memory, tool output, and execution credentials are not sent
by this adapter. Model disagreement produces clarification and no action.

Clipboard text is a separately granted local capability. Reads are bounded to
64 KiB, labeled `external_untrusted`, and redacted from the audit database.
Writes use JSON stdin with a fixed PowerShell program and exact read-back
verification; clipboard data is never included in Gemini or local-model prompts.

Screen observation is a separate exact capability. Display capture writes only
to a new PNG inside the selected modify grant, binds and rechecks display layout,
verifies dimensions/hash, and supports conflict-aware undo. Screenshot pixels are
not sent to either model by the capture tool. UI Automation inspection is
read-only, bound to one exact supported HWND/PID, capped at 250 elements/depth 5,
and treats all accessible names as untrusted data redacted from audit storage.
These controls do not prevent another same-user program from reading the screen.

UI actions require the separate `desktop.input` capability, on-screen review,
exactly one supported responsive window, exact foreground ownership, and a unique
UIA selector. Invocation requires a postcondition that is false before and true
after; value, selection and scrolling require action-specific read-back. UIA
actions remain application-dependent and are not a general rollback mechanism.

Clipboard text is a separately granted local capability. Reads are bounded to
64 KiB, labeled `external_untrusted`, and redacted from the audit database.
Writes use JSON stdin with a fixed PowerShell program and exact read-back
verification; clipboard data is never included in Gemini or local-model prompts.


---

## Part: Threat model

Scope: the current local Windows runtime, not hostile-code isolation or a complete
security certification. The master context governs expansion.

| Input or failure | Boundary implemented | Remaining limitation |
|---|---|---|
| Untrusted file/model content | Files are labeled untrusted; model has no file/memory access or tools; runtime denies non-user R2+ requests | Future adapters must preserve provenance; Python callers are trusted application code |
| Forged confirmation | Server-owned exact task, argument snapshot, root binding, expiring random token, single use | Pending approvals are invalidated by restart; R3+ tested with fixtures, no external-send tool shipped |
| Browser cross-origin request | Loopback binding, Host/Origin/session token checks, bounded JSON, CSP | Same-user hostile local processes are outside the isolation boundary |
| Path escape or alias | Dedicated root, Windows-name/ADS/reparse/hardlink checks, bounded UTF-8 writes | Native hostile-process TOCTOU protection is not established |
| Newer user edit | Undo/recovery requires recognizable current content | No general transaction across unrelated tools |
| Core/model hang | Independent guard, action deadline, Job Object, persistent pause | Direct CLI is not guarded; brokered/existing apps may survive; tray control pending |
| Guard crash | Windows closes job and kills owned tree; next launch detects running marker | Stop report may be absent when supervisor itself crashes |
| Voice playback injection | Fixed English grammar, energy VAD, half-duplex audio session, server-held expiring review token, microphone provenance and no audio-triggered execution | No general multilingual recognition, speaker authentication or always-on wake word |
| Voice review tampering/replay | Exact server-held command, source-task binding, random single-use token, cancellation and policy re-entry as `microphone_untrusted` | Same-user hostile processes remain outside the isolation boundary |
| Misleading tool success | Runtime requires PASS; app verifier re-observes visible responsive window | Foreground focus may be denied by Windows and must remain a failure |
| Sensitive data in audit | Text writes, memory values, window titles and transcript contents redacted | Operation journal and saved notes are plaintext; no secrets vault |
| Overbroad PC permission | Exact capability vocabulary, no wildcard, disabled by default, durable revoke and execution-time recheck | Same-user hostile code can still tamper with local state; OS isolation is not claimed |
| Cloud command disclosure | Gemini call requires explicit consent; fixed endpoint; bounded request text only; no files/screens/memory/clipboard | The approved request text is processed by Google under the user's account and service terms |
| Clipboard disclosure or command injection | Separate exact read/write grants; 64 KiB limit; content is untrusted and audit-redacted; fixed script receives JSON stdin; no implicit model disclosure | Other applications in the same desktop session may independently observe or change the Windows clipboard |
| Screen/UI data disclosure or stale identity | Exact screen capability; capture binds/rechecks display layout and stores create-new local PNG; UIA inspection binds/rechecks one HWND/PID and audit-redacts names | Same-user software can observe the desktop; screenshots contain sensitive pixels; UI actions are not enabled yet |
| UI action retargeting or false success | Exact desktop-input grant and review; one foreground HWND/PID; unique selector; action-specific postcondition and foreground recheck; real Calculator and disposable WPF fixture evidence | Rollback is app-dependent; arbitrary coordinates and broader application compatibility remain unimplemented |
| Audio, network, settings or power overreach | Separate exact grants; reviewed exact read-back and conflict-aware restore; bounded/redacted inventory; power requires exact phrase, 5–60 minute delay and reviewed cancel path | Positive live adapter mutation is not routinely tested; shutdown after its cancellation deadline necessarily ends applications and may lose unsaved work |
| Browser prompt injection, credential reuse or misclick | Fresh visible profile; extensions/downloads disabled; credential-free HTTP(S) URL; semantic exact locators; per-action postconditions; page data audit-redacted | Public sites can change and browser actions remain site-dependent external effects; no credential or payment automation is delivered |
| Cross-application partial failure or recovery substitution | Server-owned random single-use reviewed plan; exact forward/compensation manifests; stop on failure; declared reverse recovery; replay refusal | Recovery can itself be denied or fail and is reported rather than hidden; site-dependent effects may be irreversible |
| Clipboard disclosure or command injection | Separate exact read/write grants; 64 KiB limit; content is untrusted and audit-redacted; fixed script receives JSON stdin; no implicit model disclosure | Other applications in the same desktop session may independently observe or change the Windows clipboard |
| Model disagreement | Exact executable agreement or clarification; neither model has tools or approval authority | Agreement is not proof of correctness; review and post-action verification remain required |

No unrestricted shell, arbitrary code runner, passive keyboard recording, or
general browser automation is enabled. The local model has no cloud fallback;
Gemini is a separate, explicit-consent advisory path when configured.

Evidence includes refusal/replay/expiry tests, 60 generated provenance-policy
cases, Windows process fault injection and real command smoke checks. The 60
cases exercise a deterministic boundary; they are not an adversarial semantic
prompt-injection benchmark and do not establish a statistical security guarantee.
