# Chutku: problems, research and roadmap for Brain 2

> 2026-11-10, owner Siddhant Vashisth. A companion to [`BRAIN_2_PLAN.md`](BRAIN_2_PLAN.md). It lists every known
> problem (basic to hidden real-world ones), the AirLLM verdict, open-source projects that solve them, and the order
> of work. Every adopted idea ships only after a measured gate: scenario success, seconds against doing it by hand,
> and a safety negative case. Licences (MIT/Apache) are checked before any code is copied.

## 1. Problems, basic to advanced

### A. Basic (a user hits these on day one)
1. **Brand-new multi-step tasks are slow the first time.** The planner can take tens of seconds; a user
   compares that with 5–7 s by hand.
2. **Gemini and Groq free-tier rate limits.** Bursts give "quota/busy", slow replies and half-done tasks.
3. **No internet means a weak brain.** The offline packs are big and optional, and most users won't have them.
4. **SmartScreen "Windows protected your PC"** (the setup is unsigned) scares new users at the download.
5. **The Ctrl+Alt+Space hotkey can be taken** by another app.
6. **Mishearing:** Hinglish speech-to-text, names and app names ("telegrm", "kitkat"), and noisy rooms.
7. **"What can I say?"** discoverability is still limited; new users don't know what Chutku can do.
8. **Hindi or Hinglish voice replies** are uneven (the TTS sounds English-first).
9. **Low-end PCs:** RAM and CPU use at idle, and the first start-up time.

### B. Intermediate (real use shows them)
10. **Context gaps:** "usme / wahi / uske andar" across turns, earlier sessions, and what is on screen right now
    are not always joined together.
11. **Half-done requests:** six asks done as four, with no check that every part finished.
12. **Unknown apps and changing UIs:** the per-app atlases cover about 12 apps; any other app or a redesigned UI
    breaks the flows.
13. **Locks and passwords:** a locked chat or app lock needs a clean "pause, let the owner unlock, continue",
    and passwords must never be stored or sent.
14. **Learning is narrow:** reflex skills need two similar successes, and practice covers the task bank, not the
    user's own apps.
15. **No action replay cache:** a successful UI path is not stored as a replayable script, so it is re-planned
    every time.
16. **Suggestions:** none, or a risk of nagging; there is no "only when it's worth it" gate.
17. **Night practice is plan-mode only:** live practice and the GPU fine-tune trainer are not built yet.
18. **First-time ask policy undecided** (the owner's open question).
19. **Telegram and phone pairing still take several steps** for a non-technical user.
20. **Updates:** the setup is about 316 MB on every update, with no delta updates.

### C. Advanced (scale, safety, trust)
21. **Grounding on non-UIA apps** (games, Electron, canvas apps): UI Automation sees nothing, so vision parsing is
    needed.
22. **Prompt injection from screen text, web pages and messages** grows as Chutku acts more on its own.
23. **Code protection:** compiled `.pyc` plus hidden folders can be decompiled. Nuitka or similar is pending.
24. **Privacy:** screen text and history in cloud prompts; a clear on/off for the "know me" profile and the
    timeline.
25. **Multi-monitor and DPI scaling, and different keyboard layouts and locales** on users' PCs.
26. **Crash recovery mid-task** (power cut or sleep during a long job): resume or roll back cleanly.
27. **No anonymous crash or failure reports from users**, so we can't see what fails in the wild.
28. **Accessibility for users** (screen readers, large text), and languages beyond Hindi and English.
29. **GitHub Actions is unpaid**, so every release is a manual PC build with no automatic CI.
30. **Legal and licences:** non-commercial voice models block any future paid tier; check the licences of the
    models and repositories we adopt.

### D. Hidden: not a problem today, but will be with real users
31. **Chutku fights the user for the mouse and focus:** it acts while the user is typing, so keys land in the
    wrong window. It needs "hands-off" (background or UIA-only) actions, or to wait until the user pauses.
32. **Antivirus false positives:** an unsigned exe that injects input and runs PowerShell gets flagged or
    quarantined by Defender, Avast or Quick Heal. This is common in India.
33. **Office and school PCs:** no winget, blocked PowerShell, proxies or firewalls. Chutku must degrade and say why.
34. **Slow or patchy internet** (mobile hotspot, 4G): cloud calls time out mid-task. It needs retries, partial
    progress and an offline fallback per tier.
35. **Free tiers change or vanish:** if Gemini or Groq cut the free tier, every user breaks at once. It needs
    multi-provider routing (Cerebras, OpenRouter, NVIDIA NIM) and a local small-model floor.
36. **Irreversible actions:** a sent WhatsApp message, an email or a purchase cannot be undone. The confirmation
    must show exactly *who* and *what* before sending, and the wrong-recipient risk grows with fuzzy names.
37. **Shared PCs:** family members, kids, guests. Voice lock helps, but there are no profiles, so one person's
    memory, chats and approvals mix with another's.
38. **Elderly and non-English-literate users:** reading UI text, typing keys, understanding errors. The app needs
    voice-first answers and Hindi UI text.
39. **Trust and explanations:** "why did you do that?" and "what will you do?" must be answerable in one plain
    line, or users stop trusting it after one surprise.
40. **Laptops:** battery drain from the wake listener, the GPU model and the phone stream. It needs an eco mode on
    battery.
41. **Memory growing forever:** logs, history and embeddings get slow or huge over months. It needs compaction and
    archiving.
42. **Windows updates change Settings pages and app UIs,** silently breaking learned paths. Replay steps need a
    check that fails safely and re-plans.
43. **Support at scale:** when a stranger's Chutku fails there's no way to see why. It needs an opt-in "send this
    failure report" with private data removed.
44. **Updates breaking working setups:** a new version may change behaviour users relied on. It needs a staged
    rollout or a "go back to the previous version" option.

---

## 2. AirLLM: verdict
- **What it is:** it runs huge models (70B up to Kimi 2.8T, GLM, Qwen, DeepSeek) on a 4 GB GPU by streaming one
  layer at a time from disk ([repo](https://github.com/lyogavin/airllm)).
- **Reality:** about **2–47 seconds per token** for a 70B model even on a fast NVMe; one reply takes minutes
  ([measurements](https://runaihome.com/blog/airllm-70b-4gb-vram-inference-guide-2026/),
  [analysis](https://www.mattcullerton.com/tokdocs/airllm-runs-llama-3-3-70b-on-a-4gb-gpu-by-streaming-layers-from-disk-but-expect/)).
  It also needs hundreds of GB of disk, and Windows support isn't documented.
- **So:** it is **useless for live requests**, where speed is the owner's top need. It **can be useful offline at
  night** for a "teacher" model: Night Shift lets a huge model slowly re-solve the day's failed or hard tasks and
  write high-quality verified plans, which become fast paths and fine-tune data for the small fast models. That
  fits the existing practice and LoRA pipeline (`chutku/practice`, `data/finetune`).
- **Plan:** a small spike on the PC. Install AirLLM and run a mid-size model (for example Qwen 32B or 72B) on one
  night batch; measure seconds per task and the gain in solved items. Keep it only if it beats the Gemini or Groq
  free tier on quality per night.

## 3. GitHub projects that solve our problems

| Project | What it does | Problems it helps (#) | How we'd use it |
|---|---|---|---|
| [microsoft/UFO (UFO²)](https://github.com/microsoft/UFO) (MIT) | Windows "Desktop AgentOS": UIA plus vision, per-app agents, **speculative multi-action** (several steps in one LLM call, up to 51.5% fewer calls) | 1, 11, 12, 21 | Borrow the speculative multi-action idea and the per-app agent pattern for Brain 2's tier 3 |
| [microsoft/OmniParser](https://github.com/microsoft/OmniParser) | Turns any screenshot into structured clickable elements | 12, 21 | A vision fallback when UIA sees nothing |
| [Jeomon/Windows-Use](https://github.com/Jeomon/Windows-Use) | A light Windows GUI agent on the UIA tree, any LLM, no vision model | 12 | Compare its UIA-tree prompt format with ours, to keep prompts small and fast |
| [pig-dot-dev/muscle-mem](https://github.com/pig-dot-dev/muscle-mem) | A **behaviour cache**: records successful tool trajectories, replays them with no model, falls back to the agent on edge cases | 1, 14, 15 | The core of "second time faster than a human": a replay cache with per-step checks |
| [a11y-computer-use #123](https://github.com/Perception-Dynamics-Inc/a11y-computer-use/issues/123) | Saves runs as skill files with durable locators and checks; only failing steps go back to the planner | 15 | The design pattern for our replay skills |
| [getzep/graphiti](https://github.com/getzep/graphiti) | A temporal knowledge graph (facts with valid/invalid time), best long-memory score (LongMemEval 71%) | 10, 14 | Upgrade the mind graph to time-aware facts and relations ("Kitkat → WhatsApp/Locked") |
| [mem0ai/mem0](https://github.com/mem0ai/mem0) / [letta-ai/letta](https://github.com/letta-ai/letta) | Memory layers; Letta does self-editing memory and "sleep-time compute" | 10, 14 | Letta's sleep-time idea fits Night Shift (consolidating memory at night) |
| [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) / SimulStreaming / Parakeet | Streaming speech-to-text with low latency | 6 | Lower voice latency and partial results while the user speaks |
| [OpenWhispr](https://github.com/OpenWhispr/openwhispr) / Sotto (Whisper on OpenVINO, Hindi/Hinglish) | Local dictation with good Hinglish | 6, 8 | Hinglish speech-to-text quality and CPU speed on low-end PCs |
| [Nuitka](https://nuitka.net/) | Python to native code compiler | 23 | Native build of `chutku/` (the commercial edition adds encryption) |
| [lyogavin/airllm](https://github.com/lyogavin/airllm) | Huge models on 4 GB VRAM, slowly | 3, 14, 17 | A night-only teacher (section 2) |
| [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) + UI-TARS-1.5 (2B/7B) | An open GUI agent model that sees the screen and clicks; the 2B model is small enough for a local GPU | 1, 12, 21 | A local vision grounding model: "where is the Locked chats button?" without a cloud call |
| [ShowUI](https://github.com/foukation/ShowUI) | A lightweight vision-language-action GUI model | 21 | An alternative small grounding model |
| [AI4Bharat/IndicF5](https://github.com/AI4Bharat/IndicF5) | Near-human TTS for 11 Indian languages, including Hindi | 8, 38 | A natural Hindi voice for replies (check the licence) |
| [AI4Bharat/IndicConformerASR](https://github.com/AI4Bharat/IndicConformerASR) | Open speech-to-text for all 22 Indian languages | 6, 28, 38 | Better Hindi speech-to-text than Whisper for Indian accents |
| [LiteLLM router](https://github.com/BerriAI/litellm) ([free-tier example](https://github.com/sarthakjain004/llm-router)) | One endpoint, automatic failover across Gemini, Groq, Cerebras, OpenRouter and NVIDIA NIM | 2, 34, 35 | Multiplies free capacity and survives one provider failing. Groq free tier: 30 requests/min, 1,000/day |
| [browser-use](https://github.com/browser-use/browser-use) | A strong open web-automation agent on the browser's DOM | 12 | Ideas for faster web tasks in the signed-in browser |

Curated lists for more ideas: [trycua/acu](https://github.com/trycua/acu),
[awesome-computer-use](https://github.com/12britz/awesome-computer-use).

---

## 4. Suggested order of work (most user impact per token first)
| Phase | What | Fixes problems | Who |
|:-:|---|---|---|
| 1 | **Replay cache** (muscle-mem pattern) plus a "finish every part" checklist | 1, 11, 14, 15, 42 | web Claude: code and tests; PC: live timing |
| 2 | **Multi-provider router** (LiteLLM-style fallback across free tiers) plus speculative multi-action (UFO²) | 2, 34, 35, 1 | web Claude |
| 3 | **Context pack** (session, past sessions, screen) plus a temporal mind graph (Graphiti ideas) and fuzzy names | 10, 6, 36 | web Claude |
| 4 | **Vision fallback:** UI-TARS-2B or OmniParser locally, for apps UIA can't see | 12, 21 | PC (GPU tests) |
| 5 | **Gated suggestions** and "hands-off" actions that never fight the user's mouse | 16, 31, 39 | web Claude |
| 6 | **Hindi voice:** IndicConformer speech-to-text and IndicF5 TTS, plus eco mode on battery | 6, 8, 38, 40 | PC (models) |
| 7 | **Night teacher:** AirLLM spike, then the GPU LoRA trainer | 3, 17 | PC |
| 8 | **Trust and support:** opt-in failure reports, rollback of updates, Nuitka build | 23, 32, 43, 44 | PC |
