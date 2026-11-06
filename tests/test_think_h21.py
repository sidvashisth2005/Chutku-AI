"""H21: "dhyan se socho" / "soch ke batao" gives this one request the strongest brain with its full budget."""
import unittest
import unittest.mock

from chutku.agent_loop import AgentSession
from chutku.cloud_planner import CloudAgentPlanner, GeminiAgentPlanner
from chutku.intents.tone import thinks
from tests import test_dashboard as _harness
from tests.test_dashboard_agent import Scripted, proposal


class ThinkTests(unittest.TestCase):
    setUp, tearDown = _harness.DashboardTests.setUp, _harness.DashboardTests.tearDown

    def test_the_phrases_and_only_this_request(self):
        for said in ("dhyan se socho, kaunsa laptop lun", "soch ke batao", "think carefully about this"):
            self.assertTrue(thinks(said), said)
        for said in ("what time is it", "dhyan se file delete karna", "socho mat"):
            self.assertFalse(thinks(said), said)
        self.server.planner_factory = lambda: (Scripted(proposal("done", reply="ok")), None)
        careful = self.server.begin_session("soch ke batao kaunsa phone lun", "owner", "text")
        plain = self.server.begin_session("kaunsa phone lun", "owner", "text")
        self.assertEqual((careful.think, plain.think), (True, False))
        import time
        deadline = time.monotonic() + 10   # let both workers finish before the temporary folder goes
        while time.monotonic() < deadline and (self.server.parallel_running or self.server.action_lock.locked()
                                                or {careful.status, plain.status} - {"done", "clarify", "failed"}):
            time.sleep(0.05)

    def test_a_careful_request_goes_to_gemini_with_the_full_budget(self):
        calls = []

        def transport(system, user, schema):
            calls.append(schema)
            return {"plan": {"status": "done", "reply": "Pixel lo.", "declared_plan": [], "next_steps": [],
                             "finish": True}, "model": "gemini-test"}
        gemini = GeminiAgentPlanner("k" * 30, transport=transport, fast=True)
        planner = CloudAgentPlanner(gemini=gemini, transport=lambda *a, **k: self.fail("fast models not used"))
        session = AgentSession("soch ke batao kaunsa phone lun", mode="owner")
        session.think = True
        from chutku.app import create_runtime
        with create_runtime(self.base / "rt") as runtime:
            result, meta = planner.propose(session, runtime)
        self.assertEqual((result["reply"], meta["planner"]), ("Pixel lo.", "gemini:careful"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(gemini.fast)                     # the shared planner is untouched for other requests


class CarefulFallbackTests(unittest.TestCase):
    def test_when_careful_gemini_fails_the_fast_cloud_models_answer_not_the_local_one(self):
        """Live 2026-11-07: the careful call failed and the request fell to the local model (32 s)."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from chutku.app import create_runtime
        from chutku.gemini import GeminiUnavailable

        def broken(*_args):
            raise GeminiUnavailable("quota")
        gemini = GeminiAgentPlanner("k" * 30, transport=broken, fast=True)
        planner = CloudAgentPlanner(gemini=gemini)
        session = AgentSession("soch ke batao", mode="owner")
        session.think = True
        reply = {"status": "done", "reply": "391", "declared_plan": [], "next_steps": [], "finish": True}
        answer = (reply, {"provider": "groq", "model": "m", "seconds": 0.5})
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime, \
                unittest.mock.patch("chutku.providers.ask", lambda *a, **k: answer):
            result, meta = planner.propose(session, runtime)
        self.assertEqual((result["reply"], meta["planner"]), ("391", "cloud:groq"))


if __name__ == "__main__":
    unittest.main()
