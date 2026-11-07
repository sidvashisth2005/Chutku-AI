"""W6 (2026-10-29, HERMES_PLAN P1-P9): phone access through the owner's tailnet. The gates fail closed: wrong host,
wrong Tailscale login, no pairing, a revoked phone, a missing CSRF header, a missing PIN or a replayed approval are
all refused; control needs arming at the laptop; Funnel stops everything; nothing secret is logged."""
import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from chutku.remote import auth, control, server as remote_server, tailscale
from chutku.remote.auth import RemoteDenied, RemoteStore

HOST, LOGIN = "laptop.tail1234.ts.net", "owner@example.com"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.clock = Clock()
        self.store = RemoteStore(Path(self.temp.name), clock=self.clock)
        self.addCleanup(self.temp.cleanup)

    def test_pairing_code_is_single_use_and_expires(self):
        code = self.store.new_pairing_code()
        paired = self.store.pair(code, "Pixel", "4321")
        self.assertTrue(paired["credential"].startswith(paired["device_id"] + "."))
        with self.assertRaises(RemoteDenied):
            self.store.pair(code, "Second", "1111")                # used
        code = self.store.new_pairing_code()
        self.clock.now += auth.PAIR_SECONDS + 1
        with self.assertRaises(RemoteDenied):
            self.store.pair(code, "Late", "1111")                  # expired

    def test_five_wrong_codes_lock_pairing(self):
        code = self.store.new_pairing_code()
        for _ in range(auth.PAIR_ATTEMPTS):
            with self.assertRaises(RemoteDenied):
                self.store.pair("WRONG000", "x", "1234")
        with self.assertRaises(RemoteDenied):
            self.store.pair(code, "x", "1234")                     # even the right code is now refused

    def test_only_hashes_are_stored(self):
        paired = self.store.pair(self.store.new_pairing_code(), "Pixel", "4321")
        text = self.store.path.read_text(encoding="utf-8")
        self.assertNotIn(paired["credential"].split(".")[1], text)
        self.assertNotIn("4321", text)

    def test_five_wrong_pins_remove_the_phone(self):
        paired = self.store.pair(self.store.new_pairing_code(), "Pixel", "4321")
        for _ in range(auth.PIN_TRIES - 1):
            with self.assertRaises(RemoteDenied):
                self.store.login(paired["credential"], "0000")
        with self.assertRaises(RemoteDenied) as caught:
            self.store.login(paired["credential"], "0000")
        self.assertIn("removed", str(caught.exception))
        with self.assertRaises(RemoteDenied):
            self.store.login(paired["credential"], "4321")         # revoked: the right PIN no longer helps

    def test_sessions_expire_and_nonces_are_single_use_and_bound(self):
        paired = self.store.pair(self.store.new_pairing_code(), "Pixel", "4321")
        login = self.store.login(paired["credential"], "4321")
        self.assertEqual(self.store.session(login["token"])["device"], paired["device_id"])
        nonce = self.store.approval_nonce("s1", "step-a")
        with self.assertRaises(RemoteDenied):
            self.store.use_nonce(nonce, "s1", "step-b")            # another step
        nonce = self.store.approval_nonce("s1", "step-a")
        self.store.use_nonce(nonce, "s1", "step-a")
        with self.assertRaises(RemoteDenied):
            self.store.use_nonce(nonce, "s1", "step-a")            # replayed
        self.clock.now += auth.SESSION_SECONDS + 1
        with self.assertRaises(RemoteDenied):
            self.store.session(login["token"])

    def test_at_most_three_phones_and_rate_limit(self):
        for number in range(auth.MAX_DEVICES):
            self.store.pair(self.store.new_pairing_code(), f"p{number}", "1234")
        with self.assertRaises(RemoteDenied):
            self.store.pair(self.store.new_pairing_code(), "fourth", "1234")
        for _ in range(auth.RATE_PER_MINUTE):
            self.store.rate("d")
        with self.assertRaises(RemoteDenied):
            self.store.rate("d")
        # owner 2026-11-07: a live screen (3 frames/s) must not use up the general budget, and vice versa
        for _ in range(auth.RATES["frame"][0]):
            self.store.rate("d", "frame")
        with self.assertRaises(RemoteDenied):
            self.store.rate("d", "frame")
        self.store.rate("d", "input")
        self.store.rate("d", "poll")


class TailscaleTests(unittest.TestCase):
    def runner(self, funnel=False, logged_in=True, missing=False):
        def run(args):
            if missing:
                return 127, ""
            if args[:2] == ["status", "--json"]:
                return 0, json.dumps({"BackendState": "Running" if logged_in else "NeedsLogin",
                                      "Self": {"DNSName": HOST + ".", "UserID": 7},
                                      "User": {"7": {"LoginName": LOGIN}}})
            if args[:2] == ["funnel", "status"]:
                return 0, json.dumps({"AllowFunnel": {HOST + ":443": True}, "Web": {"8766": {}}} if funnel else {})
            return 0, ""
        return run

    def test_status_and_funnel(self):
        state = tailscale.status(runner=self.runner())
        self.assertEqual((state["host"], state["login"], state["logged_in"]), (HOST, LOGIN, True))
        self.assertFalse(tailscale.status(runner=self.runner(missing=True))["installed"])
        self.assertFalse(tailscale.status(runner=self.runner(logged_in=False))["logged_in"])
        self.assertTrue(tailscale.funnel_exposes(8766, runner=self.runner(funnel=True)))
        self.assertFalse(tailscale.funnel_exposes(8766, runner=self.runner()))
        self.assertTrue(tailscale.funnel_exposes(8766, runner=lambda args: (0, "not json")))   # unreadable: closed

    def test_manager_refuses_without_tailscale_or_with_funnel(self):
        from chutku.remote.manager import RemoteManager
        with TemporaryDirectory() as temp:
            core = type("Core", (), {"base": Path(temp)})()
            manager = RemoteManager(core, runner=self.runner(missing=True), server_factory=lambda c, p: None)
            self.assertFalse(manager.enable()["enabled"])
            manager = RemoteManager(core, runner=self.runner(funnel=True), server_factory=lambda c, p: None)
            self.assertIn("Funnel", manager.enable()["steps"])
            self.assertFalse(manager.store.settings()["enabled"])


class FakeInjector:
    def __init__(self):
        self.calls = []

    def pointer(self, kind, x, y, dy=0):
        self.calls.append(("pointer", kind, x, y))

    def text(self, text):
        self.calls.append(("text", text))

    def keys(self, parts):
        self.calls.append(("keys", tuple(parts)))


class ControlTests(unittest.TestCase):
    def session(self, window=None, locked=False, local=None):
        self.injector, self.logged = FakeInjector(), []
        ticks = {"now": 100000}
        return control.ControlSession(
            "base", inject=self.injector, log=self.logged.append, locked=lambda: locked,
            window=lambda: window or {"executable": "notepad.exe", "title": "Untitled - Notepad"},
            local_tick=lambda: local, now_tick=lambda: ticks["now"])

    def test_points_map_to_the_monitor_and_are_logged(self):
        session = self.session()
        session.pointer([{"kind": "tap", "x": 0.5, "y": 0.5}], (1920, 0, 1280, 720))   # second monitor
        self.assertEqual(self.injector.calls, [("pointer", "tap", 1920 + 640, 360)])
        self.assertEqual(self.logged[0]["origin"], "phone_control")
        with self.assertRaises(control.ControlRefused):
            session.pointer([{"kind": "tap", "x": 1.5, "y": 0}], (0, 0, 100, 100))

    def test_typed_text_is_never_logged(self):
        session = self.session()
        session.text("नमस्ते Chutku 123")
        self.assertEqual(self.injector.calls, [("text", "नमस्ते Chutku 123")])
        self.assertNotIn("नमस्ते", json.dumps(self.logged, ensure_ascii=False))
        self.assertEqual(self.logged[0]["script"], "Devanagari")

    def test_enter_in_a_command_window_needs_the_pin(self):
        session = self.session(window={"executable": "powershell.exe", "title": "Windows PowerShell"})
        with self.assertRaises(control.ControlRefused):
            session.text("dir", enter=True)
        with self.assertRaises(control.ControlRefused):
            session.keys("enter")
        self.assertEqual(self.injector.calls, [])                     # nothing reached PowerShell
        session.text("dir", enter=True, pin_ok=True)
        self.assertEqual(self.injector.calls[-1], ("keys", ("enter",)))

    def test_ctrl_alt_del_and_lock_are_impossible(self):
        session = self.session()
        for combo in ("ctrl+alt+del", "ctrl+alt+delete", "win+l"):
            with self.assertRaises(control.ControlRefused):
                session.keys(combo)
        with self.assertRaises(control.ControlRefused):
            self.session(locked=True).text("password")

    def test_the_laptop_always_wins(self):
        session = self.session(local=100000 - 2000)                     # someone touched the laptop 2 s ago
        with self.assertRaises(control.ControlRefused) as caught:
            session.pointer([{"kind": "tap", "x": 0.1, "y": 0.1}], (0, 0, 100, 100))
        self.assertIn("using the laptop", str(caught.exception))

    def test_a_session_ends_after_its_time(self):
        clock = Clock()
        session = control.ControlSession("b", inject=FakeInjector(), log=lambda r: None, clock=clock,
                                         locked=lambda: False, window=lambda: {}, local_tick=lambda: None,
                                         now_tick=lambda: 0)
        clock.now += control.IDLE_MAX + 1
        with self.assertRaises(control.ControlRefused):
            session.keys("tab")


class ServerTests(unittest.TestCase):
    """The real phone server on 127.0.0.1 with a real (temporary) Chutku core behind it."""

    def setUp(self):
        from chutku.dashboard import DashboardServer
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.core = DashboardServer(self.base, port=0)
        self.store = RemoteStore(self.base)
        self.store.configure(host=HOST, login=LOGIN, enabled=True)
        self.inbox = self.base / "inbox"
        self.server = remote_server.RemoteServer(self.core, 0, store=self.store, inbox=self.inbox,
                                                 monitor=(0, 0, 1000, 500))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.cookie = self.csrf = ""

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        if self.core.action_lock.acquire(timeout=10):
            self.core.action_lock.release()
        time.sleep(0.2)
        self.core.server_close()
        self.temp.cleanup()

    def request(self, path, data=None, *, host=HOST, login=LOGIN, raw=None, csrf=True, extra=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        headers = {"Host": host, "Tailscale-User-Login": login, "Origin": "https://" + HOST}
        if self.cookie:
            headers["Cookie"] = "chutku_phone=" + self.cookie
        if csrf and self.csrf:
            headers["X-Chutku-CSRF"] = self.csrf
        headers.update(extra or {})
        body = raw if raw is not None else (json.dumps(data) if data is not None else None)
        if body is not None and raw is None:
            headers["Content-Type"] = "application/json"
        connection.request("POST" if body is not None else "GET", path, body, headers)
        response = connection.getresponse()
        payload = response.read()
        result = (response.status, json.loads(payload) if response.getheader("Content-Type", "").startswith(
            "application/json") else payload, dict(response.getheaders()))
        connection.close()
        return result

    def pair_and_login(self, pin="4321"):
        status, body, _ = self.request("/api/pair", {"code": self.store.new_pairing_code(), "name": "Pixel", "pin": pin})
        self.assertEqual(status, 200, body)
        status, login, headers = self.request("/api/login", {"credential": body["credential"], "pin": pin})
        self.assertEqual(status, 200, login)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("Secure", headers["Set-Cookie"])
        self.cookie = headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
        self.csrf = login["csrf"]
        return body["credential"]

    def test_only_the_tailnet_host_and_owner_login_get_in(self):
        self.assertEqual(self.request("/", host="evil.example")[0], 403)
        self.assertEqual(self.request("/", login="someone@else.com")[0], 403)
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("/api/whoami")[0], 401)               # not paired / not logged in

    def test_phone_chat_runs_as_a_phone_session_and_needs_csrf(self):
        self.pair_and_login()
        self.assertEqual(self.request("/api/chat", {"message": "time batao"}, csrf=False)[0], 403)
        status, body, _ = self.request("/api/chat", {"message": "time batao"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["session"]["origin"], "phone")
        self.assertEqual(self.request("/api/session?id=" + body["session"]["id"])[0], 200)

    def test_a_revoked_phone_is_out_at_once(self):
        credential = self.pair_and_login()
        self.store.revoke(credential.split(".")[0])
        self.assertEqual(self.request("/api/whoami")[0], 401)

    def test_approval_needs_pin_and_a_fresh_nonce_and_laptop_only_steps_stay_on_the_laptop(self):
        self.pair_and_login()
        from chutku.agent_loop import AgentSession
        session = self.core.agent_sessions.add(AgentSession("move my file", mode="owner", origin="phone"))
        pending = {"step": {"tool": "filesystem.move", "arguments": {}, "purpose": "move"},
                   "approval": {"tool": "filesystem.move", "risk": 2, "consequence": "Move a.txt"}}
        with session.lock:
            session.status, session.pending = "waiting_confirmation", pending
        view = self.request("/api/session?id=" + session.id)[1]["session"]
        nonce = view["pending"]["nonce"]
        self.assertFalse(view["pending"]["laptop_only"])
        decided = []
        self.core.confirm_session = lambda sid, approve: decided.append(approve) or session.snapshot()
        status, body, _ = self.request("/api/approve", {"id": session.id, "approve": True, "pin": "9999", "nonce": nonce})
        self.assertEqual(status, 403)                                    # wrong PIN
        status, body, _ = self.request("/api/approve", {"id": session.id, "approve": True, "pin": "4321", "nonce": nonce})
        self.assertEqual(status, 403)                                    # the nonce was spent by the failed try
        nonce = self.request("/api/session?id=" + session.id)[1]["session"]["pending"]["nonce"]
        status, body, _ = self.request("/api/approve", {"id": session.id, "approve": True, "pin": "4321", "nonce": nonce})
        self.assertEqual(status, 200, body)
        self.assertEqual(decided, [True])
        status, body, _ = self.request("/api/approve", {"id": session.id, "approve": True, "pin": "4321", "nonce": nonce})
        self.assertEqual(status, 403)                                    # replayed
        with session.lock:
            session.pending = {"step": {"tool": "power.schedule", "arguments": {}, "purpose": "x"},
                               "approval": {"tool": "power.schedule", "risk": 4, "consequence": "Shut down"}}
        view = self.request("/api/session?id=" + session.id)[1]["session"]
        self.assertTrue(view["pending"]["laptop_only"])
        self.assertNotIn("nonce", view["pending"])
        status, body, _ = self.request("/api/approve", {"id": session.id, "approve": True, "pin": "4321", "nonce": "x"})
        self.assertEqual(status, 409)
        self.assertIn("laptop", body["error"])

    def test_the_pin_once_per_session_and_risky_steps_still_ask(self):
        # owner 2026-11-07: the login PIN unlocks screen, clipboard and files for PIN_SESSION; risky approvals ask
        self.pair_and_login()
        with patch.object(remote_server, "_keep_awake"):
            self.assertEqual(self.request("/api/screen/start", {})[0], 200)            # no PIN: the login counted
        self.assertTrue(self.request("/api/whoami")[1]["pin_ok"])
        self.assertEqual(self.request("/api/screen/start", {"pin": "0000"})[0], 403)  # a wrong PIN is still wrong
        device = next(iter(self.server.pin_ok))
        self.server.pin_ok[device] = 0                                              # the session ran out
        self.assertFalse(self.request("/api/whoami")[1]["pin_ok"])
        self.assertEqual(self.request("/api/screen/start", {})[0], 403)
        self.assertEqual(self.request("/api/screen/start", {"pin": "4321"})[0], 200)   # and a PIN renews it
        self.assertTrue(self.request("/api/whoami")[1]["pin_ok"])

    def test_risky_approvals_need_the_pin_even_inside_a_session(self):
        self.pair_and_login()
        handler = remote_server.PhoneHandler.__new__(remote_server.PhoneHandler)
        handler.server = self.server
        record = {"device": next(iter(self.server.pin_ok))}
        handler._pin(record, None)                                                  # in session: fine
        with self.assertRaises(RemoteDenied):
            handler._pin(record, None, strict=True)
        handler._pin(record, "4321", strict=True)

    def test_a_laptop_video_streams_with_seeking_and_protected_files_do_not(self):
        # owner 2026-11-07: "an anime episode on my laptop" plays in the phone's own player (HTTP Range)
        self.pair_and_login()
        movie = self.base / "episode.mp4"
        movie.write_bytes(bytes(range(256)) * 40)
        with patch("chutku.core.paths.protected_zones", return_value=[]):
            status, body, headers = self.request("/api/files/stream?path=" + str(movie), extra={"Range": "bytes=10-19"})
            self.assertEqual(status, 206)
            self.assertEqual(body, bytes(range(10, 20)))
            self.assertEqual(headers["Content-Range"], "bytes 10-19/10240")
            self.assertEqual(headers["Content-Type"], "video/mp4")
            status, body, _ = self.request("/api/files/stream?path=" + str(movie))
            self.assertEqual((status, len(body)), (200, 10240))
            self.assertEqual(self.request("/api/files/stream?path=" + str(movie), extra={"Range": "bytes=99999-"})[0], 416)
        with patch("chutku.core.paths.protected_zones", return_value=[str(self.base.resolve()).casefold()]):
            self.assertEqual(self.request("/api/files/stream?path=" + str(movie))[0], 403)

    def test_the_stream_needs_a_screen_view_and_draws_the_cursor(self):
        self.pair_and_login()
        self.assertEqual(self.request("/api/screen/stream")[0], 403)                    # no view started
        from chutku.vision import Shot
        shot = Shot(np.zeros((400, 800, 3), np.uint8), 0, 0, 800, 400, {})
        drawn = remote_server._with_cursor(shot, (100, 100))
        self.assertTrue((drawn[104:110, 101] == 255).all())                           # a white arrow below the tip
        self.assertFalse(shot.pixels.any())                                            # the capture itself untouched
        body, mime = remote_server._jpeg(drawn, 8, width=400)
        if mime == "image/jpeg":
            self.assertEqual(body[:3], b"\xff\xd8\xff")

    def test_screen_view_needs_the_pin_and_sends_only_changes(self):
        self.pair_and_login()
        self.assertEqual(self.request("/api/screen/frame")[0], 403)
        from chutku.vision import Shot
        shot = Shot(np.full((500, 1000, 3), 40, np.uint8), 0, 0, 1000, 500, {})
        with patch("chutku.vision.capture", return_value=shot), patch.object(remote_server, "_keep_awake"), \
                patch("chutku.remote.control.cursor_pos", return_value=(250, 125)):
            self.assertEqual(self.request("/api/screen/start", {"pin": "0000"})[0], 403)
            self.assertEqual(self.request("/api/screen/start", {"pin": "4321"})[0], 200)
            status, image, headers = self.request("/api/screen/frame")
            self.assertEqual(status, 200)
            self.assertTrue(image[:3] == b"\xff\xd8\xff" or image[:8] == b"\x89PNG\r\n\x1a\n")   # JPEG, PNG fallback
            self.assertEqual(json.loads(headers["X-Cursor"]), [0.25, 0.25])               # the phone draws it
            for _ in range(10):   # 10 frames in a row no longer hit the old 30/min limit (they died after ~10 s)
                self.assertEqual(self.request("/api/screen/frame?h=" + headers["X-Frame-Hash"])[0], 204)
            self.assertEqual(self.request("/api/whoami")[0], 200)
            self.server.screen["beat"] -= remote_server.SCREEN_BEAT + 1                  # the phone went quiet
            self.assertEqual(self.request("/api/screen/frame")[0], 403)
        with patch("chutku.vision.capture", side_effect=OSError("secure desktop")), \
                patch.object(remote_server, "_keep_awake"):   # locked laptop: a clear 503, not a dropped connection
            self.assertEqual(self.request("/api/screen/start", {"pin": "4321"})[0], 200)
            status, body, _ = self.request("/api/screen/frame")
            self.assertEqual(status, 503)
            self.assertIn("locked", body["error"])

    def test_control_needs_arming_at_the_laptop_then_the_pin(self):
        self.pair_and_login()
        self.assertEqual(self.request("/api/control/start", {"pin": "4321"})[0], 409)      # not armed
        self.store.configure(control_allowed=True)
        injector = FakeInjector()
        with patch.object(control, "Injector", lambda: injector), \
                patch.object(control, "session_locked", lambda: False), \
                patch.object(control, "foreground", lambda: {"executable": "notepad.exe", "title": "x"}), \
                patch.object(control, "last_input_tick", lambda: None), \
                patch.object(control, "_action_log", lambda base: (lambda record: None)):
            self.assertEqual(self.request("/api/control/start", {"pin": "1111"})[0], 403)
            self.assertEqual(self.request("/api/control/start", {"pin": "4321"})[0], 200)
            status, body, _ = self.request("/api/control/input", {"events": [{"kind": "tap", "x": 0.5, "y": 0.5}]})
            self.assertEqual((status, body), (200, {"done": 1}))
            self.assertEqual(injector.calls, [("pointer", "tap", 500, 250)])
            self.server.disarm("Ctrl+Alt+Shift+P")                                          # the laptop kill hotkey
            self.assertEqual(self.request("/api/control/input", {"events": [{"kind": "tap", "x": 0, "y": 0}]})[0], 409)
            self.assertFalse(self.store.settings()["control_allowed"])

    def test_uploads_are_create_only_and_programs_blocked(self):
        self.pair_and_login()
        status, body, _ = self.request("/api/files/upload?name=photo.jpg", raw=b"abc",
                                       extra={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200, body)
        status, again, _ = self.request("/api/files/upload?name=photo.jpg", raw=b"xyz")
        self.assertNotEqual(body["saved"], again["saved"])                                    # never overwritten
        self.assertEqual(Path(body["saved"]).read_bytes(), b"abc")
        status, program, _ = self.request("/api/files/upload?name=setup.exe", raw=b"MZ")
        self.assertTrue(program["saved"].endswith("setup.exe.blocked"))

    def test_secret_and_system_files_never_go_to_the_phone(self):
        self.pair_and_login()
        secret = self.base / ".ssh" / "id_rsa"
        secret.parent.mkdir()
        secret.write_text("KEY")
        status, body, _ = self.request("/api/files/get", {"path": str(secret), "pin": "4321"})
        self.assertEqual(status, 403)
        # The test folder lives under AppData, a protected zone: it is refused too, as it should be.
        ok = self.base / "notes.txt"
        ok.write_bytes(b"hello")
        status, body, _ = self.request("/api/files/get", {"path": str(ok), "pin": "4321"})
        self.assertIn("protected", body["error"])
        with patch("chutku.core.paths.protected_zones", return_value=[]):
            self.assertEqual(self.request("/api/files/get", {"path": str(ok), "pin": "0000"})[0], 403)
            status, blob, _ = self.request("/api/files/get", {"path": str(ok), "pin": "4321"})
            self.assertEqual((status, blob), (200, b"hello"))
            self.assertEqual(self.request("/api/files/get", {"path": str(secret), "pin": "4321"})[0], 403)

    def test_service_worker_never_caches_answers(self):
        text = (remote_server.WEB / "sw.js").read_text(encoding="utf-8")
        self.assertIn('url.pathname.startsWith("/api/")', text)
        self.assertNotIn("/api/", text.split("const STATIC")[1].split(";")[0])

    def test_nothing_secret_reaches_the_logs(self):
        credential = self.pair_and_login("8642")
        log = self.base / "data" / "actions.log.jsonl"
        text = (log.read_text(encoding="utf-8") if log.exists() else "") + \
            (self.base / "data" / "remote.json").read_text(encoding="utf-8")
        self.assertNotIn("8642", text)
        self.assertNotIn(credential.split(".")[1], text)
        self.assertNotIn(self.cookie, text)

    def test_funnel_stops_the_server(self):
        self.server.tailscale_runner = lambda args: (0, json.dumps({"AllowFunnel": {HOST + ":443": True},
                                                                    "Web": {str(self.server.server_port): {}}}))
        self.pair_and_login()
        self.server.watch_funnel(every=0.05)
        deadline = time.monotonic() + 3
        while self.store.sessions and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.store.sessions, {})


class PhraseTests(unittest.TestCase):
    def test_owner_phrases(self):
        from chutku.quick_intents import quick_proposal
        cases = {"phone connect karo": "remote.enable", "phone pair karo": "remote.pair",
                 "remote band karo": "remote.disable", "phone hatao": "remote.revoke",
                 "phone control on karo": "remote.arm", "phone status": "remote.status"}
        for said, tool in cases.items():
            self.assertEqual(quick_proposal(said)["next_steps"][0]["tool"], tool, said)

    def test_the_main_dashboard_stays_local_only(self):
        from chutku.dashboard import DashboardServer
        with TemporaryDirectory() as temp:
            server = DashboardServer(Path(temp), port=0)
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")
            finally:
                server.server_close()


class KeepAwakeTests(unittest.TestCase):
    """Owner 2026-11-07: while phone access runs and the laptop is on mains power, it must not sleep."""

    def test_on_mains_only_and_released_when_phone_access_stops(self):
        from chutku.remote.manager import RemoteManager
        calls = []
        manager = RemoteManager.__new__(RemoteManager)
        server = SimpleNamespace(stopped=threading.Event())
        manager.server = server
        power = iter([True, False])

        def fake_keep(on):
            calls.append(on)
            if len(calls) == 2:
                manager.server = None   # phone access turned off
        with patch("chutku.nightshift.keep_awake", fake_keep):
            manager._keep_awake(server, every=0, check=lambda: next(power))
        self.assertEqual(calls, [True, False, False])   # mains, then battery, then released


if __name__ == "__main__":
    unittest.main()
