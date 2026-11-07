"""H16 Telegram remote control (Hermes gateway + DM pairing), a second remote path next to the phone app.

Chutku only polls OUT to api.telegram.org (long poll with urllib): no port is opened on the PC. It is off until the
owner makes a bot with BotFather and stores its token (`chutku.cli telegram set-token`, Windows Credential Manager).

Pairing: the dashboard (or "telegram pair code do") shows an 8-character code, valid for 1 hour, at most 3 waiting.
The owner sends `/pair CODE` to the bot. 5 wrong codes within an hour lock pairing for an hour. One chat is paired;
every other chat is ignored without a reply (strangers do not even learn the bot is alive) and logged as "ignored".

From the paired chat:
  text        -> a normal request (origin "phone": the same policy as the phone app), at most 20 an hour
  voice note  -> local Whisper -> the misheard-text guard -> a request; refused while the voice lock is on
  a step that asks -> Approve / Reject buttons, bound to that session and step by a single-use nonce (10 minutes).
                 Never from Telegram (remote.server.laptop_only): R4, code runners, unknown recipients, never-rules,
                 remote/telegram settings. Those answer "Ye PC pe approve karna hoga." and wait for the laptop.
Handoff: "main bahar ja raha hoon, phone pe batana" -> for 4 hours research and scheduled results and approval cards
for waiting tasks also go to Telegram; "main wapas aa gaya" (or PC input after more than 10 idle minutes) ends it.
Replies are capped at 3,500 characters and pass persona.feminine(). The token is never logged: the request URL is
built only inside _call and errors are reported without it.
"""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import threading
import time

API = "https://api.telegram.org"
CREDENTIAL = "Chutku/Telegram"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L
CODE_LENGTH = 8
CODE_TTL = 3600
MAX_PENDING = 3
MAX_WRONG = 5
LOCKOUT = 3600
RATE_PER_HOUR = 20
NONCE_TTL = 600
REPLY_CHARS = 3500
HANDOFF_HOURS = 4
POLL_SECONDS = 20
VOICE_MAX_BYTES = 2_000_000
_ACTIVE = {"gateway": None}
_LOCK = threading.RLock()


def token():
    import os
    value = os.environ.get("TELEGRAM_BOT_TOKEN")
    if value:
        return value
    try:
        from chutku.cloud_planner import stored_key
        return stored_key(CREDENTIAL)
    except Exception:
        return None


def store_token(value):
    import re
    from chutku.cloud_planner import store_key
    if not isinstance(value, str) or not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{30,60}", value.strip()):
        raise ValueError("That does not look like a BotFather token (digits:letters).")
    store_key(value.strip(), CREDENTIAL)


def state_path(base) -> Path:
    return Path(base) / "data" / "telegram.json"


def load(base):
    try:
        data = json.loads(state_path(base).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(base, data):
    from chutku.core.jsonstore import write_json
    write_json(state_path(base), data)


def paired(base):
    return load(base).get("chat_id")


class TelegramError(OSError):
    pass


def _real_transport(bot_token):
    import urllib.error
    import urllib.request

    def call(method, params, timeout):
        request = urllib.request.Request(f"{API}/bot{bot_token}/{method}", method="POST",
                                         data=json.dumps(params).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "User-Agent": "Chutku/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise TelegramError(f"Telegram answered HTTP {error.code} to {method}.") from None   # no URL: no token
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise TelegramError(f"Telegram is not reachable ({type(error).__name__}).") from None
        if not body.get("ok"):
            raise TelegramError(f"Telegram refused {method}: {str(body.get('description'))[:120]}")
        return body.get("result")

    def download(file_path, timeout):
        try:
            with urllib.request.urlopen(f"{API}/file/bot{bot_token}/{file_path}", timeout=timeout) as response:
                return response.read(VOICE_MAX_BYTES + 1)
        except urllib.error.HTTPError as error:   # its url holds the token: never let it travel up
            raise TelegramError(f"Telegram answered HTTP {error.code} to a file download.") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise TelegramError(f"Telegram is not reachable ({type(error).__name__}).") from None
    call.download = download
    return call


class Gateway:
    """One bot, one paired chat. `core` is the DashboardServer; `transport(method, params, timeout)` calls the Bot
    API (tests inject a fake); `transcribe(audio_bytes) -> text|None` hears a voice note."""

    def __init__(self, base, core=None, *, transport=None, transcribe=None, clock=time.time, laptop_only=None):
        self.base, self.core, self.clock = Path(base), core, clock
        self.transport = transport
        self.transcribe = transcribe
        self.laptop_only = laptop_only
        self.following = {}     # session id -> last status sent

    # -- state -------------------------------------------------------------------------------------------------------
    def _state(self):
        data = load(self.base)
        now = self.clock()
        data["codes"] = [c for c in data.get("codes", []) if c.get("expires", 0) > now]
        data["wrong"] = [t for t in data.get("wrong", []) if now - t < LOCKOUT]
        data["rate"] = [t for t in data.get("rate", []) if now - t < 3600]
        data["nonces"] = {k: v for k, v in (data.get("nonces") or {}).items() if v.get("expires", 0) > now}
        return data

    def new_code(self):
        """A pairing code for the owner to send as /pair CODE (shown on the laptop only)."""
        with _LOCK:
            data = self._state()
            if data.get("locked_until", 0) > self.clock():
                raise ValueError("Too many wrong codes: pairing is locked for an hour.")
            if len(data["codes"]) >= MAX_PENDING:
                raise ValueError("3 codes are already waiting. Use one of them, or wait an hour.")
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            data["codes"].append({"code": code, "expires": self.clock() + CODE_TTL})
            save(self.base, data)
            return code

    def _pair(self, chat_id, code):
        with _LOCK:
            data = self._state()
            now = self.clock()
            if data.get("locked_until", 0) > now:
                return False
            code = str(code or "").strip().upper()
            if any(secrets.compare_digest(c["code"], code) for c in data["codes"]):
                data.update(chat_id=int(chat_id), codes=[], wrong=[], paired_at=now)
                save(self.base, data)
                return True
            data["wrong"].append(now)
            if len(data["wrong"]) >= MAX_WRONG:
                data["locked_until"], data["wrong"] = now + LOCKOUT, []
            save(self.base, data)
            return False

    def unpair(self):
        with _LOCK:
            data = self._state()
            data.pop("chat_id", None)
            data.pop("handoff_until", None)
            save(self.base, data)

    # -- Bot API -----------------------------------------------------------------------------------------------------
    def _call(self, method, params, timeout=30):
        if self.transport is None:
            bot = token()
            if not bot:
                raise TelegramError("No Telegram bot token is stored.")
            self.transport = _real_transport(bot)
        return self.transport(method, params, timeout)

    def send(self, text, buttons=None):
        chat = paired(self.base)
        if chat is None:
            return None
        from chutku.persona import feminine
        params = {"chat_id": chat, "text": feminine(str(text))[:REPLY_CHARS]}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [buttons]}
        return self._call("sendMessage", params)

    # -- intake ------------------------------------------------------------------------------------------------------
    def handle(self, update):
        """One update. Returns what happened (for the log and tests): ignored / paired / request / ..."""
        if "callback_query" in update:
            return self._callback(update["callback_query"])
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = str(message.get("text") or "").strip()
        if chat_id is None:
            return "ignored"
        if chat_id != paired(self.base):
            if text.startswith("/pair ") and self._pair(chat_id, text[6:]):
                self.send("Jud gayi! Ab yahan se kaam bolo. Approve/Reject buttons yahin aayenge.")
                return "paired"
            from chutku.core.log import get_logger
            get_logger("telegram").info("ignored an update from an unpaired chat")   # no content, no chat id
            return "ignored"
        with _LOCK:
            data = self._state()
            if len(data["rate"]) >= RATE_PER_HOUR:
                save(self.base, data)
                self.send("Ek ghante mein 20 se zyada messages: thodi der baad bhejo.")
                return "rate_limited"
            data["rate"].append(self.clock())
            save(self.base, data)
        if self._paused():
            self.send("Chutku paused hai. Laptop pe Resume dabao.")
            return "paused"
        if message.get("voice"):
            text = self._hear(message["voice"])
            if text is None:
                return "voice_refused"
        if not text:
            return "ignored"
        return self._request(text, "phone_voice" if message.get("voice") else "phone")

    def _paused(self):
        from chutku import pause
        from chutku.core.action_control import ActionControl
        return ActionControl(self.base).paused or pause.engaged(self.base)

    def _hear(self, voice):
        from chutku.core.preferences import Preferences
        if Preferences(self.base).load().get("voice_lock"):
            self.send("Voice lock on hai, isliye phone ki aawaz se kaam nahi karti. Text bhejo.")
            return None
        if self.transcribe is None or int(voice.get("file_size") or 0) > VOICE_MAX_BYTES:
            self.send("Ye voice note main sun nahi paayi. Text bhejo.")
            return None
        try:
            info = self._call("getFile", {"file_id": voice["file_id"]})
            audio = self.transport.download(info["file_path"], 30)
            text = self.transcribe(audio)
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            text = None
        if not text:
            self.send("Theek se sunai nahi diya, phir se bolo ya likh do.")
            return None
        from chutku.voice.plausible import plausible, read_back
        if not plausible(text, known_names=self.core._known_names() if self.core else []):
            self.send(read_back(text))
            return None
        return text

    def _request(self, text, origin):
        if self.core is None:
            return "no_core"
        control = _handoff_words(text)
        if control == "start":
            self.handoff(True)
            self.send(f"Theek hai, agle {HANDOFF_HOURS} ghante results aur approvals yahin bhejungi.")
            return "handoff"
        if control == "end":
            self.handoff(False)
            self.send("Welcome back! Ab sab laptop pe dikhaungi.")
            return "handoff_end"
        mode = self.core.preferences.load()["handsfree_mode"]
        session = self.core.begin_session(text, mode, origin)
        self.following[session.id] = None
        self.follow()
        return "request"

    # -- results and approvals ---------------------------------------------------------------------------------------
    def follow(self):
        """Send each followed task's result once it ends, and an approval card when it waits."""
        if self.core is None:
            return
        for session_id, last in list(self.following.items()):
            try:
                snapshot = self.core.agent_sessions.get(session_id).snapshot()
            except (ValueError, KeyError):
                self.following.pop(session_id, None)
                continue
            status = snapshot["status"]
            if status == last:
                continue
            self.following[session_id] = status
            if status == "waiting_confirmation":
                self._card(snapshot)
            elif status in {"done", "failed", "stopped", "cancelled", "clarify"}:
                self.following.pop(session_id, None)
                self.send(snapshot["reply"] or status)

    def _card(self, snapshot):
        approval = (snapshot.get("pending") or {}).get("approval") or {}
        what = f"{approval.get('tool')}: {json.dumps(approval.get('arguments') or {}, ensure_ascii=False)[:300]}"
        if self._laptop_only_step(approval):
            self.send(f"'{snapshot['goal'][:80]}' ke liye ye step PC pe approve karna hoga: {what}")
            return
        with _LOCK:
            data = self._state()
            nonce = secrets.token_urlsafe(9)
            data["nonces"][nonce] = {"session": snapshot["id"], "step": _step_key(snapshot),
                                     "expires": self.clock() + NONCE_TTL}
            save(self.base, data)
        self.send(f"Approve karna hai? {what}\n({approval.get('reason') or 'ye step poochta hai'})",
                  buttons=[{"text": "Approve", "callback_data": f"a:{nonce}"},
                           {"text": "Reject", "callback_data": f"r:{nonce}"}])

    def _laptop_only_step(self, approval):
        if self.laptop_only is not None:
            return self.laptop_only(approval)
        from chutku.remote.server import laptop_only, runs_code_at
        return laptop_only(approval, runs_code_at(self.base))

    def _callback(self, query):
        chat_id = ((query.get("message") or {}).get("chat") or {}).get("id")
        if chat_id is None or chat_id != paired(self.base):
            return "ignored"
        self._answer(query)
        data_text = str(query.get("data") or "")
        if data_text[:2] not in ("a:", "r:"):
            return "ignored"
        with _LOCK:
            data = self._state()
            entry = data["nonces"].pop(data_text[2:], None)   # single use, even when the rest fails
            save(self.base, data)
        if entry is None:
            self.send("Ye button purana ho gaya. Kaam dobara bolo ya PC pe dekho.")
            return "stale"
        try:
            snapshot = self.core.agent_sessions.get(entry["session"]).snapshot()
        except (ValueError, KeyError, AttributeError):
            return "stale"
        if snapshot["status"] != "waiting_confirmation" or _step_key(snapshot) != entry["step"]:
            self.send("Ye step ab wait nahi kar raha.")
            return "stale"
        if self._laptop_only_step((snapshot.get("pending") or {}).get("approval") or {}):
            self.send("Ye PC pe approve karna hoga.")
            return "laptop_only"
        self.core.confirm_session(entry["session"], data_text[0] == "a")
        self.following[entry["session"]] = "running"
        return "approved" if data_text[0] == "a" else "rejected"

    def _answer(self, query):
        try:
            self._call("answerCallbackQuery", {"callback_query_id": query.get("id")})
        except (OSError, TypeError):
            pass

    # -- handoff -----------------------------------------------------------------------------------------------------
    def handoff(self, on, hours=HANDOFF_HOURS):
        with _LOCK:
            data = self._state()
            if on:
                data["handoff_until"] = self.clock() + hours * 3600
            else:
                data.pop("handoff_until", None)
            save(self.base, data)

    def handed_off(self):
        return load(self.base).get("handoff_until", 0) > self.clock()

    def watch_waiting(self):
        """During a handoff, approval cards for tasks waiting on the PC go to Telegram too."""
        if self.core is None or not self.handed_off():
            return
        for session in list(self.core.agent_sessions.sessions.values()):
            if session.status == "waiting_confirmation" and session.id not in self.following:
                self.following[session.id] = None
        self.follow()

    # -- loop --------------------------------------------------------------------------------------------------------
    def poll_once(self):
        data = self._state()
        updates = self._call("getUpdates", {"offset": data.get("offset", 0), "timeout": POLL_SECONDS,
                                            "allowed_updates": ["message", "callback_query"]},
                             timeout=POLL_SECONDS + 10) or []
        results = []
        for update in updates:
            with _LOCK:
                data = self._state()
                data["offset"] = max(data.get("offset", 0), int(update.get("update_id", 0)) + 1)
                save(self.base, data)
            try:
                results.append(self.handle(update))
            except Exception:
                from chutku.core.log import get_logger
                get_logger("telegram").exception("a Telegram update failed")
                results.append("error")
        self.follow()
        self.watch_waiting()
        self._end_handoff_on_return()
        return results

    def _end_handoff_on_return(self):
        """The owner is back at the PC (input after more than 10 idle minutes): the handoff ends."""
        if not self.handed_off():
            return
        try:
            from chutku.nightshift import idle_seconds
            idle = idle_seconds()
        except (OSError, AttributeError, ImportError):
            return
        data = load(self.base)
        if idle is None:
            return
        if idle > 600:
            data["was_idle"] = True
            save(self.base, data)
        elif data.get("was_idle") and idle < 60:
            data.pop("was_idle", None)
            data.pop("handoff_until", None)
            save(self.base, data)
            self.send("PC pe wapas aa gaye: ab sab laptop pe dikhaungi.")

    def run(self, stop):
        from chutku.core.log import get_logger
        log, wait = get_logger("telegram"), 2
        while not stop.is_set():
            try:
                self.poll_once()
                wait = 2
            except TelegramError as error:
                log.warning("telegram poll: %s", error)   # never the token: errors carry no URL
                if stop.wait(wait):
                    return
                wait = min(wait * 2, 300)


def _step_key(snapshot):
    pending = snapshot.get("pending") or {}
    step = pending.get("step") or {}
    return json.dumps([step.get("tool"), step.get("arguments")], sort_keys=True, default=str)


def _handoff_words(text):
    import re
    from chutku.translit import roman
    plain = " ".join(roman(text).casefold().split())
    if re.search(r"\b(?:bahar\s+ja\s+(?:raha|rahi)|phone\s+pe\s+(?:batana|bhejna|shift\s+karo)|"
                 r"i'?m\s+(?:going\s+)?out|hand\s*off)\b", plain):
        return "start"
    if re.search(r"\b(?:wapas\s+aa\s+(?:gaya|gayi)|main\s+aa\s+(?:gaya|gayi)|i'?m\s+back)\b", plain):
        return "end"
    return None


def deliver(base, text, *, kind="result"):
    """Outbound (H8 scheduled results, H15 research): sent only when a chat is paired and a handoff is on."""
    gateway = _ACTIVE["gateway"]
    if gateway is None or Path(gateway.base) != Path(base) or not gateway.handed_off():
        return False
    try:
        gateway.send(text)
        return True
    except OSError:
        return False


def whisper_transcriber(base):
    """Voice notes (OGG/Opus) -> text with the local Whisper (PyAV decodes the audio; nothing leaves the PC)."""
    def transcribe(audio):
        import io
        import numpy
        from faster_whisper.audio import decode_audio
        from chutku.voice.recognition import command_language
        from chutku.voice.whisper_stt import transcribe_pcm
        samples = decode_audio(io.BytesIO(audio), sampling_rate=16000)
        if len(samples) > 30 * 16000:
            return None
        pcm = (numpy.clip(samples, -1, 1) * 32767).astype(numpy.int16).tobytes()
        heard = transcribe_pcm(pcm, language=command_language(base), base=base)
        text = (heard.get("text") or "").strip()
        return text if text and heard.get("confidence", 0) >= 0.35 else None
    return transcribe


def register_telegram_tools(registry, base):
    """telegram.handoff: "main bahar ja raha hoon, phone pe batana" / "main wapas aa gaya" said at the PC."""
    from chutku.tools.registry import Risk, Tool, ToolResult, Verification

    def handoff(arguments, _context):
        if paired(base) is None:
            if not arguments["on"]:   # "main wapas aa gaya" is also just a greeting
                return ToolResult({"handoff": False, "summary": "Welcome back!"}, Verification.PASS)
            return ToolResult({"error": "Telegram abhi juda nahi hai (chutku.cli telegram pair)."}, Verification.FAIL)
        Gateway(base).handoff(arguments["on"])
        on = Gateway(base).handed_off()
        summary = (f"Theek hai, agle {HANDOFF_HOURS} ghante results aur approvals Telegram pe bhi bhejungi." if on
                   else "Welcome back! Ab sab laptop pe.")
        return ToolResult({"handoff": on, "summary": summary},
                          Verification.PASS if on == arguments["on"] else Verification.FAIL)
    registry.register(Tool("telegram.handoff", "Send results and approval cards to the paired Telegram chat for the "
        "next 4 hours (on=true: 'main bahar ja raha hoon, phone pe batana'), or stop (on=false: 'main wapas aa gaya').",
        Risk.REVERSIBLE, handoff, argument_schema={"type": "object", "properties": {"on": {"type": "boolean"}},
                                                   "required": ["on"], "additionalProperties": False},
        reversibility="compensatable"))


def start(core):
    """Start the long poll inside the dashboard when a token is stored (else nothing happens)."""
    if not token():
        return None
    gateway = Gateway(core.base, core, transcribe=whisper_transcriber(core.base))
    _ACTIVE["gateway"] = gateway
    threading.Thread(target=gateway.run, args=(core.closing,), name="chutku-telegram", daemon=True).start()
    return gateway
