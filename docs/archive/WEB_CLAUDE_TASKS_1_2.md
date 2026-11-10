# Instructions for the web (cloud) Claude Code session: Chutku 1.2

Written 2026-11-08 on the owner's PC for the cloud session. Work on branch **`claude/chutku-1.2`** (from `main`).
The PC session merges it and does the Windows live checks, the UAC prompts, the practice folder, the training runs
with the real models and the release. Read this whole file first, then `AGENTS.md`.

## 0. Where things stand
- Chutku **1.1.0 is published**: one `Chutku-Setup-for-Windows.exe` on `sidvashisth2005/Chutku-releases`, the in-app
  update popup (`chutku/updates.py`), the required guided setup, and the "Tiranga" design (`chutku/web/theme.css`).
  `chutku.localhost` opens the dashboard (`chutku/alias.py`).
- **Tests:** the full Windows suite is 1,670+ OK, and `scripts/check_phrases.py` is 163/163.
- **The owner's new standing rule (2026-11-08)**, the heart of this round:

  > Chutku does whatever the user asks on their PC. A user who is refused does it by hand anyway, so Chutku does it
  > for them.
  > - **Refused only:** deleting or changing Windows/system files, boot/EFI, drivers, security settings, or
  >   anything that can corrupt Windows.
  > - **Asks once (Yes/No), only for risky or first-time steps:** deleting the user's own files (they go to the
  >   Recycle Bin), power, killing programs, messages to new people, overwriting files, and admin tasks (Windows'
  >   own UAC prompt).
  > - Once a step worked for the same exact request, it no longer asks, and it remembers how.

  The owner's further asks: very rigorous training (reinforcement-style learning); treat the user like a toddler who
  learns Chutku by using it, so everything explains itself; and a normal restart must not leave Chutku paused.

## 1. Rules (from AGENTS.md and the owner; do not skip)
- **Delivery gate for every task:**
  - tests;
  - a real command path where Linux allows;
  - a negative case for every safety boundary;
  - an `IMPLEMENTATION_STATUS.md` entry with evidence.

  Write what you could not verify on Linux as "**needs the Windows check**", never as verified.
- **Commits:** `WA<n>: summary`, with **no Co-Authored-By line, ever**. Small commits; push the branch after each
  task.
- **Line endings:** keep CRLF files CRLF. Check `git diff --stat` for whole-file rewrites before committing.
- **Never break a working feature or default-off a working mode.** The owner's PC (a git checkout at
  `D:\Project\Chutku` with `data/` inside it) must keep working exactly as now.
- **Safety still holds:**
  - Text from web pages, messages or files can never authorise an action (taint rules stay).
  - Laptop-only steps stay laptop-only for phone and Telegram.
  - Keys never go into files or logs.
- **Tests never start real models, send messages, touch the network or run anything elevated** (use fakes).
- **Engineering principles** (`.claude/skills/karpathy-guidelines`, ponytail): minimum code, surgical changes,
  stdlib first; a known limit gets a `# shortcut:` comment.
- **Agent prompts:** record every helper-agent prompt verbatim in `docs/AGENT_PROMPTS.md`.

## 2. Hardening rules (apply in every task)
1. **PowerShell can hide damage, so a text check is only the first filter.**
   - Raw `system.powershell` always runs **non-admin**, so Windows itself protects system files.
   - **Elevation is only for structured tools** (machine-wide winget install/uninstall, service start/stop/startup
     type, named Windows settings, a firewall *allow* rule for an app). Their arguments are validated and the
     elevated command line is built by code.
   - Free-form text never runs elevated.
2. **Undo for system changes.**
   - Every settings, registry, startup and service change journals the previous value in
     `data/system_journal.jsonl`.
   - "undo last change" / "wo wapas karo" restores it.
   - Installs are undone by uninstalling.
3. **Ask-once memory has limits.**
   - Keyed on the exact tool, normalised arguments and target. Granted only by the owner's own click at the laptop,
     after the step verified.
   - Never applied after outside content (taint), or from phone or Telegram for laptop-only steps, or for deletes,
     elevation or damage.
   - It expires after 90 days unused, and Settings can forget each entry.
4. **"New" means a first time:** a tool and target with no verified run in the reliability ledger (n = 0). Reads and
   opens never count as new.
5. **Practice safety.** The live practice runtime:
   - is granted `D:\ChutkuPractice` only, plus allowlisted apps (Notepad, Calculator, Paint, Explorer in that
     folder); the network is read-only;
   - never sends messages, emails or posts, never elevates, never touches power, and never deletes outside the
     folder;
   - stops within 1 s when a person uses the mouse or keyboard (`chutku/remote/control.LocalInput`);
   - has a cloud budget of at most 300 calls a night.
6. **Real learning, not memorising.**
   - The task bank has a fixed 80/20 train/held-out split by hash.
   - Reflexes, lessons and fine-tune data never come from held-out items. Success rates are reported on held-out.
7. **One planner contract.**
   - The ladder is: a dedicated tool, then a desktop or browser UI flow (agent-desktop / agent-browser), then
     non-admin PowerShell.
   - "I can't" only for damage, always saying why plus what the user can do instead.
8. **Toddler-easy by default.**
   - The menu starts in a Simple view: Home, Activity, Phone, Settings, plus "What can I say?". The trust tabs sit
     under "More".
   - Each approval card says what will happen and whether it can be undone, with Yes / No / Yes-always.

## 3. Tasks, in this order (WA6, WA1 and WA2 first: the PC starts live checks as soon as they land)

### WA6: A clean restart that does not leave Chutku paused
Why: `chutku.cli control stop` is recorded by the guard as `emergency_stop` (`chutku/guard.py`, around lines
196–240, `_marker_says_quit`), which pauses actions. Every restart therefore came back paused (seen twice live on
2026-11-08).
- `chutku.cli control quit` writes `quit` to the guard's stop marker (`guard.stop`), so the guard records
  `owner_quit` and does not pause.
- A "Restart Chutku" button (Settings → About, and the tray menu) plus the phrase "chutku restart karo": quit, then
  start again. The launcher already knows how to start: `installer/launcher.cs` and `Start-Chutku.cmd`.
- `Stop-Chutku.cmd` / `control stop` stay the **emergency stop**, which pauses on purpose. Say so in its help text.
- Tests: quit leaves `actions_paused` false. **Negative:** an emergency stop still pauses.

### WA1: Policy, "never refuse" (`chutku/policy/kernel.py`, `never_rules.py`, `chutku/core/paths.py`, `chutku/runtime.py`)
- Replace the blanket "never modify" protected zones (`paths.protected_zones`) with a **damage list**, always
  refused, in `paths.system_damage(path, op)`:
  - deleting, renaming or overwriting under `%SystemRoot%`, `System32`, `WinSxS`, drivers, boot/EFI;
  - deleting an app folder under Program Files or ProgramData directly (uninstalling goes through `apps.uninstall`);
  - registry `HKLM\SYSTEM`, `BCD` and security policy;
  - disabling Defender or the firewall;
  - formatting or partitioning a drive.
- Writes that are not damage become possible with one confirmation the first time: app settings in AppData or
  ProgramData, per-user installs, the `HKCU` registry.
- **Ask-once memory** (`chutku/approval_memory.py`, `data/approval_memory.json`), with the limits in Hardening 3 and
  4. It plugs in where `earned_file_change` and trusted mode decide today. Settings gets a section "Things you let
  Chutku do without asking" with a Forget button per entry.
- `system.powershell` and `code.run_python`:
  - a damage pattern is refused (`Remove-Item` on system paths, `format`, `diskpart`, `bcdedit`,
    `reg delete HKLM`, `Set-MpPreference -Disable*`, `netsh advfirewall set * state off`, `takeown` on system
    paths);
  - otherwise they confirm the first time for the same command text, and ask-once applies after.
- **Planner** (`chutku/agent_loop.py` around line 1577, `prompts/`, `cloud_planner`): the ladder in Hardening 7. Add
  worked examples of the PowerShell and UI fallbacks to the prompt.
- Update `docs/SECURITY.md`, `chutku/tools/assistant.py` (the capabilities text), `docs/USER_GUIDE.md` §7 and
  `docs/OWNER_GUIDE.md` §6. Update the `tests/test_docs_truth.py` counts.
- Tests:
  - every damage case DENY, the negative cases;
  - first time asks, the same key then ALLOWs; a different target asks again;
  - a tainted step still asks; deletes always ask once;
  - phone or Telegram plus a laptop-only step still waits for the laptop.

### WA2: New system tools (no admin first, elevation through a broker)
- `apps.install` / `apps.uninstall` through winget: `--scope user` first; `--scope machine` goes through `elevate`.
- `settings.set`: named, common Windows settings (dark mode, night light, default browser page, power plan, display
  scale, Bluetooth, Wi-Fi on/off, notifications). Each knows how to read its current value first, for the journal.
- `registry.set_user` (HKCU only, typed values), `services.list` / `services.set` (elevated),
  `startup.list` / `startup.toggle` (HKCU Run).
- `chutku/elevate.py`: run ONE command line built by a structured tool through `Start-Process -Verb RunAs`. The
  damage check runs first, the user sees Windows' own prompt, and the output comes back through a temp file. Unit
  tests use a fake launcher.
- `data/system_journal.jsonl` plus `system.undo_last` (Hardening 2).
- Add phrase cases to `scripts/check_phrases.py` (Hinglish and English) for each new tool.

### WA3: The task bank, "what a user might say" (`tests/task_bank/*.jsonl`, about 1,500 lines)
- **Categories:**
  - apps and windows; files and folders; web and search; media; Windows settings; power; network; installs;
  - messages; reminders and schedules; memory; screen and UI; documents; developer tasks;
  - **multi-step chains** (2 to 8 steps);
  - vague or lazy phrasings, typos, voice-style rewrites;
  - Hindi (Devanagari), Hinglish and English.
- Each line: `{"id", "say", "lang", "category", "expect": {"tools": [...]} | {"plan_shape": [...]} |
  {"refuse": "damage"}, "risk", "needs": ["apps"], "multi_step": bool, "split": "train" | "heldout"}`.
- About 10% are damage requests that must be refused.
- `scripts/make_task_bank.py` (templates × slots, deterministic) plus a hand-written file of hard cases. No cloud
  needed.

### WA4: The training harness, rewarded practice (`chutku/practice/`)
- `practice.run(bank, mode, planner)`:
  - `plan` mode: the planner proposes and the result is scored against `expect`. Fakes, so it runs on Linux and in
    CI; a small CI job runs 100 items.
  - `live` mode (PC only): the practice runtime in Hardening 5; the result is checked by the tool's success
    predicate.
- **Reward:** +1 verified success; 0 asked when it shouldn't; −1 wrong or failed; −2 a damage request not refused.
  Log to `data/practice/YYYY-MM-DD.jsonl`.
- **Learning (rejection-sampling RL: learn only from verified wins):**
  1. Verified train successes become reflex/skill candidates and `past_successes` few-shot examples.
  2. Train failures become `lessons.json` entries with the corrected plan.
  3. Best-of-N plans for failed train items (the PC supplies the planners) become `data/finetune/*.jsonl` for the
     weekly LoRA.
- `scripts/practice_report.py`: success per category on held-out, the trend over time, and the worst 20 items.
- `nightshift` hook: N items a night, with live mode off by default; the PC turns it on.

### WA5: Toddler-easy UI (`chutku/web/app.js`, `index.html`, `theme.css`; keep the 1.1 Tiranga design)
- **Simple view** (Hardening 8). A "More" item shows the rest; remember the choice in `localStorage` with
  try/catch.
- **"What can I say?"** page: category cards with tap-to-try examples taken from the task bank's train split. It is
  searchable and in Hinglish and English.
- **First-week coach:** one rotating "Try saying…" tip on Home; it disappears once that kind of task has been done.
- **Every error says what to do next**, with one button: Try again, Open Settings, Show me how.
- **Approval cards in plain words**, with Yes / No / Yes-always. Yes-always feeds the ask-once memory.
- A clear empty state on every tab.
- Keep every existing id. The PC's Playwright scripts (onboarding, every-button) must still pass. List any id you
  had to change.

## 4. What to hand back (your final message, for the owner to bring to the PC session)
- The branch name, and every commit with its one-line summary.
- **Per task:** what was verified on Linux, what on the `windows-latest` runner, and what still needs the owner's
  PC (UAC prompts, live installs, the practice folder, real models).
- The new tools, phrases and settings, so the PC can run its live checks straight away.
- Open questions for the owner.
