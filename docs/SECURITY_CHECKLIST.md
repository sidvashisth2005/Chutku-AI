# Software Security & Testing Checklist: Chutku's answers

Every item of `Software Security & Testing Checklist.pdf` (Nov 9, 2026), checked against the code on 2026-11-13.
The rules themselves are in [`SECURITY.md`](SECURITY.md); the tests for every fix are in
`tests/test_security_checklist.py` (run against the code before these fixes, 16 of its first 20 tests failed; the other
4 are fuzz and regression guards that must pass both before and after).

**What Chutku is, for this list.** A same-user Windows assistant with three servers:

| Server | Reach | Users |
|---|---|---|
| dashboard (`chutku/dashboard.py`) | 127.0.0.1 only, per-launch token | the owner |
| phone server (`chutku/remote/`) | 127.0.0.1, published only in the owner's tailnet (HTTPS) | the owner's phones |
| account relay (`chutku/relay/server.py`) | the internet, behind TLS | every installed copy |

There is no SQL/NoSQL database with user queries, no templates, no GraphQL, no cloud bucket, no Docker image and no
mail domain. Items that need one of those are marked **N/A** with the reason.

**Verdicts:** **Fixed** = changed today, with a test. **In place** = already true, with where.
**Kept** = deliberately not done (owner decision or not worth it), with why. **Owner** = only the owner can do it
(listed in `docs/HANDOFF.md`). **N/A** = the thing does not exist here.

## Part 1: Security vulnerabilities

### 1. Injection

| Item | Verdict | Evidence |
|---|---|---|
| SQL injection | In place | Every query uses `?` parameters (bandit B608 reviewed: the 2 string-built queries add only a constant or `?` marks; `nosec` with the reason). |
| NoSQL injection | N/A | No NoSQL store. JSON bodies are checked for exact key sets and types (`set(data) != {...}` in `dashboard.py`). |
| Command injection | In place | All 63 `subprocess` calls pass argument lists; no `shell=True`, no `os.system` (bandit clean). Typed text goes to helper CLIs on stdin. |
| LDAP / XPath | N/A | Neither is used. |
| Template injection | N/A | No server templates; pages are static files; the one generated page (`help_page.py`) escapes text. |
| Code injection | In place | No `eval`/`exec`/`pickle`/`marshal` on outside data (bandit clean). Model-written code runs only via `code.run_python` / skills, which always ask first (`SECURITY.md` §1). |
| Header / log injection | **Fixed** | `core/log.py` now escapes CR/LF, so a goal or error text cannot forge a log line (`LogInjectionTests`). Headers: only fixed values or NTFS file names (no CR/LF possible). The action log is JSON. |

### 2. Client-side / browser

| Item | Verdict | Evidence |
|---|---|---|
| XSS | In place | No `innerHTML` in any page script (all `textContent`/DOM nodes); CSP `script-src 'self'` on all three servers. |
| CSRF | In place | Dashboard: token header + exact Origin + `Sec-Fetch-Site`. Phone: per-session CSRF header + Origin; cookie `SameSite=Strict`. Relay: bearer token (browsers never send it on their own). |
| Clickjacking | In place | CSP `frame-ancestors 'none'` on all three. |
| Open redirect | In place | The only redirect (`alias.py`, chutku.localhost) goes to a fixed server-made URL. |
| CORS | In place | No `Access-Control-Allow-*` header anywhere (`test_security_headers_and_no_cors`). |
| Insecure browser storage | Kept | Phone cookie is `HttpOnly; Secure; SameSite=Strict`. The relay phone app keeps its bearer token and E2E key in `localStorage` (a header token can't be HttpOnly); the CSP + no-`innerHTML` rule is the XSS barrier. Upgrade path noted in `phone.js` (`shortcut:`). Dashboard token: `sessionStorage`, one launch only. |

### 3. Authentication and sessions

| Item | Verdict | Evidence |
|---|---|---|
| Weak passwords | **Fixed** | The relay only ever sees a PBKDF2-derived value, so its 8-character check never saw the real password. `relay/client.password_problem` now refuses short, common, too-simple and ID-containing passwords before anything is sent (`PasswordStrengthTests`). Shortcut: a built-in common list, not a full breached list. |
| Brute force / stuffing | **Fixed** | Per-ID lockout (5 → 15 min) was there; now also 20 failed sign-ins per address per hour across all IDs (`test_many_wrong_sign_ins...`). Phone: 5 wrong PINs remove the phone; pairing locks after 5 wrong codes. |
| Missing MFA | In place | Phone access = Tailscale account + device credential + PIN. Relay phone = password + device token, and the laptop's own PIN for approvals, screen and control. |
| Password storage | In place | scrypt (relay accounts, PINs); only SHA-256 of tokens and credentials. |
| Session fixation / hijacking | In place | Fresh random session on every phone login; cookie `HttpOnly; Secure; SameSite=Strict`; dashboard token per launch. |
| Sessions never expire | In place / Kept | Phone session 12 h, PIN session 30 min, approvals single-use. Relay device tokens last until logout or password change: **owner decision 2026-11-06** ("stay signed in"); a password change signs out every other device. |
| JWT flaws | N/A | No JWTs. |
| Broken password reset | N/A | No reset flow: the password is changed only on the signed-in laptop. Login errors never say whether an ID exists, and now an unknown ID costs the same scrypt as a known one (**Fixed**, `test_an_unknown_id_costs...`). |
| OAuth / SSO | N/A | No OAuth. Tailscale identity comes from `tailscale serve`'s header plus an exact Host. |

### 4. Authorization

| Item | Verdict | Evidence |
|---|---|---|
| IDOR | In place | Relay requests go only to the same account's laptop, replies only to the same account's waiting request (`test_tokens_and_accounts_are_kept_apart`); the phone sees only phone-started tasks. |
| Privilege escalation | In place | Every step passes `PolicyKernel.authorize`; laptop-only steps (R4, code, unknown recipients, never/remote rules) can't be approved from the phone or Telegram. Chutku refuses to act when elevated. |
| Missing server-side checks | In place | All checks are server-side (kernel, approvals bound to task + args + manifest hash); a model's own "risk"/"confirmed" is ignored. |
| Mass assignment | In place | Bodies are matched against exact key sets; the relay's register/login read named fields only. |
| Forced browsing | In place | Fixed static-file maps (no file-system paths from URLs); unknown paths 404; the relay serves no admin or backup paths. |

### 5. Data protection and cryptography

| Item | Verdict | Evidence |
|---|---|---|
| No HTTPS / weak TLS | **Fixed** | Relay TLS now has a TLS 1.2 floor (`tls_context`) and HSTS on the relay and phone server; plain HTTP is refused off loopback unless TLS, a local proxy or `--home-network`. **Android app** accepted `http://` to any host, which would send the token and sign-in secret in clear: now only HTTPS or a private/home address, like the laptop (`MainActivity.allowed`). |
| Sensitive data exposure | In place | No request lines logged; event-trace redaction; error replies carry an error id, not internals (relay now also catches any unexpected error with a generic 500, **Fixed**). |
| Homemade crypto | In place | AES-256-GCM (`cryptography`, WebCrypto), PBKDF2-SHA256 600k, scrypt. |
| Hardcoded secrets | In place | Keys live in Windows Credential Manager. `scripts/security_scan.py` finds 0 secrets in tracked files and in all git history; the release gate scans the built zip. |
| Data at rest | Kept / Owner | Keys and tokens are DPAPI-protected; the relay stores hashes and only forwards ciphertext. `mind.json`, notes and the journal are plaintext under the owner's account (documented in `SECURITY.md` §4). Disk encryption (BitLocker) is the owner's choice. |
| Insecure randomness | In place | `secrets` everywhere; `random` is not used for anything secret. SHA-1 only for change detection, now marked `usedforsecurity=False`. |

### 6. Files

| Item | Verdict | Evidence |
|---|---|---|
| Malicious upload | **Fixed** | Phone uploads are create-only in ChutkuInbox; runnable types get `.blocked`. The list lacked `.reg`, `.msc`, `.wsf`, `.cpl`, `.chm`, `.iso`, `.appinstaller` and other Windows double-click types: added. |
| Path traversal | In place | `paths` rejects `..`, UNC, device names, ADS, reparse points; phone file reads resolve and check zones + secret paths; unzip and backup restore refuse unsafe member names. |
| LFI / RFI | N/A | Nothing is included or imported by path from requests. |
| XXE | In place | `xml.etree` on CPython 3.13's expat never resolves external entities and caps entity expansion. |
| Zip bombs / big files | **Fixed** | `unzip` had ratio/size limits; `.docx/.pptx/.xlsx` reading decompressed parts with no cap, and backup restore loaded members unbounded. Both now refuse parts over 50 MB before reading (`ZipBombTests`). Uploads ≤ 200 MB. |

### 7. Server-side and API

| Item | Verdict | Evidence |
|---|---|---|
| SSRF | In place | Web reading: public addresses only, connect to the checked address (no DNS rebinding), every redirect re-checked; agent browser asks for local/private addresses. |
| Insecure deserialization | In place | JSON only; no pickle/yaml/marshal of outside data. |
| API rate limiting | In place / **Fixed** | Phone: per-kind budgets per device. Relay: sign-ups and (new) failed sign-ins per address, queue bound per account, (new) at most 512 open connections. |
| Excessive data exposure | In place | `settings()` and `_phone_view` return chosen fields only. |
| Unprotected endpoints | In place | The relay's old `/t/api/` answers 426; no debug endpoints. |
| GraphQL | N/A | None. |
| Race conditions | In place | Approvals, preview tokens and phone approval nonces are single-use atomic pops (a second use finds nothing); action-log appends are file-locked. |

### 8. Business logic

In place. No prices or coupons. The logic that matters is approvals: single-use, bound to the exact step and expiring,
re-checked at approval; "Yes, always" only after a verified run (`tests/test_trusted_task*`, `test_autonomy_policy`).
The phone OTP equivalent (PIN) is re-asked for risky steps even inside a PIN session.

### 9. Misconfiguration

| Item | Verdict | Evidence |
|---|---|---|
| Default credentials | In place | None exist; every account, PIN and pairing code is chosen or random. |
| Debug mode | In place | No debug server; errors return an id, the trace goes to the local log. |
| Exposed files | In place | Static maps only, no directory listing; `.env`/`data/` are git-ignored and refused by the release gate. |
| Security headers | **Fixed** | CSP, `nosniff`, `Referrer-Policy`, `no-store` were there; HSTS added to the relay and phone server (the dashboard is plain loopback). |
| Open ports | In place | Dashboard and phone server bind 127.0.0.1; the alias port is exclusive; Funnel exposure is detected every 5 min and stops phone access. |
| Cloud misconfiguration | N/A | No cloud resources (the relay runs where the owner hosts it; see `docs/RELAY.md`). |
| Verbose errors | **Fixed** | The relay now answers any unexpected error with a generic 500 instead of dropping the connection; `Server` says only `ChutkuRelay`. |

### 10. Supply chain

| Item | Verdict | Evidence |
|---|---|---|
| Vulnerable libraries | **Fixed** | pip-audit found 34 known CVEs: pypdf 6.19.0 (18; Chutku reads untrusted PDFs), filelock 4.0.1 (14), certifi 2026.7.22 (2). Pinned to 6.21.4 / 4.2.1 / 2026.10.18 with fresh hashes; now 0. npm helpers: 0. |
| Typosquatting | In place | Every pin has PyPI SHA-256 hashes (`--require-hashes`); npm via `npm ci` with integrity hashes and `--ignore-scripts` in CI. |
| Build pipeline | In place | Workflows have `contents: read`; the release token is scoped to the releases repo only; the installer is signed when a certificate exists (`installer/sign.ps1`). |
| Outdated runtime | In place | CI builds with the newest CPython 3.13 embeddable pin. No Docker images. |
| SBOM | **Fixed** | `security_scan.py --sbom` writes a CycloneDX SBOM (58 components); CI keeps it as an artifact for 90 days. |

### 11. Phishing and spoofing

| Item | Verdict | Evidence |
|---|---|---|
| SPF / DKIM / DMARC | N/A | No mail domain. Chutku sends mail only through the owner's own account, drafts first. |
| Lookalike domains, site clones, subdomain takeover | Owner | Only relevant once a public relay domain exists (`docs/HANDOFF.md`). |
| User education | In place | Chutku never asks for a password and refuses to type into a password box, even after an approval; the owner types it (`SECURITY.md` §2). |
| Employee phishing | N/A | One owner; MFA on the owner's Tailscale and GitHub accounts is the owner's step. |

### 12. Availability

| Item | Verdict | Evidence |
|---|---|---|
| DoS / DDoS | Owner | The relay should sit behind a CDN/WAF proxy when public (`--behind-proxy` exists). |
| Application-level DoS | **Fixed** | Body caps everywhere; relay connection cap (512) and bounded queues; load test below. |
| ReDoS | **Fixed** | The instant router's tab patterns were quadratic on long runs of commas/spaces; now linear. Goals are capped at 2000 characters (`AgentSession`); 2,240 crafted goals at the cap: worst 1.7 s (`ReDoSTests`). |
| Resource exhaustion | In place | Size limits on bodies, uploads, archives, documents, queues and log rotation. |

### 13. Mobile (`android/`, a WebView around the relay page)

In place: `allowBackup="false"`, no file or content access in the WebView, other sites open in the browser, no keys in the
APK (only the relay address), only the launcher activity exported. **Fixed:** plain-HTTP relay addresses off the home
network are refused. **Kept:** no certificate pinning (the relay's certificate is the owner's choice, and any HTTPS
relay must work); no root detection or obfuscation (nothing secret in the APK; it will be open source); screenshots are
allowed (the owner screenshots the laptop view); `FLAG_SECURE` is an owner choice.

### 14. Infrastructure

Mostly N/A: no servers, SSH, containers or networks are run by this project. The relay host is the owner's
(`docs/RELAY.md`): patching, SSH and segmentation are the owner's steps. **Ransomware readiness:** `chutku.cli backup` makes
verified backups; keeping a copy offline is the owner's step.

### 15. Logging and incident response

| Item | Verdict | Evidence |
|---|---|---|
| Log logins, failures, permission changes, admin actions | **Fixed** | The hash-chained action log already had every action and grant change. Now also phone pairing, failed pairing, sign-ins, each wrong PIN and removals (`PhoneAuditTests`), and at the relay an `events` table with register, sign-ins, failed sign-ins, lock-outs, logouts and account changes (90 days). Never a password, PIN or token. |
| Alerts | **Fixed** | A phone removed by wrong PINs now shows the owner a Windows notification. (Funnel exposure already did.) SIEM: N/A for one PC. |
| Incident response + disclosure | **Fixed** | `SECURITY.md` §7: a short response plan and how to report. |

### 16. Privacy and compliance

In place: local-first, data minimisation for the cloud (`cloud_view`, redaction), private apps never captured,
backup and delete paths. DPDP Act 2023: Chutku is a personal, non-commercial tool (owner 2026-11-13); the relay
holds only an ID, hashes and the times and sizes of messages. HIPAA, PCI-DSS and SOC 2: N/A.

## Part 2: Security testing methods

| Method | How Chutku does it |
|---|---|
| SAST | bandit (medium+), in CI (`security` job) and `scripts/security_scan.py`. Reviewed skips in `pyproject.toml`. |
| DAST | Real-server tests: `tests/test_security_checklist.py`, `test_relay_*`, `test_phone_*` attack the running servers over HTTP (wrong hosts, origins, tokens, bodies). |
| IAST | N/A (commercial agents only). |
| SCA | pip-audit on `requirements.lock`, `npm audit` on the helpers, both in CI. |
| Secret scanning | `security_scan.py` (the release gate's key formats) over tracked files and every commit in CI. |
| Container / IaC | N/A (none). |
| Fuzz testing | hypothesis: password check, E2E envelopes, 60 random relay requests per run, and the path guard (`test_paths_property`). |
| Penetration / red team | Owner: before the relay goes public; the injection suites (`test_injection*`) are the automated part. |
| Vulnerability / SSL scanning | Owner: SSL Labs or testssl.sh on the public relay address. |
| Threat modelling | `SECURITY.md` is the threat model (STRIDE-style: who can reach what, and how each boundary fails closed). |

## Part 3: Performance and stress

`scripts/load_test_relay.py` (real relay, 20 accounts, fake laptops long-polling, half `/relay/me`, half full
phone→laptop round trips). 2026-11-13 on the owner's PC:

| Users | Req/s | Errors | p50 | p95 | p99 |
|---|---|---|---|---|---|
| 10 | 631 | 0 | 18 ms | 23 ms | 25 ms |
| 50 | 599 | 0 | 64 ms | 151 ms | 156 ms |
| 200 | 448 | 0 | 298 ms | 1.47 s | 1.65 s |
| 450 | 481 | 0 | 791 ms | 2.97 s | 3.58 s |
| 712 (past the 512 cap) | 948 | 65% refused | 1.24 s | 3.04 s | 3.66 s |
| 10 again (recovery) | 655 | 0 | 16 ms | 23 ms | 25 ms |

Soak, 2 minutes at 50 users: 67,646 requests, 0 errors, memory −0.3 MB (no growth; longer: `--soak-minutes 30`).
Breaking point: the connection cap, by design; the relay refuses the excess instead of falling over and recovers at
once. Spike = the 712 row. Volume, scalability, capacity, chaos and failover: N/A for one relay process (the guard
restarts the laptop's core after a crash: `SECURITY.md` §5). Benchmarks: `--json` for comparing versions.

## Part 4: Other tests

| Test | Where |
|---|---|
| Unit, integration, regression | `python -m unittest discover -s tests` (CI on every push) |
| E2E | `tests/test_relay_accounts.EndToEndTests` (phone → relay → laptop → phone), `scripts/verify_*.py` live checks |
| Smoke | CI `package` job: the built package starts, answers, passes doctor, stops |
| API | the real-server tests above (status codes, error bodies) |
| Compatibility | Windows 11 + CPython 3.13 is the only supported platform; the phone page runs in any current mobile browser |
| Accessibility, usability, UAT | Owner (real use is the UAT; `scripts/replay_real_goals.py` replays the owner's real requests) |
| Localization | Hinglish/Hindi/English phrase routing: `scripts/check_phrases.py` in CI |
| Install / upgrade | CI `package` job: clean-machine install, tampered package refused, uninstall |

## Recommended order

1. During development: SAST, SCA, secret scanning and unit tests in CI: **done** (`tests.yml` `unit` + `security`).
2. Before release: DAST (real-server tests) and load test are scripted; pentest, SSL scan and UAT are owner steps.
3. After launch: the `security` CI job also runs every Monday, so a new CVE in a pin shows up without a push; disclosure channel in `SECURITY.md` §7.
