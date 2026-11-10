# Chutku Delivery Gate

> **Where to look first:** [`docs/CODEMAP.md`](docs/CODEMAP.md) (one line per module), then only the files your task
> needs. Current state and the newest entries are in `IMPLEMENTATION_STATUS.md`. Both cloud handoffs (1.0 W1–W8 and
> 1.2 WA1–WA6) are merged into `main`. The owner's open steps are in [`docs/HANDOFF.md`](docs/HANDOFF.md).
> `docs/archive/` holds finished plans and old history: don't read it unless the task asks for that history.

This repository uses a verification-first delivery rule.

Before reporting any implementation change as delivered, an agent must:

1. Run the relevant automated tests.
2. Run at least one real command path for changed user-facing behavior.
3. Inspect the result for the required final state or verification outcome.
4. Fix failures before continuing to dependent work.
5. Update `IMPLEMENTATION_STATUS.md` in the same change with concrete verification evidence.

Do not describe unexecuted code as implemented, verified, safe, or complete. Do not carry a failing or unverified component forward as a foundation for later work.

For safety-sensitive behavior, verification must include a negative case that proves the boundary fails closed where practical.

## Engineering principles

These are adapted from Andrej Karpathy's notes on LLM coding mistakes. The full text is in
`.claude/skills/karpathy-guidelines/SKILL.md` (MIT, forrestchang/andrej-karpathy-skills).

1. **Think before coding.** State your assumptions, and name any tradeoff or simpler route. Ask only about owner
   decisions: changing or deleting the owner's files, publishing, R4 actions, and unknown recipients. Otherwise state
   the assumption in one line and proceed.
2. **Simplicity first.** Write the minimum code that solves the request. No speculative features, single-use
   abstractions or unrequested configuration. If 200 lines could be 50, rewrite it. Take the first rung of this
   ladder that fully works (from `.claude/skills/ponytail`, MIT):
   1. Is it needed at all?
   2. Is there already a helper in this repo?
   3. Does the standard library do it?
   4. Does an installed dependency do it?
   5. Does one clear line do it?
   6. Otherwise, write the minimum code.

   Never cut validation at trust boundaries, data-loss handling, security or anything the owner asked for. A known
   limit gets a `# shortcut: <the limit>, <when to upgrade>` comment.
3. **Surgical changes.** Every changed line traces to the request. Match the surrounding style. Remove what your own
   change made unused. Remove pre-existing dead code only when the owner asks for a cleanup, and only after grepping
   for both symbol and string references (tools are registered and reached by name). Never turn off a working
   user-facing mode as a side effect.
4. **Goal-driven execution.** Turn each task into a check that can fail: a test that reproduces the bug, or the gate
   above. Loop until it passes.

## Helper-agent prompts

Every prompt given to a helper agent (sub-agent) or a skill with your own input is recorded in `docs/AGENT_PROMPTS.md`: word for word, with the date, why it was used and what came of it. Add the entry in the same change that uses the agent's result.
