# ChatGPT (Windows app) — feature map (App Mastery A0)

Sources (local copies in `data/apps/chatgpt/sources/`): [ChatGPT Windows app guide (chatai.guide)](https://chatai.guide/features/chatgpt-windows-app/) · [WebNots tips](https://www.webnots.com/10-tips-to-use-chatgpt-windows-app/). The official help page ([Using the ChatGPT Windows app](https://help.openai.com/en/articles/9982051-using-the-chatgpt-windows-app)) refuses automated downloads (403); its key facts, read through search on 2026-10-08: **Alt+Space** opens the companion window (changeable in Settings → App), Enter sends, Shift+Enter new line, Esc closes it, the window remembers its position.

## Privacy
Anything sent to ChatGPT goes to OpenAI's cloud. Text that came from a web page or a message (taint) is never sent without the owner's click; files/screenshots are sent only when the owner asked for exactly that.

## Ways in
- **Launch:** Start-menu "ChatGPT".
- **Companion window:** Alt+Space (works while another app is in front, when ChatGPT is running).
- **Web shortcuts (also in the app; lab-verify):** Ctrl+Shift+O new chat · Ctrl+Shift+S toggle sidebar · Shift+Esc focus input · Ctrl+Shift+C copy last response · Ctrl+Shift+; copy last code block · Ctrl+/ shortcut list.
- **Read the answer back:** "copy" button under the reply / Ctrl+Shift+C → clipboard → `clipboard.read_text` (exact text, no OCR errors).

## Screens
Main window (sidebar with chats/projects/GPTs, model picker, input "Ask anything", attach (+), voice) · companion window (single input bar) · chat view (messages, copy/like/read-aloud buttons under replies) · settings (General, App: companion hotkey, Personalisation, Data controls).

## Action catalogue
| id | What | Channel | Risk | Verifier |
|---|---|---|---|---|
| open | open ChatGPT | launch | safe | window |
| ask(text) | ask and read the answer back | Alt+Space or main input → type → Enter → wait for reply end → copy last response | consequential-lite (sends text to OpenAI; asks only when the text is tainted) | clipboard holds a new reply |
| new_chat | fresh chat | Ctrl+Shift+O | safe | empty chat landmark |
| ask_about_screenshot(question) | screenshot + question | `screen.capture` → attach (+) → question | consequential (sends an image; asks the first time per session) | reply copied |
| ask_about_file(path, question) | attach a file | attach → file dialog → question | consequential (asks) | reply copied |
| copy_last_code | code block to clipboard | Ctrl+Shift+; | safe | clipboard changed |
| continue_last_chat | reopen newest chat | sidebar first item | safe | title |
| read_aloud_last | speak the reply | reply "Read aloud" button / Chutku's own TTS of the copied text | safe | — |
| search_chats(text) | find an old chat | sidebar search | safe | results |

**New ideas (cross-app, A14):** "ChatGPT se poochho ye error kya hai" (VS Code problem text → ask → speak answer); "ChatGPT ka code VS Code mein daalo" (copy_last_code → VS Code paste at cursor); "is screen ke baare mein ChatGPT se poochho".
