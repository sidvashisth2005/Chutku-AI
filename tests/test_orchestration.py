from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.app import create_runtime
from chutku.orchestration import OrchestrationCoordinator, build_orchestration, run_orchestration
from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification


class OrchestrationTests(unittest.TestCase):
    def runtime(self, temp, effects):
        runtime = create_runtime(Path(temp))
        def add(name, risk, effect, reversibility="compensatable"):
            runtime.registry.register(Tool(name, name, risk,
                lambda a, c, e=effect: (effects.append(e) or ToolResult({}, Verification.FAIL if e == "fail" else Verification.PASS)),
                argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility=reversibility))
        add("test.open", Risk.REVERSIBLE, "open"); add("test.close", Risk.EXTERNAL_SIDE_EFFECT, "close", "not_applicable")
        add("test.fail", Risk.OBSERVATION, "fail", "not_applicable"); add("test.observe", Risk.OBSERVATION, "observe", "not_applicable")
        return runtime

    def test_failure_recovers_completed_steps_in_reverse_with_approval(self):
        effects=[]
        with TemporaryDirectory() as temp, self.runtime(temp,effects) as runtime:
            plan=build_orchestration([
                {"tool":"test.open","arguments":{},"compensation":{"tool":"test.close","arguments":{}}},
                {"tool":"test.fail","arguments":{},"compensation":None}],runtime)
            result=run_orchestration(plan,runtime,approve=lambda approval: True)
            self.assertEqual(result["state"],"FAILED"); self.assertTrue(result["recovered"])
            self.assertEqual(effects,["open","fail","close"])

    def test_denied_recovery_is_reported_not_hidden(self):
        effects=[]
        with TemporaryDirectory() as temp, self.runtime(temp,effects) as runtime:
            plan=build_orchestration([
                {"tool":"test.open","arguments":{},"compensation":{"tool":"test.close","arguments":{}}},
                {"tool":"test.fail","arguments":{},"compensation":None}],runtime)
            result=run_orchestration(plan,runtime,approve=lambda approval: False)
            self.assertFalse(result["recovered"]); self.assertEqual(result["recovery"][0]["state"],"DENIED")

    def test_manifest_change_and_missing_compensation_fail_closed(self):
        effects=[]
        with TemporaryDirectory() as temp, self.runtime(temp,effects) as runtime:
            with self.assertRaises(ValueError):
                build_orchestration([{"tool":"test.open","arguments":{},"compensation":None}],runtime)
            plan=build_orchestration([{"tool":"test.observe","arguments":{},"compensation":None}],runtime)
            plan["steps"][0]["manifest_version"]="sha256:changed"
            result=run_orchestration(plan,runtime)
            self.assertEqual(result["state"],"FAILED"); self.assertEqual(effects,[])

    def test_success_runs_exact_reviewed_order(self):
        effects=[]
        with TemporaryDirectory() as temp, self.runtime(temp,effects) as runtime:
            plan=build_orchestration([{"tool":"test.observe","arguments":{},"compensation":None}],runtime)
            result=run_orchestration(plan,runtime)
            self.assertEqual(result["state"],"COMPLETED"); self.assertEqual(effects,["observe"])

    def test_server_owned_token_is_single_use_and_preview_tampering_has_no_effect(self):
        effects=[]
        with TemporaryDirectory() as temp, self.runtime(temp,effects) as runtime:
            coordinator=OrchestrationCoordinator(runtime)
            prepared=coordinator.prepare([{"tool":"test.observe","arguments":{},"compensation":None}])
            prepared["plan"]["steps"][0]["tool"]="test.fail"
            result=coordinator.execute(prepared["token"])
            self.assertEqual(result["state"],"COMPLETED"); self.assertEqual(effects,["observe"])
            with self.assertRaises(ValueError): coordinator.execute(prepared["token"])

if __name__=="__main__": unittest.main()
