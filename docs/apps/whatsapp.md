# WhatsApp Desktop — feature map (App Mastery A0)

Sources (local copies in `data/apps/whatsapp/sources/`): [noobspace list](https://noobspace.com/whatsapp-keyboard-shortcuts-for-desktop/) · [tutorialtactic list](https://tutorialtactic.com/blog/whatsapp-desktop-shortcuts/) · [WebNots list](https://www.webnots.com/whatsapp-keyboard-shortcuts-for-desktop-apps-windows-and-mac/). The official FAQ page loads by script and could not be saved; the app's own list is in **Settings (Ctrl+,) → Keyboard shortcuts**. Existing Chutku tools: `message.open_chat`, `message.read_chat`, `message.send` (delivery checked by reading the chat) — see memory "WhatsApp UI facts" (Ctrl+F broken, green highlight = exact match, no UIA).

## ⚠ The sources disagree
Desktop app (Ctrl+Alt+… prefix) and web/older versions (Ctrl+…/Ctrl+Shift+…) differ, and the same keys mean different things in different lists (**Ctrl+Shift+D = "delete chat" in one, "dark mode" in another**). Rule: a shortcut is used only after the Action Lab confirms it on this PC; **destructive actions (delete, block, exit group) are never done by shortcut** and always ask.

## Ways in
- **Launch:** Start-menu "WhatsApp" (Store app).
- **Click-to-chat:** `whatsapp://send?phone=<intl number>&text=<urlencoded>` and `https://wa.me/<number>?text=…` open a chat with a draft (nothing is sent until Enter).
- **Typing in the chat box** + Enter sends (existing `message.send` verifies by reading the chat back).

## Shortcuts (candidates — desktop app first, lab-verify each)
| Area | Desktop app (Ctrl+Alt) | Older/web style |
|---|---|---|
| Chats | New chat Ctrl+Alt+N · Next/prev chat Ctrl+Alt+Tab / Ctrl+Alt+Shift+Tab · Search Ctrl+Alt+/ · Search in chat Ctrl+Alt+Shift+F · Close chat Esc | Ctrl+N · Ctrl+Tab · Ctrl+F · Ctrl+Shift+F |
| Chat state | Mark unread Ctrl+Alt+Shift+U · Mute Ctrl+Alt+Shift+M · Archive Ctrl+Alt+Shift+E · Pin Ctrl+Alt+Shift+P · Delete Ctrl+Alt+Backspace | Ctrl+Shift+U/M/E(A)/P/D |
| App | Profile Ctrl+Alt+P · Settings Ctrl+Alt+, (or Ctrl+,) · Lock Ctrl+Alt+L · New group Ctrl+Alt+Shift+N | Ctrl+P · Ctrl+, · Ctrl+L |
| Compose | Bold Ctrl+B · Italic Ctrl+I · Strike Ctrl+Shift+X · Mono Ctrl+Shift+M · Line break Shift+Enter · Emoji Ctrl+Alt+E · GIF Ctrl+Alt+G · Sticker Ctrl+Alt+S | Ctrl+E/G/S |
| Calls | Voice Ctrl+Shift+C · Video Ctrl+Shift+V · Mute in call Ctrl+Shift+M · Camera Ctrl+Shift+O · End Esc | |
| Voice notes | Speed up/down Shift+. / Shift+, | |

## Screens
- **Chat list** (left): search box, filters "All · Unread · Favourites · Groups", rows with name, last message, time, unread badge (green number).
- **Open chat** (right): header with name + "online/last seen", messages, input "Type a message", attach (+), mic.
- **Chat info** (click header), **Settings** (gear: Account, Privacy, Chats, Notifications, Keyboard shortcuts…), **Archived**, **Calls**, **Status/Updates**, **Communities**.

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open | open WhatsApp | launch | safe | window |
| open_chat(name) | open a saved person's chat | existing `message.open_chat` | safe | header shows name (exact, green highlight) |
| read_chat(name, n) | last messages | existing `message.read_chat` | safe | — |
| unread_summary | who has unread messages | Unread filter + OCR badges | safe | count matches badges |
| send(name, text) | send text | existing `message.send` (unknown recipient asks) | consequential | message appears in chat |
| send_file(name, path) | send a file/screenshot | attach (+) → file dialog path → Enter | consequential | file bubble in chat |
| send_last_screenshot(name) | newest file in Pictures\Screenshots | send_file | consequential | file bubble |
| reply_last(name, text) | reply to their last message | hover → Reply / Alt+R → type | consequential | quoted reply bubble |
| mark_read(name) / mark_unread(name) | toggle | verified shortcut | changes | badge state |
| mute(name, hours) | mute chat 8 h / 1 week / always | shortcut / chat menu | changes (undo: unmute) | bell-off icon |
| pin / archive (name) | organise | shortcut / menu | changes | position / Archived list |
| search_messages(text) | find a message | search box | safe | results list |
| call_voice / call_video(name) | start a call | header buttons / shortcut | consequential (asks) | call window |
| draft_to_number(number, text) | open chat with draft, not sent | `whatsapp://send` URI | safe | draft text in input |
| lock | lock WhatsApp | Ctrl+Alt+L | safe | lock screen |
| delete_chat / block / exit_group | — | menu only | **destructive** (always asks, never shortcut) | — |

**New ideas:** "UB ka last message padh ke sunao"; "jisne bhi aaj message kiya unki list"; "mammi ko bolo main 10 min mein aa raha" (existing send + people memory); "is PDF ko UB ko bhej do" (send_file from `files.recent`).
