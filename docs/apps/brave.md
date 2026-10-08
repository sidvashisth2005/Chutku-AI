# Brave (+ YouTube) — feature map (App Mastery A0)

Sources (local copies in `data/apps/brave/sources/`): [Chrome keyboard shortcuts (official, Chromium = Brave)](https://support.google.com/chrome/answer/157179?hl=en&co=GENIE.Platform%3DDesktop) · [YouTube keyboard shortcuts (official)](https://support.google.com/youtube/answer/7631406?hl=en) · [Brave shortcut list](https://tutorialtactic.com/blog/brave-browser-shortcuts/) · [internal pages](https://www.stefanjudis.com/today-i-learned/how-to-find-all-internal-pages-in-chromiums-and-firefox/). Brave is the owner's default browser (memory: real https handler may be Edge — always launch Brave explicitly). Existing tools: `web.open`, `web.search`, `youtube.play`, `browser.workflow`, `browser.inspect`, `keyboard.shortcut`.

## Ways in
- **Launch / open URL:** `brave.exe <url>`; `--new-window`, `--incognito` (private window).
- **Internal pages:** `brave://settings`, `brave://history`, `brave://downloads`, `brave://bookmarks`, `brave://extensions`, `brave://newtab`, `brave://rewards`, `brave://wallet`, `brave://flags`, `brave://chrome-urls` (full list), `about:about`.
- **Site search:** existing `web.search` (google, youtube, maps, github, amazon, flipkart, flights, images…).

## Browser shortcuts (Windows)
| Area | Keys |
|---|---|
| Tabs | Ctrl+T new · Ctrl+W close · Ctrl+Shift+T reopen closed · Ctrl+Tab / Ctrl+Shift+Tab next/prev · Ctrl+1…8 tab n · Ctrl+9 last tab · Ctrl+Shift+A tab search |
| Windows | Ctrl+N new window · Ctrl+Shift+N private window · Ctrl+Shift+W close window |
| Page | Ctrl+L / Alt+D / F6 address bar · F5 / Ctrl+R reload · Ctrl+F find · Ctrl+P print/save PDF · Ctrl+S save page · Ctrl+±/0 zoom · F11 full screen · Alt+←/→ back/forward · Ctrl+D bookmark |
| Pages | Ctrl+H history · Ctrl+J downloads · Ctrl+Shift+O bookmarks manager · Ctrl+Shift+B bookmarks bar · Ctrl+Shift+Delete clear browsing data · Shift+Esc task manager · F12 dev tools |

## YouTube player (official)
k play/pause · j / l back/forward 10 s · ←/→ 5 s · m mute · f full screen · t theatre · i miniplayer · c captions · Shift+> / Shift+< speed · 0–9 jump to 0–90 % · Shift+N next video · Shift+P previous (playlist) · / search box.

## Screens
New tab page (search box, shortcuts) · any page (address bar, tab strip) · YouTube watch page (player, title, channel, Like, Subscribe, up-next list) · YouTube home/search results · brave:// settings pages · downloads page · history page.

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open_url(url) | open a site | existing `web.open` | safe | tab title |
| search(site, text) | search | existing `web.search` | safe | results title |
| new_tab / close_tab / reopen_closed_tab | tabs | Ctrl+T / Ctrl+W / Ctrl+Shift+T | safe | tab count / title |
| next_tab / tab_n(n) / tab_search(text) | switch | Ctrl+Tab / Ctrl+n / Ctrl+Shift+A + text | safe | window title |
| private_window | private | Ctrl+Shift+N / `--incognito` | safe | "Private" in title |
| bookmark_page | bookmark | Ctrl+D + Enter | changes | star filled |
| save_pdf | save page as PDF | Ctrl+P → "Save as PDF" → path | changes (create-only) | file exists |
| open_history / downloads / bookmarks / settings / extensions | pages | Ctrl+H / Ctrl+J / Ctrl+Shift+O / `brave://…` | safe | page title |
| zoom_in / zoom_out / zoom_reset / fullscreen / reload | view | keys | safe | — |
| find_on_page(text) | find | Ctrl+F + text | safe | match counter OCR |
| close_duplicate_tabs | (new) | tab search list → close duplicates | changes | tab count |
| clear_browsing_data | — | Ctrl+Shift+Delete | **destructive** (asks) | — |
| **YouTube:** play(query) | existing `youtube.play` | — | safe | media session |
| yt_pause / yt_skip_10 / yt_back_10 / yt_speed_up / yt_speed_down / yt_captions / yt_theatre / yt_fullscreen / yt_next_video / yt_mute | player keys (YouTube tab in front) | k / l / j / Shift+> / Shift+< / c / t / f / Shift+N / m | safe | media session / OCR |
| yt_skip_ad | "Skip ad" button | `screen.act_on_visible("Skip")` | safe | ad gone |
| yt_like / yt_subscribe | — | buttons | changes (subscribe: consequential) | button state |

**New ideas:** "is page ka summary" (web.read on current URL); "ye video 1.5x pe chalao"; "saare YouTube tabs band karo"; "last download kholo" (Ctrl+J → first item / `files.recent` Downloads).
