# File Explorer — feature map (App Mastery A0)

Sources (local copies in `data/apps/explorer/sources/`): [Keyboard shortcuts in Windows (official)](https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec) · [iTechGuides Explorer shortcuts](https://www.itechguides.com/keyboard-shortcuts-for-file-explorer-in-windows-11/) · [ElevenForum list of shell: commands](https://www.elevenforum.com/t/list-of-shell-commands-in-windows-11.1080/). Existing tools do the file work with undo and protection (`filesystem.*`, `files.find/open/recent/organize/zip/unzip`); Explorer actions here are about **showing** things to the owner.

## Ways in
- **Command line:** `explorer.exe <folder>` · `explorer.exe /select,"<file>"` (opens the folder with the file highlighted) · `explorer.exe "shell:<name>"`.
- **shell: folders:** `shell:Downloads` · `shell:Desktop` · `shell:Personal` (Documents) · `shell:My Pictures` · `shell:My Music` · `shell:My Video` · `shell:Screenshots` · `shell:Recent` · `shell:RecycleBinFolder` · `shell:Startup` · `shell:AppsFolder` · `shell:ControlPanelFolder` · `shell:Libraries` · `shell:Camera Roll` · `shell:Fonts` · `shell:SendTo` · `shell:Templates`.
- **Win+E** opens Explorer.

## Shortcuts (Windows 11)
| Area | Keys |
|---|---|
| Navigate | Alt+D / Ctrl+L address bar · Alt+← / Backspace back · Alt+→ forward · Alt+↑ up a level · F4 address history · Ctrl+E / Ctrl+F search box |
| Tabs/windows | Ctrl+T new tab · Ctrl+W close tab · Ctrl+Tab next tab · Ctrl+N new window |
| Items | Ctrl+Shift+N new folder · F2 rename · Alt+Enter properties · Ctrl+A select all · Ctrl+C/X/V · Ctrl+Z undo · Delete → Recycle Bin · Ctrl+Shift+C copy as path (Win 11) |
| View | Ctrl+Shift+1…8 view modes (extra large → content) · Alt+P preview pane · Alt+Shift+P details pane · Ctrl+Shift+E expand to current folder · Ctrl+mouse wheel icon size |

## Screens
Navigation pane (Home, Gallery, OneDrive, This PC, drives) · address/breadcrumb bar · command bar (New, Cut/Copy/Paste, Rename, Share, Delete, Sort, View, …) · file list (Name, Date modified, Type, Size) · preview/details pane · search results.

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open_folder(path or shell name) | show a folder | `explorer` path / `shell:` | safe | window title |
| show_file(path) | open the folder with the file highlighted | `explorer /select,` | safe | title + selection |
| open_downloads / screenshots / recent / recycle_bin | well-known | `shell:` | safe | title |
| sort_by(date/size/name/type) | sort | command bar Sort → option | safe | column header arrow |
| view(details/list/large icons) | view mode | Ctrl+Shift+n | safe | — |
| show_hidden_files on/off | view option | View → Show → Hidden items | changes (undo: toggle) | — |
| copy_path(file) | path to clipboard | existing clipboard tool (exact) | safe | clipboard |
| search_here(text) | search the open folder | Ctrl+E + text | safe | results OCR |
| new_folder(name) | create | existing `filesystem.create_directory` (journaled) | changes | exists |
| rename / move / copy / zip / unzip | file work | existing `filesystem.*` / `files.*` (undo, protection, never-rules) | changes | existing verifiers |
| delete | → Recycle Bin | existing `filesystem.recycle` | **asks** (owner rule) | — |
| properties(file) | size/dates | existing `filesystem.inspect` | safe | — |

**New ideas:** "last download ka folder kholo"; "sabse badi files dikhao Explorer mein" (filesystem.largest → /select first); "is file ka path copy karo"; "screenshots folder kholo".
