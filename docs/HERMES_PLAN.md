# Phase 3b: Hermes-inspired upgrades + remote phone access for Chutku (H1–H30, P1–P9)

> **Status:** plan, 2026-10-07. Nothing in this file has been built yet.
> **Inserted:** in `docs/MASTER_PLAN.md` after S22. S0–S22 are all done; S22 shipped as commit `380d02f`. Phase 3b therefore ends with its own release slice, **H30**, which redoes S22's evidence, docs and reviews for the H changes.
> **Copy of record:** `docs/HERMES_PLAN.md` (this file, word for word).

---

## 0. Context

### 0.1 Why
The owner asked (2026-10-06) whether Hermes Agent can be integrated into Chutku. Hermes is Nous Research's open-source self-improving agent, MIT license, Python.

Owner decisions:
1. **Rebuild Hermes ideas inside Chutku**, in her style and under her safety rules.
2. **Copy Hermes code only where it is clearly better** and helps a lot. Otherwise write our own.
3. **Build every Hermes feature Chutku lacks.** Exceptions: features that break a standing owner rule. These are listed in §3 with the reason for each.
4. On 2026-10-07: research more, then rectify and enhance the plan "for best innovation and most features".

Hermes is **never installed or run**. The reasons:
- It is Linux/macOS-first.
- It expects a big model; our RTX 3050 has 4 GB.
- It would act outside Chutku's kernel, approvals, action log and rewind.

### 0.2 What Chutku already matches (not rebuilt)
| Hermes | Chutku today |
|---|---|
| Checkpoints & `/rollback` (shadow git, keeps the user's hand edits) | **S18 causal rewind**: dependency-ordered undo for files, settings, reminders and apps, conflict-safe. Stronger than Hermes. |
| Cron (natural language, once or repeating) | `chutku/scheduled.py` (once later, at a time, repeating) |
| Wake word, voice mode, TTS | `voice/handsfree.py`, Gemini Live, SAPI (Kokoro spike, S10) |
| Computer use, browser, vision | `uia*`, `screen*`, `browser.py`, `local_vision.py`, `screen.understand` |
| Self-written instant skills | **S17 reflex compiler** (verified, regex, risk ≤ 1) |
| Background improvement | **S20 night shift** (reflex compile, regression replay, maintenance, LoRA readiness) |
| Approvals | Policy kernel R0–R4, owner mode, taint, S15 suspicious flag, S19 voice lock |
| Stop | "stop" control intent (current task), guard, tray |
| Episodic recall | S21 timeline (window titles), `recall.py` word overlap |

### 0.3 Standing rules (from MASTER_PLAN §0.3; apply to every slice)
1. **AGENTS.md gate:** unit tests, one real command path, one negative case that fails closed, and an `IMPLEMENTATION_STATUS.md` entry with concrete evidence.
2. Every live check reports **seconds AND an independent correctness check** (`scripts/live_check.py` pattern).
3. Update `docs/OWNER_GUIDE.md` for every phrase, control or safety change; re-run `scripts/check_phrases.py` (all-instant).
4. **Owner-mode asks may be added, never removed.** Current asks: file changes (except create-only tools), deletions, R4, unknown message recipients, tainted R2+.
5. **Chutku is female:** prompts start from `persona.IDENTITY`; replies go through `persona.feminine()`; fixed strings use the female verb forms.
6. **Test isolation:** tests never start real models, never send messages, never type into the owner's documents, and never call Telegram or Gemini.
7. Regenerate the evidence only in H30, after the last H code edit, because `source_digest` makes any earlier regeneration stale.
8. Python is `.venv\Scripts\python.exe`. Tests: `-m unittest discover -s tests`.
9. Benchmarks: stop Chutku's llama-server first and run on AC power.
10. Commits are `H<n>: <summary>`, with **no co-author line**.
11. Every helper-agent prompt used goes into `docs/AGENT_PROMPTS.md`.

### 0.4 Code-borrowing rule
- Before each slice, fetch the named Hermes file from `raw.githubusercontent.com/NousResearch/hermes-agent/main/…`.
- Copy only when it is smaller or better tested than what we would write, then adapt it to Windows, PowerShell and Hinglish.
- Credit each copy in `THIRD_PARTY_LICENSES.md` (MIT notice + source path + commit hash), with a `# Adapted from hermes-agent <path> (MIT)` comment at the copy site.
- Never copy code that loads plugins, runs hooks or opens network listeners.

| Slice | Hermes source to study or copy | Expected use |
|---|---|---|
| H1 | `tools/approval_detection.py`, `tools/approval_floors.py` | Port the normalization steps and the Windows patterns; adapt the floor ordering |
| H3 | `tools/cronjob_prompt_scan.py`, memory threat patterns (in `tools/` memory tool) | Port the patterns |
| H2 | `agent/estop.py` | Copy the idea; ~30 lines of our own |
| H4 | `hermes_state*.py` FTS parts | Schema and query sanitizer |
| H9 | `agent/error_classifier.py`, `agent/credential_pool*.py` | Error classes, cooldowns |
| H12 | `agent/background_review.py` | The quality-gate rules text and limits |
| H13 | `agent/curator.py` | Lifecycle constants and the never-delete invariant |
| H16 | `gateway/` pairing code | Pairing constants and lockout |
| H6 | `agent/context_references.py` | The sensitive-path list and size limits |
| H15 | kanban dispatcher + `tools/delegate_tool*.py` | Statuses, heartbeat and stall timings, circuit breaker |
| H20 | voice-mode silence and hallucination filter (in `tools/` or `hermes_cli/` voice code) | Phantom phrase list, thresholds |
| H25 | `hermes backup` / `import` code | Manifest format, exclusions |

---

## 1. Order (breadth-first: small, safe, high value first)

| # | Slice | Group | Size |
|---|---|---|---|
| H1 | Approval floors: hard block + owner "never" rules | Safety | S |
| H2 | Pause switch (global emergency stop) | Safety | S |
| H3 | Content scanner + bounded-memory meter | Safety/Memory | S |
| **P1** | **Phone access: Tailscale HTTPS + QR pairing + phone PIN** | Remote | M |
| **P2** | **Phone app: chat, live progress, approvals (installable PWA)** | Remote | M |
| **P3** | **Phone voice: push-to-talk + spoken replies** | Remote | S |
| **P4** | **Live screen view (view-only) + keep-awake** | Remote | M |
| H4 | Fast chat-history search (FTS5) | Memory | M |
| H5 | Step summaries instead of dropping | Brain | S |
| H6 | `@file` / `@folder` / `@url` references in typed chat | Input | S |
| H7 | Weekly insights ("is hafte kya kiya") | Insight | S |
| H8 | Scheduled-task upgrades (continuity, silent tick, chaining, incidents) | Automation | M |
| H9 | Brain resilience: fallback chain, error classes, per-request brain choice | Brain | M |
| H10 | Proven lessons from mistakes | Learning | M |
| H11 | Procedure skills (SKILL.md) with progressive disclosure | Learning | L |
| H12 | Background review + learning inbox | Learning | M |
| H13 | Curator: lifecycle for skills, reflexes and lessons (in night shift) | Learning | S |
| H14 | For-each steps (many items, one plan round) | Brain | M |
| H15 | Task board + background research workers | Automation | L |
| H16 | Telegram remote control with pairing | Reach | L |
| H17 | Reply style presets (female persona kept) | Persona | S |
| H18 | Busy mode: queue / steer / side question | Voice/Chat | M |
| H19 | Free neural voice online (Edge TTS) + sentence streaming | Voice | M |
| H20 | Voice polish (phantom filter, exact stop, barge-in) | Voice | S |
| H21 | Think harder / answer fast | Brain | S |
| H22 | Second opinion ("pakka?") + ask-both | Brain | S |
| H23 | Blueprints + my shortcuts | Automation | M |
| H24 | Standing goals | Planning | M |
| H25 | Backup & restore | Safety | M |
| H26 | Doctor that can repair | Ops | S |
| H27 | Learn on request ("ye seekh lo") | Learning | S |
| H28 | Learning journey view | Insight | M |
| H29 | Conversation tools + context gauge | Chat | M |
| H30 | Phase 3b release: evidence, docs, reviews | Release | M |
| *P5–P9* | *Phone full control (tap, keyboard, clipboard, files, point-and-ask). Planned; built on the owner's word, with its own release check repeating H30's review items* | *Remote* | *L* |

---

## 2. Slices

### H1: Approval floors: hard block + owner "never" rules
**From Hermes:** `approval_floors.py`. Some decisions never reach a prompt: hardline blocks, a sudo-stdin guard and user deny rules, all checked before any bypass mode. Commands are normalized before matching.

**New `chutku/policy/hardline.py`**
- `normalize(text)`, ported from Hermes `_normalize_command_for_detection` and extended for Windows:
  1. strip ANSI escapes;
  2. Unicode NFKC;
  3. remove null bytes;
  4. remove empty `""` / `''` pairs;
  5. join line continuations: `\`+newline, PowerShell backtick+newline, cmd `^`+newline;
  6. remove the cmd caret escape (`f^o^r^m^a^t` → `format`) and PowerShell backtick escapes (`` f`ormat `` → `format`);
  7. expand `%SystemRoot%`, `%COMSPEC%`, `$env:SystemRoot`, `$env:USERPROFILE`;
  8. fold `C:\Users\<owner>` to `~`;
  9. lowercase everything except flags.
- **Decode, then rescan:** `-EncodedCommand` / `-enc` / `-e <base64>` is decoded (UTF-16LE) and the result scanned again. `python -c`, `powershell -Command`, `cmd /c` and `pwsh -c` arguments are scanned as commands (Hermes `_REINTERPRETED_ARGUMENT_RE`). If a payload cannot be decoded, the command is blocked (fail closed).
- `HARDLINE`: a list of `(regex, reason_hi)`. **Blocked in every mode, approval cannot override:**
  - `format <drive>:`, `Format-Volume`, `Clear-Disk`, `diskpart`, `Initialize-Disk`;
  - `vssadmin delete shadows`, `wmic shadowcopy delete`, `wbadmin delete`;
  - `bcdedit`, `reagentc /disable`;
  - `cipher /w`;
  - recursive delete of a drive root, `~`, `C:\Windows`, `C:\Program Files*` or `C:\Users` (`rd /s`, `rmdir /s`, `Remove-Item -Recurse`, `del /s`, `shutil.rmtree`, `os.removedirs`);
  - `reg delete HKLM`, `reg delete HKCU\Software\Microsoft\Windows`;
  - `Set-MpPreference -Disable*`, `Add-MpPreference -ExclusionPath`, `netsh advfirewall set * state off`;
  - pipe-to-shell: `iwr|irm|curl|wget … | iex|Invoke-Expression|sh|bash|python`, `iex (New-Object Net.WebClient).DownloadString`;
  - `takeown`/`icacls … /grant` on `C:\Windows`, `C:\Program Files*`;
  - `schtasks /create` with `/ru SYSTEM`;
  - `net user … /add`, `net localgroup administrators … /add`;
  - fork bombs (`:(){`, `%0|%0`, a `while(1){Start-Process` loop).
- `DANGEROUS` (the Hermes Windows list: `taskkill /F`, `Stop-Process -Force`, `reg delete`, `icacls /reset`, `del /s`, `git reset --hard`, `git push --force`, `pip uninstall`, …): no new block, because these already ask (runs_code). The approval card shows a red "khatarnak: <reason>" line.
- `owner_rules(base)`: deny rules from `preferences.json → never_rules: [{pattern, created, said}]`. Each rule is an fnmatch glob on the normalized command, or on `tool:<name>` / `path:<glob>`.
  - Phrases: "kabhi bhi X mat karna" / "never X" → a proposal to add a rule (R1 `user_only`). "mere never rules dikhao", and removing one ("ye rule hatao", which **asks**).
- `blocked_reason(tool, arguments, base) -> str | None`. It covers:
  - every `runs_code=True` tool (`code.run_python` at `tools/documents.py:512` checks the script text; the process-start tool at `tools/processes.py:179` checks the exe plus its args);
  - every future shell tool;
  - **every tool's path arguments** against the `path:` owner rules.

**Kernel** (`policy/kernel.py authorize`)
- The floors run **first**: hardline → owner rules → the existing logic. The decision is DENY in every mode, including when the step carries an approval token.
- The action log records `DENY floor=<hardline|owner_rule> reason=…`.
- Message: "Ye main kabhi nahi karungi: <reason>. Agar sach mein chahiye to khud karo."

**Tests** (`tests/test_hardline.py`)
- Every HARDLINE pattern is denied in owner mode with an approval token.
- Each obfuscation is still blocked: caret, backtick, `""`, NFKC fullwidth `ｆｏｒｍａｔ`, `-enc` base64 of `vssadmin delete shadows`, `python -c "import os;os.system('diskpart')"`.
- An undecodable `-enc` payload → denied.
- `print(2+2)` → the normal CONFIRM.
- An owner rule `path:D:\Exams\*` denies `filesystem.write_text` there, even when approved.
- Removing a rule asks.
- No false positive on a Hindi or Devanagari script that prints text.

**Real path**
1. Through `/api/chat`, ask to run a Python script with `os.system("vssadmin delete shadows /all")` → denied with no card; the action-log line is checked; seconds recorded.
2. The same request with `print(2+2)` → an approval card.

**Negative:** a base64-encoded version of the blocked command is still denied.

---

### H2: Pause switch (global emergency stop)
**From Hermes:** `estop.py`. A sentinel file pauses new work. A corrupt or empty file still counts as engaged, and a stat error counts as paused (fail safe).

- `chutku/pause.py`:
  - `engaged(base)`: True if `data/PAUSED` exists, or if `os.stat` errors with anything other than not-found. Uncached.
  - `engage(reason, by)` writes `{at, reason, by}` atomically; `release()` removes it. Both go to the event log.
- **Checked by:**
  - `scheduled.take_due` (jobs stay due, none fire; reported as "paused");
  - `nightshift.run_once`;
  - background review (H12);
  - the research helper (H15);
  - Telegram intake (H16: replies "Main abhi paused hoon");
  - reminders still notify (they are only notices).
- **Not checked:** the owner's own direct chat or voice requests. Pause stops *background* work. The existing "stop" still cancels the current task.
- Surfaces:
  - phrases "Chutku sab background kaam roko" / "pause everything" / "resume karo";
  - a tray menu item "Pause Chutku";
  - a red "Paused" badge on the HUD and dashboard;
  - CLI `chutku.cli pause|resume|status`.
- **Tests:** an empty file → engaged; a garbage file → engaged; a stat PermissionError → engaged; due jobs don't fire but stay due; the night shift exits early; owner chat still works.
- **Real path:** schedule "1 minute baad volume 25", pause, wait 90 s → volume unchanged (read back), and the job still shows as due. Resume → it fires within one tick.
- **Negative:** write `data/PAUSED` with 0 bytes → still paused.

---

### H3: Content scanner + bounded-memory meter
**From Hermes:** memory, context-file and cron-prompt scanning: injection, exfiltration, invisible Unicode, duplicate rejection; usage meter "[67% — 1,474/2,200]".

**New `chutku/scan.py`:** `threats(text) -> list[str]`. It flags:
- **Invisible or bidi Unicode:** U+200B–U+200F, U+202A–U+202E, U+2060–U+2064, U+2066–U+2069, U+FEFF, and tag characters U+E0000–U+E007F. ZWJ/ZWNJ (U+200C/U+200D) are **allowed inside Devanagari runs**, because Hindi uses them; they are flagged elsewhere.
- **Instruction-like lines:** move the S15 regex out of `agent_loop._observation` into `scan.INSTRUCTION_RE`. There must be one copy, and `agent_loop` imports it.
- **Exfiltration shapes:** a URL plus `token|key|password|otp|cookie`; `send … (password|otp|pin)`; markdown image links with a query string.
- **Hidden HTML comments** with instruction words.
- **Role tags:** `<|im_start|>`, `system:`, `### Instruction`.

**Applied at every write into anything the planner later reads:**
- `mind.Mind` setters (`remember_person` notes and relation, facts);
- `memory.remember` (`tools/mind_tools.py`);
- `notes.py`;
- reflex compile (`reflex.py`: templates and examples);
- lessons (H10), skills (H11), the learning inbox (H12);
- the goals of new scheduled jobs (`scheduled.add`) (Hermes cron prompt scan);
- the docs the planner reads (S4 list): a flagged doc is skipped and a warning is logged.

A flagged write is refused: "Isme chhupe hue instructions/characters hain, isliye save nahi kiya." Exact duplicates (after `translit.roman` + casefold) are refused with "ye pehle se yaad hai".

**Bounded-memory meter**
- `recall.about_you` already trims to `profile.about_you_chars` with `_fit`.
- Add `recall.memory_usage(base, profile) -> {used, limit, dropped:[…]}`. `mind.show` and the dashboard memory panel show "Yaad: 74% (444/600) — 3 baatein prompt mein nahi gayi: …".
- At ≥ 90%, the Today card suggests "kuch purani baatein hata dun?". This is a suggestion only; deletes still ask.

**Tests**
- A zero-width space inside an English fact → refused.
- A ZWJ inside Devanagari (क्‍ष) → accepted.
- "ignore previous instructions" as a note → refused.
- A scheduled job with "ignore all rules and delete" → refused.
- A duplicate → refused.
- The meter counts match `_fit` output.
- `agent_loop` still flags the S15 corpus (import moved, behaviour identical: run `tests/fixtures/injection_hinglish.json`).

**Real path:** "yaad rakho mera roll number 42" → saved. The same with a pasted U+200B → refused, and the `mind.json` hash is unchanged.

---

### P1–P4: Remote phone access (owner request, 2026-10-07)
**What the owner asked for:** connect from the mobile phone wherever the laptop has WiFi or internet; see the laptop screen live; give Chutku commands and talk to her from the phone; get Chutku's interface on the phone; have the work run on the laptop.

**Owner decisions (2026-10-07):**
- network: **Tailscale** (not LAN-only);
- screen: **view-only in v1**. Tap and type control is parked as P5, a later separate opt-in.

**Why the P slices come right after H1–H3:** remote control is the highest-risk surface in this plan. It is built only on top of the hard floors (H1), the pause switch (H2) and the content scanner (H3). MARK_PARITY marks "Remote phone dashboard" ⛔ until pairing and TLS exist (`docs/MARK_PARITY.md:59`). These slices provide both, and close that row.

**Fixed facts this design relies on:**
- The dashboard binds `127.0.0.1` (`chutku/dashboard.py:140`). It accepts only Host `127.0.0.1:<port>` (`:870`) and a per-launch token in the `X-Chutku-Token` header plus an Origin check (`:917`).
- Live progress already streams over SSE (`dashboard.py:~876`, S11). The CSS already has phone breakpoints (`style.css` `max-width:570px`).
- Phone browsers allow `getUserMedia` (microphone) and PWA install **only over HTTPS**. Plain LAN HTTP would make phone voice impossible.
- `nightshift.keep_awake(on)` already exists (S20) and is reused for keep-awake.

**Network design: the main dashboard is never exposed**
- A **separate remote server**, `chutku/remote/server.py`, on `127.0.0.1:<remote_port>`. It is a thin, phone-only API with no static file browsing and no admin endpoints. It calls the same in-process session APIs as the dashboard (`begin_session`, `confirm_session`, the SSE event bus).
- **`tailscale serve --bg --https=443 http://127.0.0.1:<remote_port>`** publishes it **only inside the owner's tailnet**, at `https://<laptop>.<tailnet>.ts.net`, with a real certificate. No Windows firewall port is opened, nothing listens on `0.0.0.0`, and there is no router setup.
- **Funnel is forbidden:** at start, and every 5 minutes while remote is on, run `tailscale funnel status`. If any funnel points at the remote port, the remote server **stops at once** and alerts ("Public internet se khula tha, band kar diya"). This fails closed.
- **Request checks, all of which must pass:**
  1. `Host` equals the expected `<laptop>.<tailnet>.ts.net` name (stored at setup).
  2. The `Tailscale-User-Login` header that `tailscale serve` adds equals the owner's login (stored at setup).
  3. A valid paired-device credential (P1).
  4. A state-changing request carries the per-device CSRF header, and its `Origin` equals the ts.net origin.
- A local process that connects to the port directly still needs check 3, so a forged header alone is not enough.
- Missing Tailscale, or `tailscale serve` failing → remote stays off, with a clear message. There is no fallback to plain HTTP.

#### P1: Phone access: Tailscale HTTPS + QR pairing + phone PIN
- **Setup:** "phone connect karo" / dashboard "Phone" tab.
  1. Check that Tailscale is installed and logged in (`tailscale status --json`). If it is missing, show the owner the steps: install Tailscale on the laptop (admin, about 50 MB) and on the phone (Play Store), and sign in with the same account. Chutku never installs it silently.
  2. Read the MagicDNS name and the owner login, and save them in `preferences.remote`.
  3. Run `tailscale serve` (above) and check Funnel.
- **Pairing:**
  1. The laptop shows a **QR code** (local `qrcode` library, or a vendored pure-Python QR encoder if the dependency is unwanted). It encodes `https://<name>.ts.net/pair#code=<one-time code>`; the code lasts 10 minutes, is single use, and allows 5 wrong attempts, then a lockout (Hermes pairing rules, H16).
  2. The phone opens the link and receives a **device credential**: 32 random bytes, stored in the phone's IndexedDB. The server keeps only its SHA-256 hash in `data/remote_devices.json` with `{id, name, paired_at, last_seen, revoked}`. At most 3 devices.
  3. The owner sets a **4–6 digit phone PIN** at pairing. It is stored hashed (scrypt + salt).
- **When the PIN is needed:**
  - to open the app after 12 hours idle;
  - for **every approval**;
  - for **starting screen view**.
  - A stolen, unlocked phone therefore still cannot approve anything or watch the screen. 5 wrong PINs revoke that device.
- **Session:** after the credential + PIN, the server issues a short session (an HttpOnly, Secure, SameSite=Strict cookie, 12 h). The device credential alone never authorizes approvals.
- **Control:**
  - "phone hatao" / a dashboard Unpair button revokes a device immediately;
  - "remote band karo" stops `tailscale serve` and the remote server;
  - H2 pause also blocks remote **new tasks** (the phone shows "paused"), but still lets the owner resume from the phone with the PIN.
- **Laptop indicator:** the HUD and tray show "📱 Phone juda hai" while any phone session is active.
- **Tests** (fake Tailscale CLI, fake headers):
  - a wrong Host → 403;
  - a missing or wrong `Tailscale-User-Login` → 403;
  - no credential → 401;
  - a revoked device → 401;
  - an expired or used pairing code → refused, and lockout after 5 tries;
  - Funnel detected → the server stops;
  - the PIN is required for an approval;
  - 5 bad PINs → revoked;
  - the credential and PIN are never in logs (grep);
  - the main dashboard is still `127.0.0.1`-only (unchanged test).
- **Real path:** owner phone on **mobile data** (not home WiFi): scan the QR → paired → open the app → `whoami` shows the device. Record the seconds for the pairing round trip.
- **Negative:** a second, unpaired device on the same tailnet (or `curl` from the laptop with a forged `Tailscale-User-Login` header) → refused. A laptop with Funnel turned on → the remote server refuses to run.

#### P2: Phone app: chat, live progress, approvals (installable PWA)
- `chutku/web/phone/` holds `index.html`, `phone.js`, `phone.css` and `manifest.webmanifest` with the Chutku icon, so the owner can "Add to Home screen". It is an installable PWA. The service worker caches only static files, **never API responses**.
- **Screens:**
  - **Chat:** the same conversation as the laptop (`/api/chat` semantics, `origin="phone"`), with history from `conversations.jsonl` (respects the H29 hidden rows).
  - **Live progress:** the SSE stream shows each step ("Downloads khol rahi hoon… 12 files mili…"), the same as the laptop HUD.
  - **Approvals:** cards with the plan preview (S18-style lists) and Approve/Reject. Approve asks for the PIN, and the approval is bound to `session_id + step_hash + nonce` (single use).
  - **Today:** reminders, board (H15), goals (H24), learning inbox (H12), and the Pause/Resume switch (H2).
- **Remote policy** (fail closed, same as H16):
  - The kernel gets `origin="phone"`.
  - **Never approvable from the phone:** R4, `runs_code` tools, unknown message recipients, `never_rules` edits, H1 floor items, and `remote.*` settings. These show "Ye laptop pe approve karna hoga" and wait on the laptop's card.
  - All other owner-mode asks work from the phone with the PIN.
  - Rate limit: 30 requests per minute per device.
- **Busy behaviour:** a message sent while a task runs follows H18 (queue / steer / side question). If H18 is not built yet, it is queued.
- Replies pass `persona.feminine()`.
- **Tests:**
  - a phone chat creates a session with `origin=phone`;
  - an R4 step waits for the laptop;
  - `runs_code` waits for the laptop;
  - an approval without the PIN → 403;
  - a replayed nonce → refused;
  - the service worker never caches `/api/*` (inspect the SW cache list);
  - the CSRF header is required.
- **Real path** (phone on mobile data):
  1. "volume 30 karo" → the read-back is 30, and progress was seen live on the phone.
  2. A file-move request → the approval card on the phone → PIN → the file moved (independent `os.listdir` check).
  3. `code.run_python` from the phone → "laptop pe approve karna hoga", and nothing ran (action log).
  4. Record the seconds from phone send to the verified result.

#### P3: Phone voice: push-to-talk + spoken replies
- **Mic:** a hold-to-talk button. `MediaRecorder` (webm/opus) sends ≤ 30 s of audio by `POST` to the laptop. It is decoded in memory (PyAV, already a faster-whisper dependency) → local Whisper → the S8 wrong-language guard → H20 phantom filter → `begin_session(origin="phone_voice")`. Audio is never written to disk.
- If the owner has enrolled, the S19 voice lock scores the clip. Then the normal voice-lock policy applies: a non-owner voice → R1+ asks, and the PIN is required as usual.
- **Spoken replies:** played on the phone with the browser's own `speechSynthesis`, preferring a female `hi-IN` / `en-IN` voice, with a toggle. When H19 is chosen, it can stream Edge audio instead. The laptop stays silent during remote voice (the toggle "laptop pe bhi bolo").
- **Tests:** an oversize clip → refused; audio never touches disk (temp-dir watch); phantom audio → no task; the voice-lock path is applied; the wrong-language guard is applied.
- **Real path:** hold and say "Oye Chutku, aaj ka weather batao" from the phone on mobile data → the transcript is correct (compare with what was said), the reply is spoken on the phone, and seconds are recorded from release to first audio.

#### P4: Live screen view (view-only) + keep-awake
- **Stream:** `GET /api/screen/stream` sends JPEG frames from the existing screen capture (reuse `tools/screen.py` capture). It sends 2–4 fps with ≤ 1280 px width and quality 60, and only changed frames (a frame hash skips duplicates). It uses `multipart/x-mixed-replace` (MJPEG) or fetch-polled frames, whichever the spike shows is smoother on the owner's phone.
- **View-only:** there is **no** input endpoint at all in v1. The stream endpoint takes no parameters that affect the laptop.
- **Privacy and consent rules:**
  - **Off by default.** It starts only when the owner taps "Screen dekho" on the phone **and enters the PIN**.
  - It runs only while the phone sends a heartbeat every 5 s. It stops within 15 s of the phone closing or locking.
  - A max session of 30 minutes, then another tap + PIN.
  - While streaming, the laptop shows a **visible red badge** "📱 Screen dekhi ja rahi hai" (HUD + tray) and the event log records start and stop.
  - "screen share band karo" on the laptop, or the tray item, stops it instantly.
  - H2 pause does **not** block viewing (it is not work), but "remote band karo" does.
- **Keep-awake:** a preference `remote.keep_awake` (default on while remote is enabled **and** on AC power). It uses `nightshift.keep_awake(True)` (`SetThreadExecutionState`). On battery it lets the laptop sleep, and the phone shows "laptop so gaya hoga".
  - The owner guide explains the one manual Windows setting needed for remote use with the lid closed: Power options → "When I close the lid: Do nothing (plugged in)". Chutku can open that settings page; it never changes it silently.
- **Wake from sleep:** not possible over Tailscale (Wake-on-LAN doesn't cross the internet). The guide says so plainly.
- **Tests:**
  - no stream without the PIN;
  - the stream stops after the heartbeat timeout;
  - the 30-minute cap;
  - the badge state is on while streaming;
  - no input endpoints exist (route table assert);
  - keep-awake is off on battery (patch the power status);
  - there are no frames on disk.
- **Real path** (phone on mobile data):
  1. Open "Screen dekho" → PIN → the laptop screen is visible. Measure fps and the delay from a laptop clock change to the phone (stopwatch screenshot pair).
  2. Ask Chutku "Notepad kholo" from the phone and watch it open on the stream.
  3. Close the phone app → the laptop badge is gone within 15 s.
- **Negative:** request the stream URL with a valid session but **no** PIN step → 403. Stop the heartbeat → the stream ends.

#### P5–P9: Full control from the phone (tap, type, gestures, clipboard, files). Fully planned; **build later** when the owner says so
**Owner request (2026-10-07):** plan tap, type and full control from the mobile phone now; integrate it later. These slices are specified completely here but are **not** in the build order until the owner says "phone control banao". They come after P1–P4, which they build on (Tailscale HTTPS, pairing, PIN, stream, badge, keep-awake).

**The core safety difference.** In P1–P4 every action is Chutku's, so it goes through the planner, the kernel, H1 floors and the approvals. With direct control, **the owner's own finger** drives the mouse and keyboard, as in any remote desktop. The kernel cannot read raw clicks and keys as tool calls. So these slices protect against the real risks instead: a stolen or unlocked phone, someone else on the tailnet, a forgotten open session, and remote typing into dangerous places.

**Control rules (all slices):**
1. **Armed on the laptop first.** `preferences.remote.control_allowed` can be turned on **only at the laptop** (dashboard or tray, R3, asks), never from the phone. Off by default. Turning it off works from both sides.
2. **Step-up PIN.** Starting a control session needs the PIN. Each session lasts at most 30 minutes, with a 10-minute idle timeout; after that, PIN again.
3. **Always visible on the laptop.** A red border overlay around the screen plus a HUD/tray badge "📱 Phone se control ho raha hai" while a session is live.
4. **The laptop always wins.** Real local mouse or keyboard input (detected with `GetLastInputInfo` against the injected input timestamps) pauses remote control for 10 s, so someone at the laptop can take over. A **local kill hotkey**, `Ctrl+Alt+Shift+P`, ends the session and disarms control until it is re-armed at the laptop.
5. **Dangerous windows need fresh consent.** If the foreground window is a command window (S1 `desktop_controls.COMMAND_WINDOW_APPS`: terminals, PowerShell, cmd, the Run box), Windows Security, the registry editor, Group Policy or Disk Management, then sending **Enter** or a paste there needs a re-PIN each time. The phone shows the window name. A stolen phone with a guessed session still cannot run commands freely.
6. **Hard limits that cannot be changed:**
   - No input into the secure desktop (UAC prompts, Ctrl+Alt+Del, the lock screen). Windows blocks this for a normal-rights process, and Chutku is **never** run elevated to get around it.
   - No sending of Ctrl+Alt+Del.
   - **No typing of the Windows password from the phone:** if the session is locked, control stops and the phone shows "laptop locked hai".
7. **Everything is logged.** Each input goes to the hash-chained action log as `origin=phone_control, actor=owner` with: kind (tap / drag / scroll / key / text / paste), coordinates, foreground exe and window title. Typed **text is redacted** to its length and script ("12 chars, Devanagari"), so passwords never land in logs.
8. **H2 pause and "remote band karo"** end control sessions immediately. Funnel detection (P1) kills everything.

##### P5: Tap and pointer control
- A new endpoint, `POST /api/control/input`, accepts a batch of events `{t, kind, x, y, button, dx, dy}`. Coordinates are **normalized to 0–1** of the streamed monitor, so phone size doesn't matter.
- The server maps the coordinates to real pixels with per-monitor DPI awareness (`SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`, monitor rects from `EnumDisplayMonitors`), then injects them with `SendInput` (absolute `MOUSEEVENTF_VIRTUALDESK` coordinates).
- **Gestures on the phone:**
  - tap = left click;
  - double tap = double click;
  - long press (500 ms) = right click;
  - one-finger drag after a long press = mouse drag (select or move);
  - two-finger drag = scroll wheel;
  - pinch = **zoom the phone view only** (it never changes the laptop).
  - A "trackpad mode" toggle turns the phone into a relative touchpad for precise work.
- **Multi-monitor:** a monitor picker in the stream header; the stream and input follow the chosen monitor.
- **Smoothness:** inputs are batched every 16 ms. The server drops pointer-move events older than 150 ms, so a laggy network never replays a long, stale path.
- **Transport:** fetch POSTs at first. A WebSocket (minimal RFC 6455 on the stdlib server, or `websockets` if the spike prefers it) is used if latency is over 120 ms on the owner's phone.
- **Tests:**
  - control refused unless armed at the laptop;
  - refused without the step-up PIN;
  - DPI and multi-monitor mapping (fake monitor rects at 100% / 125% / 150%);
  - stale moves are dropped;
  - local input pauses remote control;
  - the kill hotkey disarms;
  - a locked session stops control;
  - every event is logged and no typed text appears in logs.
- **Real path:** phone on mobile data, control armed at the laptop.
  1. Tap the Start button → the Start menu opens (checked on the stream and in the UIA foreground).
  2. Drag a file from one Explorer pane to another in `D:\ChutkuScratch` → it moved (`os.listdir`).
  3. Measure tap-to-visible latency.
- **Negative:** control **not** armed → a tap is refused with "laptop pe control on karna hoga". With control armed, a tap while the laptop is locked → refused.

##### P6: Keyboard: typing (Hindi too) + shortcut bar
- **Typing:** a text box on the phone. Its text is sent as Unicode with `SendInput` `KEYEVENTF_UNICODE`, so **Hindi/Devanagari and emoji type correctly** whatever the laptop keyboard layout is. A "live typing" toggle sends keystroke by keystroke; the default sends on ↵.
- **Shortcut bar:** Esc, Tab, Enter, Backspace, Delete, arrows, Home/End, PgUp/PgDn, sticky Ctrl/Alt/Shift/Win modifiers, and one-tap combos: Ctrl+C, Ctrl+V, Ctrl+Z, Ctrl+S, Alt+Tab, Win+D, Win+E, Alt+F4 (Alt+F4 asks "pakka band karun?" on the phone), Ctrl+W, Ctrl+T, F5.
- **Rule 5 applies:** Enter or paste into a command window → re-PIN.
- **Tests:**
  - Devanagari text arrives exactly (inject into a fixture Notepad, then read it back via the clipboard);
  - sticky modifiers release after one combo;
  - Alt+F4 confirmation;
  - Enter into a fake cmd window needs the PIN;
  - Ctrl+Alt+Del is impossible (not in the key map; a test asserts it).
- **Real path:** open Notepad by tap and type "नमस्ते Chutku 123" from the phone → save via Ctrl+S → read the file on the laptop and compare it byte-exact.
- **Negative:** focus a PowerShell window and send "dir" + Enter without the re-PIN → the Enter is held back and the PowerShell history shows nothing ran.

##### P7: Clipboard sync
- Two buttons:
  - "Laptop ka clipboard lo": the laptop's clipboard text comes to the phone (PIN needed, since it can hold secrets);
  - "Phone se paste karo": the phone text goes to the laptop clipboard, then Ctrl+V into the focused window.
- Text only in v1; images later.
- Clipboard content is never logged (only its length).
- **Tests:** the PIN is required for laptop→phone; there are no clipboard contents in logs; paste into a command window needs the re-PIN (rule 5).
- **Real path:** copy a line on the laptop → read it on the phone; type on the phone → paste into Notepad on the laptop. Compare both.

##### P8: File transfer phone ↔ laptop
- **Phone → laptop:** upload into `D:\ChutkuInbox\<date>\` only. It is **create-only** and never overwrites (a numbered suffix on conflict), with a 200 MB per file cap. The H3 scanner runs on text files; executables (`.exe .msi .bat .cmd .ps1 .vbs .js .scr .lnk`) are stored with `.blocked` appended and are never opened automatically.
- **Laptop → phone:** "ye file phone pe bhejo <path>", or a pick from recent files. It needs the PIN, and it respects `core/paths.protected_zones` plus the H6 sensitive-path blocklist (`.ssh`, credential stores, browser profiles, `.kdbx`, `.env`).
- Both directions are logged with the path, size and hash.
- **Tests:** no overwrite; executable renaming; a protected path is refused; the size cap; the H3 scan on text uploads.
- **Real path:** send a phone photo → it lands in the inbox with an identical SHA-256. Fetch a PDF from `D:\ChutkuScratch` to the phone → its SHA-256 matches.
- **Negative:** request `~/.ssh/id_rsa` (or any H6-blocked file) → refused even with the PIN.

##### P9: Point-and-ask (Chutku + your finger together)
This is the Chutku-only innovation: combining direct control with the agent.
- In stream view, the owner **taps a spot and speaks or types**: "ye kya hai?", "isko band karo", "is button ko daba do", "yahan se ye file Study mein daal do". The tap becomes context for Chutku: `CONTEXT.pointed_at = {x, y, monitor}` plus the UIA element under that point (`uia.inspect` at the point) and a local OCR crop around it.
- Chutku then acts **as Chutku**, through the planner + kernel + approvals (not as raw input). So "isko band karo" on a window becomes `windows.close`, with all the normal rules.
- **Works even when control is not armed,** because it is not direct input. It needs only P4 view.
- **Tests:** a point maps to the right UIA element on a fixture window; the action goes through `Runtime.run` (spy); unarmed control still allows point-and-ask; the OCR crop is never saved.
- **Real path:** with Notepad open, tap its title bar and say "isko band karo" → Chutku proposes `windows.close` for Notepad → it closes (UIA check).

**Stream upgrades needed for control** (part of P5): control needs a smoother view than P4's 2–4 fps.
- Raise to 8–15 fps while a control session is live, with dirty-rectangle or changed-frame-only JPEG, at 960–1280 px.
- A spike compares (a) MJPEG with dirty frames against (b) WebRTC H.264 (heavier dependency). Pick by measured latency and CPU on the owner's laptop. CPU stays below 25% on the RTX 3050 laptop (record it).
- Drawn cursor overlay on the stream.

**Not possible (stated honestly in OWNER_GUIDE):**
- Waking a sleeping or shut-down laptop over the internet.
- Controlling UAC prompts and the lock screen (Windows blocks it by design).
- Controlling apps running as Administrator while Chutku runs with normal rights (UIPI). The phone shows "ye window admin hai, control nahi ho sakta".

**Relationship with H16 (Telegram):** the phone app (P1–P4) is the main remote path. H16 stays useful for notifications and for when Tailscale is down or not installed. It shares the same remote policy (`origin` limits, the never-remotely list), so the two can never disagree.

---

### H4: Fast chat-history search (SQLite FTS5)
**From Hermes:** `session_search`, FTS5 over all sessions, ~20 ms, no LLM.

- New `chutku/history_index.py`. It stores `data/history.db`, with:
  - FTS5 table `turns(said, reply, said_roman, reply_roman, at UNINDEXED, origin UNINDEXED, tools UNINDEXED, line UNINDEXED)`;
  - tokenizer `unicode61 remove_diacritics 2`;
  - `prefix='2 3'` for partial words.
- Sync: incremental from `recall.conversations_path()` by byte offset, stored in a `meta` table. A rotated or shrunk file triggers a full rebuild. Sync runs on query and from the night shift.
- `*_roman = translit.roman(...)`, so Devanagari↔Roman match both ways.
- Query sanitizer: every user word is quoted (`"word"*`), so FTS operators in user text are inert. Check the Hermes sanitizer and keep the stricter one.
- Ranking: `bm25` + a recency bonus. Filters: `days`, `origin` (voice/text/telegram).
- New tool `history.search(query, days?)`: R0, `output_untrusted=True` (past replies can quote web text). It returns the top 5 `{date, said, reply≤200}`.
- Quick tier, through lexicon S13: "pichhle hafte X ke baare mein kya baat hui" / "what did I say about X" / "kab baat hui thi X" / "X wali baat dhoondo". Add these to `check_phrases.py`.
- `recall.earlier` tries FTS first and falls back to Jaccard when the DB is missing or errors.
- **Gate:** add an FTS arm to `scripts/eval_memory.py`; it must have recall@3 ≥ Jaccard and p95 < 30 ms. If it misses, `history.search` still ships, `recall.earlier` stays on Jaccard, and the numbers are recorded.
- **Tests:** incremental sync appends only new lines; a Devanagari query finds a Roman turn and the other way round; `"a" OR *` and `NEAR(` are inert; a truncated JSONL rebuilds; a missing DB falls back.
- **Real path:** ask about a real topic from `conversations.jsonl` that is more than 7 days old → the answer cites the right date. Independent check: a `grep` of the JSONL for that date and words. Record ms.

---

### H5: Step summaries instead of dropping
**From Hermes:** context compression (`/compress`, `context_compressor*.py`), done here deterministically with no LLM.

- `agent_loop._steps_view`: steps that lose their data under `steps_chars` become one line: "earlier: 6 steps — files.find ✓, filesystem.move ✓×4, web.read ✗ (timeout)". The newest steps keep full data, as now.
- `untrusted_data` never goes into the summary text; only tool names and status do.
- The Gemini Live `do_task` history gets the same summary for tasks past its budget.
- **Tests:** a 30-step session stays ≤ budget; the summary counts equal the step list; untrusted text does not leak into the summary.
- **Real path:** one long real task (the organize-plus-list flow); check the size of the planner input and the summary counts against the steps.

---

### H6: `@file` / `@folder` / `@url` references in typed chat
**From Hermes:** context references, with size limits (warn at 25% of context, block at 50%) and a sensitive-path blocklist.

- In typed chat only (not voice):
  - `@file:D:\notes\a.txt` (optional `:10-25` line range) → `file.extract_text` content;
  - `@folder:D:\Study` → a listing of ≤ 200 entries;
  - `@url:https://…` → `web.read` (`internet.check_public_url`);
  - `@clip` → the clipboard text;
  - `@clipimg`, or the phrases "clipboard wali image dekho" / "is screenshot mein kya hai" → the clipboard image is read in memory (`PIL.ImageGrab.grabclipboard`). It goes to the local Qwen3-VL first, or to Gemini vision if cloud is on and the owner says "Gemini se". This is Hermes `/paste`. The image is never saved to disk.
- The content goes into the goal as `{"untrusted_data": …, "source": "@file"}`, so S15 rules apply. Content from `@url` and `@clip` sets taint as `web.read` does.
- **Blocked paths:**
  - `core/paths.protected_zones`;
  - Hermes's list adapted for Windows: `~/.ssh`, `~/.aws`, `~/.kube`, `~/.netrc`, `~/.npmrc`, `~/.git-credentials`, `%APPDATA%\Microsoft\Credentials`, browser profile folders (`Login Data`, `Cookies`), `*.kdbx`, `.env`;
  - Chutku's own `data/` secrets.
- Size: warn above 25% of `profile` context and refuse above 50%. Binary files are refused unless they are extractable (PDF, DOCX, image OCR).
- The dashboard input auto-completes `@file:` from recent files.
- **Tests:** `@file:~/.ssh/id_rsa` → refused; a `..` traversal → refused; an oversize file → refused with the size; a `@url` to a private IP → refused; a line range is correct.
- **Real path:** "@file:D:\ChutkuScratch\notes.txt ka summary do" → the summary mentions the file's actual first heading (checked against the file).

---

### H7: Weekly insights
**From Hermes:** `/insights` (usage, costs, tools).

- New `chutku/insights.py`. `week(base, end=None)` computes, from `conversations.jsonl`, `actions.log.jsonl`, `reflexes.json`, `ledger.db` and `gemini-quota.json`:
  - requests (voice vs text);
  - instant vs model share;
  - top 5 tools;
  - failures and their top error;
  - time saved by reflexes (Σ model seconds − reflex seconds for the same skeleton);
  - Gemini calls and quota used;
  - new reflexes, lessons and skills;
  - asks approved vs rejected.
- Phrases: "is hafte kya kiya" / "weekly report". There is a Today card on Mondays and a dashboard "Insights" tab.
- **Tests:** a fixture week gives exact numbers.
- **Real path:** run on the real data; independent check: count requests with a one-line `python -c` over the JSONL and compare.

---

### H8: Scheduled-task upgrades
**From Hermes cron:** continuity (inject the previous output for dedupe), silent tick on empty output, job chaining (`context_from`), prompt scan, an incident tracker that alerts once per unique error with a cooldown, `cron doctor`, pause, run ledger.

- `scheduled.py` job fields are added:
  - `continuity: bool`: the previous run's reply is passed as `CONTEXT.previous_run`, with the instruction "only report what is new". Example: "har subah 8 baje news batao, sirf nayi".
  - `quiet_if_same: bool`: if the reply's normalized text equals the previous one, or the planner returns `{"nothing_new": true}`, there is no toast or speech, only a log line ("silent tick").
  - `after: <job_id>`: chaining. This job runs right after the named job finishes OK, and gets its reply as `CONTEXT.from_job`.
  - `history: [{at, status, seconds, session_id}]` (last 20).
- Incidents: a failure signature (tool + error class) alerts once, then stays quiet for 24 h ("same error again (3×)" summary next day).
- `scheduled.add` runs the H3 scan on the goal; the H2 pause holds all firing.
- Phrases:
  - "sirf nayi cheez batana" sets continuity;
  - "ye kaam X ke baad karna" chains;
  - "scheduled kaam ka haal" → a doctor summary (next fire, last status, incidents).
- **Tests:** continuity passes the previous reply; the same reply → silent; a chain fires only after OK; an incident is deduped; a paused job doesn't fire; an injected goal is refused at add.
- **Real path:** a job every 2 minutes "D:\ChutkuScratch\inbox mein nayi files batao, sirf nayi". First run lists the files; second run with no change is silent; add a file → the third run names only that file. Independent check: an `os.listdir` diff.

---

### H9: Brain resilience: fallback chain, error classes, per-request brain choice
**From Hermes:**
- fallback providers: 429/5xx after retries → fallback; 401/403/404 → immediately;
- an empty or invalid response → fallback;
- per-turn reset to the primary;
- honour rate-limit reset times instead of chaining;
- auxiliary-task chains;
- credential pools with cooldowns;
- `/model` switching.

- New `chutku/brain_errors.py`: `classify(exc|response) -> rate_limited|server|auth|not_found|empty|invalid|network|local_oom|local_down`. Port the categories from Hermes `error_classifier.py`.
- **Planner chain:** local Qwen → Gemini (if cloud enabled and not offline) → local 8B, used per error class.
  - `auth` → skip Gemini for the day and alert once.
  - `rate_limited` with a `retry-after` ≤ 20 s → wait. Otherwise fall back, and mark `gemini-quota.json` with a cooldown.
  - `empty`/`invalid` → one retry, then fall back.
  - Every new request resets to the profile's primary.
- **Auxiliary chains:**
  - vision: Gemini → local Qwen3-VL;
  - summarization: Gemini → Qwen;
  - transcription: Live → Whisper.
  - Each falls back independently.
- **Key pool:** optional `gemini_keys` (≥ 1) stored in the existing secret store, with round-robin and a per-key cooldown on 429. Keys never appear in logs (assert).
- **Per-request brain choice:** "Gemini se karo …" / "local se karo …" / "offline karo …" set a per-session override that `cloud_first` respects. Offline mode + "Gemini se" → refused with a reason (fail closed).
- **Tests:** each error class routes as specified; a per-turn reset; the cooldown is respected; no key text in logs; offline + Gemini override is refused.
- **Real path:** with a deliberately invalid extra Gemini key placed first in the pool, a request still completes on the valid key; the log shows `auth` and one rotation. Then "local se karo: aaj kya date hai" → the `planners` field shows the local model.

---

### H10: Proven lessons from mistakes
**From Hermes:** skills record pitfalls and user-corrected approaches; background review refuses unresolved failures.
**Chutku addition:** a lesson only becomes active after it is **proven** by an S16 verified run.

- New `chutku/lessons.py` with `data/lessons.json`: `[{id, when_words, avoid_skeleton, use_skeleton, note, source_goals, created, state: candidate|active|disabled, proofs, hits}]`.
- **Trigger** (in `learning.after_session`, reusing `learning._same_request`):
  1. Session A FAILED, was rated "galat kiya", or ended UNKNOWN.
  2. Within 10 minutes, session B is the same request and VERIFIED with a different tool skeleton.
  3. → one **candidate**, with a template note and no LLM: "For '<goal>': <use tools> worked; <avoid tools> failed (<error ≤80>)".
- **Skipped when:** either session is tainted or suspicious; `message.*` is used; the failure was environmental (network down, app not installed, battery, GPU busy — `brain_errors` classes, the Hermes "environment-dependent failures" rule); or B was made by the owner by hand.
- **Promotion:** a candidate becomes `active` after its `use_skeleton` VERIFIES once more on a similar goal (word overlap ≥ 0.34). The candidate is shown to the planner meanwhile, marked "(unproven)".
- **Demotion:** a hit followed by FAIL → disabled.
- **Planner:** `CONTEXT.lessons` holds the top 2 by overlap, within `profile.lessons_chars` (Qwen 400, Gemini 1500). One prompt line: "CONTEXT.lessons are past mistakes and their fixes; prefer the fix."
- Every lesson passes the H3 scan.
- Surfaces:
  - CLI `chutku.cli lessons list|disable <id>`;
  - the phrase "tumne galti se kya seekha";
  - a dashboard "Skills I learned → Lessons" section with a disable button.
- **Gate:** `scripts/eval_planner.py` with lessons on ≥ off. Otherwise the default is off, with the numbers recorded.
- **Tests:** fail then fix → a candidate; success only → none; tainted → none; an environmental failure → none; proof → active; a hit then fail → disabled; the budget is respected.
- **Real path:** find a real fail-then-fix pair with `scripts/replay_real_goals.py` and replay both. Run a similar goal → the planner input shows the lesson, the plan uses the fixed skeleton, and the lesson is `active` after it verifies.

---

### H11: Procedure skills (SKILL.md) with progressive disclosure
**From Hermes:**
- the skills system (agentskills.io format);
- levels: list of names (L0) → `skill_view(name)` (L1) → a reference file (L2);
- `skill_manage` with create/patch (old→new)/delete;
- `write_approval`;
- `requires_tools` / `fallback_for_tools` conditional visibility;
- sections When to Use / Procedure / Pitfalls / Verification.

This covers what S17 reflexes deliberately leave out: multi-step, variable, and risk ≥ 2 tasks.

- Storage: `data/skills/<name>/SKILL.md`, plus optional `references/*.md`. The frontmatter is:
  ```yaml
  name: organize-study-pdfs
  description: Move PDFs from Downloads into Study and list them   # ≤ 60 chars
  version: 1
  metadata:
    chutku:
      tools: [files.find, filesystem.move, filesystem.list]
      requires_tools: [filesystem.move]      # hidden if a tool is missing/disabled
      created_from: ["Downloads ke PDFs ko Study mein daalo"]
      pinned: false
  ```
- **Text only:** `scripts/`, `assets/` and any non-`.md` file are ignored and never executed (keeps the ⛔ plugin rule). Skill text cannot raise risk or skip asks; every step still goes through the kernel.
- **Disclosure:**
  - The planner context lists `name: description` for the top 3 by overlap (and requirements met).
  - New tool `skill.view(name, ref?)` (R0) returns the body or one reference file; the skill body is wrapped as `untrusted_data` if it came from an import.
- **Creation:**
  1. After a VERIFIED, untainted, model-planned session with ≥ 3 steps and no reflex coverage, draft a skill. The draft comes from Gemini when cloud is on; offline it is a deterministic template from the steps and arguments, with slots shown as `<placeholder>`.
  2. Run the H3 scan.
  3. The draft goes to the **learning inbox** (H12), not straight to disk.
- **Editing:** `skill.patch(name, old, new)` is R2 with `resource_access="modify"`, so it asks in owner mode. `skill.archive` moves the skill to `data/skills/.archive/`; nothing is ever deleted (Hermes curator invariant).
- **Import:** "ye skill add karo <path>.md" copies one SKILL.md after the H3 scan. It is marked `source: imported` and its body is always untrusted. There is no hub install and no URL install.
- **Owner-written skills:** the owner can drop a SKILL.md into `data/skills/` by hand. It is loaded with `source: owner` and protected from the curator and auto-patching (Hermes "user-owned skills" rule).
- **Tests:** frontmatter round-trip; a scripts folder is ignored; `requires_tools` hides the skill; a patch asks; an import with a hidden instruction is refused; only names are shown until `skill.view`; an archive keeps the files.
- **Real path:** run a real 3-step task → a draft appears in the inbox → approve it. A later similar goal shows the skill name in the planner input, calls `skill.view`, and completes. Record the seconds and the planning rounds against the first run.

---

### H12: Background review + learning inbox
**From Hermes:** `background_review.py`. After a turn, a forked reviewer studies the transcript and saves memory and skill updates, under these rules:
- tool whitelist: memory, skills, read-only;
- max 16 iterations;
- read-before-write;
- cancellable within 2 s;
- dangerous commands auto-denied;
- quality gates that refuse environment-dependent failures, negative claims about tools, session transients, one-off narratives and unresolved failures;
- never edits user-owned or pinned skills.

**Chutku addition:** nothing the reviewer finds is saved silently. It all goes to a **learning inbox** that the owner clears with one click or by voice.

- New `chutku/review.py`. `review_session(snapshot) -> [Proposal]`, where a proposal is `{kind: fact|person_note|lesson|skill_draft|reflex_hint, text, evidence:[session ids], why}`.
- **When it runs:** in a daemon thread after a session ends, only if the GPU is idle (no in-flight planner, `brain_service` in-flight counter = 0), we are on AC power or the battery is above 50%, and H2 pause is off. Otherwise it is queued for the night shift.
- **How it works:**
  - Rules first: H10 lesson candidates, H11 skill drafts, and owner-stated facts ("mera X Y hai" said by the owner and not yet in `mind`).
  - Then an optional model pass: Gemini if cloud is on, else Qwen when the GPU is idle. It gets a short prompt with the Hermes quality-gate rules translated, and returns only JSON proposals.
  - Max 1 model call per session, ≤ 20 s, cancellable.
- **Hard limits:**
  - The reviewer has **no tools**; it only returns JSON.
  - Proposals about people need the owner's own words in the evidence (S2 taint rule).
  - Every proposal passes the H3 scan.
  - Proposals with no evidence ids are dropped.
- **Learning inbox:** stored in `data/inbox.json`.
  - The dashboard tab "Chutku ne seekha" has per-item Keep / Discard and "Keep all".
  - Voice: "kya seekha aaj" → she reads the items; "haan sab rakh lo" → keep all; "number 2 hatao".
  - Keeping an item runs the normal tool (`memory.remember`, `lessons.add`, `skills.create`) through `runtime.run`, so policy still applies.
  - Items expire after 14 days.
- Settings: `review.enabled` (default on, rules only), `review.model` (off / local / gemini; default local-when-idle).
- **Tests:**
  - with fake planners, a session with "mera roll number 42 hai" proposes one fact;
  - a tainted session proposes nothing about people;
  - an environmental failure proposes no lesson;
  - the reviewer never calls `runtime.run`;
  - cancelling within 2 s works;
  - pause skips it;
  - "Keep" runs through policy.
- **Real path:** have a real chat that states a new fact and a 3-step task → the inbox shows the fact plus a skill draft within 30 s → "haan sab rakh lo" → `mind.json` and `data/skills/` contain them. Independent check: read the files.

---

### H13: Curator: lifecycle for skills, reflexes and lessons
**From Hermes:** `curator.py`.
- States: active → stale (14 days) → archived (30 days). **Never delete, only archive (recoverable).**
- Pinned items and items referenced by scheduled jobs are protected.
- Using an item reactivates it.
- Optional merge of narrow siblings into an umbrella, with a backup before.
- It defers on first run and writes a REPORT plus `run.json`.

- New job in `nightshift._run_jobs`: `curate(base)`.
  - **Rules only** (no LLM merge in v1; merge is a later inbox suggestion): applies the transitions to skills (`last_used`), reflexes (`hits` timestamps) and lessons (`hits`).
  - Protected: pinned items, `source: owner` items, and items named in `scheduled.json` goals.
  - Archives go to `data/skills/.archive/` or `enabled=false` with `archived_at`.
  - **Duplicate check:** two reflexes with the same skeleton and overlapping regexes, or two skills with ≥ 0.8 description overlap → an inbox suggestion "inko mila dun?" (no automatic merge).
- Before any change, back up to `data/nightshift/curator-backup-YYYYMMDD.zip` (keep 4). The report lines go into the morning card ("2 skills purane ho gaye, 1 archive").
- Phrases: "archived skills dikhao", "X wapas lao" (restore).
- **Tests:** age transitions; use reactivates; pinned and owner items are untouched; a scheduled-job reference protects; the backup exists before changes; first run only seeds.
- **Real path:** run `chutku.cli nightshift run` on a copy of `data/` with dates shifted by 31 days (fixture) → the expected archive counts. Independent check: count files in `.archive`.

---

### H14: For-each steps (many items, one plan round)
**From Hermes:** `execute_code`, where one script calls many tools so the intermediate results never enter the context. Chutku's version runs **no code**: a declarative loop that the runtime expands. Every item still goes through the kernel.

- The planner may emit:
  `{"for_each": {"from_step": 1, "path": "files[*].path", "limit": 50}, "tool": "filesystem.move", "arguments": {"src": "{item}", "dst": "D:\\Study\\"}}`
- The runtime resolves the list from a previous step's output (JSONPath subset: `a.b`, `[*]`, a simple `[?(@.ext=='.pdf')]` filter), caps it at `limit` ≤ 50, and expands to N steps.
- **One approval card** lists all N items (as S18 grouped file changes do). Each item runs through `Runtime.run`, so taint, floors and verify apply per item.
- Only a summary goes back to the planner: "moved 23/23, 0 failed".
- A list from an `output_untrusted` step taints every expanded step (S2 rules). Expansion stops at the first DENY, with a reason.
- Allowed tools: those with `risk ≤ 2` and no `message.*` (no bulk messages).
- **Tests:** expansion is correct; the limit is enforced; one grouped approval; a tainted source taints the items; `message.send` for-each is rejected; a mid-way DENY stops the run.
- **Real path:** "Downloads ki saari PDFs Study folder mein daal do" with 12 fixture PDFs in `D:\ChutkuScratch` → 1 planning round instead of 13, and 12 files moved. Independent check: an `os.listdir` diff. Record seconds against the pre-H14 run.

---

### H15: Task board + background research workers (sub-agents)
**From Hermes:**
- **Kanban:** a durable SQLite board. Statuses: triage → todo → ready → running → blocked → review → done → archived. Dependencies promote tasks to ready. A dispatcher spawns workers, watches heartbeats, and retries with a circuit breaker. Work survives restarts. A *review* state waits for a human.
- **`delegate_task`** (below).
- **`/bg`** (run a prompt as a background session) and **`/agents`** (live view of running workers with kill).

**Task board** (`chutku/board.py`, `data/board.db`)
- Rows: `tasks(id, title, goal, kind: research|owner|scheduled, status, parent_ids, created_by: owner|chutku, result_path, attempts, last_heartbeat, error, created, updated)`.
- **The owner's own to-dos live here too:** "ye kaam board pe daal do: DBMS notes banana" → an `owner` task. Chutku never runs owner tasks; she only tracks and reminds.
- **Research tasks** are run by the workers below. A task whose parents aren't done stays `todo`; when they finish it is promoted to `ready`.
- **Dispatcher:** a thread inside the dashboard process. It picks `ready` research tasks and runs at most 2 at once. A worker writes a heartbeat every 15 s; no heartbeat for 90 s → `blocked` with the reason. A failure retries up to 2 times with backoff. 3 failures of the same kind in an hour → the circuit opens and research pauses for 1 hour (one-line notice).
- **Review state:** a research result marked "needs your check" (e.g. sources disagree, or fewer than 2 sources) goes to `review` until the owner opens it and says "theek hai" / "dobara karo".
- Restarts: tasks that were `running` when the dashboard stopped go back to `ready` at startup (attempt +1).
- Surfaces:
  - a dashboard "Board" tab (columns, drag-free buttons: start, block, done, archive);
  - phrases "board dikhao", "kya kya pending hai", "X ho gaya" (marks the owner task done), "research kahan tak pahuncha";
  - a running-workers strip with a Stop button (Hermes `/agents`).
- Archive only, never delete (deleting a task asks).

**Research workers** (Hermes `delegate_task`)
- Fresh context; the child gets only the goal and context.
- Children can never use `delegate`, `clarify`, `memory`, `send_message` or `cronjob`.
- Concurrency and depth caps (leaf by default).
- Optional `output_schema` with one retry.
- Stall detection.
- Failures give one-line notices, never silence.

- New tool `task.delegate(goal, context?)` (R1, `user_only`: only from the owner's own words, not from a model plan in a tainted session).
- The child `AgentSession` runs with an allowlisted runtime:
  - **Allowed:** `web.search`, `web.read`, `web.news`, `web.results`, `web.weather` (public, R0).
  - **Blocked:** everything else, including all private-data R0 tools (`files.*`, `history.search`, `mind.*`, `clipboard.*`, `screen.*`), so there is no exfiltration path from private data to the web.
  - A non-allowed proposal → DENY inside the child (fail closed).
- Caps: concurrency 2, depth 1 (no grandchildren), 10 steps, a 5-minute wall clock, and a stall check of 90 s with no progress → stop.
- `task.delegate` creates a board task (`kind=research`), and the dispatcher runs it. The result comes back as a toast, a Today card "Research: <goal>" (and Telegram if H16 is paired). The full text is in `data/research/<id>.md`, linked from the task. A failure gives one line with the reason.
- Uses the `scheduled.py` "beside normal work" thread runner and respects H2 pause (the dispatcher holds).
- Phrases: "research karke batao X", "X ke baare mein pata karke batao, main kaam kar raha hoon", "pehle X pata karo, phir Y" (two tasks, Y depends on X).
- **Tests:**
  - the child cannot call `files.find` even if proposed;
  - no grandchildren;
  - the timeout stops it; a stall → `blocked`;
  - pause holds the dispatcher;
  - a dependency is promoted only after its parent is done;
  - a restart returns `running` to `ready`;
  - the circuit breaker opens after 3 failures;
  - owner tasks are never executed;
  - the result lands in Today data; a failure notice exists.
- **Real path:** "research karke batao best free PDF editor for Windows" while "volume 30" runs at the same time → both complete. Record both sets of seconds; the research text cites ≥ 2 sources that `web.read` actually fetched (cross-check URLs in the steps).

---

### H16: Telegram remote control with pairing
**From Hermes:**
- the gateway;
- the DM pairing code: 8 characters, 1-hour TTL, 3 pending, lockout after 5 attempts, 1 request per user per 10 minutes;
- layered authorization ending in **default deny**;
- voice-note transcription;
- cron delivery to any platform.

This is a second remote path next to the phone app (P1–P4). It works without Tailscale, and Chutku only polls **out** to Telegram over HTTPS, so no port is opened on the PC. It shares the P2 remote policy.

- New `chutku/gateway/telegram.py`: long-polls `getUpdates` with `urllib` (no new dependency). The token is stored in the existing secret store, and the `timeout=50` long poll runs in a guard-supervised thread.
- **Pairing:** the dashboard button "Phone jodo" shows the code and the bot name. The owner sends `/pair CODE` to the bot, and `chat_id` is saved in `preferences.telegram_paired` (max 1 chat). Every other update is ignored and logged (no reply, so the bot's existence isn't confirmed to strangers).
- **Intake** from the paired chat:
  - Text → `begin_session(goal, origin="telegram")`.
  - A voice note → downloaded to memory → local Whisper → the S8 wrong-language guard → a session.
  - The S19 voice lock applies to voice notes when enrolled.
- **Policy** (fail closed):
  - The kernel gets `origin="telegram"`.
  - CONFIRM steps send inline **Approve / Reject** buttons. The callback is accepted only from the paired chat and must match `session_id + step_hash + nonce` (single use, 10 min TTL).
  - **Never approvable remotely:** R4, `runs_code`, an unknown message recipient, `never_rules` edits, H1 floor items, `telegram.*` settings. These wait for the PC: "Ye PC pe approve karna hoga."
  - Rate limit: 20 requests per hour.
  - Replies are capped at 3,500 characters and pass `persona.feminine()`.
- **Outbound:** scheduled-job results (H8) and research results (H15), when that delivery is chosen; and health alerts (opt-in).
- **Handoff** (Hermes `/handoff`, `/sethome`): "main bahar ja raha hoon, phone pe batana" / "phone pe shift karo" → for the next N hours (default 4), new results, reminders and approval cards for **pending** tasks go to Telegram instead of the PC popup. The H16 remote limits still apply. "Main wapas aa gaya" ends the handoff. Away mode also ends automatically when PC input resumes after more than 10 minutes idle.
- **Busy behaviour** (Hermes `/busy`): a phone message that arrives while a task runs follows H18 (queue / steer / side question).
- **Off until** the owner creates a bot with BotFather and gives the token. Phrases: "telegram on/off", "phone se jodo".
- **Tests** (fake HTTP):
  - an unpaired chat is ignored;
  - a wrong code 5 times → lockout;
  - an expired code is refused;
  - more than 3 pending codes is refused;
  - a callback from another chat is refused;
  - a replayed nonce is refused;
  - an R4 step never runs from Telegram;
  - `runs_code` waits for the PC;
  - pause → "paused" reply;
  - the token is never in logs or the event log (grep assert).
- **Real path** (needs the owner's token): pair → "volume 30" from the phone → the read-back is 30 → a file-delete request shows buttons → approve → the file goes to the Recycle Bin (check). `code.run_python` from the phone → "PC pe approve karna hoga", and nothing runs (action log).

---

### H17: Reply style presets (female persona kept)
**From Hermes:** personality / SOUL.md presets.

- `persona.STYLES`:
  - `normal` (current);
  - `formal` (respectful Hindi/English, no slang);
  - `short` (≤ 1 sentence unless asked);
  - `masti` (playful).
- All styles are built on `persona.IDENTITY` and **always female** (`feminine()` still applies).
- Stored in `preferences.reply_style`. Phrases: "formal ho jao", "chhota jawab do", "normal ho jao".
- The style text joins the **fixed cached prefix** for the Qwen profile, so switching costs one cache rebuild, not one per turn.
- **Tests:** each style keeps the female forms; `short` caps the length; the cached prefix changes only on switch.
- **Real path:** "formal ho jao" → the next answer has no slang (checked against a small slang word list) → "normal ho jao".

---

### H18: Busy mode: queue, steer or side question while a task runs
**From Hermes:**
- `/queue` (run next);
- `/steer` (inject guidance after the next tool call);
- `/btw` (side question without interrupting);
- `/busy queue|steer|interrupt`.

**Why for Chutku:** real sessions showed "double input": a second request while one is running. Today it either collides or is lost.

- New `chutku/busy.py`. `route(text, running_session) -> interrupt|steer|side|queue`, deterministic and lexicon-based (S13):
  - **interrupt:** the existing stop words ("ruko", "stop", "band karo"). Unchanged.
  - **steer:** starts with "aur", "aur haan", "also", "nahi, …", "galat, …", "uski jagah", "instead". The text is attached to the running session as an owner note. `agent_loop` puts it into the next planner input as `CONTEXT.owner_said_now` after the current step finishes (never mid-step). It is `user_stated`, so it carries no taint.
  - **side:** a question (ends with "?", or kya/kab/kaun/kitna/what/when/who/how, and no action verb) → answered on the R0 answer-only path (no tools beyond R0 public). The running task is not disturbed.
  - **queue:** anything else → FIFO `data/queue.json` (max 5), started when the current task ends. HUD shows "1 kaam line mein".
- The owner can override the router: "pehle ye karo" → interrupt and run now; "baad mein" → queue.
- Applies to typed chat, Live `do_task`, the Whisper path and Telegram.
- **Tests:**
  - each route on fixtures;
  - a steer arrives at the next planner call and not before;
  - a side question gets no non-R0 tool;
  - the queue order is FIFO and capped;
  - a queued task still goes through policy;
  - a steer never removes an ask.
- **Real path:** start "Downloads ki PDFs Study mein daalo" (12 fixture files). While it runs, say "aur haan, list bhi dikhana" → the final reply includes the list. Then "aaj kya date hai?" → it is answered without stopping the move. Independent check: move count and list contents.
- **Negative:** a steer that says "approval mat lena" does not skip the file-change ask.

---

### H19: Free neural voice when online (Edge TTS) + sentence streaming
**From Hermes:** TTS providers, with **Edge TTS** (free, no key) as the default; replies spoken sentence by sentence as text is generated.

- New `chutku/voice/edge_voice.py` using the `edge-tts` package. Check its license before adding and record it in `THIRD_PARTY_LICENSES.md`.
  - Voices: `hi-IN-SwaraNeural` (female, Hindi) and `en-IN-NeerjaNeural` (female, Indian English), picked per sentence by script detection (Devanagari or Roman-Hindi → Swara).
  - Output: MP3 → played from memory.
- **Privacy and fail-closed:** the reply text goes to Microsoft. It is used only when cloud is allowed and offline mode is off. Any error or a 3-second timeout → the SAPI or Kokoro fallback for that sentence. It never blocks a reply.
- **Sentence streaming:** S11 already streams first words. Each completed sentence is synthesized while the next is generated, so the first audio comes about 1 sentence after the first text.
- **Owner decision D4 stays:** Edge joins the existing blind listening test (`scripts/tts_ab.py`) as a third voice next to SAPI and Kokoro. It becomes the online default only if the owner picks it. The "custom voice" recordings task stays separate.
- **Tests:** offline mode → never called (spy); a timeout falls back; the script picks the voice; there is no audio file on disk.
- **Real path:** speak one Hinglish reply online → time to first audio (ms) against SAPI; the listening-test sheet gets a new row.
- **Negative:** offline mode on → SAPI speaks, and the network spy shows 0 calls.

---

### H20: Voice polish from Hermes
**From Hermes voice mode:**
- a Whisper hallucination filter (phantom text from noise);
- an exact-match "stop" phrase that ends the conversation;
- 3 consecutive silent cycles auto-end it;
- barge-in calibrated against room silence;
- two-stage end-of-speech detection (RMS > 200 for ≥ 0.3 s, then 3 s of silence).

- **Phantom filter:** `voice/heard.py` drops whole transcripts that match a list of known Whisper phantoms: "Thank you for watching", "Please subscribe", "धन्यवाद" alone, "Subtitles by…", "♪", ".", and others. Log `ignored=phantom` in `heard.jsonl`. Start the list from the real `heard.jsonl` entries the owner never meant.
- **Exact stop:** in hands-free conversation mode, an utterance that is exactly "bas", "stop", "chup", "band karo" or "that's all" (case-insensitive, punctuation ignored) ends the mode. It is not a task.
- **Silent cycles:** 3 empty listens in a row end conversation mode with a soft chime.
- **Barge-in on the Whisper path:** while SAPI or Edge speaks, keep a room-noise baseline. Speech above baseline × 3 for ≥ 0.3 s stops playback and starts listening. Live already does this.
- **Tests:** phantom lines are dropped while real short commands ("haan", "volume 30") pass; exact stop vs "stop the music" (that one is a task); the silent-cycle count; the barge-in threshold on recorded fixture audio.
- **Real path:** play 60 s of room or YouTube noise near the mic in conversation mode → 0 tasks started, and the phantom entries are logged. Then say "bas" → the mode ends.

---

### H21: Think harder / answer fast
**From Hermes:** `/reasoning` (effort level) and `/fast`.

- Phrases:
  - "dhyan se socho" / "soch ke batao" / "think carefully" → for this request only: Qwen runs **without** `/no_think` with a higher answer budget (profile `think_tokens`), or Gemini gets a higher thinking budget.
  - "jaldi batao" / "quick" → current behaviour (no-think, short).
- Auto-suggest: when a model-planned task fails twice, the retry offers "dhyan se soch ke dobara karun?"
- **Gate:** `eval_planner.py` on its hard subset with think on vs off, recording accuracy and seconds. If thinking is no better locally, the phrase routes to Gemini when cloud is on, and otherwise tells the owner it will be slow.
- **Tests:** the flag applies to one request only; the prompt differs only by the think switch; the timeout scales.
- **Real path:** one hard multi-step goal with and without "dhyan se socho"; record seconds and the verified result.

---

### H22: Second opinion ("pakka?")
**From Hermes:** `/review` (a reviewer sub-agent) and `/moa` (mixture of agents: several models, then a synthesis).

- Chutku's `ensemble.py` already reconciles *plans*. This slice adds an *answer* check:
  - "pakka?" / "double check karo" / "sure ho?" → the last factual or research answer is re-checked by the other brain (local ↔ Gemini) plus `web.read` of up to 2 sources.
  - The reply says "dono sahmat hain", or "yahan fark hai: …" with the sources.
- "sab se poocho: X" → MoA-lite: local and Gemini answer independently, a short synthesis is made, and disagreements are listed. Cloud only, with ≤ 2 Gemini calls.
- Never changes actions; it is R0 only.
- **Tests:** an agreement fixture; a disagreement fixture lists the differences; offline → uses only local and says so.
- **Real path:** ask a factual question with a known answer (e.g. a date from a fetched page) → "pakka?" → the verdict matches the page (independent check).

---

### H23: Blueprints + my shortcuts
**From Hermes:**
- `/blueprint` (automation templates with slots);
- `/suggestions` (automations proposed from what it sees, with accept/dismiss/catalog);
- user-defined quick commands.

- `chutku/blueprints.py`: a catalog of ready-made automations, each a template that creates **existing** objects (scheduled jobs, routines, reminders, board tasks) through their normal tools:
  - `morning-briefing time=08:00`;
  - `downloads-tidy every=week day=Sun` (uses `files.organize`, so it still asks);
  - `exam-countdown date=… subject=…`;
  - `battery-guard below=20`;
  - `weekly-backup` (H25);
  - `study-focus start=… minutes=…` (routine: focus mode + reminder);
  - `news-digest topics=… new-only=yes` (H8 continuity);
  - `weekly-insights` (H7);
  - `research-watch topic=… every=day` (H15 + H8).
- Dashboard "Automations" tab: catalog → fill the slots → preview the exact objects → Create. Phrases: "subah ka briefing set karo 8 baje", "kaun si automations hain".
- `suggest.py` can now suggest a blueprint when a habit is seen (e.g. the owner opens news at about 08:00 for 3 days → offer `news-digest`). It keeps its existing caps: 1 popup per hour, quiet 23:00–08:00, 3 dismissals stop that kind.
- **My shortcuts:** "jab main 'padhai time' bolun to focus mode on karo aur music band karo" → a named alias stored like a routine. It is validated the same way (every command must parse deterministically, max 4), and `check_phrases.py` includes it.
- **Tests:** each blueprint creates exactly the previewed objects; slot validation; a shortcut with an unparsable step is refused; the suggestion cap.
- **Real path:** create `morning-briefing time=<now+2min>` → it fires and is spoken. Independent check: the scheduled entry and the event log.

---

### H24: Standing goals
**From Hermes:** `/goal` (a standing goal across turns) and `/subgoal` (add a criterion).

- `chutku/goals.py` with `data/goals.json`: `[{id, text, criteria:[{kind, args, met_at}], due, created, status}]`.
- Criteria kinds are **checkable without a model:**
  - `file_exists`, `folder_count>=`;
  - `board_task_done` (H15), `reminder_done`;
  - `app_installed`;
  - `said_done` (the owner says "X ho gaya").
- "Is hafte DBMS ke 5 chapter ke notes banane hain, D:\Study\DBMS mein" → goal with `folder_count>=5`. "aur viva ki taiyari bhi" → a subgoal (`said_done`).
- Checks run after each related session (word overlap with the goal) and once a day in the night shift.
- The Today card shows "Goal: 3/5 ✓, 2 din bache". There is a gentle nudge at most once a day (suggest-style caps).
- Reached → a celebration line. Overdue → asks "aage badhaun ya hata dun?" (removing asks).
- **Tests:** each criterion kind; a subgoal append; due-date math; the nudge cap; Devanagari goal text.
- **Real path:** set a goal of 3 files in `D:\ChutkuScratch\goal`, create 2 → "2/3"; create the 3rd → "pura!". Independent check: `os.listdir`.

---

### H25: Backup & restore of Chutku's memory
**From Hermes:** `hermes backup` / `import` (zip of config + state) and `/snapshot create|restore|prune`.

- `chutku.cli backup` → `D:\ChutkuBackups\chutku-YYYYMMDD-HHMM.zip`, containing `data/` (mind, memory DB, conversations, experience, reflexes, lessons, skills, board, goals, scheduled, preferences) and a `manifest.json` with a SHA-256 for each file.
- **Excluded:** `models/`, caches, `embeddings.sqlite` (rebuildable), `history.db` (rebuildable), logs over 50 MB, `voiceprint.npy` (opt-in only), and **secrets** (Gemini key, Telegram token). The restore says to re-enter them.
- SQLite files are copied with the `sqlite3` backup API (consistent while running).
- Weekly via the night shift (blueprint `weekly-backup`). Keep the last 4 and archive older ones to the Recycle Bin (owner policy: deletes go to the Recycle Bin). Writes go to D: (C: is nearly full).
- **Restore:** "backup se wapas lao <date>" is R3 and **asks**:
  1. it first makes a pre-restore backup;
  2. it verifies the manifest hashes, aborting on any mismatch;
  3. it stops background work (H2 pause) during the restore.
- **Tests:** the manifest round-trip; a tampered file aborts the restore; secrets are never in the zip (scan the zip bytes for the key); the pre-restore backup exists; SQLite consistency while a write is in progress.
- **Real path:** back up → add a fact → restore → the fact is gone, the pre-restore zip has it. Independent check: diff the `mind.json` hashes.
- **Negative:** flip one byte in the zip → the restore refuses with nothing changed.

---

### H26: Doctor that can repair
**From Hermes:** `hermes doctor` with optional auto-repair; `cron doctor`.

- `doctor.py` is read-only today. Add `chutku.cli doctor --fix` and the phrase "khud ko theek karo". Each fix is **reversible or harmless, and logged**:
  - restart a dead brain service;
  - remove stale `execution.lock` / `guard.lock` (only when the owning PID is gone);
  - rebuild `history.db` / `embeddings.sqlite`;
  - re-register missing Task Scheduler tasks (night shift, reminders) with normal rights;
  - re-check the model manifest hashes (report only, never re-download);
  - re-pair a lost Telegram long poll.
- Anything else is reported, not fixed.
- The H8 `scheduled` doctor summary is included.
- **Tests:** a lock with a live PID is never removed; each fix is idempotent; read-only mode changes nothing (hash `data/` before and after).
- **Real path:** kill the llama-server, run "khud ko theek karo" → it is back, and a planner call works. Record seconds.

---

### H27: Learn on request ("ye seekh lo")
**From Hermes:** `/learn <what>` (distil a reusable skill from a source) and `/refine` (run the self-improvement review now).

- "ye seekh lo: <url | file path | 'jo abhi kiya'>" → a SKILL.md draft (H11) made from:
  - a web page (`web.read`, untrusted → the skill is marked `source: learned-web`, so its body is always untrusted);
  - a local document (`file.extract_text`);
  - the last session's steps.
- The draft goes to the H12 inbox. Nothing is saved directly.
- "jo seekha uspe socho" / `/refine` → runs H12 background review now on today's sessions.
- **Tests:** a web-learned skill is marked untrusted; the draft goes to the inbox only; an injection inside the page is caught by the H3 scan.
- **Real path:** "ye seekh lo: D:\ChutkuScratch\how-to-rename-photos.md" → the draft appears in the inbox with steps matching the doc's numbered list (independent check).

---

### H28: Learning journey view
**From Hermes:** `/journey` (also `/learning`, `/memory-graph`): a timeline of what the agent learned.

- A dashboard tab "Meri journey": one timeline of everything Chutku learned, with date, source session and current use count:
  - reflexes (S17), lessons (H10), skills (H11), facts and people (`mind`);
  - habits (`learning.refresh_habits`), voice-lock enrolment, LoRA adapters (S20b).
- Each item links to its evidence (session id) and has Disable/Archive.
- A simple graph view (inline SVG): people ↔ facts ↔ skills by shared words, with no external library.
- Weekly line in insights (H7): "is hafte 3 nayi cheezein seekhi".
- **Tests:** the timeline merges all sources in date order; disabled items show as disabled; there are no secrets in the view (tokens and voiceprint never listed).
- **Real path:** open the tab, and the item counts equal the independent counts from each store file.

---

### H29: Conversation tools + context gauge
**From Hermes:**
- `/undo` (drop the last exchange);
- `/title`, `/sessions search`, `/resume`;
- `/branch` (fork);
- `/context` (visual context-window breakdown).

Retry already exists ("phir se karo"), so it is not rebuilt.

- "ye baat bhool jao" / "last wali baat hata do" → the last exchange is marked `hidden=true` in `conversations.jsonl`. It is not deleted. `recall`, `history.search` (H4), `about_you`, background review (H12) and LoRA export (S20b) all skip hidden rows. Unhide with "wapas yaad karo".
- **Topics:** a session gets an auto title (the first 6 words). "kal wali DBMS baat aage badhao" → resume: the last 3 turns of that topic go to the planner as `CONTEXT.earlier` (uses H4 search).
- **Context gauge:** a dashboard "Brain view" panel shows, for the last request, the characters used by each context part (identity, tools, about_you, past_successes, lessons, skills, STEPS) against the profile budgets, with a stacked bar. This is the tool for tuning Qwen's 4K-ish working budget.
- **Tests:** hidden rows are skipped everywhere (one test per consumer); unhide; the gauge sums equal the prompt length.
- **Real path:** say a throwaway line → "ye baat bhool jao" → `history.search` for it finds nothing. Independent check: the row is still in the JSONL with `hidden`.

---

### H30: Phase 3b release: evidence, docs, reviews
This repeats S22 for the H slices.
- [ ] Regenerate the evidence after the last H code edit, and record each result in the ledger:
  - `scripts/verify_release.py --model --hardware`;
  - `scripts/check_stages.py --through all`;
  - `scripts/benchmark_agent.py` (≥ 45/45);
  - `scripts/eval_planner.py` (with H10 lessons on and off);
  - `scripts/eval_memory.py` (with the H4 FTS arm);
  - `scripts/live_check.py`.
- [ ] Docs:
  - `README.md` (tool and test counts, new features);
  - `docs/OWNER_GUIDE.md` (every H phrase and control: never rules, pause, inbox, lessons, skills, `@` refs, insights, board and research, Telegram and handoff, styles, busy mode, voices, think harder, pakka, blueprints and shortcuts, goals, backup, doctor, learn, journey, forget);
  - `docs/MARK_PARITY.md` (remote phone ✅ and the "Beyond Mark" rows);
  - `docs/ARCHITECTURE.md` module table;
  - `docs/SECURITY.md` (floors, scanner, pause, Telegram pairing and remote-approval limits);
  - `THIRD_PARTY_LICENSES.md` (every Hermes copy).
- [ ] Run `/code-review` and `/security-review` over `git diff 380d02f..HEAD`, fix the confirmed findings, and commit. Focus on:
  - H1 bypasses (obfuscation, encoding, interpreters);
  - H6 path escapes;
  - H14 taint propagation;
  - H16 auth, replay and token leaks;
  - H12 writes that skip the inbox;
  - H18 steers that try to remove an ask;
  - H25 secrets in backups and restore tampering;
  - H19 cloud calls in offline mode;
  - **P1–P4 remote:** Host / Tailscale-header / credential / PIN checks, Funnel kill, CSRF, approval replay, the never-remotely list, a stream without the PIN, and that the main dashboard is still `127.0.0.1`-only;
  - **P5–P9, when built:** arming only at the laptop, the step-up PIN for command windows, local-input takeover, the kill hotkey, text redaction in logs, and file-transfer path escapes.
- [ ] Final ledger entry: a table of H1–H30 with the evidence pointer for each.
- [ ] Record any helper-agent prompts in `docs/AGENT_PROMPTS.md`.

---

## 3. Not taken (each breaks a standing owner rule), with reasons
| Hermes feature | Why not | What we do instead |
|---|---|---|
| Smart (LLM) approvals | They auto-approve, which removes owner-mode asks (§0.3.4) | H1 floors only **add** denials; asks stay |
| `approvals.mode: off` / yolo | Removes asks | — |
| Docker, Modal, SSH, Daytona backends | Parked sandbox decision D5 | S1 "always confirm" stays |
| `execute_code` (scripts calling tools by RPC) | Runs model-written code automatically | H14 declarative for-each |
| MCP client, plugins, gateway/shell hooks, outbound webhooks | Load third-party code or send data out (⛔ plugin rule) | H11 imports text-only SKILL.md |
| Skills Hub / URL installs | Supply chain | Local file import with the H3 scan |
| OpenAI-compatible API server, ACP editor bridge | Opens a local port to PC control | Telegram outbound-only (H16) |
| Discord/Slack/Signal/Email gateways | One remote channel is enough; each adds attack surface | Telegram only; more later if asked |
| Image generation (FAL) | Paid cloud; not requested | Park; Gemini image model if asked |
| Honcho / Mem0 external memory | Sends personal memory to third parties | `mind.json` + H4 + H12 |
| Batch processing / RL environments | Research tooling | Trajectory export goes into S20b: add `chutku.cli export trajectories` (ShareGPT JSONL from verified untainted rows) |
| Credential pools for many providers | Only Gemini is used | H9 Gemini key pool |
| `/yolo`, `/approve always` / `session` | Remove or widen asks | S16 earned autonomy already handles trust, per tool and evidence-based |
| `/pet`, `/hatch` mascot, skins | Cosmetic (the avatar row in MARK_PARITY is already ⛔ cosmetic) | Park; revisit if the owner asks |
| Profiles (`/profile`, export/import of whole agents) | One owner, one Chutku | H25 backup covers moving her |
| `hermes peer` (bot-to-bot across machines) | Adds a network trust surface | — |
| `/worktree`, LSP, `/init`, `/plan`, `/diff` (coding agent tools) | Chutku is not a coding IDE agent; `code.build_project` covers her builder | Park |
| Discord voice channels, Telegram multi-topic sessions | Not used by the owner | — |
| Nous Portal tool gateway, billing commands | A third-party paid service | — |

Record these under "Parked" in `MASTER_PLAN.md`.

---

## 4. Files (representative)
**New modules**
- `chutku/policy/hardline.py`, `pause.py`, `scan.py`, `history_index.py`, `insights.py`, `brain_errors.py`, `lessons.py`, `skills.py`, `review.py`, `gateway/telegram.py`.
- Remote: `chutku/remote/server.py` (phone API), `remote/pairing.py` (QR, device credentials, PIN), `remote/tailscale.py` (status, serve, Funnel check), `remote/stream.py` (frames), and later `remote/control.py` (SendInput, DPI mapping, rule checks, P5–P7), `remote/files.py` (P8), `remote/point.py` (P9); `chutku/web/phone/` (PWA). Tests: `test_remote_access.py`, `test_remote_app.py`, `test_remote_voice.py`, `test_remote_stream.py`, and later `test_remote_control.py`, `test_remote_keyboard.py`, `test_remote_clipboard.py`, `test_remote_files.py`, `test_point_and_ask.py`.
- Also: `board.py`, `busy.py`, `voice/edge_voice.py`, `blueprints.py`, `goals.py`, `backup.py`; the H22 answer check goes in `ensemble.py`, H26 in `doctor.py`, and H29 in `recall.py`, `history_index.py` and `dashboard.py`.
- The curator goes in `nightshift.py`, `@`-refs in `dashboard.py` with a helper `refs.py`, and for-each in `runtime.py` / `agent_execution.py`.

**New tests:** `tests/test_hardline.py`, `test_pause.py`, `test_scan.py`, `test_history_index.py`, `test_steps_summary.py`, `test_refs.py`, `test_insights.py`, `test_scheduled_plus.py`, `test_brain_errors.py`, `test_lessons.py`, `test_skills.py`, `test_review.py`, `test_curator.py`, `test_for_each.py`, `test_board.py`, `test_delegate.py`, `test_telegram_gateway.py`, `test_styles.py`, `test_busy.py`, `test_edge_voice.py`, `test_voice_polish.py`, `test_think.py`, `test_second_opinion.py`, `test_blueprints.py`, `test_goals.py`, `test_backup.py`, `test_doctor_fix.py`, `test_learn.py`, `test_journey.py`, `test_forget.py`.

**Edited**
- `policy/kernel.py` (floors, `origin`), `agent_loop.py` (context: lessons, skills, previous_run; `_steps_view`; for-each proposals), `runtime.py`, `learning.py`, `mind.py`, `tools/mind_tools.py`, `notes.py`, `reflex.py`, `recall.py`, `scheduled.py`, `nightshift.py`, `cloud_planner.py`, `brain.py`, `gemini.py`, `profiles.py`, `persona.py`, `quick_intents.py` + `intents/lexicon.py`, `dashboard.py` + `web/` (inbox, insights, lessons, pause badge, phone pairing), `tray.py`, `hud.py`, `cli.py`, `tools/registry.py` registrations.
- Docs: `docs/MASTER_PLAN.md` (Phase 3b + Parked), `docs/OWNER_GUIDE.md`, `docs/MARK_PARITY.md` (Beyond Mark rows; remote phone ✅ after H16), `docs/ARCHITECTURE.md`, `docs/SECURITY.md` (floors, scanner, pause, Telegram), `THIRD_PARTY_LICENSES.md`, `IMPLEMENTATION_STATUS.md`, `docs/AGENT_PROMPTS.md`.

---

## 5. Owner inputs needed (everything else is decided)
- **P1 Tailscale:** install it on the laptop and the phone and sign in with the same account (Chutku shows the steps). Choose the phone PIN at pairing. For lid-closed use, set "When I close the lid: Do nothing (plugged in)" yourself. For the P1–P4 real paths, test with the phone on mobile data.
- **P5–P9:** say "phone control banao" when you want full control built. It is fully specified but not in the build order.
0. **H19 Edge voice:** your choice in the blind listening test (SAPI / Kokoro / Edge Swara). Nothing switches without it.
1. **Telegram bot token** from BotFather (H16). H16 is built and tested with fakes; the real path waits for the token.
2. **Extra Gemini keys** (optional, H9 pool). It works with one.
3. **Default for the review model** (H12): "local when idle" is planned. Say if you want Gemini.
4. Your first "never" rules (H1), e.g. "D:\Exams ko kabhi mat chhoona". These are optional.

---

## 6. Verification (per slice and at the end)
- Full suite: `.venv\Scripts\python.exe -m unittest discover -s tests`, all green after every slice.
- Each slice's **Real path** through `/api/chat` on the running dashboard, with seconds and an independent check, plus its **Negative**. Both go in `IMPLEMENTATION_STATUS.md` (`### 2026-MM-DD: H<n> <title>`: cause → fix → tests → evidence → limits).
- Gates: H4 (`eval_memory.py`), H10 (`eval_planner.py`), H14 (planning rounds and seconds), H21 (`eval_planner.py` think on/off), H19 (owner listening test). A missed gate ships the feature off by default, with the numbers recorded.
- `scripts/check_phrases.py` stays all-instant. `scripts/benchmark_agent.py` ≥ 45/45 at H30. The S15 injection corpus still gives zero unapproved R1+.
- H30 `/code-review` + `/security-review` cover `git diff 380d02f..HEAD`, with special attention on H1 bypasses, H6 path escapes, H14 taint propagation and H16 auth.

---

## Appendix A: Hermes facts gathered (2026-10-06/07, README, docs and source)
- **Project:**
  - Nous Research, MIT, Python.
  - Top level: `agent/`, `tools/`, `skills/`, `gateway/`, `plugins/`, `optional-mcps/`, `providers/`, `hermes_cli/`, `ui-tui/`, `web/`, `evals/`, `tests/`, `hermes_state_*.py`.
  - `agent/` includes `background_review.py`, `curator.py`, `curator_backup.py`, `estop.py`, `battery.py`, `error_classifier.py`, `credential_pool*.py`, `context_compressor*.py`, `context_references.py`, `conversation_compression*.py`, `empty_response_guard.py`, `deadline.py`, `verify/`.
  - `tools/` includes `approval*.py` (approval, context, detection, floors, smart, prompt, human_wait, gateway_wait), `checkpoint_manager.py`, `code_execution_*.py`, `cronjob_*.py` (+ `cronjob_prompt_scan.py`), `delegate_tool*.py`, `computer_use_tool.py`, `browser_*`, `clarify_tool.py`, `file_operations*.py`, `wakewords/`.
  - Runs commands locally or on Docker, SSH, Singularity, Modal, Daytona or Vercel Sandbox. 40+ tools in toggleable toolsets. Providers: Nous Portal, OpenRouter, OpenAI, custom. It needs a big model; an RTX 3050 4 GB is below its minimum.
- **Skills:**
  - Layout: `~/.hermes/skills/<category>/<name>/SKILL.md`, plus `references/`, `templates/`, `scripts/`, `examples/`, `assets/`.
  - Frontmatter: `name`, `description` ≤ 60, `version`, `platforms`, and `metadata.hermes` with tags, category, `requires_toolsets`/`fallback_for_toolsets`/`requires_tools`/`fallback_for_tools`, and config keys.
  - Body: When to Use / Procedure / Pitfalls / Verification.
  - Disclosure levels: L0 `skills_list` (~3k tokens), L1 `skill_view(name)`, L2 `skill_view(name, path)`.
  - Created after non-trivial repeatable workflows, after errors with a found fix, and after user corrections. `skill_manage`: create / patch (old_string→new_string, preferred) / delete / write_file / remove_file. `skills.write_approval` stages writes.
  - Hub trust levels: builtin → official → trusted → community, with a scanner for exfiltration, injection, destructive commands and supply-chain signals.
- **Memory:**
  - `MEMORY.md` (2,200 chars) and `USER.md` (1,375 chars), a frozen snapshot per session (keeps the prefix cache).
  - Add/replace/remove by substring; no read action. Overflow → an error, and the agent consolidates. Usage meter in the header.
  - Writes are scanned for injection, exfiltration and invisible Unicode; duplicates are refused.
  - Settings: `write_approval`, char limits, `auxiliary.background_review`.
  - External memory plugins: OpenViking, Mem0, Holographic, RetainDB, ByteRover, Honcho, Hindsight.
- **Session search:** `~/.hermes/state.db`, SQLite FTS5, ~20 ms, no LLM.
- **Background review:**
  - A daemon fork after turns, on memory and skill nudge intervals. Scopes: memory-only, skills-only (default: "most sessions produce at least one skill update"), or combined.
  - Read-before-write is enforced. It never edits curator-managed, bundled, pinned or user-owned skills.
  - It refuses environment-dependent failures, negative claims about tools, session transients, one-off narratives and unresolved failures.
  - Limits: max 16 iterations; input ≤ 75% of context (cap 600k); tools whitelisted to skill_manage, memory and read-only; dangerous commands auto-denied; 2 s cancel.
- **Curator:**
  - Active → stale (`stale_after_days` 14) → archived (`archive_after_days` 30). Never deletes; `.archive/` can be restored.
  - Runs when idle ≥ 2 h and the interval (7 days) has passed; the first run seeds and defers.
  - Phase 1 is deterministic transitions. Pinned and cron-referenced skills are protected; use reactivates.
  - Phase 2 is an optional LLM consolidation into umbrellas, with a whole-tree backup and a ledger whose actor is "curator". Dry-run mode.
  - Writes `REPORT.md` + `run.json`.
- **Approvals:**
  - Floors (never prompt): hardline, sudo-stdin guard, user `approvals.deny` fnmatch rules. These apply even in yolo or mode=off. Then the permanent allowlist, then prompts.
  - Modes: smart (an LLM rates risk), manual, off.
  - **Hardline:** `rm -r` of `/` or system dirs or `~`; `mkfs`; `dd` or `>` to block devices; `kill -1`; shutdown/reboot/halt/poweroff/init 0/6/systemctl poweroff; fork bomb.
  - **Dangerous** (approvable): `rm -r`, `find -delete`, `chmod 777`, `chown -R root`.
  - **Windows dangerous:** `cmd /c del/erase/rd/rmdir`, `Remove-Item -Recurse/-Force`, `taskkill /F`, `Stop-Process -Force`, `Format-Volume`, `Clear-Disk`, `diskpart`, `vssadmin delete shadows`, `wbadmin delete`, `bcdedit /set`, `reg delete`, `icacls /reset`.
  - Also: pipe-to-shell, `base64 -d | bash`, `eval $(curl…)`; package uninstall; `git reset --hard`, push force, `clean -f`, `branch -D`; service stop; writes to `~/.ssh`, rc files, `/etc`.
  - **Normalization:** ANSI strip, NFKC, null removal, line-continuation join, home-path fold, backslash-escape removal, `''`/`""` removal, `$IFS` substitution, lowercase except flags. `_REINTERPRETED_ARGUMENT_RE` covers `-c`/`-e`/`--command`/`--eval`.
- **ESTOP:** the sentinel `$HERMES_HOME/ESTOP`; `hermes pause`/`resume`. It halts new cron, kanban and gateway work, while in-flight work continues. Uncached stat. A corrupt or empty file, or a stat error, counts as engaged.
- **Security:**
  - Docker: drop all capabilities except DAC_OVERRIDE, CHOWN, FOWNER; 256 PIDs; `/tmp` 512 MB nosuid; no-new-privileges. Approvals are skipped inside containers.
  - Context files are scanned for "ignore previous", hidden HTML comments, exfiltration and invisible Unicode. Project files are blocked; SOUL.md is logged but loaded.
  - Gateway authorization: allow-all → DM pairing → platform allowlists → global → deny. Pairing: 8-character code, 1 h TTL, 3 pending, 5-attempt lockout, 1 request per user per 10 min.
- **Cron:**
  - Created by natural language or cron expressions with `cronjob_manage`. Each run is an isolated fresh session; the scheduler ticks every 60 s, with a file lock.
  - Skills can be attached.
  - Delivery: origin / local / platforms / all.
  - Safety: pre-dispatch validation, prompt scan, toolset control, a run ledger (completed/failed/unknown).
  - `no_agent` script jobs: empty stdout = silent tick.
  - `context_from` chaining, `continuity`, `wakeAgent` pre-run gates, `hermes pause`.
  - `cron doctor`; incidents are deduped per unique error with a cooldown.
- **Delegation:**
  - `delegate_task(goal, context, output_schema, images≤8, role leaf|orchestrator, group)`. Fresh context; inherits the toolsets and context files.
  - Children are blocked from `delegate_task` (leaf), `clarify`, `memory`, `send_message`, `cronjob`.
  - Concurrency 10, depth 1, one-shot max 2. No wall-clock timeout by default (opt-in, floor 30 s).
  - Stall monitor: 450 s idle / 1200 s in-tool + 120 s grace. One-line failure notices.
- **Code execution:** a Python script calls tools by RPC over a Unix socket (`web_search`, `web_extract`, `read_file`, `write_file`, `search_files`, `patch`, `terminal`). Only `print()` output returns. Environment secrets are stripped. Limits: 5 min, 50 KB stdout, 50 tool calls. No recursion, delegation or MCP.
- **Checkpoints:** a shared shadow git store, taken before `write_file`/`patch` and destructive terminal commands, at most one per directory per turn. Skips > 10 MB, > 50k files, `/`, `$HOME`. Keeps 20 per project, 500 MB, 7-day prune. `/rollback` list / N / N --all / diff / file. Keeps the user's hand edits by default.
- **Hooks:**
  - gateway hooks (`HOOK.yaml` + `handler.py`);
  - plugin hooks `pre_tool_call` (block/modify), `post_tool_call`, `pre_llm_call`, `post_llm_call`;
  - shell hooks;
  - outbound signed webhooks.
  - Bounded hooks fail closed on timeout.
- **Fallback:** credential pools (rotation) → primary model fallback → auxiliary-task chains. Fallback triggers: 429/5xx after retries; 401/403/404 immediately; an empty or invalid response. Per-turn reset. Rate-limit reset times are honoured.
- **Context references:**
  - Types: `@file:path[:a-b]`, `@folder:` (≤ 200), `@diff`, `@staged`, `@git:N` (≤ 10), `@url:`.
  - Size: warn at 25% of context, block at 50%.
  - Blocks `~/.ssh`, `~/.aws`, `~/.kube`, `.bashrc`, `.netrc`, `.npmrc`; traversal; binaries.
  - CLI only.
- **Other features:** voice mode, wake word, browser (Browserbase / Browser Use / CDP), vision paste, image generation (FAL, 11 models), TTS (10 providers), MCP (stdio/HTTP), provider routing, prompt caching, memory providers, API server (OpenAI-compatible), ACP (VS Code/Zed/JetBrains), personality/SOUL.md, skins, plugins, batch processing, trajectory generation for training.

- **Full slash-command list (2026-10-07):**
  - Sessions: `/new`, `/retry`, `/undo`, `/title`, `/compress`, `/rollback`, `/snapshot`, `/stop`, `/resume`, `/sessions`, `/branch`/`/fork`, `/handoff <platform>`.
  - While a task runs: `/queue`, `/steer` (inject after the next tool call), `/btw` (side question).
  - Goals and repeats: `/goal`, `/subgoal`, `/heartbeat`, `/loop`/`/proactive`.
  - Learning: `/refine` (self-review now), `/review` (reviewer sub-agent), `/learn <source>`, `/journey`/`/learning`/`/memory-graph`, `/curator`, `/memory pending|approve|reject`, `/skills pending|approve|reject|diff`.
  - Other agents: `/moa` (mixture of agents), `/bg`, `/agents`.
  - Automations: `/suggestions`, `/blueprint`, `/cron`, `/kanban`.
  - Settings: `/context` (gauge), `/model`, `/personality`, `/fast`, `/reasoning`, `/voice`, `/wake`, `/battery`, `/busy queue|steer|interrupt`, `/yolo`, `/approvals`.
  - Info and input: `/insights`, `/usage`, `/paste` (clipboard image), `/copy`, `/image`, `/pet`/`/hatch`.
  - Plus `/plan`, `/init`, `/worktree`, `/diff` (coding) and `/export`/`/import` (profiles).
  - CLI extras: `hermes -z` (one-shot), `doctor` (auto-repair), `backup`/`import`, `kanban`, `sessions`, `peer` (bot-to-bot), `lsp`.
- **Kanban:**
  - `~/.hermes/kanban.db`, statuses triage/todo/ready/running/blocked/review/done/archived.
  - The dispatcher promotes tasks when their parents are done, spawns workers as OS processes with `HERMES_KANBAN_TASK`, watches heartbeats, and retries with a circuit breaker.
  - Workers use `kanban_show`/`complete`/`request_review`/`block`. The review state waits for a human or AI.
- **Voice mode:**
  - Ctrl+B record. Telegram/Discord voice replies; Discord voice channels.
  - STT: local faster-whisper, Groq or OpenAI. TTS: Edge TTS (free, no key) up to ElevenLabs/OpenAI, streamed sentence by sentence.
  - Barge-in during generation and over replies, calibrated against room silence.
  - End of speech: RMS > 200 for ≥ 0.3 s, then 3.0 s of silence.
  - A hallucination filter for phantom Whisper text.
  - An exact "stop" utterance ends the mode; 3 silent cycles auto-end.

## Appendix B: Chutku facts this plan relies on (checked 2026-10-06/07)
- Git: S19 (`b8ae087`), S20+S21 (`1365f25`), the docs commit `7767fc3` (AGENT_PROMPTS rule) and **S22 release `380d02f` (2026-10-07)** are all done. S22 also changed things: review fixes, voice learning, an idle-based night shift, and regenerated evidence. Re-read `nightshift.py` and the touched modules before H8, H12 and H13, because the line references in this appendix were taken before S22.
- Housekeeping: S22's checkboxes in `MASTER_PLAN.md` (lines ~782–796) are still `[ ]` although its heading says done. Tick them in Step 0.
- Code-running tools: `code.run_python` (`chutku/tools/documents.py:512`) and process start (`chutku/tools/processes.py:179`).
- Planner context:
  - `CONTEXT.about_you` is trimmed by `recall._fit` (Qwen `about_you_chars` 600).
  - `CONTEXT.past_successes` comes from `experience.similar` (Jaccard ≥ 0.34; Qwen 2).
  - STEPS budget: `profile.steps_chars` (Qwen 6000, default 60000) in `agent_loop._steps_view` (~line 708).
- `recall.py` has word-overlap only (`earlier`, `talked_about`, `about_you`, `_fit`). There is no FTS5 in `chutku/`. The S12 embeddings (`memory_index.py`, `data/embeddings.sqlite`) did not meet their gate.
- S15 strips instruction-like lines in `agent_loop._observation`. There is no invisible-Unicode scan anywhere.
- S17 `reflex.py` / `data/reflexes.json`: risk ≤ 1 only; no message, delete, code or modify tools.
- `nightshift.py` jobs: `_skills` (reflex compile), `_reliability`, `regression_replay`, `maintenance`, `lora_readiness`; `on_ac_power`, `wait_for_idle`, `morning_line`, `install`.
- `scheduled.py`: `add`, `cancel`, `active`, `take_due`, `note_run`, `watch` (tick thread), `_announce`, `parse`.
- Stop and kill exist in `control_intent.py`, `guard.py`, `tray.py`, `hud.py`. There is no persistent pause sentinel.
- There is no Telegram gateway, MCP client, sub-agent, insights module or `@` references in `chutku/`.
- MARK_PARITY ⛔ rows: "Remote phone dashboard (needs pairing + TLS design)" → H16. "Drop-in Python plugins" → stays ⛔.
- `data/`: `mind.json`, `memory.db`, `embeddings.sqlite`, `experience.jsonl`, `conversations.jsonl`, `actions.log.jsonl`, `reflexes.json`, `scheduled.json`, `preferences.json`, `ledger.db`, `gemini-quota.json`, `heard.jsonl`, `rewound.json`.

## Step 0 of implementation
1. Copy this file word for word to `docs/HERMES_PLAN.md`.
2. Add Phase 3b (H1–H3, P1–P4, H4–H30 with checkboxes, in the §1 order; P5–P9 listed as "planned, build on owner's word") after S22 in `docs/MASTER_PLAN.md`. Add the "Not taken" rows to Parked, tick the S22 boxes, and change the MARK_PARITY "Remote phone dashboard" row from ⛔ to "planned: P1–P4 (Tailscale + pairing + PIN), P5–P9 full control".
3. Commit as `Docs: Hermes-inspired plan (Phase 3b)`.
4. Start at H1.
