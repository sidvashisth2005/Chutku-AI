# Spotify — feature map (App Mastery A0)

Sources (local copies in `data/apps/spotify/sources/`): [Spotify keyboard shortcuts (official)](https://support.spotify.com/us/article/keyboard-shortcuts/) · [Spotify URIs and IDs (official)](https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids) · [tutorialtactic shortcut list](https://tutorialtactic.com/blog/spotify-shortcuts/). Everything below is **from docs, not yet verified on this PC** until the Action Lab (A2) passes it.

## Ways in
- **Launch:** Start-menu "Spotify" (`Spotify.exe`, `%AppData%\Spotify`). Media keys work even when minimized.
- **URI:** `spotify:` opens the app; `spotify:search:<text>`, `spotify:track:<id>`, `spotify:album:<id>`, `spotify:artist:<id>`, `spotify:playlist:<id>`. A URI pasted into Spotify's search box also navigates.
- **Media session (Windows):** play/pause/next/previous + title/artist read-back (`tools/everyday.media`) — the verifier for every playback action.
- **Built-in shortcut list:** Ctrl+? opens it in the app.

## Shortcuts (Windows)
| Area | Keys |
|---|---|
| Playback | Space play/pause · Ctrl+→ next · Ctrl+← previous · Shift+→/← seek · Ctrl+S shuffle · Ctrl+R repeat · Alt+Shift+B like current song · Ctrl+↑/↓ volume |
| Navigate | Ctrl+K open search · Ctrl+L focus search · Ctrl+F filter in a playlist · Alt+←/→ back/forward · Alt+Shift+H Home · Alt+Shift+J Now playing · Alt+Shift+Q Queue · Alt+J context menu |
| Library | Alt+Shift+0 Library · Alt+Shift+1 Playlists · Alt+Shift+2 Podcasts · Alt+Shift+3 Artists · Alt+Shift+4 Albums · Alt+Shift+5 Audiobooks · Alt+Shift+S Liked Songs · Alt+Shift+M Made for you · Alt+Shift+N New releases · Alt+Shift+C Charts |
| Panels | Alt+Shift+R Now-playing sidebar · Alt+Shift+L Your Library sidebar |
| Edit | Ctrl+N new playlist · Ctrl+Shift+N new playlist folder · Ctrl+A/X/C/V/Z/Y · Ctrl+P preferences · Ctrl+±/0 zoom |
| App | Ctrl+Shift+W log out · Alt+F4 / Ctrl+Shift+Q quit |

**Conflict found:** mute is "M" in one source and "Ctrl+Shift+↓" in another → verify in the lab; prefer `audio.volume` / media session for volume.

## Screens (landmarks for OCR / state detection)
- **Home** — "Home", "Good morning/afternoon/evening", tiles "Made for you".
- **Search** — search box + filter chips "All · Playlists · Songs · Albums · Artists · Podcasts · Profiles". Results mix types: the **type line under each title** ("Playlist • owner", "Song • artist") decides what an item is (2026-10-08 lesson: the exact "After Party" text was a *song*).
- **Your Library sidebar** — items with "Playlist • <owner>", "Album • …", "Artist"; filter chips "Playlists · Artists · Albums".
- **Playlist / album page** — big title, big green play button next to it (NOT the player-bar play button at the bottom), track rows "# Title Album Date added".
- **Player bar** (bottom) — current song, shuffle/prev/play/next/repeat, like heart, volume.
- **Now playing / Queue** sidebars.

## Action catalogue
Risk: **safe** (view/play/navigate) · **changes** (undoable library edits) · **consequential** · **destructive**.

| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open | open Spotify | launch | safe | window |
| play_pause / next / previous | playback | media session / keys | safe | media status |
| shuffle / repeat | toggle | Ctrl+S / Ctrl+R | safe | OCR player bar |
| seek_forward / seek_back | ±5 s | Shift+→/← | safe | position changes |
| volume_up / volume_down | app volume | Ctrl+↑/↓ | safe | — (system volume via audio.volume) |
| whats_playing | title + artist | media session | safe | — |
| like_current | save song to Liked | Alt+Shift+B | changes (undo: press again) | heart state OCR |
| play_playlist(name) | play *my* playlist by name | Alt+Shift+1 → exact name + type "Playlist" → page play button | safe | media playing + title in playlist page |
| play_liked | Liked Songs | Alt+Shift+S → play | safe | media playing |
| play_artist(name) / play_album(name) | by name | Ctrl+K search → type chip → exact name + type | safe | media playing |
| play_song(name) | one song | search → Songs chip → exact title | safe | media title == name |
| search(text) | open search | Ctrl+K + type | safe | search landmarks |
| open_queue / now_playing / home / library | navigate | Alt+Shift+Q/J/H/0 | safe | landmarks |
| new_playlist(name) | create | Ctrl+N + type name | changes (undo: delete — asks) | Library shows name |
| add_current_to_playlist(name) | save current song to a playlist | Alt+J menu → "Add to playlist" → name | changes | playlist page lists song |
| sleep_timer(min) | pause later | `task.schedule` + media pause | safe | media paused at time |
| shuffle_play_playlist(name) | play a playlist shuffled | play_playlist + Ctrl+S | safe | media playing |
| quit | close Spotify | Ctrl+Shift+Q | safe | process gone |
| log_out | — | Ctrl+Shift+W | **destructive** (always asks) | — |

**New ideas (beyond the manual):** "ye gaana kaunsa hai + like kar do"; "focus music" routine (play a named playlist + DND on); "jo pichhli baar chal raha tha wahi chalao" (remember last playlist); "gaana band karke 30 min baad wapas chalao".
