"""Software Security & Testing Checklist (2026-11-13): a test for every gap the checklist found in this repo, each with
the negative case that must fail closed, plus fuzz tests. The item-by-item record is docs/SECURITY_CHECKLIST.md."""
import http.client
import io
import json
import logging
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from hypothesis import given, settings, strategies as st

from chutku.relay import client as relay_client, e2e, server as relay_server
from chutku.remote.auth import RemoteDenied, RemoteStore


class PasswordStrengthTests(unittest.TestCase):
    """3. Weak passwords: the relay sees only a derived value, so the laptop checks the real password."""

    def test_weak_passwords_are_refused_and_strong_ones_pass(self):
        for weak, account in (("short", "asha"), ("12345678", "asha"), ("Password123", "asha"), ("aaaaaaaa", "asha"),
                              ("abababab", "asha"), ("asha-2026!", "asha"), ("x9" * 101, "asha"), (None, "asha")):
            self.assertIsNotNone(relay_client.password_problem(weak, account), weak)
        for strong in ("correct horse battery", "secret-pass-1", "Mera-ghar-42"):
            self.assertIsNone(relay_client.password_problem(strong, "asha"), strong)

    def test_a_weak_password_never_reaches_the_relay(self):
        with patch.object(relay_client, "call", side_effect=AssertionError("network used")) as call:
            with self.assertRaises(relay_client.RelayCallError) as caught:
                relay_client.register("https://relay.example.com", "asha", "password123")
            self.assertEqual(caught.exception.status, 400)
            with self.assertRaises(relay_client.RelayCallError):
                relay_client.change("https://relay.example.com", "t", "secret-pass-1", new_password="12345678",
                                    account_id="asha")
            call.assert_not_called()

    def test_renaming_with_the_old_password_is_not_blocked(self):
        with patch.object(e2e, "ITERATIONS", 1000), patch.object(e2e, "store_key", lambda key: None), \
                patch.object(relay_client, "call", return_value={"id": "asha2"}) as call:
            self.assertEqual(relay_client.change("https://r.example.com", "t", "Mera-ghar-42", new_id="asha2",
                                                 account_id="asha"), "asha2")
        call.assert_called_once()


class RelayHardeningTests(unittest.TestCase):
    """A real relay on 127.0.0.1: headers, enumeration, credential stuffing, audit, errors, connection cap, TLS."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.relay = relay_server.RelayServer(("127.0.0.1", 0), Path(self.temp.name) / "relay.sqlite3")
        threading.Thread(target=self.relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.relay.accounts.db.close)
        self.addCleanup(self.relay.server_close)
        self.addCleanup(self.relay.shutdown)
        self.relay.accounts.register("asha", "secret-pass-1")

    def call(self, method, path, body=None, token=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.relay.server_port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response.status, payload, response

    def test_security_headers_and_no_cors(self):
        status, _, response = self.call("GET", "/relay/info")
        self.assertEqual(status, 200)
        self.assertEqual(response.getheader("Strict-Transport-Security"), "max-age=31536000")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
        self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
        self.assertNotIn("Python", response.getheader("Server"))

    def test_an_unknown_id_costs_the_same_scrypt_as_a_known_one(self):
        real, calls = relay_server._hash_password, []
        with patch.object(relay_server, "_hash_password", lambda *a: calls.append(1) or real(*a)):
            for account in ("asha", "nobody"):
                with self.assertRaises(relay_server.RelayError) as caught:
                    self.relay.accounts.login(account, "wrong-password", "phone", "p")
                self.assertEqual((caught.exception.status, str(caught.exception)), (401, "Wrong ID or password."))
        self.assertEqual(len(calls), 2)

    def test_many_wrong_sign_ins_from_one_address_are_stopped_across_ids(self):
        with patch.object(relay_server, "LOGIN_FAILS_PER_HOUR", 3):
            for number in range(3):
                status, _, _ = self.call("POST", "/relay/login", {"id": f"user{number:03d}", "password": "guess-1234",
                                                                  "device": "phone"})
                self.assertEqual(status, 401)
            status, body, _ = self.call("POST", "/relay/login", {"id": "asha", "password": "secret-pass-1",
                                                                 "device": "phone"})
        self.assertEqual(status, 429, body)    # even the right password, from this address, for now
        events = self.relay.accounts.db.execute("SELECT account, event, ip FROM events").fetchall()
        self.assertEqual([e[1] for e in events], ["login_failed"] * 3)
        dump = "\n".join(self.relay.accounts.db.iterdump())
        self.assertNotIn("guess-1234", dump)

    def test_sign_ins_and_logouts_are_audited_without_secrets(self):
        status, body, _ = self.call("POST", "/relay/login", {"id": "asha", "password": "secret-pass-1",
                                                             "device": "laptop"})
        self.assertEqual(status, 200)
        token = json.loads(body)["token"]
        self.assertEqual(self.call("POST", "/relay/logout", {}, token=token)[0], 200)
        events = [e[0] for e in self.relay.accounts.db.execute("SELECT event FROM events ORDER BY at, rowid")]
        self.assertEqual(events, ["login_laptop", "logout_laptop"])
        dump = "\n".join(self.relay.accounts.db.iterdump())
        self.assertNotIn(token, dump)
        self.assertNotIn("secret-pass-1", dump)

    def test_odd_bodies_and_internal_errors_get_an_answer_without_details(self):
        token = self.relay.accounts.login("asha", "secret-pass-1", "laptop", "l")
        status, body, _ = self.call("POST", "/relay/reply", raw=b"[1, 2]", token=token)
        self.assertEqual(status, 400, body)
        with patch.object(self.relay.accounts, "device", side_effect=RuntimeError("db path C:\\secret")):
            status, body, _ = self.call("GET", "/relay/me", token=token)
        self.assertEqual(status, 500)
        self.assertNotIn(b"secret", body)
        self.assertNotIn(b"Traceback", body)

    def test_connections_beyond_the_cap_are_closed_at_once(self):
        self.relay.slots = threading.BoundedSemaphore(1)
        holder = socket.create_connection(("127.0.0.1", self.relay.server_port), timeout=5)   # holds the only slot
        time.sleep(0.2)
        extra = socket.create_connection(("127.0.0.1", self.relay.server_port), timeout=5)
        try:
            extra.sendall(b"GET /relay/info HTTP/1.1\r\nHost: x\r\n\r\n")
            self.assertEqual(extra.recv(100), b"")          # closed without an answer
        except ConnectionError:
            pass                                             # Windows may reset or abort instead: also refused
        extra.close()
        holder.close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:                   # the slot comes back once the first connection ends
            try:
                if self.call("GET", "/relay/info")[0] == 200:
                    break
            except (ConnectionError, http.client.HTTPException):
                time.sleep(0.1)
        else:
            self.fail("the slot never came back")

    def test_tls_is_1_2_or_newer(self):
        import ssl
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(days=1))
                .sign(key, hashes.SHA256()))
        cert_file, key_file = Path(self.temp.name) / "c.pem", Path(self.temp.name) / "k.pem"
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        context = relay_server.tls_context(str(cert_file), str(key_file))
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)


class PhoneAuditTests(unittest.TestCase):
    """15. Pairing, sign-ins, wrong PINs and removals are logged (never a PIN or credential); a removal alerts."""

    def test_phone_security_events_are_logged_and_a_removal_alerts_the_owner(self):
        from chutku.core.action_log import ActionLog
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        alerts = []
        store = RemoteStore(temp.name, alert=lambda title, text: alerts.append(title))
        code = store.new_pairing_code()
        with self.assertRaises(RemoteDenied):
            store.pair("WRONGCOD", "Pixel", "4321")
        paired = store.pair(code, "Pixel", "4321")
        store.login(paired["credential"], "4321")
        for _ in range(5):
            with self.assertRaises(RemoteDenied):
                store.check_pin(paired["device_id"], "9999")
        log = ActionLog(Path(temp.name) / "data" / "actions.log.jsonl")
        entries = list(reversed(log.recent(50)))
        self.assertEqual([e["tool"] for e in entries],
                         ["remote.pair_failed", "remote.paired", "remote.login"] + ["remote.pin_wrong"] * 5 +
                         ["remote.removed_wrong_pins"])
        self.assertTrue(log.verify()["ok"])
        allowed = {"tool", "state", "origin", "device", "attempts", "name", "tries", "seq", "time", "prev", "hash"}
        self.assertTrue(all(set(e) <= allowed for e in entries))
        self.assertNotIn(paired["credential"].split(".")[1], log.path.read_text(encoding="utf-8"))
        self.assertEqual(alerts, ["Phone removed"])


class LogInjectionTests(unittest.TestCase):
    def test_a_newline_cannot_forge_a_log_line(self):
        from chutku.core.log import _Redact
        record = logging.LogRecord("chutku", logging.INFO, __file__, 1, "goal %s", ("hi\r\n2026 ERROR forged",), None)
        _Redact().filter(record)
        self.assertNotIn("\n", record.msg)
        self.assertNotIn("\r", record.msg)
        self.assertIn("\\n2026 ERROR forged", record.msg)


class ZipBombTests(unittest.TestCase):
    """6. A document or backup that unpacks to far more than any real one is refused before it reaches memory."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def docx(self, text):
        path = Path(self.temp.name) / "doc.docx"
        body = f'<w:document xmlns:w="w"><w:body><w:p><w:t>{text}</w:t></w:p></w:body></w:document>'
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", body)
        return path

    def test_an_office_part_that_unpacks_too_large_is_refused(self):
        from chutku.tools import documents
        self.assertEqual(documents.extract(self.docx("hello world"))[0].strip(), "hello world")
        with patch.object(documents, "MAX_FILE_BYTES", 10_000):
            with self.assertRaises(ValueError) as caught:
                documents.extract(self.docx("0" * 50_000))
        self.assertIn("zip bomb", str(caught.exception))

    def test_a_backup_with_an_oversized_file_is_refused(self):
        from chutku import backup
        path = Path(self.temp.name) / "chutku-bomb.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({"files": {}}))
            archive.writestr("data/big.bin", b"0" * 50_000)
        with patch.object(backup, "MAX_FILE", 10_000):
            with self.assertRaises(ValueError):
                backup.verify(path)
        self.assertEqual(backup.verify(path), {})   # at the real limit the same archive is fine (its manifest is empty)


class UploadTypeTests(unittest.TestCase):
    def test_windows_double_click_types_are_blocked(self):
        from chutku.remote.phone_files import BLOCKED_SUFFIXES
        for suffix in (".reg", ".msc", ".wsf", ".cpl", ".chm", ".iso", ".lnk", ".url", ".appinstaller"):
            self.assertIn(suffix, BLOCKED_SUFFIXES)


class ReDoSTests(unittest.TestCase):
    """12. ReDoS: the instant router stays fast on crafted input up to the 2000-character goal cap (AgentSession)."""

    def test_the_tab_patterns_are_linear(self):
        from chutku.quick_intents import _NEW_TAB, _SAME_TAB
        crafted = ", " * 20_000                      # was quadratic: every start position re-scanned the whole run
        for pattern in (_NEW_TAB, _SAME_TAB):
            start = time.perf_counter()
            self.assertIsNone(pattern.search(crafted))
            self.assertLess(time.perf_counter() - start, 0.5)
        self.assertEqual(" ".join(_NEW_TAB.sub(" ", "youtube kholo, new tab mein").split()), "youtube kholo")

    def test_crafted_goals_at_the_cap_finish_quickly(self):
        from chutku.quick_intents import quick_proposal
        quick_proposal("hello", apps=[])
        for front, unit, back in (("open ", ", ", " ko bolo"), ("", " ", " playlist chalao"), ("search ", ",", "!"),
                                  ("play ", "a ", " playlist"), ("har 15 min ", "1 ", ""), ("", ", ", "")):
            case = front + (unit * 2000)[:2000 - len(front) - len(back)] + back
            start = time.perf_counter()
            quick_proposal(case, apps=[])
            self.assertLess(time.perf_counter() - start, 4.0, (front, unit, back))   # measured worst 1.7 s


class SecretScanTests(unittest.TestCase):
    """Part 2, secret scanning: scripts/security_scan.py finds a real-shaped key and ignores a bare marker."""

    def test_keys_are_found_and_markers_are_not(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import security_scan
        key = b"key = 'AI" + b"za" + b"B" * 35 + b"'"   # built here, so this file holds no key-shaped string
        self.assertEqual([line for line, _ in security_scan.find_secrets(b"one\n" + key)], [2])
        body = b"-----BEGIN RSA " + b"PRIVATE KEY-----\n" + b"Q" * 64
        self.assertEqual(len(security_scan.find_secrets(body)), 1)
        self.assertEqual(security_scan.find_secrets(b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----\""), [])


class FuzzTests(unittest.TestCase):
    """Part 2, fuzz testing: random input must give a clean refusal, never a crash or a hang."""

    @settings(max_examples=200, deadline=None)
    @given(st.one_of(st.none(), st.text(max_size=300), st.integers(), st.binary(max_size=50)), st.text(max_size=40))
    def test_password_check_never_crashes(self, password, account):
        result = relay_client.password_problem(password, account)
        self.assertTrue(result is None or isinstance(result, str))

    @settings(max_examples=200, deadline=None)
    @given(st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=40),
                        lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner,
                                                                                     max_size=3), max_leaves=8))
    def test_a_random_envelope_is_only_ever_refused(self, envelope):
        if isinstance(envelope, dict) and envelope:
            envelope = dict(envelope, v=1)
        with self.assertRaises(ValueError):
            e2e.open_envelope(b"k" * 32, "asha", "req", envelope)


class RelayFuzzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.relay = relay_server.RelayServer(("127.0.0.1", 0), Path(cls.temp.name) / "relay.sqlite3")
        threading.Thread(target=cls.relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.relay.shutdown()
        cls.relay.server_close()
        cls.relay.accounts.db.close()
        cls.temp.cleanup()

    @settings(max_examples=60, deadline=None)
    @given(st.sampled_from(["/relay/login", "/relay/register", "/relay/poll", "/relay/reply", "/t/e2e",
                            "/relay/change", "/t/api/x", "/../etc/passwd", "/relay/me"]),
           st.one_of(st.binary(max_size=200),
                     st.dictionaries(st.sampled_from(["id", "password", "device", "name", "v", "iv", "ct", "rid"]),
                                     st.one_of(st.none(), st.integers(), st.text(max_size=30),
                                               st.lists(st.integers(), max_size=2)), max_size=5)
                     .map(lambda d: json.dumps(d).encode())))
    def test_random_requests_always_get_a_clean_answer(self, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", self.relay.server_port, timeout=10)
        connection.request("POST", path, body=body, headers={"Content-Type": "application/json",
                                                             "Authorization": "Bearer not-a-token"})
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        self.assertIn(response.status, {200, 201, 400, 401, 403, 404, 409, 413, 426, 429}, payload)
        self.assertIn("error", json.loads(payload) if response.status >= 400 else {"error": ""})


if __name__ == "__main__":
    unittest.main()
