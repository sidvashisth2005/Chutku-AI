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

### Risk levels and tools (199 registered, plus 136 app actions)

| Level | Count | Meaning |
|---|---|---|
| R0 observation | 78 | reads only |
| R1 reversible | 57 | easily undone (open apps or pages, window and media control) |
| R2 data modification | 27 | changes data, with runtime undo where available |
| R3 external side effect | 30 | apps.close, apps.quit, browser.workflow, code.build_project, code.run_python, email.send, evolve.approve, files.organize, input.click, input.type_text, keyboard.keys, keyboard.press_enter, message.send, mouse.click, mouse.drag, process.launch, remote.arm, remote.enable, screen.click_risky, settings.theme_restore, settings.theme_set, skill.approve, system.volume_restore, system.volume_set, uia.expand, uia.invoke, uia.scroll, uia.select, uia.set_value, windows.close |
| R4 destructive / privileged | 7 | filesystem.delete_permanent, network.adapter_restore, network.adapter_set, power.cancel, power.schedule, process.terminate, system.powershell |

**Self-written skills** (X15/X16, `chutku/skills.py`): `skill.create` has the coder write `skill.json`, `SKILL.md`, `tool.py` and `test_tool.py` into `data/skills/_pending/<name>`, runs the tests and repairs at most 3 times (a failing assertion cannot be edited away). Pending skills are never tools. `skill.approve` is `user_only` (typed, then a click): only if the tests pass again does it activate the skill and record the SHA-256 of its files; a skill whose files changed since is not registered or run. `skill.<name>` runs `python -I` in a child process (60 s, 8 KB JSON result, untrusted output) and always asks first. It runs with the owner's Windows rights: the click is the boundary, not a sandbox, and the manifest's `network` / `writes_files` flags are declarations, not enforced.

**Evolve** (Y2, `chutku/evolve.py`, `chutku/evolve_apply.py`): the nightly review only reads local logs and writes at most 3 proposals a day to `data/evolve/proposals/`; a cloud model sees only a short redacted summary of a code idea. Nothing is applied until the owner types `evolve approve <id>` (`user_only`, `runs_code`: then a click; never the agent, never voice); the approval is bound to the SHA-256 of the plan. Phrase, routine and preference ideas write through the existing data paths (reflex checks, routine checks, an allowlist of four non-safety preferences). Code ideas run in a separate process: a git worktree and branch `evolve/<id>`, the full unit suite and `scripts/check_phrases.py` before and after the change, and `git merge --ff-only` into main only if nothing that passed before fails now. Before writing and again on the committed diff, `evolve_apply.check` refuses any change that touches `chutku/policy/`, `chutku/core/`, `chutku/router/`, `chutku/remote/`, `chutku/runtime.py`, `guard.py`, `tools/registry.py`, `skills.py`, `skill_runner.py`, `app.py`, `agent_loop.py`, `agent_execution.py`, `cloud_planner.py`, `dashboard.py`, `coder.py`, `tools/builder.py`, `chutku/evolve*.py`, AGENTS.md, this file, `.github/`, `.claude/`, `requirements.lock`, `pyproject.toml`, the safety tests (`test_docs_truth`, `test_trusted_task`, `test_autonomy_policy`, `test_protected_zones`, `test_taint*`, `test_elevation`, `test_injection*`, `test_failclosed*`, `test_evolve*` and 15 more listed in the code); any changed line with a safety word (risk, approval, provenance, grants, process, network or code-running calls); any edit or removal of an existing test line or `check_phrases.py` line; test skips; more than 400 lines or 8 files. A failed or refused change deletes the worktree and branch; main is untouched. Pushing to GitHub is off unless the owner types `evolve push on`. The tests a change adds run with the owner's rights: the approval click is the boundary, as for skills.

**App actions** (`app.<app>.<action>`, App Mastery, `chutku/apps/atlas/*.json`) take their risk from the atlas class: safe → R1, changes → R2, consequential → R3, destructive → R4 with `deletes` (always asks). The atlas validator refuses URI schemes and programs that are not the app's own and unknown step verbs; keys and typing are sent only while the app's own window is in front; every action ends with its own check, and the kernel, never-rules, taint rules, ledger and action log apply as to any tool. Instant routing by phrase (`chutku/apps/phrases.py`) only picks actions the Action Lab has verified on this PC; anything else goes to the planner, which is offered an app's actions only when the request names that app. `apps.howto` (R0) reads only the checked-in feature maps (`docs/apps/*.md`), not web text.

### Autonomy modes (per request)

| Mode | Runs by itself | Always asks |
|---|---|---|
| Review | nothing | every step |
| Auto-safe | R0–R1 | R2+ |
| Auto-edits | R0–R2 with runtime undo | R3+, R2 without undo, R2 after untrusted content |
| **Owner** (default, owner's standing order 2026-10-04) | everything else | changing files (create-only tools excepted), every deletion, R4, messages to people not in memory |

**In every mode, these always ask:**
- Running code or a program with arguments (`Tool.runs_code`: `code.run_python`, `process.launch`, `system.powershell`, `skill.create`, `skill.approve`, `evolve.approve` and every `skill.<name>`). `system.powershell` is also R4, so its approval is never reused by a later request (a scheduled task or a re-sent task asks again).
- Typing into a command window, opening the Run box, or launching a command-line app.
- Changing a saved contact's phone or WhatsApp name.
- Sending an email (`email.send`, which also needs the `email.send` capability, not granted by default). `email.draft` only opens a draft in the mail app; the owner presses Send there.
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
  - R1 steps that start or remember things (`apps.launch`, `files.open`, `mind.*`, `memory.remember`, `settings.offline_mode`, `settings.chutku`, `task.schedule`) ask;
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
- **Cloud keys:** in Windows Credential Manager ("Chutku/Gemini", "Chutku/Groq", "Chutku/Cerebras", and "Chutku/Email" for the Gmail app password; DPAPI) or environment variables, never in files or logs. Gemini is off until its key is stored *and* `cloud.gemini` is granted. Groq/Cerebras are used only after the owner stores a key (`chutku.cli cloud set-key groq`).
- **Cloud-first brain (W2, owner decision 2026-10-29):** with `brain: cloud_first` (default) and the internet up, Groq → Cerebras → Gemini plan first and the local model is the fallback. They all receive the same `cloud_view` as Gemini below, and their proposals pass the same validation and policy. `cloud brain off` makes planning local-only; offline mode also turns it off.
- **What the cloud models see:**
  - the goal and the tool catalog;
  - step summaries and allowlisted public results;
  - the memory slice related to the goal;
  - screenshots for screen tasks: `screen.ask` (the W5 screen copilot) sends the foreground window, cropped and scaled to 1280 px, to Gemini first (20 s budget), with local vision as the fallback; `screen.understand` still tries local vision first. Apps on the owner's private list (`timeline_private`) are never captured for either.
- **Audit redaction:** message text, typed text, file contents, clipboard, phone numbers (`mind.show`/`mind.who`), the public IP (`net.check`), window titles and OCR text are redacted from the event trace.
- **Plaintext data (not a secrets vault):** `mind.json`, saved notes and the operation journal (it keeps file contents so undo can work).

## 4b. Phone access (W6, 2026-10-30)
- Off until the owner says "phone connect karo". Phone server on 127.0.0.1:8766 only, published inside the owner's tailnet by `tailscale serve` (HTTPS); Funnel detected every 5 min stops everything.
- Every request: exact ts.net Host, the owner's Tailscale-User-Login, a paired device credential (hash stored) + PIN session (scrypt), CSRF + Origin on changes, 30 req/min.
- PIN again for every approval (single-use nonce bound to the step), screen view (30 min, 15 s heartbeat), control, laptop clipboard, laptop files. 5 wrong PINs revoke the phone.
- Never from the phone: R4, power/network/process.terminate, permanent delete, code running, unknown recipients, never-rules, remote.* settings.
- Direct control: armed only at the laptop, red border, local input wins 10 s, Ctrl+Alt+Shift+P kills, Enter/paste in command windows needs the PIN, no Ctrl+Alt+Del, nothing while locked, typed text logged only as length/script.
- Files: phone uploads create-only in ChutkuInbox (`D:\ChutkuInbox` if that folder exists, else `%USERPROFILE%\ChutkuInbox`) (programs saved as .blocked); laptop files refused in protected zones and secret paths.

## 4c. What Chutku learns about the owner (2026-11-01)
- `chutku/know_me.py` builds `data/know_me.json` locally every 6 hours: the owner's video library (Videos, Downloads, Telegram Desktop and the folders in the `media_folders` preference), VLC's recent-media history, app launch counts (Windows UserAssist) and the most-visited domains from a temporary copy of Brave's History database (30 days).
- It never leaves the PC: `me.profile` is a private tool, so a network step after it asks, and nothing from it is in what the cloud brain sees.

## 5. Stop and recovery

- **Guard.** `Start-Chutku.cmd` runs a separate guard. It puts Chutku in a kill-on-close Windows job, watches heartbeat and action deadlines, and owns Ctrl+Alt+F12.
- **On stop:**
  - Chutku's own helpers (model servers, OCR) die with the job;
  - the owner's apps that Chutku opened (browser, VS Code, built apps) are started outside the job, so they survive.
- **Pause after a stop (changed 2026-10-29, F1).** Every stop leaves a pause that records who made it (`data/actions.paused`: owner, guard or startup).
  - The **owner's** pause and the **emergency stop** stay until the owner resumes (button, tray, typed "resume", or Ctrl+Alt+Space then a spoken "resume"; a wake phrase can never lift it).
  - After a **watchdog** stop (hang, crash, slow start) the guard starts a fresh core (at most 3 times in 30 minutes), and that core lifts the guard's own pause after 30 s of healthy running and says so.
  - No action is replayed automatically: the interrupted task is reported, never re-run.
  - A stuck core loop writes every thread's stack to `data/logs/hang-*.txt`.

## 6. Honest limits

- Same-user programs can read the screen and clipboard, or change local files and databases. Path checks are not hostile-process isolation (a time-of-check/time-of-use race exists).
- In Owner mode, code builds (`code.build_project`) run model-written code without asking (the owner's choice). They write only to a new project folder, but the code itself runs with the owner's rights. A reduced-rights sandbox for builds and scripts is a parked item in `docs/MASTER_PLAN.md`.
- Voice transcripts are untrusted, and voice cannot approve R3+ steps unless the owner answers a direct yes/no question.
- **Owner Voice Lock (S19)** is off until the owner enrolls and types "voice lock on". Then a voice that does not match the voiceprint (`data/voiceprint.npy`, local only) makes every R1+ step wait for an on-screen click, and that request cannot be approved by voice.
  - It is a convenience filter, not authentication: a recording of the owner can pass.
  - Until it is switched on, anyone near the microphone can give tasks in hands-free mode.
- The injection tests exercise deterministic boundaries; they are not a statistical security guarantee.

Report vulnerabilities privately to the project owner. Never put secrets or sensitive screenshots in logs or issues.
