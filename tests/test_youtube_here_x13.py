"""X13 (2026-11-06): a YouTube video can play inside Chutku's own window."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import presence
from chutku.tools import internet
from tests import test_dashboard as _harness

RESULTS = '... "videoRenderer":{"videoId":"abcDEF12345", ... "title":{"runs":[{"text":"Lofi Mix"}] ...'


class ToolAndStateTests(unittest.TestCase):
    _base = _harness.DashboardTests
    setUp, tearDown, request = _base.setUp, _base.tearDown, _base.request

    def test_the_tool_saves_the_video_and_the_window_shows_it_until_closed(self):
        with patch.object(internet, "fetch", return_value=(RESULTS, "https://www.youtube.com/results")), \
                patch.object(internet, "hud_video_file", return_value=self.base / "data" / "hud-video.json"):
            out = internet._youtube_here({"query": "lofi"}, None)
        self.assertEqual((out.output["video_id"], out.output["video_title"]), ("abcDEF12345", "Lofi Mix"))
        self.assertEqual(self.server.hud_video(), {"id": "abcDEF12345", "title": "Lofi Mix"})
        status, body, headers = self.request("/presence")
        self.assertIn("frame-src https://www.youtube-nocookie.com;", headers["Content-Security-Policy"])
        self.request("/api/presence/video/close", {})
        self.assertIsNone(self.server.hud_video())

    def test_an_old_or_malformed_video_is_never_shown(self):
        path = self.base / "data" / "hud-video.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": "abcDEF12345", "title": "x", "at": time.time() - 5 * 3600}), encoding="utf-8")
        self.assertIsNone(self.server.hud_video())
        path.write_text(json.dumps({"id": "javascript:alert(1)", "title": "x", "at": time.time()}), encoding="utf-8")
        self.assertIsNone(self.server.hud_video())


class WatcherTests(unittest.TestCase):
    def test_a_new_video_opens_the_full_window_once(self):
        expands = []

        class Bridge:
            def expand(self):
                expands.append(1)

            def peek(self):
                pass

            def unpeek(self):
                pass
        state = {"phase": "done", "video": {"id": "abcDEF12345"}}
        watcher = presence.StateWatcher(Bridge(), "http://127.0.0.1:1/#token=t", fetch=lambda: state)
        for now in range(3):
            watcher.step(float(now))
        self.assertEqual(len(expands), 1)


if __name__ == "__main__":
    unittest.main()
