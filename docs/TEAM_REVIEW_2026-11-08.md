# Launch review of Chutku 1.0.0: what a 7-person team found and what was fixed (2026-11-08)

**Who:** a cloud session (Linux) ran seven reviewers on `main` 5c398e1 (v1.0.0): CEO (first 10 minutes), CTO (every API),
Head of Design (every tab), CMO (every claim), CFO (cost and limits), CISO (security) and QA lead (phone app).

**How:**
- Each reviewer used its own temporary copy of Chutku, with fake screen, input, Telegram and cloud.
- Nothing touched the owner's PC.
- Their prompts are in `docs/AGENT_PROMPTS.md` §25.

**Tests (Linux):**
- Full suite: 1,645 tests, with no failure outside the Windows-only Linux baseline (587).
- `check_phrases`: 161/167. The 6 misses are the Linux-only `files.*` set.

## Fixed in this change

| # | Seat | Finding | Fix | Test |
|---|---|---|---|---|
| 1 | CEO | **Blocker:** a new install had no PC permissions (251 of 387 tools need one), so "open notepad" was refused, and only the CLI could grant them | When an installed app first finishes setup, it grants the everyday permissions and the user's own folders. Power, ending programs, running code, network changes, email and the signed-in browser stay off. The new Settings card "What Chutku may do" turns each on or off, and the denial text points there. The owner's git checkout is untouched | `test_setup_page_w5.PermissionTests`; the real install needs the Windows check |
| 2 | CTO, Design | The Voice lock tab was a dead end ("Unknown action.") | `voice_enroll` handles `status`; switching tabs clears the old error | live API check |
| 3 | CISO | `C:\ProgramData\ChutkuBoot` could be pre-created and owned by a normal user, who could then swap the SYSTEM helper | Setup refuses a link, removes an existing folder with `rmdir /s` (does not follow junctions), recreates it and sets Administrators as owner. The remove script does the same | `test_boot_access_card` (static); **needs the Windows check** |
| 4 | CEO, Design | Settings and Help could not be reached at 1280x800, and four tabs at 1280x640 | The sidebar scrolls; spacing is tighter on short windows | needs a look on the PC |
| 5 | CEO | Typed requests ran in "Owner/Full" even when setup chose Safe | The chat follows the setup level until the user picks one there | needs a look |
| 6 | CEO | A typed key or name on the Setup page was wiped by any re-render | Typed values are kept | needs a look |
| 7 | CFO, CMO | Out of quota: raw internals, a "Needs more detail" badge, the wrong reason on retry, and a CLI command in the text | One plain sentence with the next step (Settings). Status is "failed". The planner's words go to the log. The provider error kind survives. "No key" and "resting" are told apart | `test_brain_choice_h9`, `test_w6_tabs_pool` |
| 8 | CFO | A rejected key blocked Groq for 24 h, even after the right key was saved | Saving a key clears that provider's cooldowns | `test_w6_tabs_pool` |
| 9 | CTO | One local error stopped Telegram for good, while the card still said it was connected | The poll survives any error, retries, and shows `error` in the status | `test_telegram_gateway` |
| 10 | CISO | A stranger's 5 wrong codes locked the owner out of Telegram pairing | Wrong codes count and lock per chat | `test_telegram_gateway` |
| 11 | CTO | A changed bot token kept the old update offset | The offset is reset when the bot changes | — |
| 12 | CISO | After the 30-minute PIN session, the phone could still set the clipboard, speak on the laptop and upload | These need the PIN session; the phone asks for the PIN | `test_phone_z5` |
| 13 | CTO | `/api/remote` closed the connection on a Tailscale timeout | A plain 409 or 500 with an error id | — |
| 14 | CTO | "Turn off" boot access ran an admin prompt when nothing was installed | Says "It is already off." | `test_boot_access_card` |
| 15 | CISO | Curly apostrophes in the install path broke the PowerShell command | All single-quote forms are doubled | `test_boot_access_card` |
| 16 | CISO | The release scan missed Telegram, Tailscale and Hugging Face tokens | Added to `SECRETS` | `test_release_gate_w8` |
| 17 | CTO | Emergency stop hid the real reason | Plain reason, shown in the UI | — |
| 18 | CTO | Setup accepted `5` or `null` as a name | Text only, up to 60 characters | — |
| 19 | CTO | Cancelling an automation said "FAILED" | "That automation was already gone." | — |
| 20 | CTO | `nightshift report` printed `null` / `None` | "No Night Shift report yet." | — |
| 21 | CEO, CMO | "kitni jagah bachi hai", "aaj ki news" and "30 min baad yaad dilana pani peena" went to the slow AI | Instant now | `check_phrases` |
| 22 | Design | Help showed raw Markdown | A styled HTML page (`chutku/help_page.py`, text escaped) | `test_docs_w7` |
| 23 | Design | The orb's step list never became readable | Re-renders only when the steps change | — |
| 24 | Design, CMO | The "LOCAL BRAIN" pill and "Local model first" were wrong; there were four sets of autonomy names; "Owner: no approvals" was false | The pill follows the brain setting. One set of names everywhere: Review / Safe / Safe + file edits / Full (asks only for risky steps) | — |
| 25 | Design, CMO | Developer text shown to users (guard, sandbox path, CLI hints, "pinned SHA-256") | Plain words | — |
| 26 | QA | The phone's approval card was out of view; Pair/Unlock errors were cut off; old header messages stayed; the "[Verified]" tag showed; `#code=` links in an open tab failed; "Approve (PIN)" asked for no PIN; a wrong address showed raw JSON | All fixed in `phone.js` and `server.py` | `test_phone_*` |
| 27 | CMO, CFO | False privacy claims (memory, file names and screenshots do reach the AI service; Telegram is not end to end), "free" without the billing caveat, the size without packs, the README example that only opens Spotify search, and the guide example that could not be saved | `README_PUBLIC.md` and `USER_GUIDE.md` corrected; phone data use stated | `test_docs_w7` |

## Not done (left for the PC session or the owner)

- **Windows checks of the fixes above:**
  - #1: a fresh install, then "open notepad";
  - #3: run Turn on with a pre-made folder, then `(Get-Acl C:\ProgramData\ChutkuBoot).Owner`;
  - #4–6: look at 1280x800;
  - Telegram and boot after restart.
- **Design polish (minor):**
  - Capabilities tab: 387 raw tool cards, and the "Try these commands" developer list;
  - Automations: slugs and "(Hnn)" codes, and the weekday typed as text;
  - Memory: "Save note" jumps to chat;
  - Today tiles stay at "…" on error;
  - small fonts (8–9 px) and panel spacing.
- **Phone:**
  - Gboard composition on a real phone (finding QA-9);
  - "Forget this phone" only clears the phone itself.
- **Cost:**
  - Gemini can pick Pro models, which cost money if billing is on (keep auto-selection on Flash?);
  - the MJPEG fallback has no rate cap;
  - the presence window polls quickly when idle;
  - Night Shift can use up the free quota;
  - the installer's licence page shows only MIT.
- **CTO:**
  - Tailscale and the phone server's start errors are not shown on the page;
  - "Pair a different phone" says "Paired" at once;
  - a pasted key is called "ready" without a test call.
- **CISO (theoretical):**
  - a `/pair` sent in a group chat would pair the whole group;
  - files the elevated setup reads could be changed by same-user code before the UAC prompt.
