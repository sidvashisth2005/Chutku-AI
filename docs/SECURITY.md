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

### Risk levels and tools (254 registered, plus 194 app actions)

| Level | Count | Meaning |
|---|---|---|
| R0 observation | 95 | reads only |
| R1 reversible | 83 | easily undone (open apps or pages, window and media control) |
| R2 data modification | 32 | changes data, with runtime undo where available |
| R3 external side effect | 37 | apps.close, apps.install, apps.quit, apps.uninstall, browser.act_risky, browser.workflow, code.build_project, code.run_python, desktop.act_risky, email.send, evolve.approve, files.organize, input.click, input.type_text, keyboard.keys, keyboard.press_enter, message.send, mouse.click, mouse.drag, process.launch, remote.arm, remote.enable, screen.click_risky, services.set, settings.theme_restore, settings.theme_set, skill.approve, system.bluetooth_set, system.volume_restore, system.volume_set, uia.expand, uia.invoke, uia.scroll, uia.select, uia.set_value, windows.close, windows.close_this |
| R4 destructive / privileged | 7 | filesystem.delete_permanent, network.adapter_restore, network.adapter_set, power.cancel, power.schedule, process.terminate, system.powershell |

**Self-written skills** (X15/X16, `chutku/skills.py`): `skill.create` has the coder write `skill.json`, `SKILL.md`, `tool.py` and `test_tool.py` into `data/skills/_pending/<name>`, runs the tests and repairs at most 3 times (a failing assertion cannot be edited away). Pending skills are never tools. `skill.approve` is `user_only` (typed, then a click): only if the tests pass again does it activate the skill and record the SHA-256 of its files; a skill whose files changed since is not registered or run. `skill.<name>` runs `python -I` in a child process (60 s, 8 KB JSON result, untrusted output) and always asks first. It runs with the owner's Windows rights: the click is the boundary, not a sandbox, and the manifest's `network` / `writes_files` flags are declarations, not enforced.

**Imported skills and backups** (W1, 2026-11-07):
- `skill.import` writes a pending skill from a GitHub README but runs **nothing**: not the skill, not its tests. The
  README reaches the coder only as `untrusted_data`, with instruction-like lines removed. The pending folder carries
  `_untrusted.json` (its source). `skill approve` is the first time its code runs, and its description says so.
- `backup restore` never brings back security state: `telegram.json`, `remote.json`, `never_rules.json`, the
  capability and resource grant databases, `skills/approved.json` and active skill folders. They are listed as
  `skipped_security`. `--include-security` restores them only after a typed `YES`.

**For-each, research, Telegram** (H14/H15/H16, 2026-11-07; see `docs/HANDOFF.md`):
- `steps.for_each` never runs itself: it expands into ordinary steps that each pass `Runtime.run`. Only tools up to R2
  that are not messages, emails, deletes, code runners or owner-only; at most 50 items; a list taken from outside
  content taints every item. One card lists all items and covers only them, and only until read content tries to
  give instructions (S15): then every item asks again.
- Research workers run on `research.AllowlistRuntime`: the menu and the runtime allow only `web.results`, `web.read`,
  `web.news`, `web.weather`. Any other proposal is DENIED inside the child, so private data has no path to the web.
  No grandchildren, 10 steps, 5 minutes, 90 s stall check.
- Telegram is outbound-only (long poll, no listening port). One paired chat; others get no reply. Pairing: 8-character
  code, 1 hour, at most 3 pending, 5 wrong codes lock pairing for 1 hour. Buttons carry single-use nonces bound to
  the session and step (10 minutes). `remote.server.laptop_only` (shared with the phone app) keeps R4, code, unknown
  recipients and never/remote/telegram tools on the laptop. The token lives in Credential Manager and is not in any
  log or state file (errors carry no URL).
- `task.delegate`, `board.*` and `telegram.*` are taint-sensitive R1: after outside content they ask first.

**Evolve** (Y2, `chutku/evolve.py`, `chutku/evolve_apply.py`): the nightly review only reads local logs and writes at most 3 proposals a day to `data/evolve/proposals/`; a cloud model sees only a short redacted summary of a code idea. Nothing is applied until the owner types `evolve approve <id>` (`user_only`, `runs_code`: then a click; never the agent, never voice); the approval is bound to the SHA-256 of the plan. Phrase, routine and preference ideas write through the existing data paths (reflex checks, routine checks, an allowlist of four non-safety preferences). Code ideas run in a separate process: a git worktree and branch `evolve/<id>`, the full unit suite and `scripts/check_phrases.py` before and after the change, and `git merge --ff-only` into main only if nothing that passed before fails now. Before writing and again on the committed diff, `evolve_apply.check` refuses any change that touches `chutku/policy/`, `chutku/core/`, `chutku/router/`, `chutku/remote/`, `chutku/relay/`, `android/`, `chutku/runtime.py`, `guard.py`, `tools/registry.py`, `skills.py`, `skill_runner.py`, `app.py`, `agent_loop.py`, `agent_execution.py`, `cloud_planner.py`, `dashboard*.py`, `coder.py`, `tools/builder.py`, `chutku/evolve*.py`, AGENTS.md, this file, `.github/`, `.claude/`, `requirements.lock`, `pyproject.toml`, the safety tests (`test_docs_truth`, `test_trusted_task`, `test_autonomy_policy`, `test_protected_zones`, `test_taint*`, `test_elevation`, `test_injection*`, `test_failclosed*`, `test_evolve*` and 15 more listed in the code); any changed line with a safety word (risk, approval, provenance, grants, process, network or code-running calls); any edit or removal of an existing test line or `check_phrases.py` line; test skips; more than 400 lines or 8 files. A failed or refused change deletes the worktree and branch; main is untouched. Pushing to GitHub is off unless the owner types `evolve push on`. The tests a change adds run with the owner's rights: the approval click is the boundary, as for skills.

**Background app control and the signed-in browser** (D1/Z6, 2026-11-07; `chutku/tools/desktop.py`,
`chutku/tools/signed_in_browser.py`): two pinned CLIs from vercel-labs (Apache-2.0), installed by `npm ci --prefix
tools` from `tools/package-lock.json` (npm integrity hashes), run as separate processes.
- `desktop.look` / `desktop.act` (agent-desktop) read an app window's UI Automation tree and act on one element
  through UI Automation patterns only (strict headless: never `--headed`, no mouse, no keystrokes, no focus
  stealing by Chutku). A ref is accepted only if a look in the last 3 minutes returned it. Typed text goes to the CLI
  on stdin, never on its command line. Window text is untrusted (TAINTING) and private (PRIVATE).
- `browser.open` / `browser.look` / `browser.act` / `browser.type` (agent-browser) drive a dedicated Brave/Edge profile
  (`data/browser-profile`), headless. The owner signs in once with `chutku.cli browser login`, which opens that
  profile as a plain browser with no automation attached; the everyday profile is never touched. Signed-in pages
  (mail, orders) are untrusted and private (TAINTING and PRIVATE). `browser.open url=` and `browser.type` (fill,
  Enter) are network egress, so after any private read they ask: an injected line in a mail cannot make Chutku
  open `https://evil.example/?d=<OTP>` on its own (release review 2026-11-07, test
  `SignedInPagesArePrivateTest`). Re-reading the open page (`browser.look`) and clicking what the page offers
  (`browser.act`) are not egress. Local and private
  addresses ask first; `file://` access is off. Commands go through `batch` with JSON on stdin. The daemon stops
  after 10 idle minutes. `browser.act`/`browser.type` need the `browser.input` capability (not granted by default).
- App Mastery A14-A16 (W6, 2026-11-07):
  - `desktop.do` (R1, `desktop.input`) acts on an element found by its name, through the same `desktop.act` code, so
    send/delete/pay-like names are refused (only `desktop.act_risky` presses them, always confirmed). Routines may hold
    such steps; they replay through `desktop.do` and the kernel like any step.
  - `teach.start` (R0, `screen.observe`) reads one named window's UI Automation tree for at most 5 minutes;
    `teach.stop` saves the changes as a routine. Password, PIN, OTP, CVV, protected and masked fields are never
    recorded.
  - `desktop.survey` (R0, `screen.observe`) lists window skeletons only and stores nothing.

**App actions** (`app.<app>.<action>`, App Mastery, `chutku/apps/atlas/*.json`) take their risk from the atlas class: safe → R1, changes → R2, consequential → R3, destructive → R4 with `deletes` (always asks). The atlas validator refuses URI schemes and programs that are not the app's own and unknown step verbs; keys and typing are sent only while the app's own window is in front; every action ends with its own check, and the kernel, never-rules, taint rules, ledger and action log apply as to any tool. Instant routing by phrase (`chutku/apps/phrases.py`) only picks actions the Action Lab has verified on this PC, or (Z3, 2026-11-06) a safe parameter-free action that only focuses its app and presses a documented shortcut, unless its latest lab run failed; anything that changes something still needs the lab; anything else goes to the planner, which is offered an app's actions only when the request names that app. `apps.howto` (R0) reads only the checked-in feature maps (`docs/apps/*.md`), not web text.

### Autonomy modes (per request)

| Mode | Runs by itself | Always asks |
|---|---|---|
| Review | nothing | every step |
| Auto-safe | R0–R1 | R2+ |
| Auto-edits | R0–R2 with runtime undo | R3+, R2 without undo, R2 after untrusted content |
| **Owner** (default, owner's standing order 2026-10-04) | everything else | changing files (create-only tools excepted), every deletion, R4, messages to people not in memory |

**In every mode, these ask** (the first time: the owner's "Yes, always" plus a verified run lets the exact same step skip the question afterwards, within the ask-once limits above; deletes and R4 other than the owner's own PowerShell or script always ask):
- Running code or a program with arguments (`Tool.runs_code`: `code.run_python`, `process.launch`, `system.powershell`, `skill.create`, `skill.approve`, `evolve.approve`, `skill.import` and every `skill.<name>`). `system.powershell` is also R4, so its approval is never reused by a later request (a scheduled task or a re-sent task asks again).
- Typing into a command window, opening the Run box, or launching a command-line app.
- Changing a saved contact's phone or WhatsApp name.
- Pressing a send / delete / pay / submit-like element in an app or on a web page (`desktop.act_risky`,
  `browser.act_risky`). The card names the element as the latest look saw it; a label that is not that element is
  refused before any card, and the name is checked again when the step runs.
- Sending an email (`email.send`, which also needs the `email.send` capability, not granted by default). `email.draft` only opens a draft in the mail app; the owner presses Send there.
- Agent browser steps on local or private addresses.
- Keys or clicks that would save, delete, move files, or click an "approve"-like button.
- A kind of step that keeps failing (earned autonomy: at least 2 recent failures and a low success bound).
- Any deletion (always to the Recycle Bin). Permanent delete is `user_only`, so the agent can never choose it.

## 2. Hard boundaries (no approval overrides them)

- **The system-damage list is always refused** (WA1, owner 2026-11-08, `paths.system_damage`, `paths.damage_in_text`):
  - Windows' own folder, start-up and recovery folders, drive-root system files and the drive root itself, user
    registry hives;
  - deleting or moving anything under Program Files or ProgramData (uninstall instead);
  - Chutku's own code and data folder (except `sandbox\`), so it can never change its own grants or rules;
  - in `system.powershell` text and `code.run_python` scripts: format/diskpart/bcdedit, deleting or taking over
    system paths, `HKLM` deletes, turning Defender or the firewall off;
  - if AppData is unknown, every change is refused.
- **An installed app's own files ask the first time** (Program Files, ProgramData, AppData writes; `sensitive_reason`),
  in every mode, including a typed command.
- **System tools (WA2):** `apps.install`/`apps.uninstall` use winget per-user first (a machine installer raises
  Windows' own prompt); `settings.set` (named settings, read back), `registry.set_user` (HKCU\\Software only;
  Policies and Defender keys refused) and `startup.toggle` (StartupApproved, never deletes the entry) journal the
  previous value in `data/system_journal.jsonl` for `system.undo_last`. `services.set` runs `sc.exe` through
  `chutku/elevate.py` (one structured command line, damage check first, Windows' UAC prompt, output via a temp file);
  security services (Defender, firewall, event log, RPC, WMI, Windows Update and others) are refused. Free text is
  never elevated.
- **Ask-once memory** (`chutku/approval_memory.py`, `data/approval_memory.json`):
  - only the owner's "Yes, always" on the laptop, and only after that exact step verified;
  - the key is the tool plus normalised arguments, so another target asks again;
  - never after outside content, never for deletes or R4 (except the owner's exact PowerShell or script), and never
    for laptop-only steps asked from the phone or Telegram;
  - an entry expires after 90 days unused; Settings forgets each one.
- **Never types a password** (2026-11-10): `keyboard.type_text` and app-action typing refuse when UI Automation says
  the focused element is a password box (`desktop_controls.focused_is_password`), even after an approval click; the
  owner types it, then says continue. Typing the owner does himself (the phone's remote keyboard) is not blocked. If
  UI Automation cannot tell, typing goes ahead (a box that hides its type is not detected).
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
- PIN again for every approval (single-use nonce bound to the step), screen view (30 min, 15 s heartbeat), control, laptop clipboard, laptop files. 5 wrong PINs revoke the phone and show the owner a Windows notification.
- Pairing, failed pairing codes, sign-ins, each wrong PIN and removals go to the hash-chained action log as `remote.*` entries (never a PIN or credential; 2026-11-13).
- Never from the phone: R4, power/network/process.terminate, permanent delete, code running, unknown recipients, never-rules, remote.* settings.
- Direct control: armed only at the laptop, red border, local input wins 10 s, Ctrl+Alt+Shift+P kills, Enter/paste in command windows needs the PIN, no Ctrl+Alt+Del, nothing while locked, typed text logged only as length/script.
- Files: phone uploads create-only in ChutkuInbox (`D:\ChutkuInbox` if that folder exists, else `%USERPROFILE%\ChutkuInbox`) (programs saved as .blocked); laptop files refused in protected zones and secret paths.

## 4b-2. Phone app through the account relay (2026-11-06)
- **Account:** one ID and password, made at setup. It lives in the relay's SQLite database as a scrypt hash. An ID that exists is refused. 5 wrong passwords lock it for 15 minutes; registrations are capped per IP per hour, and so are failed sign-ins (20 per address per hour, across all IDs). An unknown ID costs the same scrypt as a known one, so timing does not show which IDs exist.
- **Password strength (2026-11-13):** the relay sees only the derived auth value (below), so the laptop checks the real password before register or change: at least 8 characters, not a common password, not too simple, not containing the ID (`relay/client.password_problem`). It also protects the E2E key, which ciphertext at the relay could be guessed against offline.
- **Relay audit and limits:** an `events` table keeps register, sign-ins, failed sign-ins, lock-outs, logouts and account changes with the time and address for 90 days (never a password or token). At most 512 connections are open at once; the rest are closed at once. TLS 1.2 is the minimum, HSTS is sent, and an unexpected error is a generic 500. The Android app refuses a plain-http relay address off the home network, like the laptop.
- **Device tokens** last until logout. Only their SHA-256 is stored. A password change (laptop only) signs out every other device. The laptop's token is in Windows Credential Manager (`Chutku/RelayToken`). The password is never stored, and the `.env` holds only the relay address and the ID.
- **Isolation at the relay:**
  - a phone's `/t/api/...` request is queued only for its own account's laptop;
  - phone tokens cannot poll and laptop tokens cannot send;
  - bodies are capped (8 MB in, 16 MB out) and the queue is bounded.
- **On the laptop** (`chutku/relay/client.py`):
  - only GET/POST to `/api/*` is replayed, on the phone server over loopback, with that server's per-run secret (`X-Chutku-Relay`, compared in constant time; loopback only);
  - such a request is the `relay` device: rate limit, its PIN (set at setup; 5 wrong revoke it) for approvals, screen and control, laptop-only steps, and control armed only at the laptop all apply as for a paired phone;
  - CSRF is not used, because a bearer token is not sent by a browser on its own.
- **Transport:** the laptop refuses a plain-http relay unless it is loopback or a private address. The relay listens on 127.0.0.1 by default and refuses plain HTTP on any other address unless `--tls-cert`, `--behind-proxy` or `--home-network` is given; with `--behind-proxy`, sign-up limits count real clients through X-Forwarded-For, believed only from a proxy on the same machine. It cannot read the forwarded content (below).
- **End-to-end encryption (W6, 2026-11-07, `chutku/relay/e2e.py`, `chutku/web/phone/e2e.js`):**
  - the phone and the laptop each derive the same AES-256-GCM key from the account password
    (PBKDF2-HMAC-SHA256, 600 000 iterations, salt `chutku-e2e-key:<id>`);
  - the relay is given a different value as the password (`chutku-e2e-auth:<id>`), so it never sees the password
    and cannot derive the key. An account made before W6 is upgraded at its next login: one login with the
    password, which is then replaced by the auth value;
  - every phone request (method, path, body) and every answer travels as `{v, iv, ct}` on `/t/e2e`. The associated
    data binds the account and the direction, a request older than 2 minutes or seen before is dropped, and the
    answer repeats the request's nonce. The plaintext route answers 426, and the relay stores and forwards only
    ciphertext;
  - the relay still learns the account, the time and the size of each message;
  - PBKDF2 rather than scrypt: WebCrypto has no scrypt, and a hand-written one would be unvetted;
  - the laptop keeps the key in Credential Manager (`Chutku/RelayKey`). The phone keeps it in its browser storage
    next to its token. Logging out removes it.
- **Replies:** a reply is kept only for a request of the same account that is still waiting. A late reply, or one from another account, is dropped.

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

## 7. Reporting and incident response

Report vulnerabilities privately to the project owner (not in a public issue). Never put secrets or sensitive screenshots in logs or issues. The item-by-item security checklist is `docs/SECURITY_CHECKLIST.md`; `scripts/security_scan.py` and the CI `security` job run SAST, dependency CVEs and the secret scan.

If something looks wrong:
1. **Stop:** Ctrl+Alt+F12 or the tray's emergency stop (everything pauses until the owner resumes); "remote band karo" or Ctrl+Alt+Shift+P ends phone control.
2. **Cut access:** remove phones on the laptop's Phone page; change the account password on the laptop (every other device is signed out); revoke a cloud key at the provider, then store a new one with `chutku.cli cloud set-key`.
3. **Look:** `chutku.cli doctor` checks the action log's hash chain; the action log (`remote.*` entries), the relay's `events` table and `data/logs/chutku.log` show what happened and from where.
4. **Recover:** undo with `log.undo` or Causal Rewind; restore memory from a verified backup; rotate anything that may have leaked.
5. **Fix and record:** a failing test first, then the fix, then an entry in `IMPLEMENTATION_STATUS.md`.
