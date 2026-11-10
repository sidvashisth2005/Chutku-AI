# Instructions for the web (cloud) Claude Code session: Chutku 1.0

Written 2026-11-07 on the owner's PC for the cloud session to carry out. Work on a branch; the PC session merges it
and runs the Windows live checks afterwards. Read this whole file first, then `AGENTS.md`.

## 0. Where things stand (verified on the PC, commit after this file)
- **Tests:** the full Windows suite passes (1,540+ tests); `scripts/check_phrases.py` is 159/159.
- **Done and live-verified on the PC:**
  - D1: background app control. `chutku/tools/desktop.py` drives the agent-desktop CLI.
  - Z6/D2: the signed-in browser. `chutku/tools/signed_in_browser.py` drives the agent-browser CLI, through the
    tools `browser.open`, `browser.look`, `browser.act`, `browser.type` and `browser.act_risky`.
- **P1 security baseline, done:**
  - **Relay:**
    - loopback by default;
    - plain HTTP is refused off loopback unless `--tls-cert`, `--behind-proxy` or `--home-network` is given;
    - `X-Forwarded-For` is trusted only from a local proxy.
  - **System programs:** called by their absolute System32 path (`chutku.health.system_exe`).
  - **Telegram:** no error carries the token. Test: `tests/test_telegram_token_leak.py`.
  - **Dashboard:** the session token is no longer printed to stdout or the guard log.
  - **Dependencies:** `requirements.lock` is hashed (`scripts/hash_lock.py`). CI and `install.ps1` use
    `--require-hashes`. A clean venv install succeeded.
  - **Security review, finding 1 (HIGH, private signed-in pages):** fixed and live re-checked. Findings 2 and 3 are
    task W1 below.
- **The owner's decisions for 1.0:**
  - The code repo `sidvashisth2005/Chutku-AI` stays **private**. Only built app packages are published, to a
    separate **public** repo `sidvashisth2005/Chutku-releases` (GitHub Releases, SHA-256 checked).
  - The installer offers the offline AI models. Cloud brain is the default; offline packs are optional.
  - The installer is **unsigned** for now (SmartScreen "Run anyway"), but signing-ready.
  - The user must never see Python, consoles, git or the code: it installs and runs like any app.

## 1. Rules (from AGENTS.md and the owner; do not skip)
- **Delivery gate for every task:**
  - tests;
  - a real command path;
  - a negative case for safety boundaries;
  - an `IMPLEMENTATION_STATUS.md` entry with evidence;
  - tick the box in `docs/MASTER_PLAN.md`.

  Write what you could not verify on Linux as "needs the Windows check", never as verified.
- **Commits:** `<ID>: summary`, with **no Co-Authored-By line, ever**. Small commits; push your branch after each
  task.
- **Line endings:** keep CRLF files CRLF. Check `git diff --stat` for whole-file rewrites before committing.
- **Never break a working feature or default-off a working mode.** Gemini Live stays the default voice path. The owner's
  PC (a git checkout at `D:\Project\Chutku` with `data/` inside it) must keep working exactly as now.
- **Never weaken a safety rule.** Very risky steps, deletes and code always ask. Evolve may never edit safety code.
  Keys and tokens never go into files or logs.
- **Tests never start real models, send messages or touch the network** (use fakes).
- **Agent prompts:** record every helper-agent prompt verbatim in `docs/AGENT_PROMPTS.md`.
- **Engineering principles** (`.claude/skills/karpathy-guidelines`, ponytail): minimum code, surgical changes,
  stdlib first; a known limit gets a `# shortcut:` comment.
- **Linux limits:** Windows-only behaviour can't be run on Linux. Test it with fakes, and prove it on the
  `windows-latest` GitHub Actions runner where a task says so.

## 2. Tasks, in this order

### W1: The two open security-review findings
1. **`skill.import` runs code written from an untrusted README** (`chutku/skill_import.py:92-99` →
   `chutku/skills.py:390`).
   - Import must not run `create_skill`'s tests. Leave the skill pending and untested; only the existing
     `skill approve` (user_only plus a click) builds and tests it.
   - Wrap the README as untrusted data in the coder prompt (reuse the `_defang` / untrusted-data pattern used for
     web text).
   - Fix the tool description and the approval text so they say plainly that the README drives code that will run
     at approve time.
   - Tests: a malicious README cannot cause any subprocess before approve.
2. **Backup restore brings back security state** (`chutku/backup.py:111-151`).
   - Restore never writes `telegram.json`, `remote.json`, `skills/approved.json`, active skill folders,
     capability or resource grants, or never-rules. It lists them as skipped.
   - Add an opt-in `--include-security` that asks again on screen.
   - Tests for both.

### W2 (P2): Data lives outside the app folder
- **One helper:** `chutku/core/paths.py: home()`.
  - `CHUTKU_HOME` if set;
  - else the repo root when running from a git checkout (`(root/".git").exists()`), which keeps the owner's PC
    working unchanged;
  - else `%LOCALAPPDATA%\Chutku`.
  - Add `data_dir()` and `models_dir()` next to it.
- **Replace every write location:** `PROJECT_ROOT / "data"`, `.env` (`chutku/identity.py`), `models/`,
  `chutku/icon.py`'s `ensure_icon` (it writes into `chutku/web/`) and `chutku/hud.py`'s `LAYOUT_FILE`.
  - About 20 modules compute `PROJECT_ROOT`: `grep -rn "parents\[" chutku`.
  - Read-only bundled files (`chutku/web`, `vendor/`) stay next to the code.
- **Protected zones** (`chutku/core/paths.py`): cover both the code folder and `home()`.
- **Defaults for new installs only** (an existing `data/preferences.json` is never changed):
  - `handsfree_mode` = `auto_safe`;
  - browser = the system default (the `http` UrlAssociations ProgId in the registry);
  - `know_me` reads the default browser's history (Chrome/Edge/Brave share the format).
  - Today the defaults are `owner` and Brave, in `chutku/core/preferences.py`.
- **Test:** with `CHUTKU_HOME` set to a temp folder, a full dashboard start/stop plus a text command writes nothing
  under the code folder (compare file lists).

### W3 (P3): App package and `Chutku.exe` launcher
- **`scripts/build_release.py`** builds `dist/Chutku-<version>-win64.zip` containing:
  - the python.org **embeddable** CPython 3.13 for win-amd64, pinned with its SHA-256 in `models/manifest.json`
    (new `python` entry);
  - site-packages installed from `requirements.lock` with `--require-hashes --only-binary=:all:
    --platform win_amd64 --python-version 3.13 --target ...`;
  - `chutku/` compiled to `.pyc` (`compileall -b`, no `.py`);
  - `vendor/`;
  - the two native exes from `tools/node_modules/agent-desktop/bin/agent-desktop-win32-x64.exe` and
    `agent-browser/bin/agent-browser-win32-x64.exe` (users need no Node);
  - the licence files, a `NOTICE` and `version.json`.

  Drop `playwright` if nothing needs it any more (check `browser.workflow`; the signed-in browser replaces it), and
  remove it from the lock with a fresh `scripts/hash_lock.py` run. Update `desktop.binary()` and
  `signed_in_browser.binary()` to also look next to the package (`<app>/bin/`).
- **`installer/launcher.cs`:** compiled with the .NET Framework `csc.exe` that ships with Windows.
  - It embeds the icon (from `chutku/icon.py`) and version info, and allows a single instance.
  - It starts `<app>\python\pythonw.exe -m chutku.guard` with `CHUTKU_HOME=%LOCALAPPDATA%\Chutku`, with no window.
  - If Chutku is already running, it opens the window instead (`-m chutku.cli open`).
- **`chutku/autostart.py`:** points the sign-in task at `Chutku.exe` when it runs from a package.
- **Verify on `windows-latest`** (a workflow job): build, unzip, run `Chutku.exe`, then check:
  - the dashboard answers on 127.0.0.1;
  - `doctor` passes;
  - no file is created under the app folder;
  - stop.

### W4 (P4): `ChutkuSetup.exe` and releases
- **`installer/chutku.iss`** (Inno Setup 6):
  - per-user install to `{localappdata}\Programs\Chutku` with `PrivilegesRequired=lowest`;
  - branding and icon; licence page; "Start Chutku when I sign in"; Start Menu and Desktop shortcuts;
  - "Launch Chutku" on finish;
  - an uninstaller that removes the app and asks before deleting `%LOCALAPPDATA%\Chutku` (the user's data).
- **The setup is small and downloads the app** with Inno's built-in download page:
  - it reads `latest.json` from `https://github.com/sidvashisth2005/Chutku-releases/releases/latest/download/latest.json`
    (`{version, url, sha256, size}`);
  - it downloads the zip through `DownloadTemporaryFile` with the SHA-256 and refuses a mismatch;
  - it unzips. Upgrades replace the app and keep the data.
- **`installer/sign.ps1`:** signtool when a certificate is given; skipped otherwise.
- **`.github/workflows/release.yml`**, on a tag `v*` on `windows-latest`:
  1. tests;
  2. `build_release.py`;
  3. install Inno Setup (choco);
  4. build the setup;
  5. a **clean-machine test**: `ChutkuSetup.exe /VERYSILENT /SUPPRESSMSGBOXES` (point the setup at the local zip
     with a `/PACKAGE=` switch for this test), the installed `doctor`, one text command through the installed app,
     then uninstall;
  6. publish `ChutkuSetup.exe`, the zip and `latest.json` to `sidvashisth2005/Chutku-releases` through `gh release
     create`, with the secret `RELEASES_TOKEN`.

  Without the secret, the job must fail at the publish step with a clear message (the owner adds the token).
- **Negative cases:**
  - a tampered zip (wrong hash) is refused;
  - no network gives a clear message.
- **Do not create the public repo yourself** unless your GitHub access allows it. Otherwise write
  `installer/RELEASES_REPO.md` with the exact steps for the owner.

### W5 (P5): First-run setup inside the app (no console)
- **A first-run page in `chutku/web/`** (`index.html` / `app.js`), shown while `home()/data/setup.json` has no
  `"done": true`. Its endpoints in `chutku/dashboard.py` sit behind the existing `_authorized` (token, Host and
  Origin) checks.
- **It reuses the logic in `chutku/setup_wizard.py`.** Split that module into pure functions the CLI and the page
  both call. The steps:
  1. Name the assistant and pick a personality (`identity.save`).
  2. Your name (`Mind.set_fact`).
  3. Free cloud brain: paste a Gemini or Groq key, with a how-to link. The key goes to Credential Manager through
     `cloud_planner`'s existing functions. Never echo it back.
  4. **Optional downloads with progress and resume.** Move `scripts/setup_all.py`'s download/hash code into
     `chutku/models.py` and keep `setup_all.py` as a thin CLI. The packs:
     - **Offline voice:** stt and tts, about 0.8 GB.
     - **Offline brain:** Qwen3-4B, about 2.5 GB.
     - **Offline screen understanding:** about 2.8 GB.

     The essentials ship in the package: wake word, speaker, embed (about 160 MB).
  5. Mic test, as a level meter.
  6. Autonomy: Safe (default), Edits, or Full.
  7. Optional: phone account; signed-in browser login (a button that runs `signed_in_browser.login()`).
- **The same items under Settings,** so they can be changed later.
- **Tests:**
  - every endpoint refuses a bad token;
  - a wrong-hash download is refused and deleted;
  - setup state persists.
- Fix `scripts/install.ps1`'s "4 quick setup questions" to match the real count.

### W6 (P6): Remaining plan items
- **Dashboard tabs:**
  - **Board** (`/api/board`, `/api/board/stop`, `chutku/board.py`);
  - **Automations** (the H23 blueprint APIs: list, create, cancel).

  Both follow the existing tab pattern in `chutku/web/index.html` (`data-tab`) and `app.js` (`switchTab`).
- **H23 habit suggestions:** repeated requests at similar times in `ledger.db` and history become a suggested
  automation card. Nothing is created without a click.
- **H9 key pool:** several Gemini/Groq keys in Credential Manager (`Chutku/Gemini#2` …), rotated on HTTP 429 or a
  quota error. Tests use fakes.
- **Relay end-to-end encryption:**
  - The phone and laptop derive a key from the account password at login: scrypt, then AES-GCM (WebCrypto in
    `chutku/web/phone/phone.js`; on the laptop, check whether `cryptography` is acceptable in the lock or use
    another vetted path).
  - The relay forwards only ciphertext.
  - Tests show the relay's database and queue never hold plaintext.
  - Update `docs/SECURITY.md` §4b-2.
- **A14, A15, A16:** each built on `desktop.look`/`desktop.act` and the Action Lab, unit-tested with fakes.
  - **A14 cross-app recipes:** a routine of verified app actions and `desktop.act` steps.
  - **A15 teach mode:** record the refs by name while the owner shows the steps once; replay with `desktop.act`.
  - **A16 screen survey:** skeletons of the open windows, summarized.

  Mark each "needs the Windows live check".

### W7 (P7): READMEs and docs
- **`installer/README_PUBLIC.md`:** the README for the public releases repo, written for normal users, with no tech
  stack. It covers:
  - what Chutku does;
  - download and install, with the SmartScreen "More info → Run anyway" note;
  - first-run setup and things to say;
  - privacy and safety in plain words;
  - uninstall;
  - FAQ and troubleshooting.
- **`README.md`** (this repo) is for developers: architecture, dev setup (`Install-Chutku.cmd`), build and release
  commands, tests, the delivery gate.
- **`docs/USER_GUIDE.md`:** a generic version of `docs/OWNER_GUIDE.md` without the owner's PC details (no §10).
  Served in the app as Help.
- **Licences in `THIRD_PARTY_LICENSES.md` and the package `NOTICE`:**
  - openWakeWord models are CC BY-NC-SA 4.0 (non-commercial, attribution);
  - espeak-ng is GPL (ship its licence and a source link);
  - exclude the PortAudio ASIO DLL variant from the package.

### W8 (P8): Release gate
1. Full suite, `check_phrases`, `doctor`, and CI green on `windows-latest`.
2. The release workflow's clean-machine install job passes.
3. Run `/security-review` and `/code-review` (high) over the full release diff. Fix every valid finding with a test
   and record it in `docs/RELEASE_CHECKLIST.md`.
4. A secret and personal-data scan of the built zip: no `data/`, `.env`, history, the owner's name, keys or the
   user path.
5. Record a size and time table: setup size, package size, install time, first launch.
6. Do not tag `v1.0.0` until the PC session has run the Windows live checks. Leave that as the first item for the
   PC session in your final report.

## 3. What to hand back (your final message, for the owner to bring to the PC session)
- The branch name, and every commit with its one-line summary.
- **Per task:** what was verified on Linux, what on the `windows-latest` runner, and what still needs the owner's
  PC.
- The exact list of owner-only steps:
  - the `RELEASES_TOKEN` secret and creating the public repo, if you could not;
  - optionally, a signing certificate;
  - `chutku.cli browser login` and `chutku.cli authority grant browser.input`;
  - Telegram's BotFather token;
  - the phone relay or Tailscale;
  - voice and wake-word live checks.
