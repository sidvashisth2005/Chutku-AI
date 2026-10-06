# Security and threat model

Rewritten 2026-10-06 (master plan S4) to match the code. `tests/test_docs_truth.py` checks the parts that can drift: the tool counts and the R3/R4 tool list.

Chutku is a same-user Windows assistant. It is **not** an isolation boundary against other programs running under the owner's account. Its job is to keep its *own* actions authorized, verified, logged and reversible, and to refuse to be steered by content it reads.

## 1. How a step is authorized

Every tool call goes through `Runtime.run`:

1. **Validation:** arguments are checked against the tool's own validator, and on the agent path also against the manifest schema.
2. **Never elevated:** if Chutku runs as administrator, every action is refused.
3. **The action log must be writable.** Otherwise nothing runs.
4. **`PolicyKernel.authorize`.** Its inputs:
   - the runtime-owned risk;
   - the resource grant (observe/modify roots);
   - the exact capability grant;
   - the protected zones;
   - provenance (user / delegated / microphone);
   - the autonomy mode;
   - taint and exposure;
   - a step-specific question.

   A model's own "risk" or "confirmed" field is ignored.
5. **CONFIRM** creates a single-use, expiring approval. It is bound to the task, arguments, root, grant version, capability version and tool-manifest hash, and all of them are re-checked when the owner approves.
6. **Execute, then verify** independently. Only `PASS` counts as done.
7. **Logging:** each step goes to the event trace (SQLite) and the hash-chained action log (`data/actions.log.jsonl`, rotated at 5 MB with a continuous chain).

### Risk levels and tools (160 registered)

| Level | Count | Meaning |
|---|---|---|
| R0 observation | 62 | reads only |
| R1 reversible | 44 | easily undone (open apps or pages, window and media control) |
| R2 data modification | 23 | changes data, with runtime undo where available |
| R3 external side effect | 25 | apps.close, apps.quit, browser.workflow, code.build_project, code.run_python, files.organize, input.click, input.type_text, keyboard.keys, keyboard.press_enter, message.send, mouse.click, mouse.drag, process.launch, screen.click_risky, settings.theme_restore, settings.theme_set, system.volume_restore, system.volume_set, uia.expand, uia.invoke, uia.scroll, uia.select, uia.set_value, windows.close |
| R4 destructive / privileged | 6 | filesystem.delete_permanent, network.adapter_restore, network.adapter_set, power.cancel, power.schedule, process.terminate |

### Autonomy modes (per request)

| Mode | Runs by itself | Always asks |
|---|---|---|
| Review | nothing | every step |
| Auto-safe | R0–R1 | R2+ |
| Auto-edits | R0–R2 with runtime undo | R3+, R2 without undo, R2 after untrusted content |
| **Owner** (default, owner's standing order 2026-10-04) | everything else | changing files (create-only tools excepted), every deletion, R4, messages to people not in memory |

**In every mode, these always ask:**
- Running code or a program with arguments (`Tool.runs_code`: `code.run_python`, `process.launch`).
- Typing into a command window, opening the Run box, or launching a command-line app.
- Changing a saved contact's phone or WhatsApp name.
- Agent browser steps on local or private addresses.
- Keys or clicks that would save, delete, move files, or click an "approve"-like button.
- A kind of step that keeps failing (earned autonomy: at least 2 recent failures and a low success bound).
- Any deletion (always to the Recycle Bin). Permanent delete is `user_only`, so the agent can never choose it.

## 2. Hard boundaries (no approval overrides them)

- **Protected zones are observe-only:**
  - the folders: Windows, Program Files (all), ProgramData, Common Files;
  - AppData (from the shell's known folder, not only `%USERPROFILE%`; if AppData is unknown, every change is refused);
  - drive-root system folders and files, and user registry hives;
  - Chutku's own folder (except `sandbox\`).
- **Paths fail closed:** UNC, `\\?\`, device names, alternate data streams, `..`, trailing dots or spaces, reparse points and hard links are refused.
- **Never elevated.** `network.adapter_set` needs administrator rights, so it is `user_only` and usually fails by design.
- **No silent overwrite:** file moves and organize never replace an existing file; undo refuses when the owner changed a file since.

## 3. Content Chutku reads (prompt-injection defence)

- **Tainting and exposing tools.** Output of the tools in `agent_loop.TAINTING_TOOLS` (web pages, chats, clipboard, screen and OCR text, file text, image descriptions, script output) *taints* the session. Tools in `PRIVATE_TOOLS` (files, clipboard, screen, memory, file listings) *expose* it.
- **After taint:**
  - R2+ steps ask;
  - R1 steps that start or remember things (`apps.launch`, `files.open`, `mind.*`, `memory.remember`, `settings.offline_mode`) ask;
  - an argument the owner said themselves (whole words, at least 4 characters) is exempt.
- **After exposure:** any network request asks, so a URL built from private data can't leak it.
- **Screen clicks:**
  - a consequential click must name the element's label, which is re-checked against the current screen;
  - Chutku never clicks its own dashboard, HUD or tray.
- **Web reading:** public addresses only. The connection goes to the very address that was checked (no DNS rebinding), every redirect is re-checked, the size is bounded, and there is a total time limit.
- **Gemini:** model output from Gemini and from the local model is only a *proposal*. It passes the same validation, policy and verification as any other step.

A test (`tests/test_taint_v2.py`) fails if any name in these lists is not a real tool. A stale name once silently disabled the clipboard rule.

## 4. Data and secrets

- **Dashboard:**
  - bound to `127.0.0.1` only;
  - needs a per-launch random token (from the URL fragment), with exact Host/Origin checks and cross-site fetches refused;
  - JSON bodies are bounded and a strict CSP is set.
  - The session link is stored in `data/dashboard-session.json` (same-user readable).
- **Gemini key:** in Windows Credential Manager ("Chutku/Gemini", DPAPI). Off until the key is stored *and* `cloud.gemini` is granted.
- **What Gemini sees:**
  - the goal and the tool catalog;
  - step summaries and allowlisted public results;
  - the memory slice related to the goal;
  - screenshots only for screen tasks, when local vision fails.
- **Audit redaction:** message text, typed text, file contents, clipboard, phone numbers (`mind.show`/`mind.who`), the public IP (`net.check`), window titles and OCR text are redacted from the event trace.
- **Plaintext data (not a secrets vault):** `mind.json`, saved notes and the operation journal (it keeps file contents so undo can work).

## 5. Stop and recovery

- **Guard.** `Start-Chutku.cmd` runs a separate guard. It puts Chutku in a kill-on-close Windows job, watches heartbeat and action deadlines, and owns Ctrl+Alt+F12.
- **On stop:**
  - Chutku's own helpers (model servers, OCR) die with the job;
  - the owner's apps that Chutku opened (browser, VS Code, built apps) are started outside the job, so they survive.
- **Pause after a stop.** Any stop leaves a persistent pause until the owner resumes. No action is replayed automatically.

## 6. Honest limits

- Same-user programs can read the screen and clipboard, or change local files and databases. Path checks are not hostile-process isolation (a time-of-check/time-of-use race exists).
- In Owner mode, code builds (`code.build_project`) run model-written code without asking (the owner's choice). They write only to a new project folder, but the code itself runs with the owner's rights. A reduced-rights sandbox for builds and scripts is a parked item in `docs/MASTER_PLAN.md`.
- Voice transcripts are untrusted, and voice cannot approve R3+ steps unless the owner answers a direct yes/no question.
- **Owner Voice Lock (S19)** is off until the owner enrolls and types "voice lock on". Then a voice that does not match the voiceprint (`data/voiceprint.npy`, local only) makes every R1+ step wait for an on-screen click, and that request cannot be approved by voice.
  - It is a convenience filter, not authentication: a recording of the owner can pass.
  - Until it is switched on, anyone near the microphone can give tasks in hands-free mode.
- The injection tests exercise deterministic boundaries; they are not a statistical security guarantee.

Report vulnerabilities privately to the project owner. Never put secrets or sensitive screenshots in logs or issues.
