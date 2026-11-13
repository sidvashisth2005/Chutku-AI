"""Phone pairing, credentials, PIN, sessions and approval nonces (W6 / HERMES_PLAN P1).

Stored in data/remote.json (same-user readable, like every Chutku file): only SHA-256 hashes of device credentials
and session tokens, and scrypt hashes of the PIN. Nothing secret is ever logged.

Rules (fail closed):
- a pairing code lasts 10 minutes, is single use, and 5 wrong tries lock pairing until a new code is made;
- at most 3 devices; a device is revoked by "phone hatao", the dashboard, or 5 wrong PINs;
- a session (after credential + PIN) lasts 12 hours; the credential alone never approves anything;
- every approval, screen view and control session needs the PIN again (step-up), and an approval is bound to
  session + step + a single-use nonce;
- 30 requests per minute per device;
- pairing, sign-ins, wrong PINs and removals go to the hash-chained action log (never a PIN or credential), and a
  phone removed by wrong PINs shows the owner a Windows notification.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time

from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
PAIR_SECONDS = 600
PAIR_ATTEMPTS = 5
MAX_DEVICES = 3
SESSION_SECONDS = 12 * 3600
PIN_TRIES = 5
RATE_PER_MINUTE = 30
# Owner 2026-11-07, "the screen never shows": frames (3/s), the trackpad and chat polling all spent the one 30/min
# budget, so the view died after ~10 s with 429. Each kind now has its own (count, seconds) budget per phone.
RATES = {"general": (RATE_PER_MINUTE, 60.0), "frame": (24, 3.0), "input": (180, 3.0), "poll": (9, 3.0)}
NONCE_SECONDS = 300
RELAY_DEVICE = "relay"   # the phone app reaching this laptop through the account relay (chutku/relay)
_lock = threading.RLock()


class RemoteDenied(PermissionError):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pin_hash(pin: str, salt: bytes) -> str:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


def valid_pin(pin) -> bool:
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 6


class RemoteStore:
    def __init__(self, base=PROJECT_ROOT, clock=time.time, alert=None):
        self.path = Path(base) / "data" / "remote.json"
        self.clock = clock
        self.alert = alert     # alert(title, message): the owner's notification for suspicious activity
        self.sessions = {}     # token hash -> {device, until, csrf}     (memory only: a restart logs the phone out)
        self.nonces = {}       # nonce -> {session, step, until}
        self.hits = {}         # (device, kind) -> [timestamps]
        self.last_seen = {}    # device -> the time of its latest request

    # -- storage --------------------------------------------------------------------------------------------------
    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
        temporary.replace(self.path)

    def settings(self) -> dict:
        data = self.load()
        return {"host": data.get("host"), "login": data.get("login"), "enabled": bool(data.get("enabled")),
                "control_allowed": bool(data.get("control_allowed", True)),   # owner 2026-11-08: on unless turned off
                "devices": [{k: d.get(k) for k in ("id", "name", "paired_at", "last_seen", "revoked")}
                            for d in data.get("devices", [])]}

    def configure(self, *, host=None, login=None, enabled=None, control_allowed=None):
        with _lock:
            data = self.load()
            if host is not None:
                data["host"] = host
            if login is not None:
                data["login"] = login
            if enabled is not None:
                data["enabled"] = bool(enabled)
            if control_allowed is not None:
                data["control_allowed"] = bool(control_allowed)
            self.save(data)
            return self.settings()

    def _audit(self, event, device_id, **details):
        try:
            from chutku.core.action_log import ActionLog
            ActionLog(self.path.parent / "actions.log.jsonl").append(
                {"tool": "remote." + event, "state": "COMPLETED", "origin": "phone", "device": device_id, **details})
        except (OSError, ValueError):
            pass

    # -- pairing --------------------------------------------------------------------------------------------------
    def new_pairing_code(self) -> str:
        """Shown on the laptop only (dashboard Phone panel / QR). 8 characters, no look-alikes."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        with _lock:
            data = self.load()
            data["pairing"] = {"hash": _hash(code), "until": self.clock() + PAIR_SECONDS, "attempts": 0}
            self.save(data)
        return code

    def pair(self, code: str, name: str, pin: str) -> dict:
        """Returns {"device_id", "credential"} once; the credential is shown to the phone only now."""
        if not valid_pin(pin):
            raise RemoteDenied("Choose a 4-6 digit PIN.", 400)
        with _lock:
            data = self.load()
            pairing = data.get("pairing") or {}
            if not pairing or self.clock() > pairing.get("until", 0) or pairing.get("attempts", 0) >= PAIR_ATTEMPTS:
                raise RemoteDenied("This pairing code has expired. Make a new one on the laptop.")
            if not hmac.compare_digest(_hash(str(code).strip().upper()), pairing["hash"]):
                pairing["attempts"] = pairing.get("attempts", 0) + 1
                data["pairing"] = pairing
                self.save(data)
                self._audit("pair_failed", None, attempts=pairing["attempts"])
                raise RemoteDenied("Wrong pairing code.")
            devices = [d for d in data.get("devices", []) if not d.get("revoked") and d.get("id") != RELAY_DEVICE]
            if len(devices) >= MAX_DEVICES:
                raise RemoteDenied(f"At most {MAX_DEVICES} phones can be paired. Remove one on the laptop first.")
            device_id, secret = secrets.token_hex(6), secrets.token_urlsafe(32)
            salt = secrets.token_bytes(16)
            data.setdefault("devices", []).append({
                "id": device_id, "name": str(name or "phone")[:40], "secret": _hash(secret), "pin_salt": salt.hex(),
                "pin": pin_hash(pin, salt), "paired_at": self.clock(), "last_seen": None, "revoked": False,
                "bad_pins": 0})
            data.pop("pairing", None)     # single use
            self.save(data)
        self._audit("paired", device_id, name=str(name or "phone")[:40])
        return {"device_id": device_id, "credential": f"{device_id}.{secret}"}

    def set_relay_pin(self, pin: str):
        """The phone app (account relay) acts as one device, "relay": its PIN guards approvals, screen and control
        like a paired phone's. Setting it again replaces the PIN and lifts a lock-out."""
        if not valid_pin(pin):
            raise RemoteDenied("Choose a 4-6 digit PIN.", 400)
        salt = secrets.token_bytes(16)
        with _lock:
            data = self.load()
            devices = [d for d in data.get("devices", []) if d.get("id") != RELAY_DEVICE]
            devices.append({"id": RELAY_DEVICE, "name": "Phone app (account)", "secret": _hash(secrets.token_urlsafe(32)),
                            "pin_salt": salt.hex(), "pin": pin_hash(pin, salt), "paired_at": self.clock(),
                            "last_seen": None, "revoked": False, "bad_pins": 0})
            data["devices"] = devices
            self.save(data)

    def relay_ready(self):
        return any(d.get("id") == RELAY_DEVICE and not d.get("revoked") for d in self.load().get("devices", []))

    def revoke(self, device_id):
        with _lock:
            data = self.load()
            for device in data.get("devices", []):
                if device["id"] == device_id:
                    device["revoked"] = True
            self.save(data)
        self.sessions = {k: v for k, v in self.sessions.items() if v["device"] != device_id}

    # -- credentials, PIN, sessions -------------------------------------------------------------------------------
    def device(self, credential: str) -> dict:
        device_id, _, secret = str(credential or "").partition(".")
        for device in self.load().get("devices", []):
            if device["id"] == device_id and hmac.compare_digest(device["secret"], _hash(secret)):
                if device.get("revoked"):
                    raise RemoteDenied("This phone was removed. Pair it again on the laptop.", 401)
                return device
        raise RemoteDenied("This phone is not paired.", 401)

    def check_pin(self, device_id: str, pin) -> None:
        with _lock:
            data = self.load()
            device = next((d for d in data.get("devices", []) if d["id"] == device_id), None)
            if device is None or device.get("revoked"):
                raise RemoteDenied("This phone is not paired.", 401)
            if valid_pin(pin) and hmac.compare_digest(pin_hash(pin, bytes.fromhex(device["pin_salt"])), device["pin"]):
                device["bad_pins"] = 0
                self.save(data)
                return
            device["bad_pins"] = device.get("bad_pins", 0) + 1
            if device["bad_pins"] >= PIN_TRIES:
                device["revoked"] = True
            self.save(data)
        self._audit("pin_wrong", device_id, tries=device["bad_pins"])
        if device.get("revoked"):
            self.revoke(device_id)
            self._audit("removed_wrong_pins", device_id)
            if self.alert:
                self.alert("Phone removed", f"{PIN_TRIES} wrong PINs: phone '{device.get('name')}' was removed. "
                                            "If this was not you, change the account password on the laptop.")
            raise RemoteDenied("5 wrong PINs: this phone has been removed. Pair it again on the laptop.", 401)
        raise RemoteDenied(f"Wrong PIN ({PIN_TRIES - device['bad_pins']} tries left).")

    def login(self, credential: str, pin) -> dict:
        device = self.device(credential)
        self.check_pin(device["id"], pin)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
        self.sessions[_hash(token)] = {"device": device["id"], "until": self.clock() + SESSION_SECONDS, "csrf": csrf}
        self._seen(device["id"])
        self._audit("login", device["id"])
        return {"token": token, "csrf": csrf, "device_id": device["id"], "name": device["name"]}

    def session(self, token: str) -> dict:
        record = self.sessions.get(_hash(str(token or "")))
        if record is None or self.clock() > record["until"]:
            raise RemoteDenied("Log in again with your PIN.", 401)
        device = next((d for d in self.load().get("devices", []) if d["id"] == record["device"]), None)
        if device is None or device.get("revoked"):
            raise RemoteDenied("This phone was removed.", 401)
        return record

    def logout(self, token: str):
        self.sessions.pop(_hash(str(token or "")), None)

    def _seen(self, device_id):
        with _lock:
            data = self.load()
            for device in data.get("devices", []):
                if device["id"] == device_id:
                    device["last_seen"] = self.clock()
            self.save(data)

    def rate(self, device_id, kind="general"):
        limit, window = RATES[kind]
        now = self.clock()
        key = (device_id, kind)
        recent = [t for t in self.hits.get(key, []) if now - t < window]
        if len(recent) >= limit:
            raise RemoteDenied("Too many requests from this phone; slow down a moment.", 429)
        self.hits[key] = recent + [now]
        self.last_seen[device_id] = now

    def active(self, within=120):
        now = self.clock()
        return any(r["until"] > now for r in self.sessions.values()) and any(
            now - self.last_seen.get(r["device"], 0) < within for r in self.sessions.values())

    # -- approvals ------------------------------------------------------------------------------------------------
    def approval_nonce(self, session_id: str, step_key: str) -> str:
        nonce = secrets.token_urlsafe(16)
        self.nonces[nonce] = {"session": session_id, "step": step_key, "until": self.clock() + NONCE_SECONDS}
        return nonce

    def use_nonce(self, nonce: str, session_id: str, step_key: str):
        record = self.nonces.pop(str(nonce or ""), None)   # single use, even when it does not match
        if record is None or self.clock() > record["until"] or record["session"] != session_id \
                or record["step"] != step_key:
            raise RemoteDenied("This approval is no longer valid; open it again.")
