import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.cloud_planner import GeminiAgentPlanner, cloud_view, fallback_planner
from chutku.gemini import GeminiUnavailable

SECRET = "PRIVATE-FILE-CONTENT-12345"


def envelope(status="done", steps=(), reply="ok"):
    return {"plan": {"status": status, "reply": reply, "declared_plan": [],
                     "next_steps": [{"tool": t, "arguments_json": json.dumps(a), "purpose": "p"} for t, a in steps]},
            "model": "gemini-test"}


class FailingPlanner:
    name = "local"

    def propose(self, session, runtime, check=None):
        raise ValueError("local model truncated")


class CloudPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_observations_and_sensitive_arguments_never_leave(self):
        session = AgentSession("summarise my notes", mode="auto_safe")
        session.steps.append({"tool": "filesystem.write_text", "arguments": {"path": "a.txt", "content": SECRET},
                              "state": "COMPLETED", "observation": SECRET, "purpose": "p",
                              "verification": "PASS", "task_id": "t", "message": None})
        session.steps.append({"tool": "filesystem.read_text", "arguments": {"path": "a.txt"},
                              "state": "COMPLETED", "observation": json.dumps({"text": SECRET}), "purpose": "p",
                              "verification": "PASS", "task_id": "t", "message": None})
        sent = []
        planner = GeminiAgentPlanner("k" * 30, model="gemini-test",
                                     transport=lambda system, user, schema: (sent.append(system + user), envelope())[1])
        planner.propose(session, self.runtime)
        self.assertNotIn(SECRET, sent[0])
        self.assertIn("a.txt", sent[0])
        self.assertNotIn(SECRET, cloud_view(session, self.runtime))

    def test_public_results_are_shared_but_private_content_is_not(self):
        session = AgentSession("research laptops", mode="auto_safe")
        for tool, observed in (("web.results", "PUBLIC-SEARCH-RESULT"), ("file.extract_text", SECRET),
                               ("clipboard.read_text", SECRET), ("screen.read_text", SECRET)):
            session.steps.append({"tool": tool, "arguments": {}, "state": "COMPLETED", "observation": observed,
                                  "purpose": "p", "verification": "PASS", "task_id": "t", "message": None})
        view = cloud_view(session, self.runtime)
        self.assertIn("PUBLIC-SEARCH-RESULT", view)
        self.assertNotIn(SECRET, view)

    def test_fallback_used_when_local_fails_and_output_is_validated(self):
        cloud = GeminiAgentPlanner("k" * 30, model="gemini-test",
                                   transport=lambda *a: envelope("continue", [("system.get_time", {})]))
        # after the step, the scripted cloud says done
        responses = iter([envelope("continue", [("system.get_time", {})]), envelope("done", reply="time shown")])
        cloud.transport = lambda *a: next(responses)
        snap = AgentSession("time?", mode="auto_safe").advance(self.runtime, FailingPlanner(), fallback=cloud)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["planners"][0]["planner"], "gemini")
        self.assertEqual([s["tool"] for s in snap["steps"]], ["system.get_time"])

    def test_cloud_cannot_propose_unknown_tools_or_bad_arguments(self):
        for bad in (envelope("continue", [("shell.run", {"cmd": "del"})]),
                    envelope("continue", [("filesystem.write_text", {"path": "x", "content": "y", "extra": 1})]),
                    {"plan": {"status": "continue", "reply": "", "declared_plan": [],
                              "next_steps": [{"tool": "system.get_time", "arguments_json": "{not json",
                                              "purpose": "p"}]}}):
            cloud = GeminiAgentPlanner("k" * 30, model="gemini-test", transport=lambda *a, b=bad: b)
            snap = AgentSession("x", mode="auto_edits").advance(self.runtime, FailingPlanner(), fallback=cloud)
            self.assertEqual(snap["status"], "clarify")
            self.assertEqual(snap["steps"], [])

    def test_outage_or_quota_degrades_to_local_clarification(self):
        def down(*_):
            raise GeminiUnavailable("Gemini unavailable (quota exhausted); local planning only.")
        cloud = GeminiAgentPlanner("k" * 30, model="gemini-test", transport=down)
        snap = AgentSession("x", mode="auto_safe").advance(self.runtime, FailingPlanner(), fallback=cloud)
        self.assertEqual(snap["status"], "failed")   # 2026-11-08 review: a brain outage is not "needs more detail"
        self.assertIn("free AI limit is used up", snap["reply"])

    def test_disabled_without_capability_or_key(self):
        base = Path(self.temp.name)
        with patch("chutku.cloud_planner.api_key", return_value="k" * 30):
            self.assertIsNone(fallback_planner(base))
            self.runtime.capability_grants.grant("cloud.gemini")
            self.assertIsNotNone(fallback_planner(base))
        with patch("chutku.cloud_planner.api_key", return_value=None):
            self.assertIsNone(fallback_planner(base))


class ModelChoiceTests(unittest.TestCase):
    def test_newest_stable_model_is_chosen_and_special_models_skipped(self):
        from chutku import gemini
        names = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.1-pro-preview", "gemini-3.8-flash",
                 "gemini-3.8-flash-tts", "gemini-3.8-flash-lite", "gemini-embedding-001", "gemini-3.8-pro"]
        with patch.object(gemini, "available_models", return_value=names), patch.dict("os.environ", {}, clear=False):
            gemini._chosen.clear()
            self.assertEqual(gemini.ranked_models("k" * 30, "code")[0], "gemini-3.8-pro")  # same version: Pro wins
            # planning uses lite models first: the free tier gives the big ones ~20 requests a day
            self.assertEqual(gemini.ranked_models("k" * 30, "plan")[0], "gemini-3.8-flash-lite")
            self.assertEqual(gemini.ranked_models("k" * 30, "plan")[1], "gemini-3.8-flash")
            gemini._chosen.clear()
        with patch.object(gemini, "available_models", return_value=names[:4]):
            self.assertEqual(gemini.ranked_models("j" * 30, "code")[0], "gemini-3.8-flash")  # newer beats older Pro
            gemini._chosen.clear()


if __name__ == "__main__":
    unittest.main()
