# Chutku (developer README)

Chutku is a voice and chat assistant that runs a Windows PC, in English, Hindi and Hinglish. This README is for
developers. Users get [`installer/README_PUBLIC.md`](installer/README_PUBLIC.md) (the public releases page) and
[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) (the in-app Help).

Measured results and their limits are in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). What is planned is in
[docs/MASTER_PLAN.md](docs/MASTER_PLAN.md).

## Architecture

```text
voice (Gemini Live by default; local whisper offline) / typed chat / phone (E2E relay)
  -> quick_intents: deterministic instant phrases (no model)      -> chutku/quick_intents.py
  -> agent loop: cloud brain (Groq/Cerebras/Gemini, key pool) or the local llama.cpp planner
  -> Runtime: argument schema -> policy kernel (fixed risk per tool, grants, never-rules)
     -> approval when required -> tool -> independent verification (PASS / FAIL / UNKNOWN)
  -> hash-chained action log, undo journal, task trace -> honest reply with a verified tally
```

- **The model never authorizes.** Each tool (`chutku/tools/`, registered in `tools/builtin.py`) has a fixed risk
  level. `chutku/core/` holds policy, grants, the protected zones and elevation refusal.
- **Text read from the outside is untrusted.** It is defanged before any model sees it, and it makes later changes
  ask first.
- **The dashboard** (`chutku/dashboard.py`, `chutku/web/`) is loopback only, behind a session token. `chutku/guard.py`
  supervises it and restarts it on a hang.
- **Desktop control** goes through UI Automation (agent-desktop, `chutku/tools/desktop.py`). The signed-in browser
  goes through agent-browser. Both are headless and never use the mouse.
- **State lives in `paths.home()`:**
  - `CHUTKU_HOME`, if set;
  - otherwise the repository in a git checkout;
  - otherwise `%LOCALAPPDATA%\Chutku` in an installed app.
  - Code-relative files use `paths.CODE_ROOT` / `paths.resource()`.

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DESIGN.md](docs/DESIGN.md),
[docs/SECURITY.md](docs/SECURITY.md), [docs/DEVELOPER.md](docs/DEVELOPER.md), [docs/RELAY.md](docs/RELAY.md).

## Dev setup (Windows 10/11, a normal user, Python 3.11+; the package bundles 3.13; Node.js LTS for app control)

```powershell
git clone https://github.com/sidvashisth2005/Chutku-AI.git
cd Chutku-AI
.\Install-Chutku.cmd                 # venv, hash-locked packages, agent-desktop/agent-browser, health check
.\Install-Chutku.cmd -Models         # also the local models (hash-checked)
.\Start-Chutku.cmd                   # then Open-Chutku.cmd; Stop-Chutku.cmd stops it
```

In a checkout, data stays in the repo's `data/` (git-ignored), exactly as before the installer existed. Useful CLI
commands are `python -m chutku.cli doctor`, `setup`, `cloud set-key groq`, `cloud add-key groq` and
`authority list`. The full list is in [docs/DEVELOPER.md](docs/DEVELOPER.md).

## Tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests    # the whole suite (on the PC)
.venv\Scripts\python.exe scripts\check_phrases.py         # instant-phrase coverage and speed
python scripts\ci_tests.py                                 # what CI runs on windows-latest
```

- Tests never start real models, send messages or touch the network: they use fakes (`tests/agent_fakes.py`,
  `tests/test_desktop_d1.py`'s fake agent-desktop).
- On Linux about 580 tests fail because they are Windows-only. Compare against that set, never against zero.
- CI (`.github/workflows/tests.yml`) runs on `main` and `claude/**` pushes.

## Build and release

```powershell
python scripts\build_release.py --out dist        # dist\Chutku-<version>-win64.zip + .sha256 (embedded CPython 3.13)
python -c "from chutku.icon import icon_bytes; open('installer/chutku.ico','wb').write(icon_bytes())"
iscc /DAppVersion=<version> installer\chutku.iss  # dist\ChutkuSetup.exe (Inno Setup 6)
```

- **`package.yml`** builds both on `windows-latest` for every push, then installs, runs doctor, sends a text command
  and uninstalls (`installer/ci_install_check.ps1`).
- **A tag `v*`** runs `release.yml`, which publishes the zip, `latest.json` and the setup to the public releases
  repository. It needs the owner's `RELEASES_TOKEN`; the steps are in
  [installer/RELEASES_REPO.md](installer/RELEASES_REPO.md).
- **Signing** is optional (`installer/sign.ps1`, two secrets).
- **The package holds** `.pyc` files only, no `data/`, no `.env` and no ASIO DLLs. The stage check refuses anything
  else.

## The delivery gate

From [AGENTS.md](AGENTS.md). Before calling a change delivered:

1. Run the relevant tests.
2. Run one real command path for changed behaviour.
3. Inspect the result.
4. Fix failures first.
5. Write the evidence in `IMPLEMENTATION_STATUS.md` in the same change.

Safety-sensitive changes also need a negative case that proves they fail closed. What could not be checked is
written as "needs the Windows check", never as verified. Coding principles: think first, minimum code, surgical
changes, goal-driven checks ([CONTRIBUTING.md](CONTRIBUTING.md)).

## License

MIT ([LICENSE](LICENSE)). Bundled components and models keep their own licences, listed in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) and the package `NOTICE`. The openWakeWord models are
CC BY-NC-SA 4.0 (non-commercial).
