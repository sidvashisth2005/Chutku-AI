# Chutku Brain 2: understand, act, finish — fast, accurate, on any task

> Status: DRAFT plan (2026-11-09), owner Siddhant Vashisth. Branch `claude/brain-2`. Nothing here touches `main` or
> the releases repo. This is the plan a cloud session and the PC session both work from; it is not a promise that
> every line is built. Build it in phases; each phase must pass the gate in AGENTS.md before the next.

## 1. What the owner asked for (the contract, in his words)

Chutku ships to ordinary new users. From their point of view:

1. **Execute, don't interrogate.** The user says a thing; Chutku does it. No back-and-forth, no "teach me first".
2. **Do it fully and accurately.** Not half the request. If six things were asked, all six happen, in order.
3. **Add value on its own, and suggest.** When there is a clearly useful extra step or a better way, Chutku does
   the sensible extra or offers ONE short suggestion. Suggestions are a real feature — but gated, only when the
   suggestion is genuinely worth it, never on every turn.
4. **Fast.** If a task would take the user ~5-7 seconds by hand, Chutku should match or beat that. A plan that takes
   50-60 seconds to think is a failure — the user would just do it himself.
5. **Any task, any complexity, any phrasing.** Not two or three rehearsed flows. A human can say anything; Chutku
   must cope with new, multi-step, messy requests, not only the ones it was trained on.
6. **Context.** It understands exactly what is being said: this session's earlier turns, past sessions, the mind
   graph, and what is on screen right now.
7. **Learn and remember.** Each task updates the memory graph and, where it worked, becomes a fast path next time,
   so the same thing is instant later.

Use existing models (Gemini, Groq/Cerebras). We do NOT train our own LLM; that will never beat them for free.

## 2. The honest constraints (say these out loud, do not pretend otherwise)

- **Speed and novelty trade off.** A *known or learned* task can be sub-second to a couple of seconds. A *brand-new
  multi-step UI task* the FIRST time cannot be 5 seconds: looking at the screen, acting, and checking each step
  takes real time. The honest promise is: first time it is careful (and may be slower than manual); after that it is
  a learned fast path and beats manual. Tier 3 below is where we spend effort to shrink that first-time cost.
- **We cannot pre-train every scenario.** Coverage does not come from listing cases; it comes from a design that
  generalises: understand -> work from the live screen -> verify -> learn. The scenario test set (section 8) measures
  how well that generalisation holds, it does not enumerate the world.
- **Locks and passwords are a hard stop, not a question.** A locked chat, an app lock, a password box: Chutku pauses
  and asks the owner to unlock, then continues. This is safety, not weakness. No password is ever logged or sent to
  any model or the cloud.
- **Free tiers are rate-limited.** Groq/Cerebras/Gemini free tiers count tokens per minute. The design must keep
  prompts small and calls few, or it gets slow and throttled. Speed work and token budget are the same work.

## 3. The shape: three speed tiers

Every request is answered at the cheapest tier that can do it correctly. Learning pushes requests DOWN the tiers
over time, which is how the speed goal is met for repeat work.

- **Tier 1 - Reflex (milliseconds, no model).** Fixed phrases and learned skills. Already exists
  (`quick_intents`, `reflex`, `skill.<name>`). Goal: grow this set from real use so the common things are instant.
- **Tier 2 - One-shot (one fast cloud call, ~1-2 s).** A single clear action with a known target: one call to the
  fastest model (Groq), execute, verify, done. No multi-round loop.
- **Tier 3 - Deliberate (the full loop).** Novel or multi-step work. Understand -> plan -> act on the live screen one
  step at a time -> verify each -> recover on failure -> learn. Slower, but this is where "any task" lives. Every
  Tier-3 success that is clean becomes a Tier-1/2 fast path for next time.

A router decides the tier from: is it a known reflex/skill? is it one action with a resolvable target? else Tier 3.

## 4. Tier 3 loop: understand -> act -> finish (the core of "thinks like a human")

### 4.1 Understand first (one cheap step, produces a task card)
Before planning tool calls, one model call turns the request + context into a structured task card, e.g.:

```
intents: [ open WhatsApp, open locked-chats (needs unlock), open chat "Kitkat" (first in list), send "hello" ]
targets: { app: WhatsApp, place: Locked chats, chat: {name: Kitkat, position: 1}, message: "hello" }
unknown: []            # anything it could not resolve
confidence: high
```

- If something critical is **unknown and cannot be inferred**, that is the only time it asks — one short question,
  not an interview.
- Otherwise it does NOT ask. It shows the understanding as a **non-blocking one-liner while it is already acting**
  ("WhatsApp -> Locked chats -> Kitkat -> 'hello'"), so the user can interrupt if it is wrong, but nothing waits on
  a reply. This is how we satisfy "execute, don't interrogate" and still stay transparent.

### 4.2 Act on the live screen, step by step
Open app -> look at the window -> decide the next real action -> do it -> look again -> next. After each action it
re-reads the screen (`desktop.look` / `screen.understand`) so it reacts to what is actually there, not to a guess.
On a dead end it tries another route; only if genuinely stuck does it ask one specific question.

### 4.3 Finish fully and verify
All parts of the request must complete, in order. Each changing step is checked (message actually sent, chat
actually open). The reply is honest about what happened. "Half done" counts as a failure in the test set.

### 4.4 Lock / password handling
On any lock, app-lock or password screen, Chutku stops and asks the owner to unlock, then resumes from exactly
there. Passwords stay with the owner; never stored, logged, or sent anywhere.

## 5. Context pack (what every Tier-2/3 call gets)

Small, relevant, and privacy-safe (same redaction rules as today — no file contents, clipboard, or typed secrets
leave the machine):

- **This session:** the last few turns, so "usme", "wahi", "uske andar" resolve.
- **Past sessions:** only related items, pulled by search over history (not everything).
- **Mind graph:** people, chats, groups, and which app each lives in (Kitkat -> WhatsApp/Locked; Chutku -> Telegram).
- **Live screen:** the foreground app and what its window currently shows.
- **Fuzzy names:** mis-heard or mis-typed app/chat names ("logged", "telegrm") map to the real one by sound and
  spelling, so the right app's own tools are offered to the model instead of falling back to web search.

## 6. Learn and remember (gets smarter, and faster, by itself)

- After each task, update the mind graph with what was learned (where a chat lives, a new alias, a correction the
  owner made: "no, the Telegram one").
- A clean Tier-3 success is saved as a fast path (a skill / past-success example), so the same request is Tier-1/2
  next time. This is the engine of the speed promise for repeat work.
- Corrections are remembered so the same mistake is not repeated.
- This reuses what already exists (mind graph, history index, skills, practice/Night Shift); Brain 2 wires them into
  the loop instead of adding a new memory model. No LSTM/RNN of our own.

## 7. Proactive help and suggestions (a gated feature)

- **Do the sensible extra automatically** only when it is low-risk, clearly implied, and reversible (owner/Full
  autonomy already allows more without asking).
- **Offer ONE short suggestion** only when a clearly-valuable adjacent action exists with high confidence. Not every
  turn. The user's accept/ignore is logged so Chutku learns which suggestions are wanted and stays quiet otherwise.
- Never let a suggestion delay or replace the actual task.

## 8. How we prove it (the gate for every phase)

- **Scenario test set:** ~100+ real, messy, multi-step requests (including this WhatsApp-locked-chat case and the
  Telegram one), in English/Hindi/Hinglish, with the correct outcome for each. Built from the Activity log of real
  failures, grown over time. This is the "all variety of tasks" measure.
- **Accuracy:** full completion (all parts), correct target, no wrong action. Half-done = fail. Report on a
  held-out slice so we measure real generalisation, not memorised answers.
- **Latency budget (hard numbers, measured, not hoped):**
  - Tier 1: < 0.3 s. Tier 2: target < 3 s end to end. Tier 3: first time as fast as the loop allows, and the SAME
    request must drop to Tier 1/2 on repeat. Every change reports before/after latency, like the task-bank work did.
- **Safety negative cases:** locks stop; damage refused; nothing private leaves the machine. Fail-closed.

## 9. Phases (each ships something that works; gate between each)

| Phase | What | Verified where |
|:--:|:--|:--|
| 1 | Router + Understand step + context pack + fuzzy app/chat names + non-blocking "understood" line | Linux here (fakes) |
| 2 | Tier-3 screen loop: look -> act -> verify each step, recover on failure | Owner's PC (real UI) |
| 3 | Lock / password hard-stop and resume | PC |
| 4 | Learn: graph update + clean success -> fast path; corrections remembered | Linux + PC |
| 5 | Proactive extra + gated suggestions | Linux + PC |
| 6 | Scenario test set + model A/B (Gemini vs Groq per tier) + latency report | Linux + PC |

## 10. What stays untouched

- `main` and the releases repo: not touched by this work. All of it lands on `claude/brain-2` first.
- Existing safety: text from pages/messages never authorises an action; private data never leaves; laptop-only
  steps stay laptop-only; no step runs elevated without the Windows prompt.
- No new paid service, no self-trained model. Existing free models only.

## 11. Open questions for the owner

1. The example: the locked chat "Kitkat" was in **WhatsApp** (password 123456), right? Confirm so Phase 2 targets
   that exact flow first.
2. Default autonomy for new users: should a fresh install default to "Full / do more on its own" (fewer stops,
   matches "execute, don't interrogate") or stay at the safer "Safe steps by themselves"? This is an owner choice.
3. Which apps matter most for the first scenario set (WhatsApp, Telegram, Chrome/Brave, ...), so we cover those
   first.

## 12. Research additions (2026-11-10, PC session)
See [`PROBLEMS_AND_RESEARCH.md`](PROBLEMS_AND_RESEARCH.md) (44 problems, AirLLM verdict, projects, phases). It
adds these to this plan:
- **Tier 1.5, the replay cache** (the muscle-mem / a11y-computer-use pattern): a clean success is saved as a script
  with locators and checks and replayed with no model; only a failing step goes back to the planner.
- **Speculative multi-action in tier 3** (UFO²): several predicted steps per model call, so fewer calls.
- **Multi-provider router** (LiteLLM-style failover across the Gemini, Groq, Cerebras, OpenRouter and NIM free
  tiers), so one provider's limit or outage does not stop Chutku.
- **Vision fallback** for apps UI Automation cannot see: a local UI-TARS-2B or OmniParser.
- **Temporal mind graph** (Graphiti ideas: facts with valid-from and valid-to) plus memory consolidation at night
  (Letta's "sleep-time" idea).
- **Hands-off actions:** never fight the user's mouse and keyboard; act in the background or wait for a pause.
- **Night teacher:** an AirLLM spike (too slow live, at 2–47 s per token; possibly useful at night).
- **Hindi voice:** IndicConformer speech-to-text and IndicF5 TTS (check the licences).

