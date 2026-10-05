import tempfile
import unittest
from pathlib import Path

from chutku.policy.kernel import AutonomyMode, Decision, PolicyKernel
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


def tool(risk, reversibility="none", name="test.tool"):
    return Tool(name, "test", risk, lambda a, c: ToolResult({}, Verification.PASS),
                argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
                reversibility=reversibility)


class AutonomyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.kernel = PolicyKernel()

    def decide(self, risk, mode, reversibility="none", tainted=False, confirmed=False, provenance="delegated"):
        return self.kernel.authorize(tool(risk, reversibility), {}, confirmed, provenance=provenance,
                                     autonomy=mode, tainted=tainted).decision

    def test_review_mode_confirms_every_step(self):
        for risk in (Risk.OBSERVATION, Risk.REVERSIBLE, Risk.DATA_MODIFICATION):
            self.assertEqual(self.decide(risk, "review", "journaled"), Decision.CONFIRM)

    def test_auto_safe_allows_only_up_to_r1(self):
        self.assertEqual(self.decide(Risk.OBSERVATION, "auto_safe"), Decision.ALLOW)
        self.assertEqual(self.decide(Risk.REVERSIBLE, "auto_safe"), Decision.ALLOW)
        self.assertEqual(self.decide(Risk.DATA_MODIFICATION, "auto_safe", "journaled"), Decision.CONFIRM)

    def test_auto_edits_allows_only_undoable_r2(self):
        self.assertEqual(self.decide(Risk.DATA_MODIFICATION, "auto_edits", "journaled"), Decision.ALLOW)
        self.assertEqual(self.decide(Risk.DATA_MODIFICATION, "auto_edits", "compensatable"), Decision.ALLOW)
        self.assertEqual(self.decide(Risk.DATA_MODIFICATION, "auto_edits", "irreversible"), Decision.CONFIRM)
        self.assertEqual(self.decide(Risk.DATA_MODIFICATION, "auto_edits", "none"), Decision.CONFIRM)

    def test_r3_and_r4_confirm_and_r5_denies(self):
        for mode in AutonomyMode:
            # Owner mode (the owner's standing order, 2026-10-04) runs R3 by itself; see test_owner_mode.
            r3 = Decision.ALLOW if mode == AutonomyMode.OWNER else Decision.CONFIRM
            self.assertEqual(self.decide(Risk.EXTERNAL_SIDE_EFFECT, mode.value, "journaled"), r3, mode)
            self.assertEqual(self.decide(Risk.DESTRUCTIVE_OR_PRIVILEGED, mode.value, "journaled"), Decision.CONFIRM)
            self.assertEqual(self.decide(Risk.DISABLED, mode.value, confirmed=True), Decision.DENY)

    def test_deletes_ask_first_in_every_mode_and_for_typed_commands(self):
        delete = Tool("test.delete", "delete", Risk.DATA_MODIFICATION, lambda a, c: ToolResult({}, Verification.PASS),
                      argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
                      reversibility="journaled", deletes=True)
        for mode in AutonomyMode:
            self.assertEqual(self.kernel.authorize(delete, {}, False, provenance="delegated", autonomy=mode.value,
                                                   tainted=False).decision, Decision.CONFIRM, mode)
        self.assertEqual(self.kernel.authorize(delete, {}, False).decision, Decision.CONFIRM)
        self.assertEqual(self.kernel.authorize(delete, {}, True).decision, Decision.ALLOW)

    def test_agent_can_never_choose_a_permanent_delete(self):
        permanent = Tool("test.nuke", "permanent", Risk.DESTRUCTIVE_OR_PRIVILEGED,
                         lambda a, c: ToolResult({}, Verification.PASS),
                         argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
                         reversibility="irreversible", deletes=True, user_only=True)
        for provenance in ("delegated", "delegated_microphone"):
            self.assertEqual(self.kernel.authorize(permanent, {}, True, provenance=provenance, autonomy="review",
                                                   tainted=False).decision, Decision.DENY)
        for provenance in ("inferred", "tool_observed", "external_untrusted", "reviewed_inferred"):
            self.assertEqual(self.kernel.authorize(permanent, {}, True, provenance=provenance).decision, Decision.DENY)
        self.assertEqual(self.kernel.authorize(permanent, {}, False).decision, Decision.CONFIRM)
        self.assertEqual(self.kernel.authorize(permanent, {}, True).decision, Decision.ALLOW)

    def test_tainted_changes_confirm_even_in_auto_edits(self):
        self.assertEqual(self.decide(Risk.DATA_MODIFICATION, "auto_edits", "journaled", tainted=True), Decision.CONFIRM)
        self.assertEqual(self.decide(Risk.OBSERVATION, "auto_edits", tainted=True), Decision.ALLOW)

    def test_web_requests_only_confirm_after_private_data_was_read(self):
        web = Tool("test.web", "web", Risk.OBSERVATION, lambda a, c: ToolResult({}, Verification.PASS),
                   argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
                   network_egress=True)

        def decide(**flags):
            return self.kernel.authorize(web, {}, provenance="delegated", autonomy="auto_edits", **flags).decision
        self.assertEqual(decide(tainted=True, exposed=False), Decision.ALLOW)    # only public web content seen
        self.assertEqual(decide(tainted=True, exposed=True), Decision.CONFIRM)   # a file/screen was read: could leak
        self.assertEqual(decide(tainted=True), Decision.CONFIRM)                 # callers that don't say stay strict
        self.assertEqual(decide(tainted=False, exposed="yes"), Decision.DENY)    # malformed flag fails closed

    def test_unknown_or_missing_mode_denies(self):
        for mode in (None, "", "yolo", "AUTO_EDITS", 2):
            self.assertEqual(self.decide(Risk.OBSERVATION, mode), Decision.DENY)
        self.assertEqual(self.decide(Risk.OBSERVATION, "auto_safe", tainted="no"), Decision.DENY)

    def test_mode_cannot_upgrade_non_delegated_provenance(self):
        for provenance in ("inferred", "microphone_untrusted", "user_stated", "reviewed_inferred"):
            self.assertEqual(self.decide(Risk.OBSERVATION, "auto_edits", provenance=provenance), Decision.DENY)

    def test_on_screen_confirmation_allows_confirmed_step(self):
        self.assertEqual(self.decide(Risk.EXTERNAL_SIDE_EFFECT, "auto_safe", confirmed=True), Decision.ALLOW)

    def test_grants_still_bind_delegated_steps(self):
        guarded = Tool("t.x", "x", Risk.OBSERVATION, lambda a, c: None, required_capability="screen.observe")
        result = self.kernel.authorize(guarded, {}, provenance="delegated", autonomy="auto_edits",
                                       capability_allowed=False)
        self.assertEqual(result.decision, Decision.DENY)


class AutonomyRuntimeTests(unittest.TestCase):
    def test_confirmed_step_keeps_mode_through_approval(self):
        from chutku.app import create_runtime
        with tempfile.TemporaryDirectory() as temp:
            with create_runtime(Path(temp)) as runtime:
                runtime.registry.register(tool(Risk.EXTERNAL_SIDE_EFFECT, name="test.external"))
                waiting = runtime.run("test.external", {}, provenance="delegated", autonomy="auto_edits")
                self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
                done = runtime.approve(waiting["approval"]["token"])
                self.assertEqual(str(done["state"]), "COMPLETED")
                denied = runtime.run("system.get_time", {}, provenance="delegated", autonomy="bogus")
                self.assertEqual(str(denied["state"]), "DENIED")


if __name__ == "__main__":
    unittest.main()
