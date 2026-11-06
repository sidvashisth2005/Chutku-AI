"""Y3 (2026-11-06): one Live conversation runs several tasks side by side, and each one's result is reported.

Owner: "it still can't do multiple tasks simultaneously" and "Gemini says done while it still runs, or it is done and
Gemini is unaware"."""
import threading
import time
import types
import unittest
from unittest.mock import patch

from chutku.voice import heard
from chutku.voice.live import MAX_TASKS, PERSONA, LiveConversation
from tests.test_heard import chunk


class Session:
    def __init__(self, session_id, goal):
        self.id, self.goal, self.status, self.reply = session_id, goal, "running", ""

    def snapshot(self):
        return {"id": self.id, "goal": self.goal, "status": self.status, "reply": self.reply, "steps": [],
                "pending": None}


class Server:
    def __init__(self):
        self.sessions, self.stopped = {}, []
        self.agent_sessions = types.SimpleNamespace(get=lambda session_id: self.sessions[session_id])

    def live_task(self, goal):
        session = Session(f"s{len(self.sessions) + 1}", goal)
        self.sessions[session.id] = session
        return session

    def stop_session(self, session_id):
        self.stopped.append(session_id)
        self.sessions[session_id].status = "cancelled"

    def live_event(self, *_):
        pass


class LiveParallelTests(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.live = LiveConversation(self.server, "key", audio=False)
        self.live.active.set()
        self.injected = []
        self.live.inject = self.injected.append
        patcher = patch.object(heard, "log_heard", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.live.active.clear)   # the followers end with the conversation

    def order(self, words, goal):
        for level in [0.001] * 20 + [0.2] * int(1.0 / self.live.gate.chunk_seconds):   # a pause, then speech
            self.live.gate.feed(chunk(level))
        self.live.heard_since_task = words
        return self.live.dispatch("do_task", {"goal": goal})

    def wait_for(self, text):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(text in item for item in self.injected):
                return next(item for item in self.injected if text in item)
            time.sleep(0.05)
        self.fail(f"no update with {text!r}: {self.injected}")

    def test_a_second_order_starts_while_the_first_runs_and_each_result_is_reported(self):
        started = time.perf_counter()
        self.assertEqual(self.order("spotify chalao", "open spotify")["status"], "started")
        self.assertEqual(self.order("aur notepad bhi kholo", "open notepad")["status"], "started")
        self.assertEqual([s.goal for s in self.server.sessions.values()], ["open spotify", "open notepad"])

        # The OLDER task finishes while the newer one still runs: it is still reported, naming what still runs.
        self.server.sessions["s1"].status, self.server.sessions["s1"].reply = "done", "Spotify is open."
        update = self.wait_for("'open spotify' finished with status done")
        self.assertIn("Still running: open notepad", update)
        self.server.sessions["s2"].status, self.server.sessions["s2"].reply = "failed", "Notepad did not open."
        update = self.wait_for("'open notepad' finished with status failed")
        self.assertIn("Nothing else is running", update)
        print(f"\n[Y3 live] two side-by-side tasks reported in {time.perf_counter() - started:.2f}s")

    def test_at_most_max_tasks_run_and_stop_stops_them_all(self):
        for index in range(MAX_TASKS):
            self.assertEqual(self.order(f"kaam number {index} karo", f"task number {index}")["status"], "started")
        refused = self.order("ek aur kaam karo", "one more task")
        self.assertIn("already running", refused["error"])       # negative case: the cap holds
        self.assertEqual(len(self.server.sessions), MAX_TASKS)
        stopped = self.live.dispatch("stop_task", {})
        self.assertEqual((stopped["status"], self.server.stopped), ("stopped", ["s1", "s2", "s3"]))
        self.assertEqual(self.live.dispatch("task_status", {})["tasks"][0]["status"], "cancelled")

    def test_a_done_claim_is_corrected_while_the_newest_task_still_runs(self):
        self.order("spotify chalao", "open spotify")
        self.live.said_this_turn = "Ho gaya, Spotify khul gaya!"
        self.assertIsNotNone(self.live._claimed_success())         # nothing is done yet: corrected
        self.server.sessions["s1"].status = "done"
        self.wait_for("finished with status done")
        self.order("notepad kholo", "open notepad")
        # A claim right after a new task started is corrected again (the done update came before it).
        self.assertIsNotNone(self.live._claimed_success())

    def test_an_approval_answers_the_task_that_is_waiting(self):
        confirmed = []
        self.server.confirm_session = lambda session_id, approve: confirmed.append((session_id, approve))
        self.order("spotify chalao", "open spotify")
        self.order("mummy ko hi bhejo", "send hi to mummy on whatsapp")
        self.server.sessions["s1"].status = "waiting_confirmation"   # the OLDER task asks
        self.live.speech_at_question = 0.0
        self.live.heard_since_question = " haan"
        self.assertEqual(self.live.dispatch("answer_approval", {"approve": True})["status"], "approved")
        self.assertEqual(confirmed, [("s1", True)])

    def test_the_voice_model_is_told_tasks_can_run_together(self):
        self.assertIn("Several tasks can run at the same time", PERSONA)
        self.assertIn("never say both cannot be done together", PERSONA)


if __name__ == "__main__":
    unittest.main()
