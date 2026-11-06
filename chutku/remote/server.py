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
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit

from chutku.core.paths import user_folder
from chutku.remote.auth import RemoteDenied, RemoteStore

WEB = Path(__file__).resolve().parents[1] / "web" / "phone"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/phone.js": ("phone.js", "text/javascript; charset=utf-8"),
          "/phone.css": ("phone.css", "text/css; charset=utf-8"), "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json")}
MAX_BODY = 2 * 1024 * 1024                 # JSON and voice clips
MAX_UPLOAD = 200 * 1024 * 1024             # P8 phone -> laptop files
SCREEN_MAX = 30 * 60
SCREEN_BEAT = 15.0
INBOX = Path(user_folder("ChutkuInbox"))
BLOCKED_SUFFIXES = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".lnk", ".com", ".hta", ".jar"}
# Steps that may never be approved from the phone, whatever the PIN: they wait for the laptop's own card.
LAPTOP_ONLY_PREFIXES = ("never.", "remote.", "power.", "filesystem.delete_permanent", "process.terminate",
                        "network.")


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
        super().__init__(("127.0.0.1", port), PhoneHandler)

    # -- laptop-side state ----------------------------------------------------------------------------------------
    def viewing(self):
        screen = self.screen
        return bool(screen and time.monotonic() < screen["until"] and time.monotonic() - screen["beat"] < SCREEN_BEAT)

    def controlling(self):
        return bool(self.control and self.control.alive())

    def disarm(self, reason="disarmed at the laptop"):
        """Ctrl+Alt+Shift+P, the tray, "remote band karo", Funnel: end control (and screen view) now."""
        if self.control is not None:
            self.control.end(reason)
        self.control = None
        self._border(False)
        self.store.configure(control_allowed=False)

    def end_all(self, reason):
        self.disarm(reason)
        self.screen = None
        self.store.sessions.clear()

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
        self.end_all("server stopped")
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
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; manifest-src 'self'; "
                         "worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _deny(self, error):
        self._reply(getattr(error, "status", 403), {"error": str(error)})

    # -- the gates ------------------------------------------------------------------------------------------------
    def _tailnet(self):
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
        settings = self._tailnet()
        record = self.server.store.session(self._cookie())
        if mutation:
            if self.headers.get("X-Chutku-CSRF") != record["csrf"] or \
                    self.headers.get("Origin") != "https://" + settings["host"]:
                raise RemoteDenied("Request refused (CSRF).")
        self.server.store.rate(record["device"])
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

    def _pin(self, record, pin):
        self.server.store.check_pin(record["device"], pin)

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
                self._reply(200, {"device": device.get("name"), "control_allowed": settings["control_allowed"],
                                  "paused": self._paused(), "csrf": record["csrf"]})
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
            elif path == "/api/say":
                self._say(query.get("id", [""])[0])
            else:
                self._reply(404, {"error": "Not found."})
        except RemoteDenied as error:
            self._deny(error)
        except (KeyError, ValueError) as error:
            self._reply(400, {"error": str(error)[:200]})

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
        if path in ("/api/voice", "/api/laptop/voice"):
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
        tool = str(approval.get("tool") or "")
        if tool.startswith(LAPTOP_ONLY_PREFIXES):
            return True
        risk = approval.get("risk")
        if isinstance(risk, (int, float)) and risk >= 4:
            return True
        reason = str(approval.get("reason") or "").casefold()
        if "not in memory" in reason or "new recipient" in reason or "unknown" in reason:
            return True
        try:
            from chutku.app import create_runtime
            with create_runtime(self.server.core.base) as runtime:
                return bool(getattr(runtime.registry.get(tool), "runs_code", False))
        except (KeyError, ValueError, OSError):
            return True     # unknown tool: the laptop decides

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
        self._pin(record, data.get("pin"))
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
        return {"viewing": True, "minutes": SCREEN_MAX // 60}

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
        shot = vision.capture()
        width = 1280 if self.server.controlling() else 960
        pixels = vision.scaled(shot.pixels, width)
        digest = hashlib.sha1(pixels[::8, ::8].tobytes()).hexdigest()
        if digest == last_hash:
            self._reply(204, b"", "text/plain", headers={"X-Frame-Hash": digest})
            return
        self._reply(200, _png(pixels, level=1), "image/png",
                    headers={"X-Frame-Hash": digest, "X-Monitor": json.dumps([shot.left, shot.top, shot.width, shot.height])})

    # -- P5/P6: direct control ---------------------------------------------------------------------------------------
    def _post_control_start(self, record, data):
        if not self.server.store.settings()["control_allowed"]:
            raise RemoteDenied("Laptop pe control on karna hoga (dashboard or tray).", 409)
        self._pin(record, data.get("pin"))
        from chutku.remote.control import ControlSession
        self.server.control = ControlSession(self.server.core.base)
        self.server._border(True)
        return {"control": True, "minutes": 30}

    def _control(self):
        control = self.server.control
        if control is None or not control.alive():
            raise RemoteDenied("Start control with your PIN first.", 409)
        return control

    def _monitor(self):
        if self.server.monitor is not None:
            return self.server.monitor
        from chutku.remote.control import primary_monitor
        return primary_monitor()

    def _post_control_input(self, record, data):
        events = data.get("events")
        if not isinstance(events, list):
            raise RemoteDenied("Send a list of events.", 400)
        return self._control().pointer(events, self._monitor())

    def _post_control_text(self, record, data):
        pin_ok = False
        if data.get("pin") is not None:
            self._pin(record, data.get("pin"))
            pin_ok = True
        return self._control().text(data.get("text", ""), enter=bool(data.get("enter")), pin_ok=pin_ok)

    def _post_control_keys(self, record, data):
        pin_ok = False
        if data.get("pin") is not None:
            self._pin(record, data.get("pin"))
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
        from chutku.tools.clipboard import _invoke
        _invoke({"action": "write", "text": text})
        _log(self.server.core.base, "clipboard_from_phone", {"characters": len(text)})
        if data.get("paste"):
            pin_ok = False
            if data.get("pin") is not None:
                self._pin(record, data.get("pin"))
                pin_ok = True
            self._control().keys("ctrl+v", pin_ok=pin_ok)
        return {"copied": len(text), "pasted": bool(data.get("paste"))}

    # -- P8: files ---------------------------------------------------------------------------------------------------
    def _upload(self, record):
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


def file_refusal(path):
    """Why a laptop file may not go to the phone (None = allowed)."""
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
    if resolved.stat().st_size > MAX_UPLOAD:
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
