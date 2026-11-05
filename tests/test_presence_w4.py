"""W4 (2026-10-29): the presence orb page, its state endpoint, the corner window and the speaking envelope."""
import struct
import unittest
from unittest.mock import patch

from chutku import presence
from chutku.voice import tts
from tests import test_dashboard as _harness


class PresenceServerTests(unittest.TestCase):
    setUp, tearDown, request = _harness.DashboardTests.setUp, _harness.DashboardTests.tearDown, \
        _harness.DashboardTests.request

    def test_presence_files_are_served_with_the_strict_policy(self):
        for path, kind in (("/presence", "text/html"), ("/presence.js", "text/javascript"),
                           ("/presence.css", "text/css"), ("/theme.css", "text/css"), ("/icon.png", "image/png"),
                           ("/manifest.webmanifest", "application/manifest+json")):
            status, body, headers = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["Content-Type"].startswith(kind), path)
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        status, body, _ = self.request("/icon.png")
        self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", body[16:24]), (256, 256))

    def test_presence_state_needs_the_token_and_reports_the_phase(self):
        status, _, _ = self.request("/api/presence", headers={"X-Chutku-Token": "wrong"})
        self.assertEqual(status, 403)
        status, body, _ = self.request("/api/presence")
        self.assertEqual(status, 200)
        self.assertEqual(body["phase"], "idle")
        for key in ("mic_level", "voice_level", "heard", "reply", "steps", "pending", "paused"):
            self.assertIn(key, body)

    def test_paused_shows_as_paused(self):
        from chutku.core.action_control import ActionControl
        ActionControl(self.base).pause()
        _, body, _ = self.request("/api/presence")
        self.assertEqual(body["phase"], "paused")
        self.assertTrue(body["paused"])

    def test_orb_click_listens_like_the_hotkey(self):
        calls = []
        self.server.handsfree_request = lambda *a, **k: calls.append(a)
        status, body, _ = self.request("/api/presence/talk", {})
        self.assertEqual((status, body), (200, {"listening": True}))
        import time
        time.sleep(0.2)
        self.assertEqual(calls, [()])
        status, _, _ = self.request("/api/presence/talk", {"x": 1})
        self.assertEqual(status, 400)

    def test_dashboard_page_links_the_theme_and_manifest(self):
        _, body, _ = self.request("/")
        html = body.decode("utf-8")
        self.assertIn('href="/theme.css"', html)
        self.assertIn('rel="manifest"', html)


class WindowTests(unittest.TestCase):
    def test_presence_url_keeps_the_token_fragment_and_refuses_other_hosts(self):
        self.assertEqual(presence.presence_url("http://127.0.0.1:8765/#token=abc"),
                         "http://127.0.0.1:8765/presence#token=abc")
        for bad in ("https://evil.example/#token=abc", "http://127.0.0.1:8765/"):
            with self.assertRaises(ValueError):
                presence.presence_url(bad)

    def test_the_test_install_never_opens_a_window(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from chutku.dashboard import DashboardServer
        with TemporaryDirectory() as temp:
            server = DashboardServer(Path(temp), port=0)
            try:
                self.assertFalse(server.start_presence())
            finally:
                server.server_close()


class SpeakingLevelTests(unittest.TestCase):
    def test_envelope_follows_her_voice_and_is_silent_after(self):
        import numpy as np
        rate = 24000
        quiet, loud = np.zeros(rate // 2, np.float32), np.full(rate // 2, 0.5, np.float32)
        played = []
        backend = type("SD", (), {"play": staticmethod(lambda s, r: played.append(len(s))),
                                  "stop": staticmethod(lambda: None), "wait": staticmethod(lambda: None)})
        with patch.object(tts.time, "sleep", lambda s: None), \
                patch.object(tts.time, "monotonic", side_effect=[100.0, 100.0, 101.6, 200.0]):
            tts._play(np.concatenate([quiet, loud]), rate, backend)
        self.assertEqual(tts.speaking_level(), 0.0)          # finished: silent
        envelope = tts._envelope(np.concatenate([quiet, loud]), rate)
        self.assertEqual(round(envelope[0], 2), 0.0)
        self.assertEqual(round(envelope[-1], 2), 1.0)
        tts.SPEAKING.update(envelope=envelope, started=10.0)
        self.assertEqual(tts.speaking_level(now=10.0), 0.0)
        self.assertEqual(tts.speaking_level(now=10.9), 1.0)
        tts.SPEAKING["envelope"] = ()


if __name__ == "__main__":
    unittest.main()
