"""Phone pairing, credentials, PIN, sessions and approval nonces (W6 / HERMES_PLAN P1).

Stored in data/remote.json (same-user readable, like every Chutku file): only SHA-256 hashes of device credentials
and session tokens, and scrypt hashes of the PIN. Nothing secret is ever logged.

Rules (fail closed):
- a pairing code lasts 10 minutes, is single use, and 5 wrong tries lock pairing until a new code is made;
- at most 3 devices; a device is revoked by "phone hatao", the dashboard, or 5 wrong PINs;
- a session (after credential + PIN) lasts 12 hours; the credential alone never approves anything;
- every approval, screen view and control session needs the PIN again (step-up), and an approval is bound to
  session + step + a single-use nonce;
- 30 requests per minute per device.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAIR_SECONDS = 600
PAIR_ATTEMPTS = 5
MAX_DEVICES = 3
SESSION_SECONDS = 12 * 3600
PIN_TRIES = 5
RATE_PER_MINUTE = 30
NONCE_SECONDS = 300
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
    def __init__(self, base=PROJECT_ROOT, clock=time.time):
        self.path = Path(base) / "data" / "remote.json"
        self.clock = clock
        self.sessions = {}     # token hash -> {device, until, csrf}     (memory only: a restart logs the phone out)
        self.nonces = {}       # nonce -> {session, step, until}
        self.hits = {}         # device -> [timestamps]

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
                "control_allowed": bool(data.get("control_allowed")),
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
                raise RemoteDenied("Wrong pairing code.")
            devices = [d for d in data.get("devices", []) if not d.get("revoked")]
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
        return {"device_id": device_id, "credential": f"{device_id}.{secret}"}

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
        if device.get("revoked"):
            self.revoke(device_id)
            raise RemoteDenied("5 wrong PINs: this phone has been removed. Pair it again on the laptop.", 401)
        raise RemoteDenied(f"Wrong PIN ({PIN_TRIES - device['bad_pins']} tries left).")

    def login(self, credential: str, pin) -> dict:
        device = self.device(credential)
        self.check_pin(device["id"], pin)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
        self.sessions[_hash(token)] = {"device": device["id"], "until": self.clock() + SESSION_SECONDS, "csrf": csrf}
        self._seen(device["id"])
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

    def rate(self, device_id):
        now = self.clock()
        recent = [t for t in self.hits.get(device_id, []) if now - t < 60]
        if len(recent) >= RATE_PER_MINUTE:
            raise RemoteDenied("Too many requests from this phone; wait a minute.", 429)
        self.hits[device_id] = recent + [now]

    def active(self, within=120):
        now = self.clock()
        return any(r["until"] > now for r in self.sessions.values()) and any(
            now - max(self.hits.get(r["device"], [0])) < within for r in self.sessions.values())

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
