"""Scheduled tasks: "30 min baad X", "har 15 min X", "12 baje X" run later by themselves, beside normal work."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from chutku import mind, scheduled
from chutku.app import create_runtime
from chutku.policy.kernel import Decision
from chutku.quick_intents import quick_proposal

NOW = datetime(2026, 10, 6, 9, 30)


def parsed(text):
    found = scheduled.parse(text, NOW)
    return None if found is None else (found["goal"], found["at"].strftime("%d %H:%M"), found["every_minutes"])


class ParseTests(unittest.TestCase):
    def test_every_after_and_at(self):
        cases = {
            "har 15 min Claude chat mein continue bhej do": ("Claude chat mein continue bhej do", "06 09:45", 15),
            "send continue in claude chat every 15 minutes": ("send continue in claude chat", "06 09:45", 15),
            "har ghante paani peene ka bolo": ("paani peene ka bolo", "06 10:30", 60),
            "har 2 ghante mein weather batao": ("weather batao", "06 11:30", 120),
            "30 min baad UB ko hi bhej dena": ("UB ko hi bhej dena", "06 10:00", None),
            "after 30 minutes send hi to UB": ("send hi to UB", "06 10:00", None),
            "send hi to UB in 2 hours": ("send hi to UB", "06 11:30", None),
            "12 baje bday boy ko wish kar dena": ("bday boy ko wish", "07 00:00", None),   # birthday: midnight
            "raat 12 baje Rahul ko happy birthday bhejna": ("Rahul ko happy birthday bhejna", "07 00:00", None),
            "12 baje spotify kholo": ("spotify kholo", "06 12:00", None),                 # otherwise the next 12
            "at 9 pm send good night to mammi": ("send good night to mammi", "06 21:00", None),
            "send good night to mammi at 9:30 pm": ("send good night to mammi", "06 21:30", None),
            "kal subah 8 baje news sunao": ("news sunao", "07 08:00", None),
            "5 baje spotify kholo": ("spotify kholo", "06 17:00", None),                   # 1-6 is evening
            "8 baje weather batao": ("weather batao", "06 20:00", None),                   # 8 am has passed
        }
        for text, expected in cases.items():
            self.assertEqual(parsed(text), expected, text)

    def test_not_a_schedule(self):
        for text in ("remind me in 10 min to stretch", "30 min baad yaad dilana", "open tab 2", "set volume to 30",
                     "play song 7 years", "har baar galat karti ho", "open spotify", "note that the meeting is at 5",
                     "remember the exam is at 9 am", "meeting kal 5 baje hai"):
            self.assertIsNone(parsed(text), text)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_off_runs_once(self):
        job = scheduled.add(self.base, "open notepad", datetime.now() + timedelta(minutes=5))
        self.assertEqual(scheduled.take_due(self.base, datetime.now()), [])
        due = scheduled.take_due(self.base, datetime.now() + timedelta(minutes=6))
        self.assertEqual([j["id"] for j in due], [job["id"]])
        self.assertEqual(scheduled.take_due(self.base, datetime.now() + timedelta(minutes=7)), [])
        self.assertEqual(scheduled.active(self.base), [])

    def test_repeating_moves_on_and_never_catches_up(self):
        start = datetime.now().replace(microsecond=0) + timedelta(minutes=1)
        job = scheduled.add(self.base, "time batao", start, every_minutes=15)
        later = start + timedelta(minutes=50)   # three times were missed while busy or off
        self.assertEqual(len(scheduled.take_due(self.base, later)), 1)   # runs once, not three times
        nxt = datetime.strptime(scheduled.active(self.base)[0]["next_at"], "%Y-%m-%dT%H:%M:%S")
        self.assertEqual(nxt, start + timedelta(minutes=60))
        self.assertEqual(scheduled.active(self.base)[0]["runs"], 1)
        self.assertEqual(scheduled.cancel(self.base, job["id"])[0]["id"], job["id"])
        self.assertEqual(scheduled.take_due(self.base, later + timedelta(hours=1)), [])

    def test_a_one_off_more_than_6_hours_late_is_reported_missed_not_run(self):
        scheduled.add(self.base, "send hi to UB", datetime.now() + timedelta(minutes=1))
        self.assertEqual(scheduled.take_due(self.base, datetime.now() + timedelta(hours=8)), [])
        job = scheduled.load(self.base)[0]
        self.assertEqual((job["active"], job["ended"], job["history"][-1]["status"]), (False, "missed", "missed"))

    def test_cancel_all_and_bad_input(self):
        for goal in ("a", "b"):
            scheduled.add(self.base, goal, datetime.now() + timedelta(minutes=5))
        self.assertEqual(len(scheduled.cancel(self.base)), 2)
        self.assertEqual(scheduled.active(self.base), [])
        with self.assertRaises(ValueError):
            scheduled.add(self.base, "x", datetime.now() - timedelta(hours=1))
        with self.assertRaises(ValueError):
            scheduled.add(self.base, "x", datetime.now() + timedelta(minutes=5), every_minutes=0)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_watch(self, paused=False):
        started = []

        class Server:
            base = self.base

            def begin_session(self, goal, mode, origin, silent=False):
                started.append((goal, mode, origin, silent))
                return type("S", (), {"id": "sid"})()

        stop = threading.Event()
        with patch("chutku.core.action_control.ActionControl.paused", new=paused), \
                patch.object(scheduled, "_announce"):
            thread = threading.Thread(target=scheduled.watch, args=(Server(), stop, 0.02))
            thread.start()
            time.sleep(0.3)
            stop.set()
            thread.join(2)
        return started

    def test_a_due_task_starts_as_a_normal_request_in_its_own_mode(self):
        job = scheduled.add(self.base, "open notepad", datetime.now() - timedelta(seconds=1), mode="auto_safe",
                            origin="voice")
        self.assertEqual(self.run_watch(), [("open notepad", "auto_safe", "voice", True)])
        self.assertEqual(scheduled.load(self.base)[0]["history"][-1], {"at": scheduled.load(self.base)[0]["history"][-1]["at"],
                                                                       "status": "started", "session": "sid"})
        self.assertEqual(scheduled.load(self.base)[0]["id"], job["id"])

    def test_nothing_starts_while_paused(self):
        scheduled.add(self.base, "open notepad", datetime.now() - timedelta(seconds=1))
        self.assertEqual(self.run_watch(paused=True), [])
        self.assertEqual(len(scheduled.active(self.base)), 1)   # still waiting for resume


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.mind_root = patch.object(mind, "PROJECT_ROOT", self.state)
        self.mind_root.start()
        self.runtime = create_runtime(self.state)

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def test_schedule_list_cancel_through_the_runtime(self):
        at = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
        result = self.runtime.run("task.schedule", {"goal": "send hi to UB", "at": at, "every_minutes": 15})
        self.assertEqual(result["state"], "COMPLETED", result)
        job = scheduled.active(self.state)[0]
        self.assertEqual((job["goal"], job["mode"], job["every_minutes"]), ("send hi to UB", "owner", 15))
        listed = self.runtime.run("task.list", {})
        self.assertEqual(listed["output"]["count"], 1)
        self.assertEqual(self.runtime.run("task.cancel", {"id": job["id"]})["state"], "COMPLETED")
        self.assertEqual(scheduled.active(self.state), [])

    def test_a_delegated_order_keeps_its_mode(self):
        from chutku.tools.schedule_tools import _schedule
        from chutku.tools.registry import ExecutionContext
        context = ExecutionContext("t", None, self.state, autonomy="auto_safe", provenance="delegated_microphone")
        out = _schedule({"goal": "time batao", "in_minutes": 5}, context).output
        self.assertEqual((out["mode"], scheduled.active(self.state)[0]["origin"]), ("auto_safe", "voice"))

    def test_a_task_with_its_own_time_or_from_read_content_is_refused(self):
        at = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
        self.assertEqual(self.runtime.run("task.schedule", {"goal": "har 5 min spotify kholo", "at": at})["state"],
                         "FAILED")
        tool = self.runtime.registry.get("task.schedule")
        with patch.object(self.runtime, "current_capability"):
            clean = self.runtime.authorize(tool, {"goal": "open notepad", "at": at}, provenance="delegated",
                                           autonomy="owner").decision
            tainted = self.runtime.authorize(tool, {"goal": "open notepad", "at": at}, provenance="delegated",
                                             autonomy="owner", tainted=True).decision
        self.assertEqual((clean, tainted), (Decision.ALLOW, Decision.CONFIRM))   # a page can't plant a task

    def test_scheduling_a_tell_me_task_finishes_without_the_model(self):
        from chutku.agent_loop import AgentSession, RuntimeRouter, default_context
        from chutku.quick_intents import QuickPlanner

        class NoModel:
            name = "local"

            def propose(self, *args, **kwargs):
                raise AssertionError("the model must not be asked: the telling happens later")

        router = RuntimeRouter(self.runtime)
        session = AgentSession("har 1 min time batao", mode="owner", context=default_context(router))
        session.quick = QuickPlanner()
        snapshot = session.advance(router, NoModel())
        self.assertEqual(snapshot["status"], "done", snapshot)
        self.assertIn("then every minute", snapshot["reply"])
        self.assertEqual(scheduled.active(self.state)[0]["goal"], "time batao")

    def test_quick_phrases(self):
        steps = {t: quick_proposal(t)["next_steps"][0] for t in (
            "har 15 min Claude chat mein continue bhej do", "scheduled tasks dikhao", "scheduled tasks band karo",
            "cancel scheduled task 3fa2c1")}
        self.assertEqual(steps["har 15 min Claude chat mein continue bhej do"]["tool"], "task.schedule")
        self.assertEqual(steps["scheduled tasks dikhao"]["tool"], "task.list")
        self.assertEqual(steps["scheduled tasks band karo"]["arguments"], {"all": True})
        self.assertEqual(steps["cancel scheduled task 3fa2c1"]["arguments"], {"id": "3fa2c1"})
        self.assertEqual(quick_proposal("remind me in 10 min to stretch")["next_steps"][0]["tool"], "reminder.set")


if __name__ == "__main__":
    unittest.main()
