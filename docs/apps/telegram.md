# Telegram Desktop — feature map (App Mastery A0)

Sources (local copies in `data/apps/telegram/sources/`): [Deep links (official, core.telegram.org)](https://core.telegram.org/api/links) · [Winaero hotkey list](https://winaero.com/telegram-desktop-keyboard-shortcuts/) · [UseTheKeyboard](https://usethekeyboard.com/telegram/). Existing tool: `message.send` already accepts Telegram for some flows (Mark parity row "Send message: WhatsApp / Telegram").

## Ways in
- **Launch:** Start-menu "Telegram".
- **Deep links (official):** `tg://resolve?domain=<username>` (open a chat) · `tg://resolve?domain=<username>&text=<draft>` (chat with a draft, not sent) · `tg://resolve?phone=<number>&text=<draft>` · `tg://msg_url?url=<url>&text=<text>` (share a link — choose chat) · `tg://join?invite=<hash>` · `tg://resolve?domain=<channel>&post=<id>` (a post) · `tg://resolve?domain=<username>&voicechat` · `tg://addstickers?set=<name>`.

## Shortcuts (Windows)
| Area | Keys |
|---|---|
| Chats | Ctrl+Tab / Ctrl+PageDown / Alt+↓ next chat · Ctrl+Shift+Tab / Ctrl+PageUp / Alt+↑ previous · Ctrl+1…8 folder n · Ctrl+9 archive · **Ctrl+0 Saved Messages** · Ctrl+Shift+↑/↓ previous/next folder · Ctrl+F search in chat · Esc close/back · Ctrl+J contacts |
| Messages | Ctrl+↑ reply to previous message · Ctrl+O send file · Shift+Enter / Ctrl+Enter new line |
| Format | Ctrl+B bold · Ctrl+I italic · Ctrl+U underline · Ctrl+Shift+X strike · Ctrl+Shift+M mono · Ctrl+Shift+N plain · Ctrl+K link |
| App | Ctrl+L lock (if passcode set) · Ctrl+M minimise · Ctrl+W hide to tray · Ctrl+Q quit |

## Screens
Folder tabs (left/top) · chat list (unread badges, muted grey badges) · open chat (header, messages, input "Write a message…", attach 📎) · Saved Messages · settings.

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open | open Telegram | launch | safe | window |
| open_chat(username) | open a chat | `tg://resolve?domain=` | safe | header OCR == name |
| draft(username, text) | chat with a draft (not sent) | `tg://resolve?domain=&text=` | safe | input holds draft |
| send(name, text) | send | draft + Enter (unknown recipient asks) | consequential | message bubble |
| send_file(name, path) | send a file | open_chat + Ctrl+O + path | consequential | file bubble |
| save_to_saved(text/file) | note to self | Ctrl+0 + type/attach + Enter | changes | bubble in Saved Messages |
| read_chat(name, n) | latest messages | open_chat + OCR | safe | — |
| unread_summary | chats with unread | chat list OCR badges | safe | — |
| folder(n) / archive / saved | navigate | Ctrl+n / Ctrl+9 / Ctrl+0 | safe | header |
| share_link(url) | share a page | `tg://msg_url?url=` | consequential (choose chat → asks) | — |
| mute(name) / pin / archive_chat | organise | chat context menu | changes | icon |
| lock / hide / quit | app | Ctrl+L / Ctrl+W / Ctrl+Q | safe | — |
| delete_chat / leave_group / block | — | menus | **destructive** (asks) | — |

**New ideas:** "ye link apne Saved Messages mein daal do"; "Telegram ke unread padh ke sunao"; "is file ko phone pe bhejo" = Saved Messages (reaches the owner's phone).
