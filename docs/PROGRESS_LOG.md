# Chutku progress log (sessions of 2026-11-05 and 2026-11-06)

This log says what was done, what is finished, and what remains of the plan, so the next session can start at once.

- Evidence for every item is in `IMPLEMENTATION_STATUS.md` (newest first).
- The plan with tick boxes is in `docs/MASTER_PLAN.md`, Phases 5, 6 and 7.
- Every helper-agent prompt is in `docs/AGENT_PROMPTS.md` (#12–#21).
- Repo: `sidvashisth2005/Chutku-AI`, branch `main`, pushed after every slice.
- CI: `.github/workflows/tests.yml`, green since the Sentinel merge.
- Last full suite: 1,331 tests OK.

## What the owner asked for (all requests in these two sessions)

1. Read, fix and implement the Karpathy guidelines; adopt the ponytail skill.
2. Remove dead code, and improve the code where needed.
3. Make Chutku open-source ready, so anyone can install it. The decision: MIT, prepare only, don't publish.
4. Make it the best free assistant. Any PC task with one voice command, with little or no internet.
5. The 19 capabilities:
   - self-coding;
   - web autopilot;
   - skill import from GitHub;
   - drive scan, window snapping, telemetry, OS commands;
   - eyes, lip-sync, YouTube in the HUD;
   - building apps;
   - memory, email, stocks, phone.
6. A team of agents with personalities.
7. A minimal UI: a small rounded bar with reactive eyes and an expand option. Hidden until a hotkey, then smaller,
   draggable, and showing the live conversation.
8. Fewer approvals: decide by itself and ask only for very risky steps. "Approve once for the whole task". Fix the
   voice "yes" bug.
9. "Superintelligence": improve itself every day by proposing plans; on approval, implement, test, then keep or
   revert. Many agents and tasks at once. Understand context and the owner.
10. Push to GitHub regularly. Write this log.

## Finished and verified

**Rules and cleanup**
- **K1–K4:** the Karpathy guidelines are a project skill and part of `AGENTS.md`. The coder writes the minimum code,
  and a repair can't rewrite a failing test.
- **Ponytail skills** adopted as text only (their hooks were not installed).
- **C1–C5:** dead code removed (ensemble, dual-plan preview, the old Bridge, unused helpers), code-reviewed. Live
  checks found 3 real bugs, all fixed: double typing, a false "typed" claim, and focus from the background.

**Open source**
- **O1–O2:** owner paths became settings (`user_folder`, `media_folders`), and personal names were scrubbed.
- **O4:** `Install-Chutku.cmd`, tested in a fresh clone. It fetches models and runtimes and checks their hashes.
- **O5:** MIT `LICENSE`, a README for new users, `CONTRIBUTING.md`, CI.
- **O6:** `docs/RELEASE_CHECKLIST.md`. No keys anywhere in git history. A fresh repo is recommended for publishing.

**Phase 6**
- **X3:** one-command acceptance set (`scripts/one_command_check.py`), online and local-brain. The fixes it found:
  instant file reading, and echo replies refused.
- **X1:** Qwen3.5-4B tested; better on first steps but worse end to end, so not switched (pinned for re-tests).
- **X4:** `windows.snap`. **X6:** CPU temperature note and network speed. **X7:** `system.powershell`, which always
  asks.
- **X5:** drive index, 169,800 files in 25 s, searches in milliseconds: "X kahan hai".
- **X8:** draft-first email; sending always asks and needs the `email.send` grant.
- **X9:** stock quotes with "as of" (live TCS quote in 1.16 s).
- **X11/X12:** eyes with moods, and amplitude lip-sync.
- **X15/X16:** self-written skills: pending → tests → typed approve plus a click → `skill.<name>`. Bound to a hash,
  and every run asks.

**Phase 7**
- **Y0:** voice approvals fixed. Trusted tasks: "bina puche kar do" asks only for very risky steps (tested live).
- **Y1 + rework:** the bar is hidden until Ctrl+Alt+C, appears while she works, is 300×40, draggable, remembers
  its place, and shows the live "You/Chutku" line. A real window freeze is fixed (`NativeWindow`).
- **Y3:** questions are answered beside a running task; desktop actions stay one at a time.
- **Y2/Y4 Evolve:** nightly self-review → full-plan proposals → typed approve → branch + full tests → merge or discard. Safety code is protected. The owner profile is refreshed.

**Team used:** Auditor, Scout, Mason, Pixel, Quill, Sentinel, Forge, Sage.

## Not finished: the rest of the plan, in order

1. **Y2 Evolve: DONE 2026-11-06.** Merged and tested (13 Evolve tests, full suite 1,344). A real offline review on a copy of the logs produced one proposal. Still to do: the first owner-approved code proposal, live.
2. **Live checks that need the owner at the PC:**
   - the bar appearing on Ctrl+Alt+Space and dragging it;
   - the expand button and "to bar";
   - an approval opening the full window;
   - a real `windows.snap`;
   - Spotify 5/5;
   - wake two-stage training (`scripts/train_wake.py --two-stage`);
   - the GPU Whisper large-v3-turbo download and timings (X2/V6).
3. **Owner setup:**
   - Tailscale on the laptop and phone, then phone control live (X10/W6);
   - optionally a Gmail app password (`chutku.cli email set-account`) plus `authority grant email.send`;
   - voice enrollment;
   - a decision: should `skill.<name>` and `code.run_python` skip the 10-minute "same step, no new click" memory?
4. **Planned, not built:**
   - **X13:** YouTube inside the HUD.
   - **X14:** web autopilot in a dedicated signed-in browser profile over CDP, plus `browser.extract`.
   - **X17:** skill import from a GitHub repo.
   - **X18:** builder upgrade.
   - **O3:** no-GPU fallback test.
   - **O4:** the first-run wizard.
   - **V1–V6** leftovers: the Gemini Live check, the heal test, and the screen copilot live check.
5. **Known limits to improve:**
   - the local 4B model is weak on multi-step offline goals (X3 offline 6–9/12);
   - the presence phase follows voice only, so typed requests don't show the bar;
   - "trusted" and the mood cues are word lists, not learned models;
   - network speed reads English counter names only;
   - the openWakeWord models are CC BY-NC (settle before publishing);
   - three product notes from Sentinel are in the ledger (2026-11-06).

## How to resume

1. Read `docs/MASTER_PLAN.md` from Phase 5 onwards. The first unticked box is the next step.
2. Run `.venv\Scripts\python.exe -m unittest discover -s tests` (expect 1,331 OK) and
   `scripts\check_phrases.py` (145/145).
3. Finish Y2 first (item 1 above), then the live checks with the owner (item 2).
4. Commit `<ID>: summary` with no co-author line, push `main`, and add a ledger entry with the evidence.
