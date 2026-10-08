"""Scheduled-task upgrades (Phase 3b H8): results are reported when a task finishes, "sirf nayi" tasks get the
previous result and stay quiet when nothing changed, and the same failure is shown once per 24 hours."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import scheduled


class Session:
    def __init__(self, sid, status, reply):
        self.id, self.status, self.reply = sid, status, reply

    def snapshot(self):
        return {"status": self.status, "reply": self.reply}


class Store:
    def __init__(self):
        self.sessions = {}

    def get(self, sid):
        return self.sessions.get(sid)


class FakeServer:
    def __init__(self, base, reply="Top story: rain in Pune. [Verified: 1 of 1 steps completed.]"):
        self.base, self.agent_sessions, self.reply, self.contexts = base, Store(), reply, []

    def begin_session(self, goal, mode, origin, **kwargs):
        self.contexts.append(kwargs.get("extra_context"))
        session = Session(f"s{len(self.contexts)}", "done", self.reply)
        self.agent_sessions.sessions[session.id] = session
        return session


class Ticks:
    def __init__(self, n):
        self.left = n

    def wait(self, _seconds):
        self.left -= 1
        return self.left < 0


class ScheduledPlusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def add(self, goal):
        return scheduled.add(self.base, goal, datetime.now() + timedelta(minutes=5), every_minutes=60)

    def test_only_new_detection(self):
        self.assertTrue(scheduled.only_new("har subah news batao, sirf nayi"))
        self.assertTrue(scheduled.only_new("check my inbox folder, only new files"))
        self.assertFalse(scheduled.only_new("har ghante paani peene ka yaad dilana"))

    def test_result_is_shown_and_only_new_stays_quiet_when_unchanged(self):
        job = self.add("har ghante news batao sirf nayi")
        self.assertEqual(scheduled.run_context(self.base, job), {})          # first run: nothing to compare
        shown = scheduled.finished(self.base, job["id"], {"status": "done", "reply": "Rain in Pune."})
        self.assertEqual(shown[1], "Rain in Pune.")
        job = scheduled.load(self.base)[0]
        context = scheduled.run_context(self.base, job)["previous_run"]
        self.assertEqual(context["reply"], "Rain in Pune.")
        self.assertIn(scheduled.NOTHING_NEW, context["rule"])
        self.assertIsNone(scheduled.finished(self.base, job["id"], {"status": "done", "reply": "Rain in Pune."}))
        self.assertIsNone(scheduled.finished(self.base, job["id"], {"status": "done", "reply": "NOTHING NEW"}))
        self.assertEqual(scheduled.finished(self.base, job["id"], {"status": "done", "reply": "Exam dates out."})[1],
                         "Exam dates out.")
        history = [h["status"] for h in scheduled.load(self.base)[0]["history"]]
        self.assertEqual(history[-3:], ["nothing new", "nothing new", "done"])

    def test_ordinary_tasks_always_report(self):
        job = self.add("har ghante time batao")
        for _ in range(2):
            self.assertIsNotNone(scheduled.finished(self.base, job["id"], {"status": "done", "reply": "It's 5 PM."}))

    def test_same_failure_is_shown_once_a_day(self):
        job = self.add("har ghante backup check karo")
        now = datetime(2026, 10, 7, 12, 0)
        failed = {"status": "failed", "reply": "Drive E: not found."}
        self.assertIsNotNone(scheduled.finished(self.base, job["id"], failed, now=now))
        self.assertIsNone(scheduled.finished(self.base, job["id"], failed, now=now + timedelta(hours=1)))
        self.assertIsNotNone(scheduled.finished(self.base, job["id"], {"status": "failed", "reply": "Other error."},
                                                now=now + timedelta(hours=2)))
        self.assertIsNotNone(scheduled.finished(self.base, job["id"], failed, now=now + timedelta(hours=27)))

    def test_watch_reports_the_result_and_passes_the_previous_one(self):
        scheduled.add(self.base, "news batao sirf nayi", datetime.now() - timedelta(seconds=20))
        server = FakeServer(self.base)
        with patch.object(scheduled, "_announce"), patch.object(scheduled, "_notify") as notify:
            scheduled.watch(server, Ticks(2), tick=0)        # tick 1 starts it, tick 2 sees it finished
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], "Top story: rain in Pune.")   # the [Verified] tail is dropped
        self.assertEqual(server.contexts, [None])   # nothing extra on the first run


if __name__ == "__main__":
    unittest.main()
