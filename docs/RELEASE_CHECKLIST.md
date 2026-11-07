# Release checklist (prepared 2026-11-05, nothing published)

The owner decided: **prepare only, do not publish**. License: MIT. This file says what was checked and what is left
to do before a public release.

## Scans (2026-11-05)

| Check | Result |
|---|---|
| API keys in tracked files **and the whole git history** (Gemini `AIza…`, Groq `gsk_…`, Cerebras `csk-…`, OpenAI-style `sk-…`, GitHub `ghp_…`) | **None found.** Keys live only in Windows Credential Manager. |
| Phone numbers | Only the fake examples `+91 98765 43210` / `+91 98765 00000` / `+91 99999 99999` in tests and examples. |
| Owner's name or Windows user path in **current code** | Removed in O1/O2: paths are settings, names are generic ("AK", "Alex"). One example stays inside a tool description (`schedule_tools.py`), because descriptions are part of each tool's contract hash. |
| Owner's name or user path in **docs** | Still present in `IMPLEMENTATION_STATUS.md` (history entries), `docs/MASTER_PLAN.md`, `docs/AGENT_PROMPTS.md` and `docs/VOICE_RECORDING_GUIDE.md` (personal), plus `LICENSE` (copyright, intended). |
| Owner's name in **git history** | 109 matching lines. Old commits also contain the owner's family nicknames and real-session examples. |
| Owner data | `data/`, `sandbox/`, `models/*`, `vendor/` and `verification/archive/` are git-ignored and were never committed. |
| Pinned packages | `requirements.lock` now covers every installed runtime package (pywebview, qrcode and openwakeword were missing before 2026-11-05). Only `vulture` and `coverage` are outside it, in the `[dev]` extra. |

## Licence notes to settle before publishing

- **openWakeWord:** the code is Apache-2.0, but its pre-trained models are CC BY-NC-SA 4.0. Check which bundled
  files Chutku's wake engine loads (the melspectrogram and embedding models) and either ship them as an optional
  download with that notice, or replace them.
- **Kokoro voice:** the model is Apache-2.0. Hindi goes through espeak-ng, which is GPL; check the licence of the
  `espeakng-loader` package and how it is distributed.
- **PortAudio ASIO DLLs** in `sounddevice`: review the Steinberg terms or exclude the ASIO variants (already noted
  in `THIRD_PARTY_LICENSES.md`).
- **Models** are downloaded by `Install-Chutku.cmd -Models` from their original sources, pinned by SHA-256. They are
  not redistributed in the repo.

## Steps when the owner decides to publish

1. Create a **new** repository. Do not make the current one public, because its history contains personal data.
2. Copy the current tree without `.git`, then remove or rewrite the personal documents:
   - `docs/VOICE_RECORDING_GUIDE.md` (personal, remove);
   - the personal history parts of `IMPLEMENTATION_STATUS.md`, `docs/MASTER_PLAN.md` and `docs/AGENT_PROMPTS.md`
     (keep the engineering record, drop names and real-session quotes);
   - `docs/OWNER_GUIDE.md` §10 "Your PC right now".
3. Re-run the key and personal-data scans above on the new tree.
4. Run `Install-Chutku.cmd` in a fresh clone, then the unit tests, then `scripts/check_phrases.py`.
5. First commit, push, and check the CI run (`.github/workflows/tests.yml`).
6. Turn on GitHub private vulnerability reporting (CONTRIBUTING.md points to it).

## W8 release gate (cloud session, 2026-11-07)

| Check | Result |
|---|---|
| Full suite (Linux) | No failure outside the Windows-only Linux baseline. windows-latest `tests` was green before the last commits; re-read CI for the head commit. |
| `check_phrases.py` | 157/163 on Linux (the 6 misses are the Linux-only `files.*` set; 159/159 on the PC before W6 added 4 cases). |
| Clean-machine install (`package.yml`, windows-latest) | Tampered package refused (exit 7); install 18.1 s; doctor ok; text command answered; uninstall clean. |
| Zip secret / personal-data scan | Now **inside the build** (`scan_zip`, also `build_release.py --scan ZIP`). It refuses personal state files, key formats (Gemini, Groq, Cerebras, GitHub, OpenAI, PEM bodies), the owner's name (LICENSE excepted) and the builder's `Users\<name>\` in our files and every `.pyc`. Linux real build: clean. |
| `/security-review` | Run inline (no helper agents). **1 finding, fixed:** backup restore's security-state skip compared names case-sensitively, so `Never_Rules.json`, `Skills/approved.json`, `Skills/x/tool.py` or `telegram.json.` overwrote the real files on NTFS. That allowed an approved evil skill, reset never-rules and restored grants from a crafted zip. Now NTFS-style comparison; test `test_case_and_trailing_dots_do_not_slip_past`. |
| Code review (high, inline, no helper agents) | Read the new code paths: teach mode, `desktop.do`/survey, routines' app steps, the relay `serve()`, the key-pool `ask()`, setup `link_phone`, `/help`. **2 bugs, fixed** with a test (`InstantReplyTests`): `teach.start`, `teach.stop` and `desktop.survey` had no instant reply formatter, and the reply after "ho gaya" was dropped because teaching had already ended when the answer was built. The false-claim guard test covers the new replies. No other finding. |
| Found while building, fixed | 3,845 `.pyc` held pip's temp path, and `chutku/*.pyc` held the stage path. On Windows both contain `Users\<name>`. Fixed with `pip --no-compile` + `compileall -s`. |
| Low, left as is | The Action Lab drill paths in `chutku/apps/atlas/{explorer,notepad,vscode}.json` name `D:\ChutkuScratch` (a dev folder, not personal); the lab runs only on request. |

### Size and time (windows-latest)

| | |
|---|---|
| Setup (`ChutkuSetup.exe`, unsigned) | 1.96 MB |
| Package zip | 220.4 MB (Linux build with stand-in Python: 223.5 MB) |
| Installed | 614.5 MB |
| Package build | about 2 min 15 s |
| Install (download step skipped with `/PACKAGE=`) | 18.1 s with tar.exe (221.2 s with Expand-Archive) |
| First launch (package check) | 1.2 s |

**Do not tag `v1.0.0`** until the PC session has run the Windows live checks (HANDOFF §6).
