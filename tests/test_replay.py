"""Exact repeats of a request that fully worked reuse the plan without the local model (2026-10-05)."""
import tempfile
import unittest
from pathlib import Path

from chutku import experience
from chutku.agent_loop import AgentSession
from chutku.app import create_runtime


class Done:
    def __init__(self, goal, steps, rounds=1):
        self.goal, self.steps, self.rounds = goal, steps, rounds

    def snapshot(self):
        return {"goal": self.goal, "status": "done", "rounds": self.rounds, "planners": [{"planner": "local"}],
                "steps": [{"tool": t, "purpose": t, "arguments": a, "state": "COMPLETED"} for t, a in self.steps]}


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def session(self, goal, **extra):
        session = AgentSession(goal, mode="owner",
                               context={"past_successes": experience.similar(self.base, goal)})
        for key, value in extra.items():
            setattr(session, key, value)
        return session

    def test_exact_repeat_of_a_one_round_action_plan_is_replayed(self):
        experience.record(self.base, Done("Open Calculator and Notepad", [("apps.launch", {"name": "Calculator"}),
                                                                          ("apps.launch", {"name": "Notepad"})]))
        proposal, meta = self.session("open calculator and notepad please")._replay(self.runtime)
        self.assertEqual(meta["planner"], "replay")
        self.assertEqual([s["arguments"]["name"] for s in proposal["next_steps"]], ["Calculator", "Notepad"])
        self.assertTrue(proposal["finish"])

    def test_no_replay_when_unsafe_or_not_an_exact_repeat(self):
        experience.record(self.base, Done("open calculator", [("apps.launch", {"name": "Calculator"})]))
        experience.record(self.base, Done("find my newest pdf", [("files.find", {"query": "pdf"})], rounds=2))
        experience.record(self.base, Done("delete old.txt", [("filesystem.recycle", {"path": "D:\\old.txt"})]))
        self.assertIsNone(self.session("open calculator now")._replay(self.runtime))      # not exact
        self.assertIsNone(self.session("find my newest pdf")._replay(self.runtime))       # depended on results
        self.assertIsNone(self.session("delete old.txt")._replay(self.runtime))           # not reversible
        self.assertIsNone(self.session("open calculator", cloud_first=True)._replay(self.runtime))   # Gemini-led

    def test_a_bad_rating_stops_the_replay(self):
        experience.record(self.base, Done("open calculator", [("apps.launch", {"name": "Calculator"})]))
        rows = experience.load(self.base)
        rows[0]["rating"] = "bad"
        experience.save_rows(self.base, rows)
        self.assertIsNone(self.session("open calculator")._replay(self.runtime))

    def test_sensitive_arguments_make_a_plan_not_replayable(self):
        experience.record(self.base, Done("tell mammi hi", [("message.send", {"to": "mammi", "text": "hi"})]),
                          self.runtime)
        self.assertNotIn("replayable", experience.similar(self.base, "tell mammi hi")[0])


if __name__ == "__main__":
    unittest.main()
