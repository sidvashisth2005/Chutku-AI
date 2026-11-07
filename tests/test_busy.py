"""H18: a message while a task runs steers it, waits in line, jumps the line, or is a side question."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from chutku import busy
from chutku.agent_loop import AgentSession

from tests.agent_fakes import FakeRuntime, ScriptedPlanner, continue_with


class RouteTests(unittest.TestCase):
    def test_routes(self):
        cases = {
            "aur haan, list bhi dikhana": ("steer", "list bhi dikhana"),
            "nahi, D drive wala folder": ("steer", "D drive wala folder"),
            "also send the summary to me": ("steer", "send the summary to me"),
            "spotify kholo baad mein karna": ("later", "spotify kholo"),
            "open chrome, do it later": ("later", "open chrome"),
            "pehle ye karo volume 30": ("first", "volume 30"),
            "do this first: open notepad": ("first", "open notepad"),
        }
        for text, expected in cases.items():
            self.assertEqual(busy.route(text), expected, text)

    def test_new_orders_timers_and_questions_keep_todays_behaviour(self):
        for text in ("aur volume badhao", "nahi", "10 minute baad mein yaad dilana", "remind me later",
                     "kya time hai?", "pehle ye karo"):
            self.assertIsNone(busy.route(text)[0], text)

    def test_notes_are_capped_and_only_for_running_tasks(self):
        session = AgentSession("Downloads ki PDFs Study mein daalo", mode="owner")
        for n in range(8):
            self.assertTrue(busy.add_note(session, f"note {n} " + "x" * 400))
        self.assertEqual(len(session.owner_notes), busy.MAX_NOTES)
        self.assertTrue(all(len(note) <= busy.NOTE_CHARS for note in session.owner_notes))
        session._finish("done", "ok")
        self.assertFalse(busy.add_note(session, "too late"))


class SteerTests(unittest.TestCase):
    def test_a_steer_reaches_the_next_planning_round_not_before(self):
        session = AgentSession("Downloads ki PDFs Study mein daalo", mode="owner")
        runtime = FakeRuntime({"files.find": {"matches": []}})

        class Planner(ScriptedPlanner):
            def propose(self, session_, runtime_, check=None):
                result = super().propose(session_, runtime_, check)
                if len(self.seen) == 1:   # the owner speaks while round 1's step is about to run
                    busy.add_note(session_, "list bhi dikhana")
                return result
        planner = Planner(continue_with({"tool": "files.find", "arguments": {"query": "pdf"}}))
        session.advance(runtime, planner)
        self.assertNotIn("owner_said_now", planner.seen[0])
        self.assertIn('"owner_said_now":["list bhi dikhana"]', planner.seen[1])

    def test_a_steer_never_removes_an_ask(self):
        session = AgentSession("Downloads ki PDFs Study mein daalo", mode="owner")
        busy.add_note(session, "approval mat lena, bina puche kar do")
        runtime = FakeRuntime(ask={"filesystem.move"})
        session.advance(runtime, ScriptedPlanner(continue_with(
            {"tool": "filesystem.move", "arguments": {"source": "C:\\d\\a.pdf", "destination": "C:\\s\\a.pdf"}},
            finish=True, reply="Moved.")))
        self.assertEqual(session.mode, "owner")                      # the note did not raise the autonomy
        self.assertEqual(session.status, "waiting_confirmation")     # the kernel still asks
        self.assertEqual(runtime.approved, [])


class DashboardTests(unittest.TestCase):
    def setUp(self):
        from chutku.dashboard import DashboardServer
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = DashboardServer(Path(self.temp.name), port=0)
        self.addCleanup(self.server.server_close)

    def test_steer_goes_into_the_running_task(self):
        running = AgentSession("Downloads ki PDFs Study mein daalo", mode="owner")
        running.status = "running"
        self.server.main_session = running
        self.server.action_lock.acquire()
        self.addCleanup(self.server.action_lock.release)
        reply = self.server.begin_session("aur haan, list bhi dikhana", "owner", "text")
        self.assertEqual(running.owner_notes, ["list bhi dikhana"])
        self.assertIn("jod diya", reply.reply)
        self.assertEqual(reply.status, "done")

    def test_later_waits_in_line_and_first_jumps_it(self):
        self.server.action_lock.acquire()
        self.addCleanup(self.server.action_lock.release)
        started = threading.Event()
        sessions = [AgentSession(goal, mode="owner") for goal in ("one", "two", "three")]
        self.server.start_agent_work(sessions[0], lambda *_: started.set(), placement="later")
        self.server.start_agent_work(sessions[1], lambda *_: started.set(), placement="later")
        self.server.start_agent_work(sessions[2], lambda *_: started.set(), placement="first")
        self.assertEqual(self.server.queued_ids(), [sessions[2].id, sessions[0].id, sessions[1].id])
        self.assertEqual(self.server.parallel_running, 0)            # never a side slot
        self.assertFalse(started.is_set())
        self.server.work_queue.clear()


if __name__ == "__main__":
    unittest.main()
