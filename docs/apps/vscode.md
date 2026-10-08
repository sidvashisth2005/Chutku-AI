# Visual Studio Code — feature map (App Mastery A0)

Sources (local copies in `data/apps/vscode/sources/`): [Command Line Interface (official)](https://code.visualstudio.com/docs/configure/command-line) · [Tips and tricks (official)](https://code.visualstudio.com/docs/editing/getting-started/tips-and-tricks) · [Key bindings (official)](https://code.visualstudio.com/docs/configure/keybindings). Existing tools: `code.build_project` (writes + opens a project), `apps.launch`.

## Ways in
- **CLI (`code`):** `code <folder|file>` · `-g/--goto file:line[:col]` · `-d/--diff a b` · `-m/--merge` · `-n/--new-window` · `-r/--reuse-window` · `-a/--add <folder>` · `-w/--wait` · `--list-extensions` · `--install-extension <id>` · `--uninstall-extension <id>` · `--profile <name>` · `-s/--status`.
- **URL:** `vscode://file/<path>:<line>:<col>` opens a file at a line.
- **Command palette:** Ctrl+Shift+P + command name (any command — the universal channel).

## Shortcuts (default keymap, Windows)
| Area | Keys |
|---|---|
| Find things | Ctrl+P quick open file · Ctrl+Shift+P command palette · Ctrl+Shift+O go to symbol · Ctrl+G go to line · Ctrl+T workspace symbol · Ctrl+Shift+F search all files · Ctrl+Shift+H replace in files |
| Panels | Ctrl+B side bar · Ctrl+Shift+E explorer · Ctrl+Shift+G source control · Ctrl+Shift+X extensions · Ctrl+Shift+D run/debug · Ctrl+` terminal · Ctrl+Shift+` new terminal · Ctrl+J panel · Ctrl+Shift+M problems · Ctrl+, settings · Ctrl+K Ctrl+S keyboard shortcuts |
| Edit | Shift+Alt+F format document · Ctrl+/ toggle comment · Alt+↑/↓ move line · Shift+Alt+↓ copy line · Ctrl+D next match · Ctrl+Shift+L all matches · F2 rename symbol · F12 go to definition · Ctrl+. quick fix |
| Run | F5 debug · Ctrl+F5 run without debug · Ctrl+Shift+B run build task · Shift+F5 stop |
| View | Ctrl+K Z zen mode · Ctrl+\ split editor · Ctrl+±/0 zoom · Ctrl+K Ctrl+T theme |
| Files | Ctrl+N new file · Ctrl+S save · Ctrl+K S save all · Ctrl+W close editor · Ctrl+Shift+T reopen closed editor · Ctrl+K O open folder (Ctrl+K Ctrl+O) · Ctrl+R open recent |

## Screens
Welcome page · editor area (tabs with file names; window title "file — folder — Visual Studio Code") · Explorer/Search/Source Control/Run/Extensions side views · bottom panel (Problems, Output, Debug Console, Terminal) · command palette box · status bar (branch, errors/warnings counts, language).

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open_folder(path) / open_file(path) | open | `code <path>` (reuse window) | safe | window title contains name |
| goto(file, line) | open at line | `code -g file:line` | safe | title + status bar "Ln line" OCR |
| diff(a, b) | compare | `code -d a b` | safe | title "↔" |
| open_recent | recent projects | Ctrl+R | safe | list shown |
| command(name) | run any palette command | Ctrl+Shift+P + name + Enter | safe/changes by command | depends |
| terminal_open / new_terminal | terminal | Ctrl+` / Ctrl+Shift+` | safe | panel landmark |
| run_in_terminal(cmd) | type a command | terminal + type + Enter | **runs code** (asks, S1) | output OCR |
| git_status_summary | changed files | `git status --porcelain` via existing guarded run / Source control view OCR | safe | — |
| search_workspace(text) | search | Ctrl+Shift+F + text | safe | results count OCR |
| format_document / toggle_comment / save / save_all | edit | keys | changes (undo Ctrl+Z) | dirty dot gone |
| run_build_task / run_tests | build/test | Ctrl+Shift+B / palette "Tasks: Run Test Task" | runs code (asks) | terminal output |
| debug_start / stop | debug | F5 / Shift+F5 | runs code (asks) | debug toolbar |
| zen_mode / toggle_sidebar / split | view | Ctrl+K Z / Ctrl+B / Ctrl+\ | safe | — |
| problems_summary | errors/warnings count | status bar OCR / Ctrl+Shift+M | safe | — |
| list_extensions | extensions | `code --list-extensions` | safe | — |
| install_extension(id) | install | `code --install-extension id` | changes (undo: uninstall — asks) | in list |
| uninstall_extension(id) | — | CLI | **destructive** (asks) | — |

**New ideas:** "Chutku project kholo" (named projects remembered from `files.recent`/`code -s`); "ChatGPT ka code yahan paste karo" (A14 recipe); "kitne errors hain" (problems_summary); "aaj kaunsi files badli" (git status summary).
