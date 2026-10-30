"""Remote access from the owner's phone (W6 = HERMES_PLAN P1-P9, owner order 2026-10-29: "full control from my
phone if the PC is online").

- tailscale.py: the phone reaches the laptop only through the owner's own tailnet (`tailscale serve`, HTTPS with
  a real certificate); Funnel (public internet) is detected and stops everything.
- auth.py: one-time pairing codes, per-device credentials (only hashes stored), a phone PIN (scrypt) for sessions,
  approvals, screen view and control, single-use approval nonces, rate limits, revocation.
- control.py: direct mouse/keyboard from the phone, armed only at the laptop, with the laptop always winning, a
  kill hotkey, fresh consent for command windows, and every input logged with typed text redacted.
- server.py: the phone-only HTTPS-fronted API on 127.0.0.1 (never 0.0.0.0) and the installable phone app.
"""
