# Contributing to Chutku

Thank you for helping. Chutku acts on real PCs, so the bar is "proven", not "probably works".

## Setup

```powershell
.\Install-Chutku.cmd
.\.venv\Scripts\python.exe -m pip install -e ".[test,dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests      # about 4 minutes; never starts a model or the mic
```

## The delivery gate (from [AGENTS.md](AGENTS.md))

A change is delivered only when:
1. The relevant automated tests pass, and the full suite stays green.
2. At least one real command path for the changed behavior was run.
3. For safety-sensitive behavior, a negative case shows the boundary fails closed.
4. [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) gets an entry with the evidence (what you ran, how long it
   took, how the result was checked).

Never describe code you have not run as working.

## Coding principles

From [AGENTS.md](AGENTS.md), adapted from Andrej Karpathy's notes and the ponytail skill:
- Think first and state your assumptions.
- Write the smallest complete change. Prefer an existing helper, then the standard library.
- Make surgical diffs: every changed line traces to the task.
- Define a check that can fail, then make it pass.

Also:
- Every tool declares its risk level, argument schema and an independent verification. New R3+ tools must be listed
  in [docs/SECURITY.md](docs/SECURITY.md); a test enforces this.
- A tool's description is part of its contract hash. Changing it invalidates learned skills, so only change it on
  purpose.
- Keep files' line endings as they are (many are CRLF).
- Tests never touch the real desktop, microphone, network or models; mock them.

## Reporting a security problem

Please do not open a public issue. Use GitHub's private vulnerability reporting for this repository.
