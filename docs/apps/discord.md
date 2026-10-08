# Discord — feature map (App Mastery A0)

Sources (local copies in `data/apps/discord/sources/`): [Discord Hotkeys (official)](https://support.discord.com/hc/en-us/articles/225977308-Keyboard-Shortcuts) · [Hongkiat list](https://www.hongkiat.com/blog/keyboard-shortcuts-discord/) · [unofficial discord:// protocol routes](https://gist.github.com/ghostrider-05/8f1a0bfc27c7c4509b4ea4e8ce718af0) (Discord does not officially document its protocol; Windows client only).

## Ways in
- **Launch:** Start-menu "Discord".
- **Protocol (Windows client):** `discord://-/channels/@me` (DMs/friends) · `discord://-/channels/<guild_id>` (server) · `discord://-/channels/<guild_id>/<channel_id>` (channel) · `discord://-/channels/@me/<dm_id>` · `discord://-/users/<user_id>` · `discord://-/settings/<name>` (e.g. `voice`, `notifications`, `appearance`) · `discord://-/invite/<code>` · `discord://-/guilds/create`. IDs are learned once (copied from a channel link) and saved per name.
- **Quick switcher:** Ctrl+K + name + Enter — reaches any server, channel or DM by name without IDs.

## Shortcuts (official, Windows)
| Area | Keys |
|---|---|
| Navigate | Ctrl+K quick switcher · Ctrl+Alt+↑/↓ previous/next server · Alt+↑/↓ previous/next channel · Alt+Shift+↑/↓ previous/next **unread** channel · Ctrl+Shift+Alt+↑/↓ unread channel with mentions · Alt+←/→ back/forward |
| Read | Shift+Esc mark channel read · Shift+PageUp jump to oldest unread · Ctrl+Shift+H help |
| Voice | Ctrl+Shift+M toggle mute · Ctrl+Shift+D toggle deafen · Ctrl+Enter? (accept call — lab-verify) |
| Create | Ctrl+Shift+N create/join a server · Ctrl+Shift+T create DM group? (lab-verify) · Ctrl+Shift+U upload file |
| List | Ctrl+/ shows all shortcuts |

## Screens
Server list (left icons) · channel list (text 🗨 / voice 🔊 channels, unread = white/bold, mentions = red badge) · chat area (messages, input "Message #channel", + upload) · member list (right) · voice panel (bottom-left: connected channel, mute/deafen/settings) · user settings (gear).

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open | open Discord | launch | safe | window |
| goto(name) | server / channel / DM by name | Ctrl+K + name + Enter | safe | channel title OCR == name |
| mute_mic / unmute / deafen / undeafen | voice | Ctrl+Shift+M / Ctrl+Shift+D | safe | voice panel icon state |
| join_voice(channel) | join a voice channel | goto + click the 🔊 channel | consequential-lite (others hear you; asks first time per session) | voice panel shows channel |
| leave_voice | disconnect | voice panel "Disconnect" | safe | panel gone |
| read_channel(name, n) | latest messages | goto + OCR chat area | safe | — |
| unread_summary | channels/DMs with unread | Alt+Shift+↓ walk / OCR badges | safe | — |
| mark_read(channel) | mark read | Shift+Esc | changes | unread style gone |
| send(channel, text) | post a message | goto + type + Enter | consequential (asks for public servers; DMs to known people run) | message appears |
| upload(channel, path) | send a file | Ctrl+Shift+U → dialog | consequential (asks) | file appears |
| set_status(online/idle/dnd/invisible) | status | avatar menu | changes | status dot |
| open_settings(page) | settings page | `discord://-/settings/<page>` | safe | page title |
| leave_server / delete / kick / ban | — | menus | **destructive** (asks) | — |

**New ideas:** "gaming mode" = Discord DND + mute notifications + game launch; "kisne mujhe mention kiya" (mentions inbox); "voice mein ho to mute kar do" (one key, global).
