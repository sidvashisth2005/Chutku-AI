# Instructions for the web (cloud) Claude Code session: phone remote, part 2 (R4)

Written 2026-11-07 on the owner's PC. Read `AGENTS.md` and `docs/WEB_CLAUDE_TASKS.md` §1 first; those rules all
apply: no Co-Authored-By line, CRLF kept, tests never touch real devices, never weaken a safety rule.

## Where things stand (done and live-checked on the PC)
- **Tailscale setup:** the owner's laptop `buddy.tail473865.ts.net` and phone are on Tailscale; the phone is paired.
- **R1, fixes:**
  - the per-kind rate budgets (`auth.RATES`);
  - JPEG frames through PyAV, with the cursor in the `X-Cursor` header;
  - 503 on a capture error; a 45 s heartbeat;
  - the monitor is cached for trackpad input;
  - `apps.launch` now brings the app to the front.
- **R2, owner decisions:**
  - a standing control permission ("phone control on karo" lasts until switched off; Ctrl+Alt+Shift+P revokes
    it);
  - the PIN once per session (`server.PIN_SESSION`, `pin_ok`); risky approvals and command windows are `strict`;
    a missing PIN answers "PIN needed" and is never counted as wrong;
  - keep-awake while phone access runs on mains power (`RemoteManager._keep_awake`).
- **R3, one Remote screen** (`chutku/web/phone/`):
  - the live screen starts by itself;
  - touch on the screen is the trackpad: one finger moves, tap clicks, two-finger tap right-clicks, two-finger drag
    scrolls, long press drags;
  - modes: Trackpad, Tap here, Ask;
  - 2x zoom that follows the cursor;
  - a key row, the ⌨ live keyboard, and sheets for Chutku, Files and More.
  - Headless phone-size check through Tailscale: the first picture 1.4 s after pairing, the cursor drawn.

## R4 tasks (in order; each through the delivery gate, with a ledger entry)
1. **Emergency file fetch** (owner: "the laptop is at home and I need a file"):
   - **The Files sheet:**
     - quick folders: Recent (from `files.recent`), Desktop, Documents, Downloads, and folders the owner pins;
     - browse with breadcrumbs; search by name (reuse `files.find` / `chutku/drive_index.py`);
     - each file shows its size and date, with Download, Share (the Web Share API with the blob) and Preview
       (images and PDFs inline).
   - **New endpoints:** `/api/files/list {path}` and `/api/files/search {q}`.
     - They are read-only and use the same refusals as `/api/files/get`: protected zones, secret paths, the size cap.
     - They count against the PIN session.
     - They work while the laptop is locked: no screen capture is needed.
   - **Chat:** "Downloads se resume.pdf bhejo" / "send me the latest invoice" → the planner finds the file and the
     phone gets a download card (a new reply field `files: [{name, path, size}]` that the phone renders).
   - **Tests:** traversal, a protected path, a secret path and the size cap are all refused; listing works under a
     fake locked session.
2. **Quick actions** (a row in More, or in the Chutku sheet):
   - Lock the laptop: `win+l` is refused from the phone on purpose, so lock through `LockWorkStation` behind the PIN;
   - Show desktop; open an app (a search box → `apps.launch`); volume up, down and mute;
   - "Send me a screenshot": a full-resolution PNG download.
3. **Quality:**
   - measure the round trip per frame and adapt: smaller width (960 or 720) and higher quality numbers on slow
     links;
   - a "Data saver" toggle in More;
   - send the width the phone asks for (`/api/screen/frame?w=`), clamped to 640–1600.
4. **The laptop dashboard's Phone panel** (`chutku/web/index.html` / `app.js`; `index.html` has mixed line endings,
   so edit it bytewise):
   - one "Phone access" switch;
   - an "Allow control from my phone (standing)" switch (`remote.arm`);
   - the pairing QR and code always visible while phone access is on;
   - the paired phones with "remove";
   - the keep-awake state;
   - a 3-step first-time card: Tailscale on both devices with the same account → pair → done.
5. **The emergency guide:** `docs/USER_GUIDE.md`, section "Use your laptop from your phone". It covers:
   - leave the laptop on charger with Chutku running (it then stays awake);
   - a locked laptop still gives files and Chutku commands;
   - control needs an unlocked session (a Windows limit);
   - Ctrl+Alt+Shift+P at the laptop stops everything.

   Update `docs/SECURITY.md` §4b for the standing permission, the PIN session, keep-awake, the per-kind budgets and
   the new file endpoints.
6. **Tests and screenshots:** unit tests for every new endpoint, and Playwright screenshots of each phone screen at
   412x915 and landscape 915x412.

## Handback
List the commits and what was verified on Linux. The PC session will then:
- restart Chutku (and `control resume`);
- test on the owner's phone over Tailscale: a file fetch while locked, quick actions, data saver, and the
  dashboard panel.
