from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.agent_execution import AgentExecutionStore
from chutku.app import create_runtime
from chutku.brain import validate_tool_plan
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


class AgentExecutionTests(unittest.TestCase):
    def plan(self, runtime, steps):
        return validate_tool_plan({"reply": "Prepared.", "steps": steps,
                                   "needs_clarification": False}, runtime)

    def test_reviewed_low_risk_plan_runs_in_exact_order(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            plan = self.plan(runtime, [
                {"tool": "filesystem.create_directory", "arguments": {"path": "notes"},
                 "purpose": "Create the requested folder"},
                {"tool": "filesystem.write_text", "arguments": {"path": "notes/item.txt", "content": "ready"},
                 "purpose": "Write the requested text"},
            ])
            store = AgentExecutionStore()
            token = store.prepare(plan, runtime, provenance="reviewed_inferred")
            result = store.start(token, runtime)
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual([row["tool"] for row in result["plan_steps"]],
                             ["filesystem.create_directory", "filesystem.write_text"])
            self.assertEqual((runtime.granted_root / "notes/item.txt").read_text(), "ready")

    def test_high_risk_step_pauses_for_separate_decision_and_cancel_fails_closed(self):
        effects = []
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.registry.register(Tool("test.external", "External fixture", Risk.EXTERNAL_SIDE_EFFECT,
                lambda arguments, context: (effects.append("ran") or ToolResult({}, Verification.PASS)),
                argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable"))
            plan = self.plan(runtime, [{"tool": "test.external", "arguments": {},
                                        "purpose": "Exercise an external effect"}])
            store = AgentExecutionStore()
            token = store.prepare(plan, runtime, provenance="reviewed_inferred")
            waiting = store.start(token, runtime)
            self.assertEqual(waiting["state"], "WAITING_CONFIRMATION")
            self.assertEqual(effects, [])
            denied = store.decide(token, runtime, approve=False)
            self.assertEqual(denied["state"], "FAILED")
            self.assertEqual(effects, [])

            token = store.prepare(plan, runtime, provenance="reviewed_inferred")
            self.assertEqual(store.start(token, runtime)["state"], "WAITING_CONFIRMATION")
            completed = store.decide(token, runtime, approve=True)
            self.assertEqual(completed["state"], "COMPLETED")
            self.assertEqual(effects, ["ran"])

    def test_server_copy_is_immutable_and_manifest_change_refuses_execution(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            plan = self.plan(runtime, [{"tool": "system.get_time", "arguments": {},
                                        "purpose": "Read time"}])
            store = AgentExecutionStore()
            token = store.prepare(plan, runtime, provenance="reviewed_microphone")
            plan["steps"][0]["tool"] = "system.environment"
            self.assertEqual(store.start(token, runtime)["state"], "COMPLETED")

            plan = self.plan(runtime, [{"tool": "system.get_time", "arguments": {},
                                        "purpose": "Read time"}])
            token = store.prepare(plan, runtime, provenance="reviewed_inferred")
            original = runtime.registry.get("system.get_time")
            runtime.registry._tools["system.get_time"] = Tool(
                original.name, "Changed contract", original.base_risk, original.execute,
                argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable")
            with self.assertRaisesRegex(ValueError, "catalog|contract"):
                store.start(token, runtime)


if __name__ == "__main__":
    unittest.main()
