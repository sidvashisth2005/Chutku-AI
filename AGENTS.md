# Chutku Delivery Gate

This repository uses a verification-first delivery rule.

Before reporting any implementation change as delivered, an agent must:

1. Run the relevant automated tests.
2. Run at least one real command path for changed user-facing behavior.
3. Inspect the result for the required final state or verification outcome.
4. Fix failures before continuing to dependent work.
5. Update `IMPLEMENTATION_STATUS.md` in the same change with concrete verification evidence.

Do not describe unexecuted code as implemented, verified, safe, or complete. Do not carry a failing or unverified component forward as a foundation for later work.

For safety-sensitive behavior, verification must include a negative case that proves the boundary fails closed where practical.

## Helper-agent prompts

Every prompt given to a helper agent (sub-agent) or a skill with your own input is recorded in `docs/AGENT_PROMPTS.md`: word for word, with the date, why it was used and what came of it. Add the entry in the same change that uses the agent's result.
