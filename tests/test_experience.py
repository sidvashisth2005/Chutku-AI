import json
import tempfile
import unittest
from pathlib import Path

from chutku import experience
from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.cloud_planner import cloud_view


def finished(goal, steps, status="done"):
    session = AgentSession(goal, mode="auto_safe")
    session.steps = [{"tool": t, "arguments": a, "purpose": p, "state": state, "verification": "PASS",
                      "task_id": "t", "message": None, "observation": "{}"} for t, a, p, state in steps]
    session.status = status
    return session


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_only_fully_verified_sessions_are_kept_without_sensitive_text(self):
        good = finished("send a whatsapp to ravi saying hello", [
            ("message.send", {"app": "whatsapp", "to": "ravi", "text": "SECRET-TEXT"}, "Send the message", "COMPLETED")])
        bad = finished("delete my notes", [("filesystem.recycle", {"path": "a.txt"}, "Delete", "FAILED")])
        self.assertTrue(experience.record(self.base, good, self.runtime))
        self.assertFalse(experience.record(self.base, bad, self.runtime))
        self.assertFalse(experience.record(self.base, finished("x y", [], status="done"), self.runtime))
        stored = (self.base / "data" / "experience.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("SECRET-TEXT", stored)
        self.assertEqual(len(experience.load(self.base)), 1)

    def test_rule_matched_plans_are_never_saved_as_examples(self):
        # Live 2026-10-04: wrong quick-tier plans ("search X in WhatsApp" -> Google) were saved and reused.
        quick = finished('search for "Pita Shri" in WhatsApp', [
            ("web.search", {"query": "Pita Shri", "site": "google"}, "Search Google", "COMPLETED")])
        quick.planners = [{"planner": "quick"}, {"planner": "quick"}]
        self.assertFalse(experience.record(self.base, quick, self.runtime))
        self.assertEqual(experience.load(self.base), [])

    def test_similar_goals_are_found_and_unrelated_ones_are_not(self):
        experience.record(self.base, finished("open notepad and type hello then save it as note.txt", [
            ("apps.launch", {"name": "Notepad"}, "Open Notepad", "COMPLETED")]), self.runtime)
        self.assertEqual(experience.similar(self.base, "open notepad, type bye and save it as note.txt")[0]["goal"],
                         "open notepad and type hello then save it as note.txt")
        self.assertEqual(experience.similar(self.base, "what is the weather in delhi"), [])

    def test_gemini_sees_the_approach_but_not_argument_values(self):
        session = AgentSession("open notepad", mode="auto_safe", context={"past_successes": [
            {"goal": "open notepad", "similarity": 1.0,
             "steps": [{"tool": "apps.launch", "purpose": "Open it", "arguments": {"name": "PRIVATE-ARG"}}]}]})
        view = json.loads(cloud_view(session, self.runtime))
        self.assertEqual(view["CONTEXT"]["past_successes"][0]["steps"], [{"tool": "apps.launch", "purpose": "Open it"}])
        self.assertNotIn("PRIVATE-ARG", json.dumps(view))


if __name__ == "__main__":
    unittest.main()
