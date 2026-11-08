"""The phone server (W6 / HERMES_PLAN P1-P9): a thin, phone-only API on 127.0.0.1:<port>, published to the owner's
tailnet by `tailscale serve` (HTTPS). The main dashboard is never exposed.

Every request must pass, in order:
1. Host == the laptop's own <name>.<tailnet>.ts.net (stored at setup);
2. Tailscale-User-Login == the owner's Tailscale login (`tailscale serve` adds it; a forged one alone is not enough);
3. a session from a paired device credential + PIN (except the pairing and login calls themselves);
4. state-changing calls: the per-session CSRF header and Origin == https://<host>;
5. 30 requests per minute per device.
What the phone may do goes through the same AgentSession / policy kernel / approvals as the laptop (origin "phone"),
except direct control (P5-P7), which follows chutku/remote/control.py.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import io
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from chutku.core.paths import user_folder
from chutku.remote.auth import RELAY_DEVICE, RemoteDenied, RemoteStore

WEB = Path(__file__).resolve().parents[1] / "web" / "phone"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/phone.js": ("phone.js", "text/javascript; charset=utf-8"),
          "/e2e.js": ("e2e.js", "text/javascript; charset=utf-8"),
          "/phone.css": ("phone.css", "text/css; charset=utf-8"), "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
          "/jitter.js": ("jitter.js", "text/javascript; charset=utf-8"),   # the sound player (an AudioWorklet module)
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json")}
# Every answer's Content-Security-Policy: scripts, styles and workers only from this laptop (so an AudioWorklet must be a
# file here, not a blob: URL; live 2026-11-08 the phone said "can't play the laptop's sound" until jitter.js was served).
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; "
       "media-src 'self' blob:; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
       "form-action 'self'")
MAX_BODY = 2 * 1024 * 1024                 # JSON and voice clips
MAX_UPLOAD = 200 * 1024 * 1024             # P8 phone -> laptop files
SCREEN_MAX = 30 * 60
SCREEN_BEAT = 45.0   # one slow round trip (relay, mobile data) must not end the view
PIN_SESSION = 30 * 60   # owner 2026-11-07: the PIN once per session, renewed while the phone is used
MONITOR_SECONDS = 2.0
CURSOR_TICK = 1 / 60    # the pointer stream checks the mouse 60 times a second and sends only moves
VIDEO_FRAME = 1 / 30   # H.264: up to 30 frames/s (capture ~20 ms runs while the last frame is encoded)
HOVER_EVERY = 0.08      # what is under the pointer: looked up at most ~12 times a second (2-5 ms each)
STREAM_FRAME = 1 / 20   # the stream's fastest pace (capture ~30 ms + scale/encode ~30 ms in practice)   # trackpad input reuses the monitor rectangle instead of a capture per move
KINDS = {"/api/screen/frame": "frame", "/api/screen/stream": "frame", "/api/screen/h264": "frame", "/api/screen/audio": "frame", "/api/cursor/stream": "frame", "/api/files/stream": "frame", "/api/session": "poll", "/api/presence": "poll", "/api/say": "poll",
         "/api/whoami": "poll", "/api/files/list": "poll", "/api/files/search": "poll", "/api/files/recent": "poll",
         "/api/files/places": "poll", "/api/control/input": "input", "/api/control/text": "input", "/api/control/keys": "input"}
INBOX = Path(user_folder("ChutkuInbox"))
BLOCKED_SUFFIXES = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".lnk", ".com", ".hta", ".jar"}
# Steps that may never be approved from the phone, whatever the PIN: they wait for the laptop's own card.
LAPTOP_ONLY_PREFIXES = ("never.", "remote.", "power.", "filesystem.delete_permanent", "process.terminate",
                        "network.", "telegram.")


def laptop_only(approval, runs_code):
    """True when this pending step may be approved only on the laptop (phone app and Telegram, H16): the
    laptop-only tools, R4, an unknown recipient, and anything that runs code. `runs_code(tool)` answers True for an
    unknown tool, so the laptop decides."""
    tool = str(approval.get("tool") or "")
    if tool.startswith(LAPTOP_ONLY_PREFIXES):
        return True
    risk = approval.get("risk")
    if isinstance(risk, (int, float)) and risk >= 4:
        return True
    reason = str(approval.get("reason") or "").casefold()
    if "not in memory" in reason or "new recipient" in reason or "unknown" in reason:
        return True
    return bool(runs_code(tool))


def runs_code_at(base):
    """runs_code(tool) for the real registry of this Chutku (True for an unknown tool)."""
    def runs_code(tool):
        try:
            from chutku.app import create_runtime
            with create_runtime(base) as runtime:
                return bool(getattr(runtime.registry.get(tool), "runs_code", False))
        except (KeyError, ValueError, OSError):
            return True
    return runs_code


class RemoteServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, core, port=8766, *, store=None, tailscale_runner=None, inbox=INBOX, monitor=None):
        self.core, self.store = core, store or RemoteStore(core.base)
        self.tailscale_runner, self.inbox = tailscale_runner, Path(inbox)
        self.monitor = monitor            # (left, top, width, height) override for tests
        self.screen = None                # {"device", "until", "beat", "hash"}
        self.control = None               # control.ControlSession
        self.border = None                # the red border process while control is live
        self.stopped = threading.Event()
        # The account relay's laptop client (chutku/relay/client.py) forwards phone requests here over loopback with
        # this secret; it lives only in this process's memory.
        self.relay_secret = secrets.token_urlsafe(32)
        self.pin_ok = {}                  # device -> monotonic time its PIN session ends (in memory only)
        super().__init__(("127.0.0.1", port), PhoneHandler)

    # -- laptop-side state ----------------------------------------------------------------------------------------
    def viewing(self):
        screen = self.screen
        return bool(screen and time.monotonic() < screen["until"] and time.monotonic() - screen["beat"] < SCREEN_BEAT)

    def controlling(self):
        return bool(self.control and self.control.alive())

    def disarm(self, reason="disarmed at the laptop"):
        """Ctrl+Alt+Shift+P, the tray, "remote band karo", Funnel: end control now and keep it off until the owner
        turns it on again at the laptop."""
        self._end_control(reason)
        self.store.configure(control_allowed=False)

    def _end_control(self, reason):
        if self.control is not None:
            self.control.end(reason)
        self.control = None
        self._border(False)

    def end_all(self, reason, *, keep_allowed=False):
        """End control, the screen view and every phone session. keep_allowed: a restart or shutdown (owner
        2026-11-08: "phone control on by default; I'll stop it myself at the laptop") ends the live session but leaves
        the owner's choice as it is; the next control session still needs the PIN."""
        if keep_allowed:
            self._end_control(reason)
        else:
            self.disarm(reason)
        self.screen = None
        self.store.sessions.clear()
        self.pin_ok.clear()

    def _border(self, on):
        import subprocess
        import sys
        if on and self.border is None and self.monitor is None:
            try:
                self.border = subprocess.Popen([sys.executable, "-m", "chutku.remote.border"],
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                self.border = None
        elif not on and self.border is not None:
            try:
                self.border.terminate()
            except OSError:
                pass
            self.border = None

    def watch_funnel(self, every=300.0):
        """Every 5 minutes: if Funnel exposes the phone server to the public internet, stop everything."""
        from chutku.remote import tailscale

        def run():
            while not self.stopped.wait(every):
                if tailscale.funnel_exposes(self.server_port, runner=self.tailscale_runner):
                    self.end_all("Funnel was on")
                    try:
                        from chutku.health import notify
                        notify("Phone access stopped", "Public internet se khula tha, band kar diya (Tailscale Funnel).")
                    except Exception:
                        pass
                    threading.Thread(target=self.shutdown, daemon=True).start()
                    return
        threading.Thread(target=run, name="chutku-funnel-watch", daemon=True).start()

    def server_close(self):
        self.stopped.set()
        self.end_all("server stopped", keep_allowed=True)
        super().server_close()


class PhoneHandler(BaseHTTPRequestHandler):
    server: RemoteServer
    protocol_version = "HTTP/1.0"

    def log_message(self, *_):
        pass   # never log URLs, cookies, PINs or credentials

    # -- replies --------------------------------------------------------------------------------------------------
    def _reply(self, status, body, mime="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _deny(self, error):
        if self.command == "GET" and "text/html" in (self.headers.get("Accept") or ""):   # a person, not the app:
            import html   # a readable page with the next step instead of raw JSON (2026-11-08 review)
            page = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                    f"<title>Chutku</title><body style='font-family:sans-serif;padding:24px'><h2>{html.escape(str(error))}"
                    "</h2><p>On the phone, sign in to the Tailscale app with the same account as the laptop, then open "
                    "the link the laptop's Phone page shows (or scan its QR code).</p></body>")
            self._reply(getattr(error, "status", 403), page.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._reply(getattr(error, "status", 403), {"error": str(error)})

    # -- the gates ------------------------------------------------------------------------------------------------
    def _relayed(self):
        """True for a request the account relay client forwarded: loopback, this run's secret, and a phone PIN set up
        for the relay. Such a request is the "relay" device; PIN, approval and control rules apply as for any phone."""
        secret = self.headers.get("X-Chutku-Relay")
        if secret is None:
            return False
        if self.client_address[0] != "127.0.0.1" or not hmac.compare_digest(secret, self.server.relay_secret):
            raise RemoteDenied("Request refused.")
        if not self.server.store.relay_ready():
            raise RemoteDenied("Set up the phone app on the laptop first (chutku.cli setup).", 409)
        return True

    def _tailnet(self):
        if self._relayed():
            return self.server.store.settings()
        settings = self.server.store.settings()
        host, login = settings.get("host"), settings.get("login")
        if not settings.get("enabled") or not host or not login:
            raise RemoteDenied("Phone access is off.")
        if self.headers.get("Host") != host:
            raise RemoteDenied("Wrong address.")
        if self.headers.get("Tailscale-User-Login") != login:
            raise RemoteDenied("Only the owner's Tailscale account may connect.")
        return settings

    def _cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "chutku_phone":
                return value
        return ""

    def _session(self, mutation):
        kind = KINDS.get(urlsplit(self.path).path, "general")
        if self._relayed():   # signed in at the relay with the account's device token; no cookie, so no CSRF
            self.server.store.rate(RELAY_DEVICE, kind)
            self._renew_pin(RELAY_DEVICE)
            return {"device": RELAY_DEVICE, "csrf": ""}
        settings = self._tailnet()
        record = self.server.store.session(self._cookie())
        if mutation:
            if self.headers.get("X-Chutku-CSRF") != record["csrf"] or \
                    self.headers.get("Origin") != "https://" + settings["host"]:
                raise RemoteDenied("Request refused (CSRF).")
        self.server.store.rate(record["device"], kind)
        self._renew_pin(record["device"])
        return record

    def _body(self, limit=MAX_BODY):
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= limit or self.headers.get("Transfer-Encoding"):
            raise RemoteDenied("Request is too large.", 413)
        return self.rfile.read(length) if length else b""

    def _json(self):
        try:
            data = json.loads(self._body() or b"{}")
        except ValueError:
            raise RemoteDenied("Invalid JSON.", 400) from None
        if not isinstance(data, dict):
            raise RemoteDenied("Send a JSON object.", 400)
        return data

    def _renew_pin(self, device):
        now = time.monotonic()
        if self.server.pin_ok.get(device, 0) > now:
            self.server.pin_ok[device] = now + PIN_SESSION

    def _pin(self, record, pin, strict=False):
        """The PIN once per session: within PIN_SESSION of a correct PIN (login counts), screen, control, clipboard and
        files need no PIN again. strict (risky approvals, typing into a command window) always checks it."""
        now = time.monotonic()
        if not pin:   # no PIN sent: fine inside a PIN session, else ask for it (never counted as a wrong PIN)
            if not strict and self.server.pin_ok.get(record["device"], 0) > now:
                return
            raise RemoteDenied("PIN needed for this.", 403)
        self.server.store.check_pin(record["device"], pin)
        self.server.pin_ok[record["device"]] = now + PIN_SESSION

    # -- GET ------------------------------------------------------------------------------------------------------
    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path in STATIC or path == "/icon.png":
                self._tailnet()
                if path == "/icon.png":
                    self._reply(200, (WEB.parent / "icon.png").read_bytes(), "image/png")
                else:
                    file, mime = STATIC[path]
                    self._reply(200, (WEB / file).read_bytes(), mime)
                return
            record = self._session(mutation=False)
            query = parse_qs(urlsplit(self.path).query)
            if path == "/api/whoami":
                settings = self.server.store.settings()
                device = next((d for d in settings["devices"] if d["id"] == record["device"]), {})
                from chutku import identity
                self._reply(200, {"device": device.get("name"), "control_allowed": settings["control_allowed"],
                                  "pin_ok": self.server.pin_ok.get(record["device"], 0) > time.monotonic(),
                                  "controlling": self.server.controlling(),
                                  "paused": self._paused(), "csrf": record["csrf"],
                                  "assistant": identity.load(Path(self.server.core.base) / ".env")["ASSISTANT_NAME"]})
            elif path == "/api/session":
                session = self.server.core.agent_sessions.get(query.get("id", [""])[0])
                snapshot = session.snapshot()
                if snapshot.get("origin") not in ("phone", "phone_voice"):
                    raise RemoteDenied("Only tasks started from the phone are shown here.")
                self._reply(200, {"session": self._phone_view(snapshot)})
            elif path == "/api/presence":
                self._reply(200, self.server.core.presence_state())
            elif path == "/api/screen/frame":
                self._frame(record, query.get("h", [""])[0])
            elif path == "/api/screen/stream":
                self._stream(record, query)
            elif path == "/api/screen/h264":
                self._h264(record, query)
            elif path == "/api/cursor/stream":
                self._cursor_stream(record)
            elif path == "/api/screen/audio":
                self._audio(record)
            elif path == "/api/speedtest":
                self._speedtest(query)
            elif path == "/api/control/windows":
                self._reply(200, {"windows": self._control().windows(self._monitor())})
            elif path == "/api/files/stream":
                self._file_stream(record, query.get("path", [""])[0])
            elif path == "/api/say":
                self._say(query.get("id", [""])[0])
            else:
                self._reply(404, {"error": "Not found."})
        except RemoteDenied as error:
            self._deny(error)
        except (KeyError, ValueError) as error:
            self._reply(400, {"error": str(error)[:200]})
        except OSError:   # the screen could not be read (locked, asleep, a secure desktop): say so, keep the connection
            self._reply(503, {"error": "The laptop screen can't be read right now (locked, asleep or a secure "
                                       "screen). Files and Chutku still work."})

    # -- POST -----------------------------------------------------------------------------------------------------
    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/pair":
                self._tailnet()
                data = self._json()
                self._reply(200, self.server.store.pair(data.get("code"), data.get("name"), data.get("pin")))
                return
            if path == "/api/login":
                self._tailnet()
                data = self._json()
                login = self.server.store.login(data.get("credential"), data.get("pin"))
                self.server.pin_ok[login["device_id"]] = time.monotonic() + PIN_SESSION
                cookie = (f"chutku_phone={login['token']}; HttpOnly; Secure; SameSite=Strict; Path=/; "
                          f"Max-Age={12 * 3600}")
                self._reply(200, {"device_id": login["device_id"], "name": login["name"], "csrf": login["csrf"]},
                            headers={"Set-Cookie": cookie})
                return
            if path == "/api/files/upload":
                record = self._session(mutation=True)
                self._upload(record)
                return
            record = self._session(mutation=True)
            data = self._voice_or_json(path)
            handler = getattr(self, "_post_" + path.removeprefix("/api/").replace("/", "_"), None)
            if handler is None:
                self._reply(404, {"error": "Not found."})
                return
            result = handler(record, data)
            if isinstance(result, tuple):
                self._reply(*result)
            else:
                self._reply(200, result)
        except RemoteDenied as error:
            self._deny(error)
        except PermissionError as error:     # control refusals and others: shown to the owner as-is
            self._reply(409, {"error": str(error)[:300]})
        except (KeyError, ValueError, OSError) as error:
            self._reply(400, {"error": str(error)[:300]})

    def _voice_or_json(self, path):
        if path in ("/api/voice", "/api/laptop/voice", "/api/control/voice"):
            return {"audio": self._body(MAX_BODY)}
        return self._json()

    def _paused(self):
        from chutku.core.action_control import ActionControl
        return ActionControl(self.server.core.base).paused

    # -- P2: chat, progress, approvals -------------------------------------------------------------------------------
    def _phone_view(self, snapshot):
        view = {k: snapshot.get(k) for k in ("id", "goal", "status", "reply", "origin")}
        view["steps"] = [{"tool": s.get("tool"), "purpose": s.get("purpose"), "state": s.get("state"),
                          "verified": s.get("verification") == "PASS"} for s in snapshot.get("steps", [])][-10:]
        pending = snapshot.get("pending") if snapshot.get("status") == "waiting_confirmation" else None
        if pending:
            approval = pending.get("approval") or {}
            view["pending"] = {"tool": approval.get("tool"), "consequence": approval.get("consequence"),
                               "risk": approval.get("risk_label") or approval.get("risk"),
                               "laptop_only": self._laptop_only(approval)}
            if not view["pending"]["laptop_only"]:
                view["pending"]["nonce"] = self.server.store.approval_nonce(snapshot["id"], _step_key(pending))
        return view

    def _laptop_only(self, approval):
        return laptop_only(approval, runs_code_at(self.server.core.base))

    def _post_chat(self, record, data):
        message = str(data.get("message") or "").strip()
        if not 1 <= len(message) <= 2000:
            raise RemoteDenied("Write a request (up to 2000 characters).", 400)
        if self._paused():
            raise RemoteDenied("Chutku is paused. Resume her (PIN) first.", 409)
        mode = self.server.core.preferences.load()["handsfree_mode"]
        session = self.server.core.begin_session(message, mode, "phone")
        return {"session": self._phone_view(session.snapshot())}

    def _post_approve(self, record, data):
        session = self.server.core.agent_sessions.get(str(data.get("id")))
        snapshot = session.snapshot()
        pending = snapshot.get("pending")
        if snapshot.get("status") != "waiting_confirmation" or not pending:
            raise RemoteDenied("Nothing is waiting for approval.", 409)
        if self._laptop_only(pending.get("approval") or {}):
            raise RemoteDenied("Ye laptop pe approve karna hoga.", 409)
        self.server.store.use_nonce(data.get("nonce"), snapshot["id"], _step_key(pending))   # spent even on a bad PIN
        approval = pending.get("approval") or {}
        self._pin(record, data.get("pin"), strict=int(approval.get("risk") or 0) >= 3 or bool(approval.get("deletes")))
        if type(data.get("approve")) is not bool:
            raise RemoteDenied("Say approve or cancel.", 400)
        result = self.server.core.confirm_session(snapshot["id"], data["approve"])
        return {"session": self._phone_view(result)}

    def _post_stop(self, record, data):
        return {"session": self._phone_view(self.server.core.stop_session(str(data.get("id"))))}

    def _post_resume(self, record, data):
        """The H2 pause blocks new phone tasks, but the owner may lift it from the phone with the PIN."""
        self._pin(record, data.get("pin"))
        from chutku.core.action_control import ActionControl
        ActionControl(self.server.core.base).resume()
        return {"paused": False}

    def _post_logout(self, record, data):
        self.server.store.logout(self._cookie())
        return {"logged_out": True}

    # -- P3: voice from the phone -----------------------------------------------------------------------------------
    def _post_voice(self, record, data):
        if self._paused():
            raise RemoteDenied("Chutku is paused. Resume her (PIN) first.", 409)
        pcm = decode_audio(data["audio"])
        if len(pcm) > 30 * 32000:
            raise RemoteDenied("Keep a voice message under 30 seconds.", 413)
        from chutku.voice.recognition import command_language
        from chutku.voice.whisper_stt import transcribe_pcm
        heard = transcribe_pcm(pcm, language=command_language(self.server.core.base), base=self.server.core.base)
        text = (heard.get("text") or "").strip()
        if not text or heard.get("confidence", 0) < 0.35:
            return {"transcript": None, "message": "Theek se sunai nahi diya, phir se bolo."}
        from chutku.voice.plausible import plausible, read_back
        if not plausible(text, known_names=self.server.core._known_names()):
            return {"transcript": text, "message": read_back(text)}
        mode = self.server.core.preferences.load()["handsfree_mode"]
        session = self.server.core.begin_session(text, mode, "phone_voice")
        return {"transcript": text, "session": self._phone_view(session.snapshot())}

    def _say(self, session_id):
        """Chutku's own voice (Kokoro) for a phone task's reply, or for its approval question, as WAV (the laptop
        stays silent: Z5, owner 2026-11-06); 204 when unavailable."""
        session = self.server.core.agent_sessions.get(session_id).snapshot()
        text = spoken_text(session)
        if session.get("origin") not in ("phone", "phone_voice") or not text:
            self._reply(204, b"", "text/plain")
            return
        from chutku.voice import tts
        if not tts.available():
            self._reply(204, b"", "text/plain")
            return
        self._reply(200, wav(text), "audio/wav")

    # -- Z5: sound on the laptop, only when the owner asks for it from the phone -----------------------------------------
    def _post_laptop_say(self, record, data):
        """Chutku says the owner's words out of the laptop speakers ("tell them dinner is ready")."""
        text = str(data.get("text") or "").strip()
        if not 1 <= len(text) <= 500:
            raise RemoteDenied("Write what Chutku should say on the laptop (up to 500 characters).", 400)
        self._pin(record, data.get("pin"))   # inside the PIN session (2026-11-08 review)
        _log(self.server.core.base, "laptop_say", {"characters": len(text)})
        threading.Thread(target=self.server.core._speak, args=(text,), name="chutku-phone-say", daemon=True).start()
        return {"saying": len(text)}

    def _post_laptop_voice(self, record, data):
        """The owner's own recorded voice from the phone, played once on the laptop speakers (at most 30 s)."""
        pcm = decode_audio(data["audio"])
        if not pcm or len(pcm) > 30 * 32000:
            raise RemoteDenied("Record 1 to 30 seconds.", 413)
        _log(self.server.core.base, "laptop_voice", {"seconds": round(len(pcm) / 32000, 1)})
        threading.Thread(target=play_on_laptop, args=(pcm,), name="chutku-phone-voice", daemon=True).start()
        return {"playing_seconds": round(len(pcm) / 32000, 1)}

    # -- P4: live screen view (view-only), heartbeat, cap ------------------------------------------------------------
    def _post_screen_start(self, record, data):
        self._pin(record, data.get("pin"))
        now = time.monotonic()
        self.server.screen = {"device": record["device"], "until": now + SCREEN_MAX, "beat": now, "hash": None}
        _keep_awake(True)
        try:
            monitor = list(self._monitor())   # the phone moves its own pointer at once in these pixels
        except OSError:
            monitor = None
        return {"viewing": True, "minutes": SCREEN_MAX // 60, "monitor": monitor}

    def _post_screen_stop(self, record, data):
        self.server.screen = None
        return {"viewing": False}

    def _frame(self, record, last_hash):
        screen = self.server.screen
        now = time.monotonic()
        if not screen or screen["device"] != record["device"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        if now > screen["until"] or now - screen["beat"] > SCREEN_BEAT:
            self.server.screen = None
            raise RemoteDenied("Screen view ended (30 min max, or the phone went quiet). Start it again.", 403)
        screen["beat"] = now
        from chutku import vision
        from chutku.remote.control import cursor_pos
        shot = vision.capture()
        controlling = self.server.controlling()
        x, y = cursor_pos()
        cursor = json.dumps([round((x - shot.left) / max(shot.width, 1), 4), round((y - shot.top) / max(shot.height, 1), 4)])
        digest = hashlib.sha1(shot.pixels[::16, ::16].tobytes() + cursor.encode()).hexdigest()
        headers = {"X-Frame-Hash": digest, "X-Cursor": cursor}
        if digest == last_hash:
            self._reply(204, b"", "text/plain", headers=headers)
            return
        self.server.monitor_seen = (time.monotonic(), (shot.left, shot.top, shot.width, shot.height))
        body, mime = _jpeg(shot.pixels, 7 if controlling else 8, width=1280)   # lighter frames while the owner drives
        self._reply(200, body, mime,
                    headers={**headers, "X-Monitor": json.dumps([shot.left, shot.top, shot.width, shot.height])})

    def _file_stream(self, record, raw_path):
        """GET /api/files/stream?path=: a laptop video, audio file, photo or PDF played by the phone's own player, with
        seeking (HTTP Range). Owner 2026-11-07: "an anime episode on my laptop" plays smoothly with sound this way;
        copying the screen could never be smooth. Same refusals as a download; inside the PIN session; read-only."""
        self._pin(record, None)
        path = Path(str(raw_path or "")).expanduser()
        reason = file_refusal(path, max_size=None)
        if reason:
            raise RemoteDenied(reason)
        size = path.stat().st_size
        start, end = 0, size - 1
        ranged = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        if ranged and (ranged[1] or ranged[2]):
            if ranged[1]:
                start, end = int(ranged[1]), int(ranged[2]) if ranged[2] else size - 1
            else:   # the last N bytes
                start = max(0, size - int(ranged[2]))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if ranged else 200)
        self.send_header("Content-Type", STREAM_TYPES.get(path.suffix.casefold(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if ranged:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if start == 0:
            _log(self.server.core.base, "file_streamed_to_phone", {"path": str(path), "bytes": size})
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError):
            pass   # the player seeks by closing this request and asking for another range

    def _stream(self, record, query):
        """GET /api/screen/stream: the screen as one continuous MJPEG stream (multipart/x-mixed-replace), shown by a
        plain <img>. No round trip per frame (owner 2026-11-07: "frames are still laggy"). The pointer is not in the
        picture: the phone draws it from /api/cursor/stream and moves it at once under your finger.
        Ends when the phone goes away, the view is stopped or replaced, or after SCREEN_MAX."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        from chutku import vision
        width = max(640, min(1920, int((query.get("w") or ["1280"])[0])))
        screen["stream"] = token = secrets.token_hex(4)   # a newer stream from this phone replaces this one
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=chutkuframe")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, sent_at = None, 0.0
        try:
            while self.server.screen is screen and screen.get("stream") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                started = time.monotonic()
                screen["beat"] = started
                try:
                    shot = vision.capture()
                    pixels = shot.pixels
                except OSError:   # locked or a secure desktop: try again shortly, keep the stream open
                    time.sleep(1.0)
                    continue
                digest = _changed(pixels)
                if digest != last or started - sent_at > 2.0:   # unchanged screens cost nothing (a keep-alive every 2 s)
                    self.server.monitor_seen = (started, (shot.left, shot.top, shot.width, shot.height))
                    body, mime = _jpeg(pixels, 8 if self.server.controlling() else 9, width=width)
                    self.wfile.write(b"--chutkuframe\r\nContent-Type: " + mime.encode() + b"\r\nContent-Length: "
                                     + str(len(body)).encode() + b"\r\n\r\n" + body + b"\r\n")
                    self.wfile.flush()
                    last, sent_at = digest, started
                time.sleep(max(0.0, STREAM_FRAME - (time.monotonic() - started)))
        except (BrokenPipeError, ConnectionError, OSError):
            pass   # the phone closed the stream

    def _h264(self, record, query):
        """GET /api/screen/h264: the screen as H.264 (owner 2026-11-08: "no lag or jitter"), decoded on the phone by
        WebCodecs. Each packet is [4-byte length][1 byte: 1 = keyframe][4-byte capture ms, _clock_ms][Annex B bytes]; the first is a keyframe. 409
        when no encoder works here: the phone falls back to /api/screen/stream. A still screen is sent 3 more times so
        it sharpens, then nothing until it changes. A different screen size ends the stream (the phone reconnects)."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        import struct
        width = max(640, min(1920, int((query.get("w") or ["1280"])[0])))
        grab = _Grabber()
        grab.start()
        first = grab.take(3.0)
        if first is None:
            grab.stop.set()
            raise RemoteDenied("The laptop is locked or showing a secure screen.", 503)
        size = (first[0].width, first[0].height)
        out_w = min(width, size[0])
        try:
            kbps = max(500, min(8000, int((query.get("kbps") or ["3000"])[0])))   # Watch mode asks for more
            encoder = H264(out_w, round(size[1] * out_w / size[0]), bit_rate=kbps * 1000)
        except (OSError, ImportError):
            grab.stop.set()
            raise RemoteDenied("No H.264 encoder on this laptop.", 409)
        grab.latest = first
        grab.fresh.set()   # the first capture is the first frame
        screen["stream"] = token = secrets.token_hex(4)   # a newer stream from this phone replaces this one
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Encoder", encoder.name)
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, settle = None, 0
        try:
            while self.server.screen is screen and screen.get("stream") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                taken = grab.take(1.0)
                screen["beat"] = time.monotonic()
                if taken is None:   # locked for a moment: keep the stream open
                    continue
                shot, digest = taken
                if (shot.width, shot.height) != size:
                    break
                settle = 3 if digest != last else settle - 1
                if settle >= 0:
                    self.server.monitor_seen = (time.monotonic(), (shot.left, shot.top, shot.width, shot.height))
                    stamp = _clock_ms(shot.taken)
                    for key, data in encoder.encode(shot.pixels, "bgra"):
                        self.wfile.write(struct.pack(">IBI", len(data), key, stamp) + data)
                    self.wfile.flush()
                    last = digest
        except (BrokenPipeError, ConnectionError, OSError):
            pass   # the phone closed the stream
        finally:
            grab.stop.set()

    # -- owner 2026-11-08: sound, speed test, window switcher, read aloud, voice click / voice typing -----------------
    def _audio(self, record):
        """GET /api/screen/audio: what the laptop plays, as Opus packets [4-byte length][4-byte capture ms][Opus 20 ms] (chutku/remote/audio.py),
        while the screen view lasts. 409 when there is no sound device to record from. Silence sends nothing."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        import struct
        from chutku.remote import audio
        try:
            source = audio.Loopback()
            encoder = audio.Opus(source.rate)
        except Exception:
            raise RemoteDenied("No sound device to record from on this laptop.", 409)
        screen["audio"] = token = secrets.token_hex(4)   # a newer one from this phone replaces this one
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            while self.server.screen is screen and screen.get("audio") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                samples = source.read()
                if samples is not None:
                    packets, now = encoder.encode(samples), time.monotonic()
                    for index, packet in enumerate(packets):
                        stamp = _clock_ms(now - 0.02 * (len(packets) - 1 - index))
                        self.wfile.write(struct.pack(">II", len(packet), stamp) + packet)
                    self.wfile.flush()
                time.sleep(0.02)
        except (BrokenPipeError, ConnectionError, OSError):
            pass   # the phone closed it
        finally:
            source.close()

    def _speedtest(self, query):
        """GET /api/speedtest?mb=N: N MB (1-20) for the phone to time, laptop -> phone, over whatever path Tailscale
        uses right now (direct or a relay)."""
        size = max(1, min(20, int((query.get("mb") or ["5"])[0]))) * 1024 * 1024
        chunk = secrets.token_bytes(64 * 1024)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for start in range(0, size, len(chunk)):
                self.wfile.write(chunk[:min(len(chunk), size - start)])
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _post_control_window(self, record, data):
        return self._control().focus(int(data.get("id")), self._monitor())

    def _post_control_read(self, record, data):
        """Read aloud: the paragraph of text under the finger (the phone speaks it), while the screen is shared."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        from chutku.remote import targets
        from chutku.remote.control import to_pixels
        x, y = to_pixels(self._monitor(), data.get("x"), data.get("y"))
        return {"text": targets.text_at(x, y)}

    def _post_control_voice(self, record, data):
        """Voice click and voice typing: "Save pe click karo" / "click Save" clicks the button named Save in the front
        window (UI Automation); anything else said is typed where the text cursor is."""
        control = self._control()
        pcm = decode_audio(data["audio"])
        if len(pcm) > 15 * 32000:
            raise RemoteDenied("Keep it under 15 seconds.", 413)
        from chutku.voice.recognition import command_language
        from chutku.voice.whisper_stt import transcribe_pcm
        heard = transcribe_pcm(pcm, language=command_language(self.server.core.base), base=self.server.core.base)
        text = (heard.get("text") or "").strip()
        if not text or heard.get("confidence", 0) < 0.35:
            return {"heard": None, "message": "Theek se sunai nahi diya, phir se bolo."}
        from chutku.remote import targets
        from chutku.remote.control import spoken_click
        monitor = self._monitor()
        name = spoken_click(text)
        if name is None:
            control.text(text)
            return {"heard": text, "did": "type"}
        target = targets.find_by_name(name, monitor)
        if not target:
            from chutku.remote.control import VK
            if name in VK:   # "press Enter", "Escape dabao": no button by that name, so the key itself
                control.keys(name)
                return {"heard": text, "did": "key", "key": name}
            return {"heard": text, "message": f'"{name}" naam ka button is window mein nahi mila.'}
        left, top, width, height = target["rect"]
        x = min(1.0, max(0.0, (left + width / 2 - monitor[0]) / monitor[2]))
        y = min(1.0, max(0.0, (top + height / 2 - monitor[1]) / monitor[3]))
        control.pointer([{"kind": "tap", "x": x, "y": y}], monitor)
        return {"heard": text, "did": "click", "target": targets.on_monitor(target, monitor)}

    def _cursor_stream(self, record):
        """GET /api/cursor/stream: where the mouse is (0..1 of the streamed monitor), as server-sent events, whenever it
        moves (owner 2026-11-07, "the cursor still lags"). Like Chrome Remote Desktop / RustDesk / Parsec, the phone
        draws the pointer itself; this only corrects it, and shows moves made at the laptop. A newer one replaces it."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        from chutku.remote.control import cursor_pos
        screen["cursor"] = token = secrets.token_hex(4)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last, sent_at, hovered, looked_at, looked_pos = None, 0.0, None, 0.0, None
        try:
            while self.server.screen is screen and screen.get("cursor") == token and time.monotonic() < screen["until"] \
                    and not self.server.stopped.is_set():
                monitor = self._monitor()
                left, top, width, height = monitor
                x, y = cursor_pos()
                at = [round((x - left) / max(width, 1), 4), round((y - top) / max(height, 1), 4)]
                now = time.monotonic()
                if at != last or now - sent_at > 10:   # a keep-alive every 10 s finds a phone that went away
                    self.wfile.write(b"data: " + json.dumps(at).encode() + b"\n\n")
                    self.wfile.flush()
                    last, sent_at = at, now
                # the magnetic pointer (owner 2026-11-08): what is under it, while the phone controls the laptop
                if at != looked_pos and now - looked_at > HOVER_EVERY and self.server.controlling():
                    from chutku.remote import targets
                    found = targets.hover(x, y, monitor)
                    found = targets.on_monitor(found, monitor) if found else None
                    looked_pos, looked_at = at, now
                    if found != hovered:
                        self.wfile.write(b"event: hover\ndata: " + json.dumps(found).encode() + b"\n\n")
                        self.wfile.flush()
                        hovered = found
                time.sleep(CURSOR_TICK)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    # -- P5/P6: direct control ---------------------------------------------------------------------------------------
    def _post_control_start(self, record, data):
        if not self.server.store.settings()["control_allowed"]:
            raise RemoteDenied("Laptop pe control on karna hoga (dashboard or tray).", 409)
        self._pin(record, data.get("pin"))
        from chutku.remote.control import ControlSession
        self.server.control = ControlSession(self.server.core.base)
        self.server._border(True)
        if self.server.monitor is None:   # smart tap: start UI Automation now, so the first tap is not skipped
            from chutku.remote import targets
            targets.warm()
        return {"control": True, "minutes": 30}

    def _control(self):
        control = self.server.control
        if control is None or not control.alive():
            raise RemoteDenied("Start control with your PIN first.", 409)
        return control

    def _monitor(self):
        if self.server.monitor is not None:
            return self.server.monitor
        seen = getattr(self.server, "monitor_seen", None)   # the latest frame's monitor: no capture per trackpad move
        if seen and time.monotonic() - seen[0] < MONITOR_SECONDS:
            return seen[1]
        from chutku.remote.control import primary_monitor
        rect = primary_monitor()
        self.server.monitor_seen = (time.monotonic(), rect)
        return rect

    def _post_control_input(self, record, data):
        events = data.get("events")
        if not isinstance(events, list):
            raise RemoteDenied("Send a list of events.", 400)
        return self._control().pointer(events, self._monitor())

    def _post_control_text(self, record, data):
        pin_ok = False
        if data.get("pin") is not None:   # only sent when the laptop asked for it (a command window): always checked
            self._pin(record, data.get("pin"), strict=True)
            pin_ok = True
        return self._control().text(data.get("text", ""), enter=bool(data.get("enter")), pin_ok=pin_ok)

    def _post_control_keys(self, record, data):
        pin_ok = False
        if data.get("pin") is not None:
            self._pin(record, data.get("pin"), strict=True)
            pin_ok = True
        return self._control().keys(data.get("combo", ""), pin_ok=pin_ok)

    def _post_control_stop(self, record, data):
        if self.server.control is not None:
            self.server.control.end("stopped from the phone")
        self.server.control = None
        self.server._border(False)
        return {"control": False}

    # -- P7: clipboard -----------------------------------------------------------------------------------------------
    def _post_clipboard_get(self, record, data):
        self._pin(record, data.get("pin"))      # the laptop clipboard can hold secrets
        from chutku.tools.clipboard import _invoke
        text = _invoke({"action": "read"}).get("text") or ""
        _log(self.server.core.base, "clipboard_to_phone", {"characters": len(text)})
        return {"text": text[:20000]}

    def _post_clipboard_set(self, record, data):
        text = data.get("text")
        if not isinstance(text, str) or len(text) > 20000:
            raise RemoteDenied("Send text up to 20000 characters.", 400)
        # 2026-11-08 review: changing the laptop needs the PIN session, not only the 12-hour pairing cookie
        pin_ok = data.get("pin") is not None
        self._pin(record, data.get("pin"), strict=pin_ok)
        from chutku.tools.clipboard import _invoke
        _invoke({"action": "write", "text": text})
        _log(self.server.core.base, "clipboard_from_phone", {"characters": len(text)})
        if data.get("paste"):
            self._control().keys("ctrl+v", pin_ok=pin_ok)
        return {"copied": len(text), "pasted": bool(data.get("paste"))}

    # -- P8: files ---------------------------------------------------------------------------------------------------
    def _upload(self, record):
        self._pin(record, self.headers.get("X-Chutku-PIN") or None)   # inside the PIN session (2026-11-08 review)
        name = Path(str(parse_qs(urlsplit(self.path).query).get("name", ["phone-file"])[0])).name[:120] or "phone-file"
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            raise RemoteDenied("Files up to 200 MB.", 413)
        folder = self.server.inbox / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        if Path(name).suffix.casefold() in BLOCKED_SUFFIXES:
            name += ".blocked"            # never opened by itself
        target = _free_name(folder / name)
        digest, left = hashlib.sha256(), length
        with open(target, "xb") as stream:     # create-only: never overwrites
            while left:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                left -= len(chunk)
        if left:
            target.unlink(missing_ok=True)
            raise RemoteDenied("The upload was cut off.", 400)
        _log(self.server.core.base, "file_from_phone", {"path": str(target), "bytes": length,
                                                        "sha256": digest.hexdigest()})
        self._reply(200, {"saved": str(target), "bytes": length, "sha256": digest.hexdigest()})

    # Owner 2026-11-07: browse instead of typing a path. Read-only, inside the PIN session, the same refusals as a fetch.
    def _post_files_places(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        return files_browse.places()

    def _post_files_list(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        try:
            return files_browse.listing(data.get("path"), str(data.get("kind") or "all"))
        except PermissionError as error:
            raise RemoteDenied(str(error)) from None

    def _post_files_search(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        return files_browse.search(data.get("q"), str(data.get("kind") or "all"))

    def _post_files_recent(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        return files_browse.recent(str(data.get("kind") or "all"))

    def _post_files_get(self, record, data):
        self._pin(record, data.get("pin"))
        path = Path(str(data.get("path") or "")).expanduser()
        reason = file_refusal(path)
        if reason:
            raise RemoteDenied(reason)
        blob = path.read_bytes()
        _log(self.server.core.base, "file_to_phone", {"path": str(path), "bytes": len(blob),
                                                      "sha256": hashlib.sha256(blob).hexdigest()})
        return 200, blob, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{path.name}"'}

    # -- P9: point-and-ask -------------------------------------------------------------------------------------------
    def _post_point(self, record, data):
        from chutku.remote.control import to_pixels
        question = str(data.get("question") or "").strip()
        if not 1 <= len(question) <= 300:
            raise RemoteDenied("Say what to do with the spot you tapped.", 400)
        monitor = self._monitor()
        x, y = to_pixels(monitor, data.get("x"), data.get("y"))
        near = ""
        try:
            from chutku import vision
            shot = vision.capture()
            lines = vision.read_lines(shot, (max(shot.left, x - 220), max(shot.top, y - 90),
                                             min(shot.left + shot.width, x + 220), min(shot.top + shot.height, y + 90)))
            near = " | ".join(str(line["text"]) for line in lines)[:400]
        except Exception:
            pass
        mode = self.server.core.preferences.load()["handsfree_mode"]
        session = self.server.core.begin_session(question, mode, "phone", extra_context={
            "pointed_at": {"x": x, "y": y, "text_near_the_point": {"untrusted_data": near}}})
        return {"session": self._phone_view(session.snapshot())}


def _step_key(pending):
    return hashlib.sha256(json.dumps(pending, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _free_name(path):
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RemoteDenied("Too many files with that name today.", 409)


STREAM_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mkv": "video/webm", ".webm": "video/webm",
                ".mov": "video/mp4", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
                ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}
# shortcut: .mkv is announced as video/webm (Matroska) so Chrome's player tries it; HEVC/AC3 episodes may still not
# play on the phone (codec support, not Chutku); then Download works.


def file_refusal(path, max_size=MAX_UPLOAD):
    """Why a laptop file may not go to the phone (None = allowed). max_size None: no cap (streamed, not loaded)."""
    from chutku.core.paths import protected_zones
    from chutku.references import secret_reason
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return "No such file."
    if not resolved.is_file():
        return "That is not a file."
    lowered = str(resolved).casefold()
    if any(lowered == zone or lowered.startswith(zone.rstrip("\\") + "\\") for zone in protected_zones()):
        return "That file is in a protected system area."
    reason = secret_reason(str(resolved))
    if reason:
        return reason
    if max_size is not None and resolved.stat().st_size > max_size:
        return "Files up to 200 MB."
    return None


def decode_audio(blob):
    """A phone recording (webm/opus, ogg, m4a, wav) -> 16 kHz mono int16 PCM, in memory (PyAV)."""
    import av
    import numpy as np
    chunks = []
    with av.open(io.BytesIO(blob)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.int16).tobytes() if chunks else b""


def spoken_text(snapshot):
    """What the phone says aloud for a task: its approval question while it waits, else its reply."""
    import re
    if snapshot.get("status") == "waiting_confirmation":
        approval = (snapshot.get("pending") or {}).get("approval") or {}
        what = approval.get("consequence") or approval.get("tool")
        return f"Ek approval chahiye: {what}. Phone pe approve ya cancel dabao."[:600] if what else ""
    return re.sub(r"\s*\[Verified:.*\]\s*$", "", snapshot.get("reply") or "")[:600]


def play_on_laptop(pcm, rate=16000):
    """Play a phone recording on the laptop speakers. The wake listener ignores it (voice session "speaking"), so
    the owner's voice from the speakers can never wake Chutku."""
    import numpy as np
    import sounddevice as sd
    from chutku.voice.session import voice_session
    with voice_session.active("speaking"):
        sd.play(np.frombuffer(pcm, dtype=np.int16), rate)
        sd.wait()


def wav(text):
    import numpy as np
    import struct
    from chutku.voice import tts
    parts, rate = [], 24000
    for sentence in tts.sentences(text) or [text]:
        samples, rate = tts.synthesize(sentence)
        parts.append(np.asarray(samples, dtype=np.float32).reshape(-1))
    audio = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2").tobytes()
    return (b"RIFF" + struct.pack("<I", 36 + len(audio)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate,
            rate * 2, 2, 16) + b"data" + struct.pack("<I", len(audio)) + audio)


def _jpeg(rgb, quality, width=None):
    """JPEG through PyAV's MJPEG encoder (already installed for speech), scaled to `width` by PyAV's scaler (9 ms for
    1080p, against 225 ms for vision.scaled), else PNG. quality: 2 (best) .. 31."""
    try:
        import av
        import numpy as np
        height, full = rgb.shape[0], rgb.shape[1]
        out_w = min(width or full, full)
        out_w, out_h = out_w - out_w % 2, round(height * out_w / full / 2) * 2
        codec = av.CodecContext.create("mjpeg", "w")
        codec.width, codec.height, codec.pix_fmt = out_w, out_h, "yuvj420p"
        codec.qmin = codec.qmax = quality
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
        frame = frame.reformat(width=out_w, height=out_h, format="yuvj420p", interpolation="AREA")
        return b"".join(bytes(packet) for packet in codec.encode(frame)), "image/jpeg"
    except Exception:   # no PyAV or no MJPEG encoder: the lossless frame still works
        from chutku import vision
        return _png(vision.scaled(rgb, width or rgb.shape[1]), level=1), "image/png"


def _clock_ms(monotonic):
    """The laptop clock both streams are stamped with (ms, wraps at 2^32): the phone lines sound and picture up by it."""
    return int(monotonic * 1000) & 0xFFFFFFFF


def _changed(pixels):
    """A checksum of every pixel (~5 ms for 1080p): a typed letter or a blinking caret is a change. The old sample of
    every 16th row and column missed them until the 2 s keep-alive."""
    import zlib
    import numpy as np
    return zlib.crc32(np.ascontiguousarray(pixels))   # the array itself: no 6-8 MB copy


class _Grabber(threading.Thread):
    """Captures the next screen while the last one is encoded and sent (owner 2026-11-08: capture ~34 ms and encode
    ~15 ms took turns, ~17 frames/s). take() gives the newest capture, never an old one twice."""

    def __init__(self):
        super().__init__(daemon=True, name="chutku-screen-grab")
        self.latest, self.fresh, self.stop = None, threading.Event(), threading.Event()

    def run(self):
        from chutku import vision
        capturer = vision.Capturer()   # BGRA, GDI objects kept: ~20 ms a frame instead of ~35
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                try:
                    shot = capturer.grab()
                except OSError:   # locked or a secure screen for a moment
                    time.sleep(1.0)
                    continue
                last = self.latest
                same = last is not None and shot is last[0]   # the GPU said nothing changed: no checksum needed
                if same:
                    self.latest = last
                else:   # a GPU frame is new only when the screen changed: no checksum (it held the GIL ~3 ms)
                    self.latest = (shot, id(shot) if shot.window.get("gpu") else _changed(shot.pixels))
                self.fresh.set()
                time.sleep(max(0.0, VIDEO_FRAME - (time.monotonic() - started)))
        finally:
            capturer.close()

    def take(self, timeout):
        if not self.fresh.wait(timeout):
            return None
        self.fresh.clear()
        return self.latest


H264_ENCODERS = (("h264_nvenc", {"preset": "p1", "tune": "ull", "zerolatency": "1", "delay": "0"}),   # the GPU
                 ("libx264", {"preset": "ultrafast", "tune": "zerolatency"}))   # in PyAV itself: every laptop
# (h264_mf left out 2026-11-08: on this laptop it gave no frames at all, with or without rate limits)


class H264:
    """The screen as H.264 (owner 2026-11-08, "no lag or jitter"): the way paid remote desktops are fast. Measured on
    this laptop at 1280x720: NVENC 15 ms, libx264 12 ms a frame, every frame out at once (no delay, no B-frames), ~4-7 KB
    a frame after the first, where a JPEG frame is ~100 KB: far less for the ~90 ms Tailscale relay to carry."""

    def __init__(self, width, height, *, names=H264_ENCODERS, bit_rate=3_000_000):
        import av
        from fractions import Fraction
        self.size, self.count, self.name = (width - width % 2, height - height % 2), 0, None
        for name, options in names:
            try:
                codec = av.CodecContext.create(name, "w")
                codec.width, codec.height = self.size
                codec.pix_fmt = "yuv420p" if name == "libx264" else "nv12"
                codec.time_base, codec.framerate = Fraction(1, 30), Fraction(30, 1)
                codec.bit_rate, codec.gop_size, codec.max_b_frames = bit_rate, 600, 0
                # a steady stream (owner 2026-11-08, "smoothness"): at most bit_rate, with a 250 ms buffer, so one big
                # frame never arrives as a burst that stalls the relay; NVENC in constant-bitrate mode
                codec.options = {**options, "maxrate": str(bit_rate), "bufsize": str(bit_rate // 4),
                                 **({"rc": "cbr"} if name == "h264_nvenc" else {})}
                codec.open()
            except Exception:   # this encoder is missing or the GPU is busy: the next one
                continue
            self.codec, self.name = codec, name
            return
        raise OSError("No H.264 encoder works on this laptop.")

    def encode(self, pixels, layout="rgb24"):
        """[(keyframe, Annex B bytes)] for one screen picture (the first is a keyframe). layout: "rgb24", or "bgra"
        straight from vision.Capturer (no RGB copy; scaling from BGRA measured 12.7 ms against 18.5 ms)."""
        import av
        import numpy as np
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(pixels), format=layout)
        frame = frame.reformat(width=self.size[0], height=self.size[1], format=self.codec.pix_fmt, interpolation="AREA")
        frame.pts, self.count = self.count, self.count + 1
        return [(bool(packet.is_keyframe), bytes(packet)) for packet in self.codec.encode(frame)]


def _png(rgb, level=1):
    import struct
    import zlib
    import numpy as np
    height, width, _ = rgb.shape
    raw = np.hstack([np.zeros((height, 1), np.uint8), rgb.reshape(height, width * 3)]).tobytes()

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b""))


def _log(base, kind, details):
    try:
        from chutku.core.action_log import ActionLog
        ActionLog(Path(base) / "data" / "actions.log.jsonl").append(
            {"tool": "remote." + kind, "state": "COMPLETED", "origin": "phone", **details})
    except (OSError, ValueError):
        pass


def _keep_awake(on):
    try:
        from chutku.nightshift import keep_awake, on_ac_power
        keep_awake(bool(on) and on_ac_power())
    except Exception:
        pass
