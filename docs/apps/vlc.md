# VLC media player — feature map (App Mastery A0)

Sources (local copies in `data/apps/vlc/sources/`): [Documentation: Command line (official wiki)](https://wiki.videolan.org/Documentation:Command_line) · [Modules/hotkeys (official wiki)](https://wiki.videolan.org/Documentation:Modules/hotkeys/) · [VLC cheat sheet](https://www.ditig.com/vlc-cheat-sheet). Note from the official wiki: on Windows use `--option="value"` syntax.

## Ways in
- **Command line (`vlc.exe`, usually `C:\Program Files\VideoLAN\VLC\`):** `vlc <file|folder|url>` · `--fullscreen` (`-f`) · `--start-time=<s>` · `--stop-time=<s>` · `--rate=<x>` · `--loop` · `--repeat` · `--random` · `--play-and-exit` · `--no-video` (audio only) · `--sub-file=<path>` · `--audio-track=<n>` · `--one-instance` / `--playlist-enqueue` (add to the running VLC).
- **Media session:** VLC exposes Windows media controls → play/pause/next and title read-back (verifier).

## Hotkeys (default, Windows)
| Area | Keys |
|---|---|
| Playback | Space play/pause · S stop · N next · P previous · [ / ] slower/faster (older: - / +) · = normal speed · L loop · R random |
| Jump | Shift+←/→ 3 s · Alt+←/→ 10 s · Ctrl+←/→ 1 min · Ctrl+T go to time · E next frame |
| Audio | Ctrl+↑/↓ volume · M mute · B cycle audio track · J/K audio delay |
| Video | F full screen · Esc leave full screen · A aspect ratio · C crop · Z zoom · Shift+S snapshot · T show time |
| Subtitles | V cycle subtitles · G/H subtitle delay |
| Files | Ctrl+O open file · Ctrl+Shift+O open multiple · Ctrl+F open folder · Ctrl+N network stream · Ctrl+L playlist · Ctrl+H minimal interface · Ctrl+P preferences · Ctrl+Q quit |

## Screens
Main window (video area, seek bar with time, controls) · playlist (Ctrl+L) · Media → Open dialogs · Tools → Preferences · full-screen controller overlay.

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| play_file(path) / play_folder(path) | play | `vlc --one-instance <path>` | safe | media title / window title |
| enqueue(path) | add to playlist | `--playlist-enqueue` | safe | playlist count |
| play_from(path, time) | start at a time | `--start-time` | safe | position OCR |
| pause / resume / stop / next / previous | playback | media session / keys | safe | media status |
| skip(seconds) / back(seconds) | jump | Shift/Alt/Ctrl + arrows (combined to reach the amount) | safe | time OCR |
| speed(x) | playback speed | ] / [ repeated, or `--rate` at start | safe | OSD text |
| fullscreen_on / off | view | F / Esc | safe | window size |
| subtitles_next / off / load(path) | subtitles | V / `--sub-file` | safe | OSD text |
| audio_track_next | language track | B | safe | OSD text |
| snapshot | save a frame | Shift+S | changes (create-only, Pictures) | new file in Pictures |
| loop / shuffle | modes | L / R | safe | OSD text |
| audio_only(path) | music without video window | `--no-video` | safe | media playing |
| quit | close | Ctrl+Q | safe | process gone |

**New ideas:** "is folder ki saari videos shuffle mein chalao"; "movie wahin se chalao jahan chhodi thi" (VLC remembers position; else saved time); "subtitle 2 second aage karo" (H ×20); "lecture 1.5x pe chalao".
