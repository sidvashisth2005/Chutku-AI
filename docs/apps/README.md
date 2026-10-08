# App feature maps (App Mastery A0, 2026-10-09)

What Chutku knows about each daily app, from its documentation — the input to the app atlases (A1) and the Action Lab (A2). Every shortcut and step here is **from docs and unverified on this PC** until the lab passes it; the docs themselves disagree in places (WhatsApp's Ctrl+Shift+D is "delete chat" in one list and "dark mode" in another), which is why nothing destructive ever runs by an unverified shortcut.

| App | Map | Ways in found | Actions catalogued |
|---|---|---|---|
| Spotify | [spotify.md](spotify.md) | `spotify:` URIs, ~45 shortcuts, media session | 28 |
| WhatsApp | [whatsapp.md](whatsapp.md) | `whatsapp://send`, wa.me, ~35 shortcuts (conflicting lists) | 21 |
| Brave + YouTube | [brave.md](brave.md) | CLI flags, `brave://` pages, ~40 browser + 16 YouTube keys | 38 |
| VS Code | [vscode.md](vscode.md) | `code` CLI (goto/diff/extensions), `vscode://`, palette, ~45 keys | 26 |
| Windows Settings | [settings.md](settings.md) | **219** `ms-settings:` URIs (official), quick settings | 27 |
| ChatGPT | [chatgpt.md](chatgpt.md) | Alt+Space companion, web shortcuts, copy-to-clipboard read-back | 9 |
| Discord | [discord.md](discord.md) | `discord://` routes, Ctrl+K switcher, ~16 official keys | 22 |
| VLC | [vlc.md](vlc.md) | official CLI options, ~40 hotkeys, media session | 23 |
| Telegram | [telegram.md](telegram.md) | official `tg://` deep links, ~25 keys | 22 |
| File Explorer | [explorer.md](explorer.md) | `/select`, ~60 `shell:` folders, ~25 keys | 25 |
| Notepad | [notepad.md](notepad.md) | `notepad.exe file`, ~25 keys | 14 |
| **Total** | | | **255 actions** (documented + new ideas) |

Source pages are saved as text in `data/apps/<app>/sources/` (local, not versioned) by `scripts/app_docs.py`, with URL, title, date and hash in each `index.json`; re-run it to refresh. Risk classes used in every catalogue: **safe** (view/play/navigate) → R1 · **changes** (undoable) → R2 · **consequential** (send/post/call/cloud) → R3 · **destructive** (delete/block/leave/uninstall) → R4, always asks.
