"""Fewer approvals (owner order 2026-10-08): a step the owner approved is not asked again in the same request,
and a step that failed or could not be confirmed is not repeated — the planner is told to try another way."""
import tempfile
import unittest
from pathlib import Path

from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.tools.registry import Risk, Tool, ToolResult, Verification
from tests.test_agent_loop import SCHEMA, ScriptedPlanner, proposal, step


class FewerAsksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.effects = []
        self.runtime.registry.register(Tool("test.send", "send", Risk.EXTERNAL_SIDE_EFFECT,
            lambda a, c: (self.effects.append("send"), ToolResult({}, Verification.PASS))[1],
            argument_schema=SCHEMA, runs_code=True))   # runs_code: asks in every mode
        self.runtime.registry.register(Tool("test.flaky", "flaky", Risk.REVERSIBLE,
            lambda a, c: (self.effects.append("flaky"), ToolResult({}, Verification.UNKNOWN))[1],
            argument_schema=SCHEMA))
        self.runtime.registry.register(Tool("test.other", "other way", Risk.REVERSIBLE,
            lambda a, c: (self.effects.append("other"), ToolResult({"ok": True}, Verification.PASS))[1],
            argument_schema=SCHEMA))

    def tearDown(self):
        self.tearDown_approvals()
        self.runtime.close()
        self.temp.cleanup()

    def tearDown_approvals(self):
        import chutku.agent_loop as loop
        loop._RECENT_APPROVALS.clear()

    def test_an_approved_step_is_not_asked_again_by_the_next_request(self):
        self.addCleanup(self.tearDown_approvals)
        first = AgentSession("send it", mode="owner")
        snap = first.advance(self.runtime, ScriptedPlanner(proposal(steps=[step("test.send")])))
        self.assertEqual(snap["status"], "waiting_confirmation")      # the first one asks
        first.decide(self.runtime, approve=True)
        again = AgentSession("send it", mode="owner")                  # the voice side re-sends the same task
        snap = again.advance(self.runtime, ScriptedPlanner(proposal(steps=[step("test.send")]),
                                                           proposal("done", reply="Finished.")))
        self.assertEqual(self.effects, ["send", "send"])                # ran without a second ask
        self.assertEqual(snap["status"], "done")
        self.runtime.registry.register(Tool("test.send2", "send elsewhere", Risk.EXTERNAL_SIDE_EFFECT,
            lambda a, c: ToolResult({}, Verification.PASS), argument_schema=SCHEMA, runs_code=True))
        other = AgentSession("send other", mode="owner")               # a different step still asks
        snap = other.advance(self.runtime, ScriptedPlanner(proposal(steps=[step("test.send2")])))
        self.assertEqual(snap["status"], "waiting_confirmation")

    def test_approval_memory_expires_and_skips_power_and_deletes(self):
        import chutku.agent_loop as loop
        self.addCleanup(self.tearDown_approvals)
        root = self.runtime.control_root
        loop.remember_approval(root, step("test.send"), now=1000.0)
        self.assertIn(("test.send", "{}"), loop.recent_approvals(root, now=1000.0 + 599))
        self.assertEqual(loop.recent_approvals("elsewhere", now=1000.0 + 599), set())   # another Chutku: separate
        self.assertEqual(loop.recent_approvals(root, now=1000.0 + 601), set())
        self.runtime.registry.register(Tool("test.kill", "kill", Risk.DESTRUCTIVE_OR_PRIVILEGED,
            lambda a, c: ToolResult({}, Verification.PASS), argument_schema=SCHEMA))
        session = AgentSession("kill it", mode="owner")
        session.advance(self.runtime, ScriptedPlanner(proposal(steps=[step("test.kill")])))
        session.decide(self.runtime, approve=True)
        self.assertNotIn(("test.kill", "{}"), loop.recent_approvals(root))   # R4 always asks again

    def test_a_cancelled_step_is_not_remembered_as_approved(self):
        planner = ScriptedPlanner(proposal(steps=[step("test.send")]))
        session = AgentSession("send it", mode="owner")
        session.advance(self.runtime, planner)
        session.decide(self.runtime, approve=False)
        self.assertEqual(session.approved_calls, set())

    def test_a_failed_step_is_replanned_another_way(self):
        planner = ScriptedPlanner(proposal(steps=[step("test.flaky")]),
                                  proposal(steps=[step("test.flaky")]),      # repeated: refused, planner nudged
                                  proposal(steps=[step("test.other")]),      # a different way
                                  proposal("done", reply="Done the other way."))
        snap = AgentSession("do the thing", mode="owner").advance(self.runtime, planner)
        self.assertEqual(self.effects, ["flaky", "other"])
        self.assertEqual(snap["status"], "done")
        self.assertIn("already failed or could not be confirmed", planner.inputs[2])   # the feedback it got


if __name__ == "__main__":
    unittest.main()
