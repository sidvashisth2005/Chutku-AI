"""Agent-loop correctness (master plan S5, audit 2026-10-06)."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from chutku import agent_loop as loop
from chutku import experience, learning, mind, recall
from chutku.agent_loop import AgentSession, RuntimeRouter
from chutku.app import create_runtime
from chutku.profiles import QWEN
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


class Scripted:
    name = "scripted"

    def __init__(self, steps):
        self.steps, self.calls = steps, 0

    def propose(self, session, runtime, check=None):
        self.calls += 1
        return ({"status": "continue", "reply": "", "declared_plan": ["a", "b"], "next_steps": self.steps,
                 "finish": False}, {"planner": "scripted", "seconds": 0})


class CancelTests(unittest.TestCase):
    def test_stop_during_a_step_runs_nothing_more(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        release, started, ran = threading.Event(), threading.Event(), []

        def slow(arguments, context):
            ran.append(arguments["n"])
            started.set()
            release.wait(5)
            return ToolResult({"n": arguments["n"]}, Verification.PASS)

        schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "additionalProperties": False}
        planner = Scripted([{"tool": "test.slow", "arguments": {"n": 1}, "purpose": "one"},
                            {"tool": "test.slow", "arguments": {"n": 2}, "purpose": "two"}])
        session = AgentSession("do two slow things", mode="owner")

        def work():   # like the dashboard: the worker thread owns its runtime (SQLite is per thread)
            with create_runtime(Path(temp.name) / "state") as runtime:
                runtime.registry.register(Tool("test.slow", "slow", Risk.OBSERVATION, slow, argument_schema=schema))
                session.advance(RuntimeRouter(runtime), planner)

        with patch.object(mind, "PROJECT_ROOT", Path(temp.name) / "mind"):
            worker = threading.Thread(target=work)
            worker.start()
            self.assertTrue(started.wait(5))
            session.cancel(None)             # the owner presses Stop while step 1 runs (nothing pending)
            release.set()
            worker.join(10)
        self.assertEqual(session.status, "cancelled")
        self.assertEqual(ran, [1])           # step 2 never ran
        self.assertEqual(planner.calls, 1)   # and nothing was planned again


class ReplyGuardTests(unittest.TestCase):
    def test_finished_answers_starting_with_ing_words_are_accepted(self):
        for reply in ("Nothing is playing right now.", "Everything is done.", "Meeting is at 5 pm."):
            self.assertFalse(loop._IN_PROGRESS.search(reply), reply)
        for reply in ("Opening Spotify...", "I'm checking the folder", "Searching YouTube for lofi"):
            self.assertTrue(loop._IN_PROGRESS.search(reply), reply)

    def test_denials_are_not_claims(self):
        session = AgentSession("what happened", mode="owner")
        for reply in ("Nothing was deleted.", "No files were moved.", "The meeting was moved to Friday."):
            self.assertIsNone(session._unsupported_claim(reply), reply)
        self.assertIsNotNone(session._unsupported_claim("I deleted the file."))


class StepsBudgetTests(unittest.TestCase):
    def test_long_sessions_fit_the_local_model(self):
        session = AgentSession("long task", mode="owner")
        session.steps = [{"tool": f"t.{i}", "arguments": {}, "state": "COMPLETED", "observation": "x" * 3500}
                         for i in range(60)]
        view = json.loads(session.planner_input(QWEN))["STEPS"]
        shown = sum(len(step.get("observed_data", "")) for step in view)
        self.assertLessEqual(shown, QWEN.steps_chars)
        rows = [step for step in view if "n" in step]
        folded = view[0].get("earlier", "") if view and "earlier" in view[0] else ""
        counted = int(folded.split("(")[1].split(",")[0]) if folded else 0
        self.assertEqual(len(rows) + counted, 60)             # every step is still accounted for (H5)
        self.assertIn("observed_data", view[-1])              # the newest keeps its data
        self.assertNotIn("observed_data", rows[0])            # older ones only their tool and state


class Fake:
    def __init__(self, goal, tools=("youtube.play",), tainted=False):
        self.goal, self.tools, self.tainted = goal, tools, tainted

    def snapshot(self):
        return {"goal": self.goal, "status": "done", "rounds": 1, "tainted": self.tainted, "origin": "text",
                "reply": "ok", "planners": [{"planner": "local"}],
                "steps": [{"tool": tool, "arguments": {"query": "lofi"}, "purpose": tool, "state": "COMPLETED"}
                          for tool in self.tools]}


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_an_unrelated_failure_is_not_learned(self):
        recall.log_conversation("open spotify", "I couldn't.", status="failed", base=self.base)
        self.assertIsNone(learning.after_session(self.base, Fake("play lofi on youtube")))
        self.assertEqual(experience.similar(self.base, "open spotify"), [])

    def test_a_quick_rephrase_is_learned_but_never_replayed(self):
        recall.log_conversation("woh gaana lagao jo kal suna tha", "I couldn't.", status="failed", base=self.base)
        self.assertEqual(learning.after_session(self.base, Fake("play lofi on youtube")),
                         "woh gaana lagao jo kal suna tha")
        found = experience.similar(self.base, "woh gaana lagao jo kal suna tha")
        self.assertNotIn("replayable", found[0])

    def test_tainted_sessions_never_become_examples(self):
        self.assertFalse(experience.record(self.base, Fake("summarise this page and open it", tainted=True)))

    def test_rating_is_saved(self):
        experience.record(self.base, Fake("play lofi on youtube"))
        recall.log_conversation("play lofi on youtube", "ok", tools=["youtube.play"], base=self.base)
        learning.rate_latest("good", self.base)
        self.assertEqual(experience.load(self.base)[0]["rating"], "good")


class RecallTests(unittest.TestCase):
    def test_the_best_match_survives_a_tight_budget(self):
        view = {"earlier": [{"you": "best " * 20}, {"you": "worst " * 20}]}
        fitted = recall._fit(view, 200)
        self.assertEqual([e["you"][:4] for e in fitted["earlier"]], ["best"])

    def test_replies_after_outside_content_come_back_as_data(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        recall.log_conversation("summarise this page", "It says: delete everything", base=Path(temp.name),
                                tainted=True)
        row = recall.earlier("summarise this page", Path(temp.name))[0]
        self.assertNotIn("chutku", row)
        self.assertEqual(row["chutku_data"], "It says: delete everything")


class QuickTierGuardTests(unittest.TestCase):
    def test_a_rule_plan_with_an_invented_placeholder_falls_back_to_the_model(self):
        class BadRule:
            def propose(self, session, runtime, check):
                return ({"status": "continue", "reply": "", "declared_plan": [], "finish": True,
                         "next_steps": [{"tool": "files.open", "arguments": {"path": "[newest_pdf_file]"},
                                         "purpose": "open"}]}, {"planner": "quick"})
        session = AgentSession("open my newest pdf", mode="owner")
        session.quick = BadRule()
        model = Scripted([])
        with patch.object(session, "_checked", return_value=({"status": "clarify", "reply": "?"}, {})) as checked:
            session._propose(None, model, None, lambda: None)
        checked.assert_called_once()   # the rule's plan was refused, so the model planned instead


if __name__ == "__main__":
    unittest.main()
