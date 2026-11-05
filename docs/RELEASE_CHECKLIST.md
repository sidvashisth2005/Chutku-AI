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
