"""Z5 (owner, 2026-11-06): the phone as a remote. A trackpad and live keyboard drive the laptop; approvals are spoken
on the phone (the laptop stays silent); sound plays on the laptop only when the owner asks for it from the phone."""
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from chutku.dashboard import PROJECT_ROOT
from chutku.remote import control, server as remote_server
from tests import test_phone_remote_w6 as _w6
from tests.test_phone_remote_w6 import FakeInjector


class TrackpadTests(unittest.TestCase):
    def session(self, cursor=(500, 300)):
        self.injector = FakeInjector()
        return control.ControlSession("base", inject=self.injector, log=lambda r: None, locked=lambda: False,
                                      window=lambda: {"executable": "brave.exe", "title": "x"},
                                      local_seen=lambda: None, cursor=lambda: cursor)

    def test_nudges_move_from_the_cursor_and_clicks_land_where_it_is(self):
        session = self.session()
        session.pointer([{"kind": "nudge", "dx": 40, "dy": -25}, {"kind": "tap", "at": "cursor"},
                         {"kind": "right", "at": "cursor"}, {"kind": "scroll", "at": "cursor", "dy": -2}],
                        (0, 0, 1920, 1080))
        self.assertEqual(self.injector.calls, [("pointer", "move", 540, 275), ("pointer", "tap", 500, 300),
                                               ("pointer", "right", 500, 300), ("pointer", "scroll", 500, 300)])

    def test_the_cursor_stays_on_the_monitor_and_huge_or_odd_moves_are_refused(self):
        session = self.session(cursor=(1910, 5))
        session.pointer([{"kind": "nudge", "dx": 300, "dy": -300}], (0, 0, 1920, 1080))
        self.assertEqual(self.injector.calls[-1], ("pointer", "move", 1919, 0))       # clamped, never off-screen
        for bad in ({"kind": "nudge", "dx": 5000, "dy": 0}, {"kind": "nudge", "dx": True, "dy": 0},
                    {"kind": "nudge", "dx": "10", "dy": 0}, {"kind": "teleport"}):
            with self.assertRaises(control.ControlRefused):
                session.pointer([bad], (0, 0, 1920, 1080))
        self.assertEqual(len(self.injector.calls), 1)                                  # nothing else was sent


class SpokenOnThePhoneTests(unittest.TestCase):
    def test_an_approval_question_is_spoken_on_the_phone_and_the_reply_after(self):
        waiting = {"status": "waiting_confirmation", "reply": "",
                   "pending": {"approval": {"tool": "message.send", "consequence": "Send 'hi' to Mom on WhatsApp"}}}
        self.assertIn("Ek approval chahiye: Send 'hi' to Mom on WhatsApp", remote_server.spoken_text(waiting))
        done = {"status": "done", "reply": "Bhej diya. [Verified: message.send]"}
        self.assertEqual(remote_server.spoken_text(done), "Bhej diya.")
        self.assertEqual(remote_server.spoken_text({"status": "waiting_confirmation", "pending": None}), "")


class LaptopSoundServerTests(unittest.TestCase):
    """The real phone server: the laptop speaks or plays the owner's voice only on these two calls."""
    setUp, tearDown = _w6.ServerTests.setUp, _w6.ServerTests.tearDown
    request, pair_and_login = _w6.ServerTests.request, _w6.ServerTests.pair_and_login

    def test_chutku_speaks_on_the_laptop_only_when_asked_and_within_limits(self):
        said = []
        self.core._speak = said.append
        self.assertEqual(self.request("/api/laptop/say", {"text": "Khana ready hai"})[0], 401)   # not logged in
        self.pair_and_login()
        self.assertEqual(self.request("/api/laptop/say", {"text": "Khana ready hai"}, csrf=False)[0], 403)
        status, body, _ = self.request("/api/laptop/say", {"text": "Khana ready hai"})
        self.assertEqual((status, body), (200, {"saying": 15}))
        self.assertEqual(self.request("/api/laptop/say", {"text": "x" * 501})[0], 400)
        deadline = time.monotonic() + 3
        while not said and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(said, ["Khana ready hai"])

    def test_the_owners_recorded_voice_plays_on_the_laptop(self):
        played = []
        self.pair_and_login()
        with patch.object(remote_server, "decode_audio", lambda blob: b"\x01\x00" * 32000), \
                patch.object(remote_server, "play_on_laptop", played.append):
            status, body, _ = self.request("/api/laptop/voice", raw=b"webm-bytes",
                                           extra={"Content-Type": "audio/webm"})
            self.assertEqual((status, body), (200, {"playing_seconds": 2.0}))
            deadline = time.monotonic() + 3
            while not played and time.monotonic() < deadline:
                time.sleep(0.02)
        self.assertEqual(len(played), 1)
        with patch.object(remote_server, "decode_audio", lambda blob: b"\x01\x00" * 16000 * 31):
            self.assertEqual(self.request("/api/laptop/voice", raw=b"long",
                                          extra={"Content-Type": "audio/webm"})[0], 413)   # over 30 s


class PhonePageTests(unittest.TestCase):
    PAGE = PROJECT_ROOT / "chutku" / "web" / "phone"

    def test_the_page_has_the_trackpad_keyboard_and_laptop_sound(self):
        # Remote 2.0 (owner 2026-11-07): no separate Trackpad tab; touching the live screen is the trackpad.
        html = (self.PAGE / "index.html").read_text(encoding="utf-8")
        for needle in ('id="stage"', 'id="frame"', 'id="cursor"', 'id="keys"', 'id="kbd"', 'id="live-keys"',
                       'id="laptop-say"', 'id="laptop-talk"', 'data-sheet="chat"', 'data-sheet="files"'):
            self.assertIn(needle, html)
        self.assertNotIn('data-tab="pad"', html)
        script = (self.PAGE / "phone.js").read_text(encoding="utf-8")
        for needle in ('kind: "nudge"', 'at: "cursor"', "/api/laptop/say", "/api/laptop/voice", "Ek approval chahiye",
                       "X-Cursor", "startScreen()", "ensureControl()", "withPin("):
            self.assertIn(needle, script)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_script_parses(self):
        subprocess.run(["node", "--check", str(self.PAGE / "phone.js")], check=True, capture_output=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
