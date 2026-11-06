"""Account relay (owner, 2026-11-06): one ID/password links an installed assistant and its phone app; both stay signed
in; phone requests reach only their own laptop and go through the laptop's phone rules (PIN, approvals)."""
import base64
import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from chutku.relay import client as relay_client, server as relay_server
from chutku.relay.server import Accounts, RelayError
from chutku.remote import server as remote_server
from chutku.remote.auth import RemoteStore


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.accounts = Accounts(Path(self.temp.name) / "relay.sqlite3", clock=self.clock)
        self.addCleanup(self.accounts.db.close)

    def test_an_id_that_exists_is_refused_and_ids_are_case_insensitive(self):
        self.assertEqual(self.accounts.register("Siddhant", "long-password"), "siddhant")
        with self.assertRaises(RelayError) as caught:
            self.accounts.register("SIDDHANT", "another-password")
        self.assertEqual((caught.exception.status, str(caught.exception)),
                         (409, "This ID already exists. Choose another one."))
        for bad_id, password in (("ab", "long-password"), ("has space", "long-password"), ("ok_id", "short")):
            with self.assertRaises(RelayError):
                self.accounts.register(bad_id, password)

    def test_only_hashes_are_stored_and_tokens_last_until_logout(self):
        self.accounts.register("asha", "secret-pass-1")
        token = self.accounts.login("asha", "secret-pass-1", "phone", "Pixel")
        dump = "\n".join(self.accounts.db.iterdump())
        self.assertNotIn("secret-pass-1", dump)
        self.assertNotIn(token, dump)
        self.clock.now += 365 * 24 * 3600                       # a year later: still signed in
        self.assertEqual(self.accounts.device(token), ("asha", "phone"))
        self.accounts.logout(token)
        with self.assertRaises(RelayError):
            self.accounts.device(token)

    def test_five_wrong_passwords_lock_the_id_for_15_minutes(self):
        self.accounts.register("asha", "secret-pass-1")
        for _ in range(relay_server.FAILS_BEFORE_LOCK):
            with self.assertRaises(RelayError):
                self.accounts.login("asha", "wrong-password", "phone", "x")
        with self.assertRaises(RelayError) as caught:
            self.accounts.login("asha", "secret-pass-1", "phone", "x")   # even the right one, for now
        self.assertEqual(caught.exception.status, 429)
        self.clock.now += relay_server.LOCK_SECONDS + 1
        self.assertTrue(self.accounts.login("asha", "secret-pass-1", "phone", "x"))

    def test_changing_the_password_on_the_laptop_signs_out_every_other_device(self):
        self.accounts.register("asha", "secret-pass-1")
        laptop = self.accounts.login("asha", "secret-pass-1", "laptop", "laptop")
        phone = self.accounts.login("asha", "secret-pass-1", "phone", "Pixel")
        with self.assertRaises(RelayError):
            self.accounts.change(phone, "secret-pass-1", new_password="new-pass-22")   # only from the laptop
        self.assertEqual(self.accounts.change(laptop, "secret-pass-1", new_id="asha2", new_password="new-pass-22"),
                         "asha2")
        self.assertEqual(self.accounts.device(laptop), ("asha2", "laptop"))             # this laptop stays in
        with self.assertRaises(RelayError):
            self.accounts.device(phone)
        self.assertTrue(self.accounts.login("asha2", "new-pass-22", "phone", "Pixel"))


class EndToEndTests(unittest.TestCase):
    """A real relay, the real laptop client and the real phone server behind it, on 127.0.0.1."""

    def setUp(self):
        from chutku.dashboard import DashboardServer
        patcher = patch.object(relay_server, "POLL_SECONDS", 1.0)   # short long-polls keep the test quick
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temp = TemporaryDirectory()
        base = Path(self.temp.name)
        self.relay = relay_server.RelayServer(("127.0.0.1", 0), base / "relay.sqlite3")
        threading.Thread(target=self.relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.relay.server_port}"
        self.core = DashboardServer(base / "laptop", port=0)
        self.store = RemoteStore(base / "laptop")
        self.store.set_relay_pin("4321")
        self.phone_server = remote_server.RemoteServer(self.core, 0, store=self.store, inbox=base / "inbox",
                                                       monitor=(0, 0, 1000, 500))
        threading.Thread(target=self.phone_server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        relay_client.register(self.url, "asha", "secret-pass-1")
        self.laptop = relay_client.RelayClient(self.url, relay_client.login(self.url, "asha", "secret-pass-1"),
                                               lambda: self.phone_server)
        self.laptop.start()
        self.phone = relay_client.call(self.url, "/relay/login", {"id": "asha", "password": "secret-pass-1",
                                                                  "device": "phone", "name": "Pixel"})["token"]
        deadline = time.monotonic() + 5
        while self.laptop.state != "online" and time.monotonic() < deadline:
            time.sleep(0.05)

    def tearDown(self):
        self.laptop.stop()
        for server in (self.phone_server, self.relay):
            server.shutdown()
            server.server_close()
        self.relay.accounts.db.close()
        if self.core.action_lock.acquire(timeout=10):
            self.core.action_lock.release()
        time.sleep(0.2)
        self.core.server_close()
        self.temp.cleanup()

    def phone_call(self, path, data=None, token=None, raw=None, content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", self.relay.server_port, timeout=40)
        headers = {"Authorization": "Bearer " + (token or self.phone)}
        body = raw if raw is not None else (json.dumps(data) if data is not None else None)
        if body is not None:
            headers["Content-Type"] = content_type
        connection.request("POST" if body is not None else "GET", path, body, headers)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        kind = response.getheader("Content-Type", "")
        return response.status, json.loads(payload) if kind.startswith("application/json") else payload

    def test_the_phone_reaches_its_laptop_and_its_rules_still_apply(self):
        started = time.perf_counter()
        status, me = self.phone_call("/t/api/whoami")
        self.assertEqual((status, me["device"], me["assistant"]), (200, "Phone app (account)", "Chutku"))
        print(f"\n[relay] phone -> relay -> laptop -> back in {time.perf_counter() - started:.3f}s")
        status, body = self.phone_call("/t/api/chat", {"message": "time batao"})
        self.assertEqual((status, body["session"]["origin"]), (200, "phone"))
        # The laptop's phone rules still hold: a screen view needs the PIN, a wrong PIN is refused.
        self.assertEqual(self.phone_call("/t/api/screen/start", {"pin": "0000"})[0], 403)
        self.assertEqual(self.phone_call("/t/api/screen/start", {"pin": "4321"})[0], 200)
        said = []
        self.core._speak = said.append
        self.assertEqual(self.phone_call("/t/api/laptop/say", {"text": "Khana ready hai"})[0], 200)

    def test_tokens_and_accounts_are_kept_apart(self):
        self.assertEqual(self.phone_call("/t/api/whoami", token="not-a-token")[0], 401)
        self.assertEqual(self.phone_call("/relay/poll", {}, token=self.phone)[0], 403)   # a phone never collects
        self.assertEqual(self.phone_call("/t/api/whoami", token=self.laptop.token)[0], 403)
        relay_client.register(self.url, "other", "other-pass-1")
        stranger = relay_client.call(self.url, "/relay/login", {"id": "other", "password": "other-pass-1",
                                                                "device": "phone"})["token"]
        status, body = self.phone_call("/t/api/whoami", token=stranger)
        self.assertEqual(status, 503)                       # "other" has no laptop online; never asha's laptop
        self.assertIn("offline", body["error"])
        self.assertEqual(self.phone_call("/relay/register", {"id": "asha", "password": "whatever-1"})[0], 409)

    def test_only_the_relay_client_with_this_runs_secret_gets_in(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.phone_server.server_port, timeout=10)
        connection.request("GET", "/api/whoami", headers={"X-Chutku-Relay": "guess"})
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()

    def test_a_logged_out_laptop_stops_and_public_http_is_refused(self):
        relay_client.call(self.url, "/relay/logout", {}, token=self.laptop.token)
        self.laptop.join(timeout=10)
        self.assertEqual(self.laptop.state, "logged_out")
        for bad in ("http://relay.example.com", "ftp://x", ""):
            with self.assertRaises(relay_client.RelayCallError):
                relay_client.check_url(bad)
        self.assertEqual(relay_client.check_url("http://192.168.1.20:8780"), "http://192.168.1.20:8780")


class SetupAccountTests(unittest.TestCase):
    def test_setup_names_the_assistant_and_makes_the_account(self):
        from chutku import identity, setup_wizard
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)

        class Relay:
            RelayCallError = relay_client.RelayCallError
            check_url = staticmethod(relay_client.check_url)
            tokens = []
            taken = {"asha"}

            def register(self, url, account_id, password):
                if account_id in self.taken:
                    raise relay_client.RelayCallError(409, "This ID already exists. Choose another one.")

            def login(self, url, account_id, password, name):
                return "token-" + account_id

            def store_token(self, token):
                self.tokens.append(token)
        relay = Relay()
        answers = iter(["Jarvis", "c", "male", "english", "", "Asha", "", "n", "",
                        "n", "https://relay.example.com", "asha", "asha.k"])
        secrets_given = iter(["secret-pass-1", "secret-pass-1", "secret-pass-1", "secret-pass-1", "4321", "4321"])
        said = []
        done = setup_wizard.run(base, ask=lambda _q: next(answers), secret=lambda _q: next(secrets_given),
                                out=said.append, mic_check=lambda _b: {}, relay=relay)
        self.assertIn("This ID already exists. Choose another one.", " ".join(map(str, said)))
        self.assertEqual(done["account"], {"id": "asha.k", "relay": "https://relay.example.com"})
        values = identity.load(base / ".env")
        self.assertEqual((values["ASSISTANT_NAME"], values["ASSISTANT_GENDER"], values["ASSISTANT_LANGUAGE"],
                          values["CHUTKU_ACCOUNT_ID"]), ("Jarvis", "male", "english", "asha.k"))
        self.assertNotIn("secret-pass-1", (base / ".env").read_text(encoding="utf-8"))   # no password in a file
        self.assertEqual(relay.tokens, ["token-asha.k"])
        self.assertTrue(RemoteStore(base).relay_ready())


if __name__ == "__main__":
    unittest.main()
