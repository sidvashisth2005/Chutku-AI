"""The laptop's side of the account relay (chutku/relay/server.py).

- `register` / `login` / `change` / `logout`: the account calls `chutku.cli setup` and `chutku.cli account` make.
- `RelayClient`: keeps a long poll open while Chutku runs. Each phone request it receives is replayed on the laptop's own
  phone server (127.0.0.1, with that server's per-run secret), so every phone rule there (PIN, approvals, control
  limits, laptop-only steps) applies unchanged; the answer goes back to the relay.

The device token is kept in Windows Credential Manager ("Chutku/RelayToken"), never in a file. It works until this
laptop logs out or the password is changed from another device.
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import logging
import threading
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

CREDENTIAL = "Chutku/RelayToken"
FORWARD_HEADERS = ("Content-Type", "X-Frame-Hash", "X-Monitor", "Content-Disposition")
_log = logging.getLogger("chutku.relay")


class RelayCallError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def check_url(url):
    """HTTPS, or plain HTTP only to this PC or the home network (a relay on the laptop for testing)."""
    parts = urlsplit(str(url or ""))
    if parts.scheme == "https" and parts.hostname:
        return url.rstrip("/")
    if parts.scheme == "http" and parts.hostname:
        try:
            address = ipaddress.ip_address(parts.hostname)
            if address.is_private or address.is_loopback:
                return url.rstrip("/")
        except ValueError:
            if parts.hostname == "localhost":
                return url.rstrip("/")
    raise RelayCallError(400, "Use an https:// relay address (plain http only for this PC or your home network).")


def call(url, path, data=None, token=None, timeout=35):
    request = urllib.request.Request(check_url(url) + path, method="POST" if data is not None else "GET",
                                     data=json.dumps(data).encode("utf-8") if data is not None else None)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read() or b"{}").get("error") or error.reason
        except ValueError:
            message = error.reason
        raise RelayCallError(error.code, str(message)) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise RelayCallError(0, f"The relay could not be reached ({error}).") from None


def register(url, account_id, password):
    return call(url, "/relay/register", {"id": account_id, "password": password})["id"]


def login(url, account_id, password, name="laptop"):
    return call(url, "/relay/login", {"id": account_id, "password": password, "device": "laptop", "name": name})["token"]


def change(url, token, password, new_id=None, new_password=None):
    return call(url, "/relay/change", {"password": password, "new_id": new_id, "new_password": new_password},
                token=token)["id"]


def me(url, token):
    return call(url, "/relay/me", token=token)


def logout(url, token):
    try:
        call(url, "/relay/logout", {}, token=token)
    finally:
        store_token("")


def stored_token():
    from chutku.cloud_planner import stored_key
    return stored_key(CREDENTIAL) or ""


def store_token(token):
    from chutku.cloud_planner import delete_key, store_key
    if token:
        store_key(token, CREDENTIAL)
    else:
        delete_key(CREDENTIAL)


class RelayClient(threading.Thread):
    """Long-polls the relay and answers each phone request through the local phone server."""

    def __init__(self, url, token, phone_server, *, call=call):
        super().__init__(name="chutku-relay", daemon=True)
        self.url, self.token, self.phone_server, self.call = check_url(url), token, phone_server, call
        self.stopping = threading.Event()
        self.state = "starting"            # starting | online | offline | logged_out
        self.served = 0

    def stop(self):
        self.stopping.set()

    def run(self):
        wait = 2.0
        while not self.stopping.is_set():
            try:
                requests = self.call(self.url, "/relay/poll", {}, token=self.token, timeout=40)["requests"]
                self.state, wait = "online", 2.0
            except RelayCallError as error:
                if error.status == 401:      # logged out elsewhere, or the password changed
                    self.state = "logged_out"
                    _log.warning("relay: this laptop was logged out; run chutku.cli account login")
                    try:
                        from chutku.health import notify
                        notify("Phone app disconnected", "This laptop was logged out of your account. Run: "
                                                         "chutku.cli account login")
                    except Exception:
                        pass   # the log line above still says it
                    return
                self.state = "offline"
                self.stopping.wait(wait)
                wait = min(wait * 2, 60.0)
                continue
            for request in requests:
                threading.Thread(target=self.serve, args=(request,), name="chutku-relay-request", daemon=True).start()

    def serve(self, request):
        try:
            status, headers, body = self.forward(request)
        except Exception as error:   # the phone gets an answer either way
            status, headers, body = 502, {"Content-Type": "application/json"}, json.dumps(
                {"error": f"The laptop could not answer ({type(error).__name__})."}).encode("utf-8")
        try:
            self.call(self.url, "/relay/reply", {"rid": request.get("rid"), "status": status, "headers": headers,
                                                 "body": base64.b64encode(body).decode("ascii")}, token=self.token)
            self.served += 1
        except RelayCallError:
            pass   # the relay is gone; the phone sees a timeout

    def forward(self, request):
        server = self.phone_server()
        if server is None:
            raise OSError("the phone server is not running")
        method, path = str(request.get("method")), str(request.get("path") or "")
        if method not in ("GET", "POST") or not path.startswith("/api/"):
            return 400, {"Content-Type": "application/json"}, b'{"error": "Not allowed."}'
        body = base64.b64decode(request.get("body") or "")
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=60)
        try:
            headers = {"X-Chutku-Relay": server.relay_secret, "Content-Length": str(len(body))}
            if request.get("content_type"):
                headers["Content-Type"] = str(request["content_type"])[:100]
            connection.request(method, path, body if body else None, headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, {k: response.getheader(k) for k in FORWARD_HEADERS if response.getheader(k)}, data
        finally:
            connection.close()


def account_command(base, action, *, ask=input, secret=None):
    """`chutku.cli account status|login|logout|change|pin` (owner: "change the ID or password on the laptop")."""
    import getpass
    from pathlib import Path
    from chutku import identity
    from chutku.remote.auth import RemoteStore
    secret = secret or getpass.getpass
    env = Path(base) / ".env"
    settings = identity.load(env)
    url, account_id, token = settings["CHUTKU_RELAY_URL"], settings["CHUTKU_ACCOUNT_ID"], stored_token()
    if action == "pin":
        pin = secret("New 4-6 digit phone PIN: ")
        if secret("Again: ") != pin:
            raise ValueError("The PINs differ.")
        RemoteStore(base).set_relay_pin(pin)
        return "Phone PIN changed."
    if not url:
        raise ValueError("No relay address yet: run `chutku.cli setup` (question 6).")
    if action == "status":
        if not token:
            return f"Not signed in (relay {url}). Run `chutku.cli account login`."
        info = me(url, token)
        return f"Signed in as {info['id']} at {url}; phone PIN {'set' if RemoteStore(base).relay_ready() else 'NOT set'}."
    if action == "login":
        account_id = ask(f"ID [Enter = {account_id or 'none'}]: ").strip().casefold() or account_id
        store_token(login(url, account_id, secret("Password: ")))
        identity.save({"CHUTKU_ACCOUNT_ID": account_id}, env)
        return f"Signed in as {account_id}. Restart Chutku to connect the phone app."
    if not token:
        raise ValueError("Not signed in: run `chutku.cli account login` first.")
    if action == "logout":
        logout(url, token)
        return "Logged out on this laptop. The phone app can no longer reach it until you log in again."
    password = secret("Current password: ")
    new_id = ask(f"New ID [Enter = keep {account_id}]: ").strip().casefold() or None
    new_password = secret("New password [Enter = keep]: ") or None
    if new_password and secret("New password again: ") != new_password:
        raise ValueError("The new passwords differ.")
    changed = change(url, token, password, new_id, new_password)
    identity.save({"CHUTKU_ACCOUNT_ID": changed}, env)
    return f"Changed. ID: {changed}." + (" Other devices (the phone app) must log in again with the new password."
                                          if new_password else "")


def start(core):
    """Start the client when this install has an account (CHUTKU_RELAY_URL, a token, a phone PIN); else None."""
    from chutku import identity
    settings = identity.load()
    url, token = settings["CHUTKU_RELAY_URL"], stored_token()
    remote = getattr(core, "remote", None)
    if not url or not token or remote is None or not remote.store.relay_ready():
        return None
    remote.start(for_relay=True)
    client = RelayClient(url, token, lambda: remote.server)
    client.start()
    return client
