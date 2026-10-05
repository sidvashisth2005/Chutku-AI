"""Guard breakaway, bounded logs and safe settings files (master plan S4)."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku.core import jsonstore, launch
from chutku.core.action_log import ActionLog
from chutku.core.event_log import EventLog


class LaunchTests(unittest.TestCase):
    def test_user_apps_break_away_from_the_guard_job(self):
        with patch.object(launch.subprocess, "Popen") as popen:
            launch.popen_user_app(["notepad.exe"], creationflags=0x8)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x8 | launch.CREATE_BREAKAWAY_FROM_JOB)

    def test_falls_back_when_breakaway_is_refused(self):
        with patch.object(launch.subprocess, "Popen", side_effect=[OSError("access denied"), "started"]) as popen:
            self.assertEqual(launch.popen_user_app(["notepad.exe"]), "started")
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0)

    def test_guard_job_allows_breakaway(self):
        source = (Path(__file__).resolve().parents[1] / "chutku" / "guard.py").read_text(encoding="utf-8")
        self.assertIn("0x2000 | 0x0800", source)


class EventLogTests(unittest.TestCase):
    def test_interrupted_check_is_fast_on_many_tasks(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = EventLog(Path(temp.name) / "events.db")
        self.addCleanup(log.close)
        rows = []
        for n in range(1000):
            task = f"T{n}"
            rows.append((task, "2026-01-01T00:00:00", "task_received", json.dumps({"tool": "x"})))
            rows.append((task, "2026-01-01T00:00:00", "task_state", json.dumps({"to": "COMPLETED" if n % 2 else
                                                                                "EXECUTING"})))
        log._connection.executemany("INSERT INTO events (task_id, timestamp, event_type, payload_json) "
                                    "VALUES (?, ?, ?, ?)", rows)
        log._connection.commit()
        started = time.monotonic()
        self.assertEqual(log.mark_interrupted(), 500)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(log.mark_interrupted(), 0)   # already marked FAILED

    def test_old_events_move_to_the_archive(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = EventLog(Path(temp.name) / "chutku.db")
        old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        log._connection.execute("INSERT INTO events (task_id, timestamp, event_type, payload_json) "
                                "VALUES ('old', ?, 'task_received', '{}')", (old,))
        log._connection.commit()
        log.append("new", "task_received", {"tool": "x"})
        self.assertEqual(log.archive_older_than(90), 1)
        self.assertEqual([r[0] for r in log._connection.execute("SELECT task_id FROM events")], ["new"])
        log.close()
        archive = sqlite3.connect(Path(temp.name) / "chutku-archive.db")
        self.assertEqual(archive.execute("SELECT task_id FROM events").fetchall(), [("old",)])
        archive.close()


class ActionLogTests(unittest.TestCase):
    def test_recent_reads_from_the_end_quickly(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = ActionLog(Path(temp.name) / "actions.log.jsonl")
        lines = [json.dumps({"seq": n, "time": "2026-10-06T00:00:00", "tool": "t"}) for n in range(1, 20001)]
        log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        started = time.monotonic()
        recent = log.recent(5)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual([e["seq"] for e in recent], [20000, 19999, 19998, 19997, 19996])
        self.assertEqual(log.get(19990)["seq"], 19990)

    def test_rotation_keeps_one_unbroken_chain(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = ActionLog(Path(temp.name) / "actions.log.jsonl")
        with patch("chutku.core.action_log.ROTATE_BYTES", 300):
            for n in range(12):
                log.append({"tool": "t", "n": n})
        self.assertGreaterEqual(len(log._rotated()), 2)
        self.assertEqual(log.verify(), {"ok": True, "entries": 12, "broken_at": None})
        self.assertEqual(log.recent(1)[0]["seq"], 12)
        self.assertEqual(log.get(1)["n"], 0)


class JsonStoreTests(unittest.TestCase):
    def test_an_unreadable_settings_file_is_kept_aside_not_lost(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "reminders.json"
        path.write_text("{ half written", encoding="utf-8")
        jsonstore.write_json(path, {"a": 1})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1})
        kept = list(Path(temp.name).glob("reminders.json.unreadable-*"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_text(encoding="utf-8"), "{ half written")


class HeardLogTests(unittest.TestCase):
    def test_test_runs_are_detected_however_started(self):
        from chutku.voice import heard
        with patch("sys.argv", ["verify_release.py"]):
            self.assertTrue(heard._under_test())


if __name__ == "__main__":
    unittest.main()
