# Chutku

**A free, open-source voice assistant that runs your Windows PC.** Say what you want in English, Hindi or
Hinglish: "Spotify pe After Party chalao", "meri last PDF kholo", "build me a calculator app",
"bluetooth settings kholo", "D drive mein kitni jagah hai". Chutku plans the steps, does them, checks each result
independently, and tells you honestly what happened.

It works with **free cloud brains** (Groq, Gemini) when you are online and **local models** when you are not.
Your files, screen text and memory stay on your PC.

> Status: works daily on the author's PC. Measured results, with the limits that are still open, are in
> [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Things that are not proven yet say so there.

## What it can do

| Area | Examples |
|---|---|
| Apps and windows | Open, close and switch apps; minimize, maximize and focus windows; recipes for Spotify, VLC, Telegram, VS Code, Explorer, Settings, Notepad, ChatGPT and Discord |
| Files | Find, open, copy, move, rename, organize and recycle files on any drive. Every change can be undone ("pichhle 10 minute ka sab wapas karo") |
| Web | Search, read pages, news, weather, YouTube, and form steps in a separate browser |
| PC | Volume, brightness, Wi-Fi/Bluetooth settings, battery, disk, RAM, CPU and GPU status, screenshots, clipboard |
| Screen | "What's on my screen?", and "click the first video" on what is visible |
| Messages | WhatsApp and Telegram drafts and sends, which always ask first |
| Coding | "Build me a snake game": writes the project, tests it, fixes its own errors and opens it in VS Code |
| Memory | Remembers people, preferences and what you did ("wo PDF jo kal shaam khola tha") |
| Routines and timers | "30 min baad ...", "har 15 min ...", reminders, scheduled tasks |
| Phone | Pair your phone over your own Tailscale network for chat, voice and approvals (setup needed) |

Talk with **Ctrl+Alt+Space** from any app. The emergency stop is **Ctrl+Alt+F12**.

## Safety model

- An LLM never decides what is allowed. Each tool has a fixed risk level, and the policy kernel outside the model
  decides.
- You choose how much runs by itself. Deleting, sending messages, running code or commands, power actions and
  messages to unknown people **always** wait for your click.
- System folders (Windows, Program Files, AppData...) are never modified.
- Every step is verified by an independent check. The answer ends with a tally such as
  `[Verified: 2 of 2 steps completed.]`.
- Text read from files and web pages is treated as untrusted and cannot order Chutku around.
- Everything is logged locally with a hash chain. Private browser windows are never recorded.

Details: [docs/SECURITY.md](docs/SECURITY.md) and [docs/DESIGN.md](docs/DESIGN.md).

## Requirements

- Windows 10 or 11, as a normal (non-administrator) user.
- Python 3.11 or newer from [python.org](https://www.python.org/downloads/).
- A microphone for voice.
- For offline use: about 8 GB of disk space for the local models. A GPU with Vulkan support (4 GB or more) makes
  them much faster. Without one, Chutku uses the cloud brains or the CPU.

## Install

```powershell
git clone https://github.com/<you>/Chutku.git
cd Chutku
.\Install-Chutku.cmd                 # packages + health check
.\Install-Chutku.cmd -Models         # also download the local models (offline use, hash-checked)
.\Install-Chutku.cmd -Autostart      # also start Chutku when you sign in
```

Then double-click **Start-Chutku.cmd**.

**Free brains (optional, recommended).** Make a free key at [console.groq.com/keys](https://console.groq.com/keys)
and/or [aistudio.google.com](https://aistudio.google.com/apikey), then:

```powershell
.\.venv\Scripts\python.exe -m chutku.cli cloud set-key groq
.\.venv\Scripts\python.exe -m chutku.cli gemini set-key
.\.venv\Scripts\python.exe -m chutku.cli authority grant cloud.gemini
```

Keys are kept in Windows Credential Manager, never in a file. The cloud sees your request, the tool list and public
results. File contents, clipboard, screen text and your memory are not sent.

## Docs

- [docs/OWNER_GUIDE.md](docs/OWNER_GUIDE.md): everything to say, controls, safety rules, troubleshooting
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEVELOPER.md](docs/DEVELOPER.md): how it is built, CLI
  and verification scripts
- [CONTRIBUTING.md](CONTRIBUTING.md): how to contribute (tests, the delivery gate, coding principles)

## License

MIT; see [LICENSE](LICENSE). Third-party components and models have their own licenses, listed in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
