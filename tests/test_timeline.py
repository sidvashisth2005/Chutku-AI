"""Episodic timeline (master plan S21): opt-in, window titles only, private windows masked, 14-day expiry."""
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku import mind, timeline
from chutku.app import create_runtime
from chutku.core.preferences import Preferences
from chutku.policy.kernel import Decision
from chutku.quick_intents import quick_proposal


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.mind_root = patch.object(mind, "PROJECT_ROOT", self.base)
        self.mind_root.start()
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def test_off_by_default_and_the_watcher_records_nothing_while_off(self):
        self.assertFalse(timeline.enabled(self.base))
        stop = __import__("threading").Event()
        with patch("chutku.tools.everyday.Desktop") as desktop:
            desktop.return_value.foreground.return_value = 1
            desktop.return_value.describe.return_value = {"executable": r"C:\x\notepad.exe", "title": "a.txt"}
            thread = __import__("threading").Thread(target=timeline.watch, args=(self.base, stop, 0.02))
            thread.start()
            time.sleep(0.2)
            stop.set()
            thread.join(2)
        self.assertFalse(timeline.path(self.base).exists())

    def test_private_windows_are_masked_and_never_returned(self):
        Preferences(self.base).update({"timeline": True, "timeline_private": ["mybank.exe"]})
        timeline.record(self.base, r"C:\Program Files\Brave\brave.exe", "Secret thing - Brave (Incognito)")
        timeline.record(self.base, r"C:\Apps\mybank.exe", "Account 1234 balance")
        timeline.record(self.base, r"C:\Apps\keepassxc.exe", "Passwords.kdbx")
        self.assertFalse(timeline.record(self.base, r"C:\Braverave.exe", "YouTube - Brave (Private)"))
        timeline.record(self.base, r"C:\Braverave.exe", "Gmail - Private with Tor - Brave")
        timeline.record(self.base, "notepad.exe", "notes.txt - Notepad")       # an ordinary window is kept
        with closing(sqlite3.connect(timeline.path(self.base))) as db:
            titles = [t for (t,) in db.execute("SELECT title FROM moments")]
        self.assertEqual(titles, ["notes.txt - Notepad"])   # 2026-11-01: private windows leave no row at all
        self.assertEqual(timeline.search(self.base, "account", "today")["matches"], [])

    def test_expiry_deletes_rows_older_than_14_days(self):
        Preferences(self.base).update({"timeline": True})
        timeline.record(self.base, "a.exe", "old window", at=time.time() - 15 * 86400)
        timeline.record(self.base, "a.exe", "new window")
        self.assertEqual(timeline.expire(self.base), 1)
        with closing(sqlite3.connect(timeline.path(self.base))) as db:
            self.assertEqual([t for (t,) in db.execute("SELECT title FROM moments")], ["new window"])

    def test_no_image_data_is_ever_stored(self):
        timeline.record(self.base, "a.exe", "x")
        with closing(sqlite3.connect(timeline.path(self.base))) as db:
            columns = [(c[1], c[2]) for c in db.execute("PRAGMA table_info(moments)")]
        self.assertEqual(columns, [("at", "REAL"), ("app", "TEXT"), ("title", "TEXT")])   # no BLOB, no pixels

    def test_kal_shaam_finds_the_pdf_from_yesterday_evening(self):
        now = datetime(2026, 10, 6, 10, 0)
        evening = datetime(2026, 10, 5, 19, 15).timestamp()
        timeline.record(self.base, r"C:\x\msedge.exe", "Invoice-Sept.pdf - Microsoft Edge", at=evening)
        timeline.record(self.base, r"C:\x\code.exe", "main.py - Chutku", at=evening + 60)
        timeline.record(self.base, r"C:\x\msedge.exe", "Other.pdf", at=datetime(2026, 10, 5, 9, 0).timestamp())
        found = timeline.search(self.base, "PDF", "kal shaam", now=now)["matches"]
        self.assertEqual([m["title"] for m in found], ["Invoice-Sept.pdf - Microsoft Edge"])   # not the morning one
        self.assertEqual(timeline.window("abhi", now)[0], now - timedelta(minutes=30))

    def test_timeline_off_deletes_what_was_stored_and_only_the_owner_can_switch(self):
        self.assertEqual(self.runtime.run("settings.timeline", {"on": True})["state"], "COMPLETED")
        timeline.record(self.base, "a.exe", "something")
        self.assertEqual(self.runtime.run("settings.timeline", {"on": False})["state"], "COMPLETED")
        self.assertFalse(timeline.path(self.base).exists())
        tool = self.runtime.registry.get("settings.timeline")
        decision = self.runtime.authorize(tool, {"on": True}, provenance="delegated", autonomy="owner").decision
        self.assertEqual(decision, Decision.DENY)

    def test_search_tool_says_when_the_timeline_is_off(self):
        result = self.runtime.run("timeline.search", {"query": "pdf", "when": "kal"})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertIn("timeline on", result["output"]["note"])

    def test_phrases(self):
        for text, arguments in (("wo PDF jo kal shaam khola tha", {"query": "PDF", "when": "kal shaam"}),
                                ("abhi kaunsa PDF khola tha", {"query": "PDF", "when": "abhi"}),
                                ("which pdf did I open yesterday evening", {"query": "pdf", "when": "yesterday evening"})):
            step = quick_proposal(text)["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]), ("timeline.search", arguments), text)
        self.assertEqual(quick_proposal("what was I working on")["next_steps"][0]["tool"], "files.recent")

    def test_the_instant_answer_reads_through_the_untrusted_wrapping(self):
        # Live 2026-10-06: the S15 wrapping made the fixed answer say "the timeline is off" while it was recording.
        from chutku.agent_loop import AgentSession, RuntimeRouter, default_context
        from chutku.quick_intents import QuickPlanner

        class NoModel:
            name = "local"

            def propose(self, *args, **kwargs):
                raise AssertionError("the model must not be needed")

        Preferences(self.base).update({"timeline": True})
        timeline.record(self.base, r"C:\x\msedge.exe", "Timeline-Check-Report.pdf - Microsoft Edge")
        router = RuntimeRouter(self.runtime)
        session = AgentSession("abhi kaunsa PDF khola tha", mode="owner", context=default_context(router))
        session.quick = QuickPlanner()
        snapshot = session.advance(router, NoModel())
        self.assertEqual(snapshot["status"], "done", snapshot)
        self.assertIn("Timeline-Check-Report.pdf", snapshot["reply"])

    def test_window_titles_taint_the_session(self):
        from chutku.agent_loop import PRIVATE_TOOLS, TAINTING_TOOLS
        self.assertIn("timeline.search", TAINTING_TOOLS)
        self.assertIn("timeline.search", PRIVATE_TOOLS)


if __name__ == "__main__":
    unittest.main()
