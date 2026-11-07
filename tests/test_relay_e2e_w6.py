"""W6: phone <-> laptop traffic through the account relay is end-to-end encrypted. The relay's queue and database never
hold plaintext, the relay never sees the password, and the browser code (e2e.js) interoperates with the laptop's."""
import base64
import http.client
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from chutku.relay import client, e2e, server

MARKER = "ZEBRA-SECRET-REQUEST-7781"
PASSWORD = "correct horse battery"
FAST = 1000   # PBKDF2 iterations in tests (600 000 in use)


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(e2e, "ITERATIONS", FAST)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key, self.auth = e2e.derive(PASSWORD, "Asha")

    def test_round_trip_and_the_relay_secret_is_not_the_key(self):
        sealed = e2e.seal(self.key, "asha", "req", {"p": "/api/chat", "b": MARKER})
        self.assertNotIn(MARKER, json.dumps(sealed))
        self.assertEqual(e2e.open_envelope(self.key, "ASHA", "req", sealed)["b"], MARKER)   # id is case-insensitive
        self.assertNotEqual(bytes.fromhex(self.auth), self.key)
        self.assertNotIn(PASSWORD, self.auth)

    def test_tampering_wrong_key_wrong_account_or_direction_is_refused(self):
        sealed = e2e.seal(self.key, "asha", "req", {"b": MARKER})
        raw = bytearray(base64.b64decode(sealed["ct"]))
        raw[0] ^= 1
        for bad in ({**sealed, "ct": base64.b64encode(bytes(raw)).decode()},):
            with self.assertRaises(ValueError):
                e2e.open_envelope(self.key, "asha", "req", bad)
        other_key, _ = e2e.derive("another password", "asha")
        for key, account, kind in ((other_key, "asha", "req"), (self.key, "ravi", "req"), (self.key, "asha", "res")):
            with self.assertRaises(ValueError):
                e2e.open_envelope(key, account, kind, sealed)
        with self.assertRaises(ValueError):
            e2e.open_envelope(self.key, "asha", "req", {"v": 0, "iv": "", "ct": ""})

    def test_replays_and_old_requests_are_refused(self):
        now = [1_000_000.0]
        guard = e2e.ReplayGuard(clock=lambda: now[0])
        guard.check(now[0], "nonce-1234")
        with self.assertRaises(ValueError):
            guard.check(now[0], "nonce-1234")                         # the same request again
        with self.assertRaises(ValueError):
            guard.check(now[0] - e2e.WINDOW_SECONDS - 1, "nonce-5678")   # too old
        with self.assertRaises(ValueError):
            guard.check(now[0], "x")                                  # no real nonce


class RelayTests(unittest.TestCase):
    """A real relay server on a loopback port, the real laptop client, and a phone speaking the protocol."""

    def setUp(self):
        patcher = patch.object(e2e, "ITERATIONS", FAST)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "relay.sqlite3"
        self.relay = server.RelayServer(("127.0.0.1", 0), self.db)
        self.queued = []
        real_ask = self.relay.mailbox.ask

        def recording_ask(account, request, timeout=server.REPLY_SECONDS):
            self.queued.append(json.dumps(request))   # exactly what sits in the relay's queue
            return real_ask(account, request, min(timeout, 3))   # a refused request times out in 3 s here
        self.relay.mailbox.ask = recording_ask
        threading.Thread(target=self.relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.relay.accounts.db.close)   # Windows cannot delete an open SQLite file
        self.addCleanup(self.relay.server_close)
        self.addCleanup(self.relay.shutdown)
        self.url = f"http://127.0.0.1:{self.relay.server_port}"
        self.stored = {}
        for name, value in (("store_key", lambda key: self.stored.__setitem__("key", key)),):
            p = patch.object(e2e, name, value)
            p.start()
            self.addCleanup(p.stop)

    def phone_call(self, path, body, token=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.relay.server_port, timeout=10)
        headers = {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}
        connection.request("POST", path, json.dumps(body), headers)
        response = connection.getresponse()
        data = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, data

    def start_laptop(self, laptop_token):
        laptop = client.RelayClient(self.url, laptop_token, lambda: None, key=self.stored["key"], account_id="asha")
        answered = []

        def forward(request):
            answered.append(request)
            body = json.dumps({"echo": base64.b64decode(request["body"]).decode()}).encode()
            return 200, {"Content-Type": "application/json"}, body
        laptop.forward = forward
        laptop.start()
        self.addCleanup(laptop.stop)
        deadline = time.time() + 5
        while not self.relay.mailbox.online("asha") and time.time() < deadline:
            time.sleep(0.05)
        return answered

    def test_a_round_trip_where_the_relay_only_ever_holds_ciphertext(self):
        self.assertEqual(client.register(self.url, "asha", PASSWORD), "asha")
        laptop_token = client.login(self.url, "asha", PASSWORD)
        answered = self.start_laptop(laptop_token)
        key, auth = e2e.derive(PASSWORD, "asha")
        status, phone = self.phone_call("/relay/login", {"id": "asha", "password": auth, "device": "phone", "name": "p"})
        self.assertEqual(status, 200)
        inner = {"m": "POST", "p": "/api/chat", "t": "application/json",
                 "b": base64.b64encode(json.dumps({"message": MARKER}).encode()).decode(), "ts": time.time(),
                 "n": "nonce-abcdef12"}
        status, answer = self.phone_call("/t/e2e", e2e.seal(key, "asha", "req", inner), token=phone["token"])
        self.assertEqual(status, 200)
        opened = e2e.open_envelope(key, "asha", "res", answer)
        self.assertEqual(opened["n"], "nonce-abcdef12")
        self.assertIn(MARKER, base64.b64decode(opened["b"]).decode())
        self.assertEqual(answered[0]["path"], "/api/chat")
        self.assertFalse(any(MARKER in item or "/api/chat" in item for item in self.queued), self.queued)
        self.assertNotIn(MARKER, json.dumps(answer))
        database = self.db.read_bytes()
        for secret in (MARKER.encode(), PASSWORD.encode(), self.stored["key"]):
            self.assertNotIn(secret, database)
        # a replay of the same envelope gets no answer from the laptop
        status, _ = self.phone_call("/t/e2e", e2e.seal(key, "asha", "req", inner), token=phone["token"])
        self.assertEqual(status, 504)
        self.assertEqual(len(answered), 1)

    def test_plaintext_requests_are_refused(self):
        client.register(self.url, "asha", PASSWORD)
        _, auth = e2e.derive(PASSWORD, "asha")
        _, phone = self.phone_call("/relay/login", {"id": "asha", "password": auth, "device": "phone", "name": "p"})
        self.assertEqual(self.phone_call("/t/api/chat", {"message": MARKER}, token=phone["token"])[0], 426)
        self.assertEqual(self.phone_call("/t/e2e", {"message": MARKER}, token=phone["token"])[0], 400)
        self.assertFalse(any(MARKER in item for item in self.queued))

    def test_an_old_account_is_upgraded_and_its_password_no_longer_works_at_the_relay(self):
        self.relay.accounts.register("asha", PASSWORD)          # made before E2E: the relay knows the password
        client.login(self.url, "asha", PASSWORD)                # upgrade: the auth secret replaces it
        _, auth = e2e.derive(PASSWORD, "asha")
        self.assertEqual(self.phone_call("/relay/login", {"id": "asha", "password": auth, "device": "phone",
                                                          "name": "p"})[0], 200)
        self.assertNotEqual(self.phone_call("/relay/login", {"id": "asha", "password": PASSWORD, "device": "phone",
                                                             "name": "p"})[0], 200)


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the phone's e2e.js")
class BrowserInteropTests(unittest.TestCase):
    """chutku/web/phone/e2e.js (run in Node's WebCrypto) and chutku/relay/e2e.py agree byte for byte."""

    def test_node_and_python_derive_and_seal_compatibly(self):
        script = Path(__file__).resolve().parents[1] / "chutku" / "web" / "phone" / "e2e.js"
        node = f"""
            const E = require({json.dumps(str(script))});
            (async () => {{
              const d = await E.derive({json.dumps(PASSWORD)}, "Asha", {FAST});
              const key = await E.importKey(d.raw);
              const sealed = await E.seal(key, "asha", "req", {{p: "/api/chat", b: {json.dumps(MARKER)}}});
              const answer = JSON.parse(require("fs").readFileSync(0, "utf8") || "null");
              let opened = null;
              if (answer) opened = await E.open(key, "asha", "res", answer);
              console.log(JSON.stringify({{raw: d.raw, auth: d.auth, sealed, opened}}));
            }})().catch(e => {{ console.error(e); process.exit(1); }});"""
        key, auth = e2e.derive(PASSWORD, "Asha", FAST)
        response = e2e.seal(key, "asha", "res", {"s": 200, "n": "n-123456789"})
        done = subprocess.run(["node", "-e", node], input=json.dumps(response), capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(base64.b64decode(out["raw"]), key)
        self.assertEqual(out["auth"], auth)
        self.assertEqual(e2e.open_envelope(key, "asha", "req", out["sealed"])["b"], MARKER)
        self.assertEqual(out["opened"], {"s": 200, "n": "n-123456789"})


if __name__ == "__main__":
    unittest.main()
