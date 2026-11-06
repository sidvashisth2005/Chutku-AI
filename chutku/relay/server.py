"""The account relay (owner, 2026-11-06): one server that every installed assistant and its phone app reach.

    python -m chutku.relay --port 8780 --db relay.sqlite3            (put HTTPS in front of it, or pass --tls-cert/--tls-key)

What it does, and nothing more:
- **Accounts.** An ID (3-32 of a-z 0-9 . _ -, case-insensitive, unique) and a password (8+ characters) are created once,
  at install on the laptop. Passwords are stored only as scrypt hashes. An ID that exists is refused.
- **Devices stay signed in.** A login gives the device a random token (only its SHA-256 is stored). It works until that
  device logs out, or the password is changed (then every other device must log in again).
- **Forwarding.** The laptop keeps a long poll open (`/relay/poll`). A phone's request to `/t/api/...` is handed to its
  own account's laptop, which runs it through the phone server's own rules (PIN, approvals, control limits) and
  replies. Phones never reach another account's laptop, and laptops never receive requests from another account.

Honest limit: the relay sees the forwarded traffic (TLS ends at the relay). Run it on a server you trust.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ID_RULE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 8
MAX_REQUEST = 8 * 1024 * 1024        # phone -> laptop body (uploads go through here too)
MAX_REPLY = 16 * 1024 * 1024         # laptop -> phone body (screen frames, files)
POLL_SECONDS = 25.0
REPLY_SECONDS = 30.0
ONLINE_SECONDS = 40.0                # a laptop that polled this recently counts as online
QUEUE_MAX = 50
FAILS_BEFORE_LOCK, LOCK_SECONDS = 5, 15 * 60
REGISTER_PER_HOUR = 10
WEB = Path(__file__).resolve().parents[1] / "web" / "phone"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/phone.js": ("phone.js", "text/javascript; charset=utf-8"),
          "/phone.css": ("phone.css", "text/css; charset=utf-8"), "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/icon.png": ("../icon.png", "image/png")}
FORWARD_REPLY_HEADERS = ("Content-Type", "X-Frame-Hash", "X-Monitor", "Content-Disposition")


class RelayError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Accounts:
    """SQLite store of accounts and device tokens (hashes only)."""

    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, salt BLOB NOT NULL, pw TEXT NOT NULL,
                                                 created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, account TEXT NOT NULL, kind TEXT NOT NULL,
                                               name TEXT NOT NULL, created REAL NOT NULL, used REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS fails (id TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL);
        """)
        self.db.commit()

    @staticmethod
    def clean_id(account_id):
        account_id = str(account_id or "").strip().casefold()
        if not ID_RULE.fullmatch(account_id):
            raise RelayError(400, "An ID is 3-32 letters, digits, '.', '_' or '-', starting with a letter or digit.")
        return account_id

    def register(self, account_id, password):
        account_id = self.clean_id(account_id)
        if not isinstance(password, str) or len(password) < MIN_PASSWORD or len(password) > 200:
            raise RelayError(400, f"Choose a password of at least {MIN_PASSWORD} characters.")
        salt = secrets.token_bytes(16)
        with self.lock:
            try:
                self.db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?)",
                                (account_id, salt, _hash_password(password, salt), self.clock()))
                self.db.commit()
            except sqlite3.IntegrityError:
                raise RelayError(409, "This ID already exists. Choose another one.") from None
        return account_id

    def _check_password(self, account_id, password):
        now = self.clock()
        with self.lock:
            fail = self.db.execute("SELECT count, since FROM fails WHERE id = ?", (account_id,)).fetchone()
            if fail and fail[0] >= FAILS_BEFORE_LOCK and now - fail[1] < LOCK_SECONDS:
                raise RelayError(429, "Too many wrong passwords. Try again in 15 minutes.")
            row = self.db.execute("SELECT salt, pw FROM accounts WHERE id = ?", (account_id,)).fetchone()
        ok = row is not None and isinstance(password, str) and \
            hmac.compare_digest(_hash_password(password, row[0]), row[1])
        with self.lock:
            if ok:
                self.db.execute("DELETE FROM fails WHERE id = ?", (account_id,))
            else:
                count = 1 if not fail or now - fail[1] >= LOCK_SECONDS else fail[0] + 1
                self.db.execute("INSERT OR REPLACE INTO fails VALUES (?, ?, ?)",
                                (account_id, count, fail[1] if fail and count > 1 else now))
            self.db.commit()
        if not ok:
            raise RelayError(401, "Wrong ID or password.")

    def login(self, account_id, password, kind, name):
        account_id = self.clean_id(account_id)
        if kind not in ("laptop", "phone"):
            raise RelayError(400, "Say which device this is: laptop or phone.")
        self._check_password(account_id, password)
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self.lock:
            self.db.execute("INSERT INTO tokens VALUES (?, ?, ?, ?, ?, ?)",
                            (_token_hash(token), account_id, kind, str(name or kind)[:60], now, now))
            self.db.commit()
        return token

    def device(self, token):
        """(account, kind) for a live token, else RelayError 401."""
        if not token:
            raise RelayError(401, "Log in first.")
        with self.lock:
            row = self.db.execute("SELECT account, kind FROM tokens WHERE hash = ?", (_token_hash(token),)).fetchone()
            if row is not None:
                self.db.execute("UPDATE tokens SET used = ? WHERE hash = ?", (self.clock(), _token_hash(token)))
                self.db.commit()
        if row is None:
            raise RelayError(401, "Logged out. Log in again.")
        return row[0], row[1]

    def logout(self, token):
        with self.lock:
            self.db.execute("DELETE FROM tokens WHERE hash = ?", (_token_hash(token),))
            self.db.commit()

    def change(self, token, password, new_id=None, new_password=None):
        """Change the ID and/or password (from the laptop). A new password signs out every other device."""
        account_id, kind = self.device(token)
        if kind != "laptop":
            raise RelayError(403, "Change the ID or password on the laptop.")
        self._check_password(account_id, password)
        target = self.clean_id(new_id) if new_id else account_id
        if new_password is not None and (not isinstance(new_password, str) or len(new_password) < MIN_PASSWORD):
            raise RelayError(400, f"Choose a password of at least {MIN_PASSWORD} characters.")
        with self.lock:
            if target != account_id:
                if self.db.execute("SELECT 1 FROM accounts WHERE id = ?", (target,)).fetchone():
                    raise RelayError(409, "This ID already exists. Choose another one.")
                self.db.execute("UPDATE accounts SET id = ? WHERE id = ?", (target, account_id))
                self.db.execute("UPDATE tokens SET account = ? WHERE account = ?", (target, account_id))
            if new_password is not None:
                salt = secrets.token_bytes(16)
                self.db.execute("UPDATE accounts SET salt = ?, pw = ? WHERE id = ?",
                                (salt, _hash_password(new_password, salt), target))
                self.db.execute("DELETE FROM tokens WHERE account = ? AND hash != ?", (target, _token_hash(token)))
            self.db.commit()
        return target


class Mailbox:
    """Phone requests waiting for their account's laptop, and the laptop's replies."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.cond = threading.Condition()
        self.queues, self.replies, self.seen = {}, {}, {}

    def online(self, account):
        with self.cond:
            return self.clock() - self.seen.get(account, -1e9) < ONLINE_SECONDS

    def ask(self, account, request, timeout=REPLY_SECONDS):
        if not self.online(account):
            raise RelayError(503, "Your laptop is offline (Chutku is not running or has no internet).")
        rid = secrets.token_urlsafe(12)
        with self.cond:
            queue = self.queues.setdefault(account, [])
            if len(queue) >= QUEUE_MAX:
                raise RelayError(429, "Too many requests are waiting for the laptop.")
            queue.append(dict(request, rid=rid))
            self.cond.notify_all()
            deadline = self.clock() + timeout
            while rid not in self.replies:
                left = deadline - self.clock()
                if left <= 0:
                    self.queues[account] = [r for r in self.queues.get(account, []) if r["rid"] != rid]
                    raise RelayError(504, "The laptop did not answer in time.")
                self.cond.wait(min(left, 1.0))
            return self.replies.pop(rid)[1]

    def poll(self, account, timeout=None):
        with self.cond:
            self.seen[account] = self.clock()
            deadline = self.clock() + (POLL_SECONDS if timeout is None else timeout)
            while not self.queues.get(account):
                left = deadline - self.clock()
                if left <= 0:
                    return []
                self.cond.wait(min(left, 1.0))
                self.seen[account] = self.clock()
            taken, self.queues[account] = self.queues[account], []
            return taken

    def reply(self, account, rid, response):
        with self.cond:
            self.replies[rid] = (account, response)
            self.cond.notify_all()


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path, *, web=WEB):
        super().__init__(address, RelayHandler)
        self.accounts = Accounts(db_path)
        self.mailbox = Mailbox()
        self.web = Path(web)
        self.register_times = {}
        self.rate_lock = threading.Lock()

    def register_allowed(self, ip):
        now = time.monotonic()
        with self.rate_lock:
            times = [t for t in self.register_times.get(ip, []) if now - t < 3600]
            if len(times) >= REGISTER_PER_HOUR:
                return False
            self.register_times[ip] = times + [now]
            return True


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "ChutkuRelay"
    sys_version = ""
    # Keep-alive: a page load reuses one connection instead of opening one per file (with HTTP/1.0 the phone app's
    # page came up without its stylesheet on a flaky network, 2026-11-06). An idle connection closes after 75 s.
    protocol_version = "HTTP/1.1"
    timeout = 75

    def log_message(self, *_):
        pass   # no request lines (paths carry nothing secret, but tokens must never reach a log)

    def _reply(self, status, body, mime="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; manifest-src 'self'; "
                         "worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _body(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > limit:
            raise RelayError(413, "Too large.")
        return self.rfile.read(length) if length else b""

    def _json(self):
        try:
            data = json.loads(self._body(64 * 1024) or b"{}")
        except ValueError:
            raise RelayError(400, "Send JSON.") from None
        if not isinstance(data, dict):
            raise RelayError(400, "Send a JSON object.")
        return data

    def _token(self):
        header = self.headers.get("Authorization") or ""
        return header[7:].strip() if header.startswith("Bearer ") else ""

    def _route(self, method):
        path = urlsplit(self.path).path
        if method == "GET" and path in STATIC:
            name, mime = STATIC[path]
            file = (self.server.web / name).resolve()
            self._reply(200, file.read_bytes(), mime)
            return
        if method == "GET" and path == "/relay/info":
            self._reply(200, {"relay": True, "version": 1})
            return
        accounts, mailbox = self.server.accounts, self.server.mailbox
        if method == "POST" and path == "/relay/register":
            if not self.server.register_allowed(self.client_address[0]):
                raise RelayError(429, "Too many new accounts from here. Try again later.")
            data = self._json()
            self._reply(201, {"id": accounts.register(data.get("id"), data.get("password"))})
            return
        if method == "POST" and path == "/relay/login":
            data = self._json()
            token = accounts.login(data.get("id"), data.get("password"), data.get("device"), data.get("name"))
            self._reply(200, {"token": token, "id": accounts.clean_id(data.get("id"))})
            return
        account, kind = accounts.device(self._token())
        if method == "GET" and path == "/relay/me":
            self._reply(200, {"id": account, "device": kind, "laptop_online": mailbox.online(account)})
        elif method == "POST" and path == "/relay/logout":
            accounts.logout(self._token())
            self._reply(200, {"logged_out": True})
        elif method == "POST" and path == "/relay/change":
            data = self._json()
            self._reply(200, {"id": accounts.change(self._token(), data.get("password"), data.get("new_id"),
                                                    data.get("new_password"))})
        elif method == "POST" and path == "/relay/poll":
            if kind != "laptop":
                raise RelayError(403, "Only the laptop collects requests.")
            self._json()
            self._reply(200, {"requests": mailbox.poll(account)})
        elif method == "POST" and path == "/relay/reply":
            if kind != "laptop":
                raise RelayError(403, "Only the laptop answers requests.")
            data = json.loads(self._body(MAX_REPLY + MAX_REPLY // 2) or b"{}")
            mailbox.reply(account, str(data.get("rid")), {
                "status": int(data.get("status", 502)), "body": str(data.get("body") or ""),
                "headers": {k: str(v)[:500] for k, v in (data.get("headers") or {}).items()
                            if k in FORWARD_REPLY_HEADERS}})
            self._reply(200, {"ok": True})
        elif path.startswith("/t/api/"):
            if kind != "phone":
                raise RelayError(403, "Only the phone app sends requests to the laptop.")
            body = self._body(MAX_REQUEST)
            answer = mailbox.ask(account, {
                "method": method, "path": self.path[2:],
                "content_type": (self.headers.get("Content-Type") or "")[:100],
                "body": base64.b64encode(body).decode("ascii")})
            data = base64.b64decode(answer["body"]) if answer["body"] else b""
            if len(data) > MAX_REPLY:
                raise RelayError(502, "The laptop's answer was too large.")
            headers = dict(answer["headers"])
            self._reply(answer["status"], data, headers.pop("Content-Type", "application/octet-stream"), headers)
        else:
            raise RelayError(404, "Not found.")

    def _handle(self, method):
        try:
            self._route(method)
        except RelayError as error:
            self._fail(error.status, str(error))
        except (ValueError, KeyError, OSError) as error:
            self._fail(400, f"Bad request ({type(error).__name__}).")

    def _fail(self, status, message):
        # The request body may be unread: close the connection so it cannot be read as the next request.
        self.close_connection = True
        self._reply(status, {"error": message}, headers={"Connection": "close"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def serve(port=8780, db="relay.sqlite3", host="0.0.0.0", cert=None, key=None):
    server = RelayServer((host, port), db)
    if cert:
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Chutku relay on {'https' if cert else 'http'}://{host}:{port} (accounts in {db})", flush=True)
    server.serve_forever()
