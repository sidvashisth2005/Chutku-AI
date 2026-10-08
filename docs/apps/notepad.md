# Notepad (Windows 11) — feature map (App Mastery A0)

Sources (local copies in `data/apps/notepad/sources/`): [Windows Notepad keyboard shortcuts (qwerty.school)](https://qwerty.school/hotkeys/windows-notepad) · [Latest features of Notepad in Windows 11 (HTMD)](https://www.anoopcnair.com/latest-features-of-notepad-in-windows-11/). Existing tools: `keyboard.type_text` (verified by save-and-read-back), `filesystem.write_text` (journaled), `apps.launch`.

## Ways in
- **Launch:** `notepad.exe [file]` (opens a file directly) · Start-menu "Notepad".
- Windows 11 Notepad has **tabs**, session autosave, spell check, a formatting toggle, and Copilot "Rewrite/Summarize/Write" (cloud; Ctrl+Q per HTMD).

## Shortcuts
| Area | Keys |
|---|---|
| File | Ctrl+N new tab · Ctrl+Shift+N new window · Ctrl+O open · Ctrl+S save · F12 / Ctrl+Shift+S save as · Ctrl+P print · Ctrl+W close tab · Ctrl+Shift+T reopen closed tab · Alt+F4 close |
| Edit | Ctrl+Z / Ctrl+Y undo/redo · Ctrl+X/C/V · Ctrl+A select all · F5 insert date/time |
| Find | Ctrl+F find · F3 / Shift+F3 next/previous · Ctrl+H replace · Ctrl+G go to line |
| View | Ctrl+±/0 zoom · word wrap via View menu · Ctrl+Tab next tab |

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open | open Notepad | launch | safe | window |
| open_file(path) | open a text file | `notepad.exe path` | safe | title contains file name |
| new_note(text) | new tab with text | Ctrl+N + existing `keyboard.type_text` | safe (unsaved) | text read back |
| save_as(path) | save the current tab | F12 + path + Enter | changes (create-only when new; overwrite asks) | file exists with text |
| write_file(path, text) | without the UI | existing `filesystem.write_text` (journaled undo) | changes | read back |
| insert_date_time | insert now | F5 | safe | — |
| find(text) / replace(a, b) | search / replace | Ctrl+F / Ctrl+H (replace all) | safe / changes (undo Ctrl+Z) | counts |
| goto_line(n) | jump | Ctrl+G + n | safe | status bar "Ln n" |
| word_wrap on/off / zoom | view | menu / Ctrl+± | safe | — |
| close_tab / reopen_closed | tabs | Ctrl+W / Ctrl+Shift+T | safe (Notepad asks itself about unsaved text) | — |

**New ideas:** "ye clipboard ka text Notepad mein khol do"; "aaj ki to-do list Notepad mein likh do" (mind lists → new_note); "is file mein 'x' ko 'y' se badal do" (replace, with undo).
