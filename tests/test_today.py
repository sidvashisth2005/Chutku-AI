import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku import today


class TodayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_snapshot_is_read_only_and_complete(self):
        self.runtime.run("filesystem.write_text", {"path": "a.txt", "content": "x"})
        before = sorted(p.name for p in (self.base / "data").iterdir())
        with patch("chutku.today.weather", return_value=None):
            snap = today.snapshot(self.base, self.runtime)
        for key in ("greeting", "date", "time", "disk", "reminders", "recent_files", "chutku_today"):
            self.assertIn(key, snap)
        self.assertEqual(snap["chutku_today"]["done"], 1)
        self.assertTrue(snap["chutku_today"]["log_intact"])
        self.assertTrue(snap["disk"]["drives"])
        self.assertEqual(sorted(p.name for p in (self.base / "data").iterdir()), before)

    def test_recent_files_only_from_granted_folders(self):
        with patch("chutku.today.weather", return_value=None):
            snap = today.snapshot(self.base, self.runtime)
        self.assertEqual(snap["recent_files"], [])  # only the sandbox is granted here
        self.assertEqual(snap["recent_scope"], [])

    def test_weather_uses_fresh_cache_and_reports_errors(self):
        cache = self.base / "data" / "today-weather.json"
        cache.write_text(json.dumps({"fetched": time.time(), "ok": True, "data": {
            "place": "Delhi, India", "now": {"temperature_c": 31, "sky": "clear", "feels_like_c": 34},
            "next_days": [{"max_c": 33, "min_c": 24}]}}), encoding="utf-8")
        with patch("chutku.today._refresh_weather") as refresh:
            self.assertEqual(today.weather(self.base)["temperature_c"], 31)
            refresh.assert_not_called()
        cache.write_text(json.dumps({"fetched": time.time(), "ok": False, "data": {"error": "Which city?"}}),
                         encoding="utf-8")
        self.assertEqual(today.weather(self.base), {"error": "Which city?"})

    def test_open_running_dashboard(self):
        from chutku.dashboard import _write_session_link, open_running_dashboard
        opened = []
        self.assertIn("not running", open_running_dashboard(self.base, opener=opened.append))
        _write_session_link(self.base, "http://127.0.0.1:9/#token=abc")  # nothing listens on port 9
        self.assertIn("not running", open_running_dashboard(self.base, opener=opened.append))
        self.assertEqual(opened, [])

    def test_interrupted_task_is_offered_after_restart(self):
        from chutku.dashboard import interrupted_task, mark_interrupted_task, record_last_task
        record_last_task(self.base, "organize my Downloads folder", "running")
        self.assertIsNone(interrupted_task(self.base))           # still running in this process
        self.assertEqual(mark_interrupted_task(self.base)["goal"], "organize my Downloads folder")  # next start-up
        self.assertEqual(interrupted_task(self.base)["status"], "interrupted")
        record_last_task(self.base, "what time is it", "running")
        record_last_task(self.base, "what time is it", "done")   # a finished task is never offered
        self.assertIsNone(mark_interrupted_task(self.base))
        self.assertIsNone(interrupted_task(self.base))

    def test_paused_explanation_says_why_and_how_to_resume(self):
        from chutku.dashboard import paused_explanation
        self.assertIn("Resume actions", paused_explanation(self.base))  # no report yet: still says how
        (self.base / "data" / "guard-last-stop.json").write_text(json.dumps(
            {"timestamp_utc": "2026-10-03T00:18:46+00:00", "reason": "heartbeat_timeout"}), encoding="utf-8")
        text = paused_explanation(self.base)
        self.assertIn("wakes from sleep", text)
        self.assertIn("Resume actions", text)

    def test_greeting(self):
        self.assertEqual([today.greeting(h) for h in (0, 1, 4, 5, 7, 13, 19, 22, 23)],
                         ["Working late"] * 3 + ["Good morning"] * 2 + ["Good afternoon", "Good evening"]
                         + ["Working late"] * 2)


if __name__ == "__main__":
    unittest.main()
