# Phase 3c: App Mastery — every daily app, every action, verified and fast (A0–A16)

> **Status:** plan, 2026-10-08. Comes **before** the rest of Phase 3b (H8–H30, below), on the owner's word. H8 (scheduled-task upgrades) is half-built in the working tree and is finished first, then A0.
> **Copy of record:** `docs/APP_MASTERY_PLAN.md` (this section, word for word).

## Context

The owner, 2026-10-08:
- "Every app I use daily (Brave, Spotify, ChatGPT, Settings, WhatsApp, Discord, VS Code…): get their documentation online and study them. Work out where each screen is and which feature lives where, including features I don't know about. List every possible action, think up new ones, and train Chutku to do them very well, efficiently and fast, so my work never gets stuck."
- "With verified pathways (known input, procedure and output) she won't need approval every time, because approval is for harmful things."

**Why now:** Chutku guesses at app UIs. On 2026-10-07/08 she searched Spotify four times, played the wrong "After Party" twice, and asked for approval each time. She has generic tools (click, keys, OCR, vision) but almost no *knowledge* of the apps. Only Spotify (search), WhatsApp (open/read/send), YouTube (play) and Steam have dedicated tools.

**Owner answers (2026-10-08):**
- **Apps (11):** Spotify, WhatsApp, Brave (+YouTube), VS Code, Windows Settings, ChatGPT, Discord, VLC, Telegram, File Explorer, Notepad.
- **Source of knowledge:** official docs and other web content **first**. The live screen survey comes **later**.
- **Survey storage:** keep screenshots **locally** (`data/apps/<app>/screens/`, never sent anywhere).
- **Teach mode:** **yes**. Chutku learns an action by watching the owner do it once.

**Outcome:**
- each app has an **App Atlas**: its ways in, its screens, and an action catalogue with sources;
- each action is a **deterministic procedure** with a built-in verifier;
- each one is **proven in the Action Lab** before it is trusted.
- Proven harmless actions run instantly with no approval. Asks remain only for harmful classes (deletes, payments, unknown recipients, R4 — the 2026-10-08 owner rules).

## 1. Design

### 1.1 How Chutku acts in an app: channels, most reliable first
Every action uses the most reliable channel the app offers. Screen-clicking is the last resort.
1. **Deep link / URI:**
   - `spotify:search:…`, `spotify:playlist:<id>`;
   - `ms-settings:bluetooth` (Microsoft's documented list);
   - `discord://`, `vscode://file/…`, `tg://resolve?domain=…`;
   - `whatsapp://send?phone=…`;
   - Explorer `shell:` folders.
2. **Command line:**
   - `code --goto file:line`, `code --diff a b`, `code --install-extension`;
   - VLC `vlc.exe --started-from-file file --fullscreen`;
   - `explorer.exe /select,path`.
3. **Documented keyboard shortcuts:**
   - Spotify Space / Ctrl+→ / Ctrl+K / Alt+Shift+B (like);
   - WhatsApp Ctrl+Alt+N / Ctrl+Shift+M (mute) / Ctrl+Shift+U;
   - Discord Ctrl+K / Ctrl+Shift+M / Ctrl+Shift+D;
   - ChatGPT Alt+Space;
   - Brave/Chromium shortcuts;
   - VS Code keybindings and the command palette;
   - VLC hotkeys; Notepad.
4. **UI Automation by name:** existing `uia.*` tools (PowerShell UIAutomationClient). Chromium/Electron apps expose names when queried.
5. **Exact text on screen:** `screen.act_on_visible` (OCR plus type-aware matching, built 2026-10-08).
6. **Vision model:** last resort, only to *locate* an element. A vision guess never verifies itself.

### 1.2 The App Atlas (`chutku/apps/atlas/<app>.json`, checked in; one per app)
```json
{ "app": "spotify", "aliases": ["spotify", "gaane", "music"], "exe": "Spotify.exe",
  "launch": {"start_menu": "Spotify", "uri": "spotify:"},
  "sources": [{"url": "https://support.spotify.com/…/keyboard-shortcuts/", "title": "…", "read": "2026-10-08"}],
  "screens": [{"id": "search", "landmarks": ["All", "Playlists", "Songs", "Albums"], "reach": [{"keys": "ctrl+k"}]}],
  "actions": [{
    "id": "play_playlist", "title": "Play a playlist by name",
    "phrases": ["play {name} playlist", "{name} playlist chalao", "{name} wali playlist bajao"],
    "params": {"name": {"type": "text"}},
    "risk": "safe", "source": "docs+invented",
    "steps": [{"focus": "spotify"}, {"keys": "alt+shift+1"}, {"click_text": "{name}", "kind": "playlist"},
              {"play_page": true}],
    "verify": {"media_playing": true, "title_in_page": true},
    "drill": {"name": "After Party"} }] }
```
- **Risk classes:**
  - `safe`: view, play, navigate, read. Becomes R1.
  - `changes`: like, add to a playlist, toggle a setting; undoable. Becomes R2.
  - `consequential`: send, post, call, buy, submit to the cloud. Becomes R3.
  - `destructive`: delete, block, leave, uninstall. Becomes R4.
- A validator (`chutku/apps/atlas.py`) refuses a malformed atlas, an unknown step verb, a URI scheme that isn't on that app's allowlist, and an executable that isn't the app's own.

### 1.3 Step language and runner (`chutku/apps/runner.py`)
- **Verbs:** `launch`, `focus`, `uri`, `cli`, `keys`, `type`, `click_text` (reuses `tools/visible.py` matching, `kind_of`), `uia` (reuses `tools/uia_actions.py`), `wait_text`, `wait_title`, `play_page` (reuses `visible._press_play`), `settings_uri`, `copy_out` (Ctrl+C, then read the clipboard).
- **Verifiers:** `media_playing`, `title_in_page`, `window_title_contains`, `ocr_contains`, `file_exists`, `clipboard_changed`, `volume_equals`, `settings_page_open`, `process_running`.
- Every step checks that the app window is in front before it sends keys or text (reuse `desktop_controls` focus checks), so keys never go to the wrong window.
- **Tool registration:** each atlas action becomes its own Tool `app.<app>.<id>`, with `base_risk` from its risk class. The kernel, never-rules (H1), taint/S15, ledger (S16), rewind (S18), reflexes (S17) and the action log then all apply unchanged. `undo` is declared per `changes` action (e.g. unlike, remove from playlist, setting restore).

### 1.4 Verified pathways and approvals (owner rule, 2026-10-08)
- An action is **verified** after 3 consecutive Action Lab passes (ledger PASS). Each pass is checked by its own verifier, not by the model.
- **Verified `safe`/`changes` actions** run at once with no approval, in owner mode and in auto modes.
- **Unverified `changes` actions** ask once, until verified.
- **`consequential`** actions follow the existing rules: a known WhatsApp/Telegram contact runs; an unknown recipient asks. A Discord post or ChatGPT prompt asks only when the text came from outside content (taint).
- **`destructive`** actions always ask.
- If a verified action fails live, it drops back to unverified (S16 ledger demotion) and is re-checked by the lab.

### 1.5 Routing: instant, with no model call for known actions
- **Phrase compiler** (`chutku/apps/phrases.py`): atlas phrases with `{slots}` become anchored regexes (reuse the `reflex.py` template-to-regex code). Romanised Devanagari is handled through `translit.roman`, and alias words like "gaane" map to an app. The quick tier tries app actions before the generic rules.
- **Planner catalogue:** when a goal names an app, or the app is in front, only that app's actions are added to the planner's tool list. This keeps Qwen's prompt small. The model then composes app actions instead of raw clicks.
- `app.howto(app, question)` (R0): answers "how do I … in X" from the harvested docs (FTS5 index, reusing `history_index` code), and says whether Chutku can do it itself.

### 1.6 Ideas beyond the manuals (creativity, as asked)
- **Spotify:** play a named playlist, liked songs or an artist radio; "save this song to <playlist>"; "what's playing + like it"; "sleep timer 30 min" (pause later via `task.schedule`); "queue songs like this".
- **WhatsApp:** unread summary (read chat list via OCR); "send my last screenshot to UB"; mute a group for 8 h; "reply to the last message from X"; "mark all read".
- **Brave/YouTube:** reopen the closed tab; a private window; "save this page as PDF"; tab search; "close duplicate tabs"; read-later list; YouTube speed, captions, theatre mode, skip ad, next video.
- **VS Code:** open a project or recent folder; go to file:line; run tests / the default build task; terminal "git status" summary; format document; search the workspace; zen mode; install an extension.
- **Settings:** Bluetooth, Wi-Fi, display scale, night light, focus/DND, battery saver, default browser page, notifications per app, storage sense, sound output (reuse existing tools).
- **ChatGPT:** ask through Alt+Space and read the answer back (copy button, then clipboard); new chat; "ask ChatGPT about this screenshot"; continue the last chat.
- **Discord:** jump to a server/channel (Ctrl+K); mute/deafen; join/leave a voice channel; read the latest messages in a channel; set status (Online/DND).
- **VLC:** play file/folder; speed; subtitles on/off; jump ±10 s; fullscreen; snapshot; loop.
- **Telegram:** open a chat (`tg://`); send a file; unread summary; mute.
- **File Explorer:** open a folder; select a file (`/select`); sort by date/size; show hidden files; zip; copy the path.
- **Notepad:** new note with text; save as; word wrap; find/replace.
- **Cross-app recipes:**
  - "screenshot → ChatGPT: what is this";
  - "copy the code ChatGPT wrote into VS Code at the cursor";
  - "send the PDF I just downloaded to UB on WhatsApp";
  - "play focus music + DND on + VS Code project open" (as a routine).

## 2. Slices (breadth-first; each passes the AGENTS.md gate: tests, a live real path with seconds plus an independent check, a negative case, ledger entry, guide, commit and push)

| # | Slice | What |
|---|---|---|
| **A0** | Docs harvest | For all 11 apps, fetch the official docs, shortcut pages, URI/CLI references, help-centre feature lists and reputable guides. Store page text in `data/apps/<app>/sources/` with URL and date, and an index. Write `docs/apps/<app>.md` (feature map: screens, features, ways in, sources). Script `scripts/app_docs.py` refreshes them. |
| **A1** | Atlas format + validator + runner + verifiers | `chutku/apps/{atlas,runner,verifiers}.py`; per-action Tools; the risk-class mapping; focus guards; unit tests with fake windows. |
| **A2** | Action Lab | `chutku.cli apps lab <app> [--action id]`. Runs each action with its `drill` params on the live PC. Consequential actions run in **dry mode**: they go up to the final send/post, check that state, then press Esc. Records seconds plus verdict in the ledger and `data/apps/<app>/lab.json`, and marks verified after 3 passes. Report: "Spotify: 38/42 verified, median 1.4 s". |
| **A3** | Phrase compiler + routing + `app.howto` | Instant routing from atlas phrases; app-scoped planner catalogue; docs Q&A. |
| A4 | **Spotify** atlas + actions + lab | First full app (the After Party case becomes `play_playlist`). |
| A5 | **WhatsApp** | Builds on existing `message.*`; adds the shortcut-based actions. |
| A6 | **Brave (+YouTube)** | Shortcuts, `brave://` pages, YouTube player keys. |
| A7 | **VS Code** | CLI, `vscode://`, command palette, tasks, terminal. |
| A8 | **Windows Settings** | The whole `ms-settings:` URI map, plus existing setting tools. |
| A9 | **ChatGPT** | Alt+Space companion, ask and read back, new chat. |
| A10 | **Discord** | Ctrl+K switcher, voice keys, read channel. |
| A11 | **VLC** | Command line plus hotkeys. |
| A12 | **Telegram** | `tg://` plus shortcuts. |
| A13 | **File Explorer + Notepad** | `shell:`, `/select`, view options; Notepad keys. |
| A14 | **Cross-app recipes** | The recipes above, as checked multi-app actions. |
| A15 | **Teach mode** | "dekh, aise karte hain" … "ho gaya". Records only inside the named app's window: clicks (plus the OCR/UIA name under the cursor), shortcuts, and typed text as named slots. **Never** password fields (UIA IsPassword), other windows, or anything while Chutku's own UI is in front. Shows the draft steps, runs them in the lab, then saves to the atlas as `"source": "taught"`. Low-level hooks are active only between the two phrases, with a visible red "learning" badge. |
| A16 | **Screen survey** (later, owner's order) | Night Shift (idle, on charger) walks each app's screens through atlas `reach` steps. Saves OCR text and positions, UIA names and **screenshots locally** (`data/apps/<app>/screens/`, 30-day expiry, never uploaded), and refines landmarks. Never changes settings or sends anything: only atlas `safe` steps plus Esc. |

Order: A0 → A1 → A2 → A3, then the apps by the owner's usage (A4 Spotify … A13), then A14, A15, A16. Each app slice is self-contained, so its value lands immediately.

## 3. Measuring "very well, fast"
- `scripts/app_bench.py`: for each app, 10 real phrasings (Hinglish/English/Devanagari) gives the success rate plus median and p95 seconds, each independently checked by the action's verifier.
- **Gate per app:** ≥ 90% success, median ≤ 3 s for URI/shortcut actions and ≤ 8 s for screen actions.
- **Night Shift** (after A2): re-runs the lab for verified `safe` actions weekly, demotes failures, and reports "Spotify: 2 actions broke after an update" in the morning line.

## 4. Safety
- Atlas URIs and CLIs are allowlisted per app. Typed text goes only into the focused app window (checked before each key).
- Consequential actions keep the existing recipient and taint rules; destructive actions always ask; never-rules (H1) still apply to every `app.*` tool.
- Teach mode never records passwords or other windows; the recording lives only in memory until the owner saves it.
- Survey screenshots stay local with a 30-day expiry; the owner's chats are visible in them, so `data/apps/*/screens` is added to `.gitignore`.

## 5. Files
- **New:**
  - `chutku/apps/{__init__,atlas,runner,verifiers,lab,phrases,howto,teach,survey}.py`;
  - `chutku/apps/atlas/*.json` (11);
  - `scripts/app_docs.py`, `scripts/app_bench.py`;
  - `docs/apps/*.md`;
  - tests `tests/test_app_{atlas,runner,lab,phrases,howto,teach}.py` and one per app `tests/test_app_<app>.py`.
- **Edited:**
  - `tools/builtin.py` (register the atlas tools);
  - `quick_intents.py` (app phrases first);
  - `agent_loop.py` (app-scoped catalogue);
  - `policy/kernel.py` (verified-pathway rule, §1.4);
  - `nightshift.py` (lab re-check, survey);
  - `tools/visible.py` (shared matching);
  - `docs/OWNER_GUIDE.md` (an "Apps" chapter: what Chutku can do in each app), `docs/MARK_PARITY.md`, `IMPLEMENTATION_STATUS.md`.

## 6. Verification (every slice)
- Full suite green, plus `check_phrases.py` all-instant (app phrases added).
- **Lab run** on the live PC for that app: the verified count, seconds, and each verdict from the action's own verifier (media session, window title, OCR, clipboard, file).
- **Negative cases:**
  - a look-alike name is refused (After Party vs Afterparty);
  - an unknown action phrase falls to the planner;
  - a destructive action asks;
  - keys are never sent when another window is in front;
  - a consequential dry run never sends.
- **App bench gate (§3)** before the slice is ticked.
