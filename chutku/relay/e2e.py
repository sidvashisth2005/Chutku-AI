"""W6: end-to-end encryption between the phone app and the laptop, through the account relay.

The relay forwards only ciphertext: it never sees a request's path, body or answer, and never holds the key.

Keys (both derived from the account password; the phone does the same in chutku/web/phone/e2e.js with WebCrypto):
  key   = PBKDF2-HMAC-SHA256(password, "chutku-e2e-key:"  + id, 600 000 iterations, 32 bytes)  -> AES-256-GCM
  auth  = PBKDF2-HMAC-SHA256(password, "chutku-e2e-auth:" + id, 600 000 iterations, 32 bytes)  -> hex
The relay is given `auth` as the account's password (it stores only its scrypt hash), so it can neither log the real
password nor derive the key. PBKDF2 instead of scrypt: WebCrypto has PBKDF2 but no scrypt, and an unvetted scrypt in
JavaScript would be worse than a vetted PBKDF2 at OWASP's iteration count.

Envelope: {"v": 1, "iv": base64(12 random bytes), "ct": base64(AES-GCM ciphertext + tag)}, with the account id and
the direction ("req"/"res") as associated data. A request carries a timestamp and a nonce; the laptop refuses one
older than 2 minutes or seen before (replay), and the answer repeats the nonce so the phone can tell the relay did
not swap answers between requests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time

ITERATIONS = 600_000
WINDOW_SECONDS = 120
CREDENTIAL = "Chutku/RelayKey"


def derive(password, account_id, iterations=None):
    """(32-byte AES key, auth secret as hex) from the account password and ID."""
    iterations = iterations or ITERATIONS
    secret, ident = str(password).encode("utf-8"), str(account_id).strip().casefold().encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", secret, b"chutku-e2e-key:" + ident, iterations, 32)
    auth = hashlib.pbkdf2_hmac("sha256", secret, b"chutku-e2e-auth:" + ident, iterations, 32).hex()
    return key, auth


def _aad(account_id, kind):
    return f"chutku-e2e-v1:{str(account_id).strip().casefold()}:{kind}".encode("utf-8")


def seal(key, account_id, kind, obj):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sealed = AESGCM(key).encrypt(iv, data, _aad(account_id, kind))
    return {"v": 1, "iv": base64.b64encode(iv).decode("ascii"), "ct": base64.b64encode(sealed).decode("ascii")}


def open_envelope(key, account_id, kind, envelope):
    """The decrypted object; ValueError for a wrong version, key, account, direction or a changed byte."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not isinstance(envelope, dict) or envelope.get("v") != 1:
        raise ValueError("Not an encrypted Chutku message (update the phone app).")
    try:
        iv, sealed = base64.b64decode(envelope["iv"]), base64.b64decode(envelope["ct"])
        return json.loads(AESGCM(key).decrypt(iv, sealed, _aad(account_id, kind)))
    except (InvalidTag, KeyError, TypeError, ValueError) as error:
        raise ValueError("The message could not be decrypted (wrong key or changed on the way).") from error


class ReplayGuard:
    """Refuse a request older than WINDOW_SECONDS, from too far in the future, or whose nonce was already used."""

    def __init__(self, clock=time.time):
        self.clock, self.lock, self.seen = clock, threading.Lock(), {}

    def check(self, timestamp, nonce):
        now = self.clock()
        if not isinstance(timestamp, (int, float)) or abs(now - timestamp) > WINDOW_SECONDS:
            raise ValueError("The request is too old (or the phone's clock is wrong).")
        if not isinstance(nonce, str) or not 8 <= len(nonce) <= 64:
            raise ValueError("The request has no valid nonce.")
        with self.lock:
            self.seen = {n: at for n, at in self.seen.items() if now - at <= 2 * WINDOW_SECONDS}
            if nonce in self.seen:
                raise ValueError("This request was already used (replay).")
            self.seen[nonce] = now


def store_key(key):
    from chutku.cloud_planner import delete_key, store_key as store
    if key:
        store(base64.b64encode(key).decode("ascii"), CREDENTIAL)
    else:
        delete_key(CREDENTIAL)


def stored_key():
    from chutku.cloud_planner import stored_key as stored
    value = stored(CREDENTIAL)
    return base64.b64decode(value) if value else None
