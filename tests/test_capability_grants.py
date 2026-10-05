from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.app import create_runtime
from chutku.core.capability_grants import CapabilityGrantStore
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


class CapabilityGrantTests(unittest.TestCase):
    def test_exact_grants_are_durable_revocable_and_have_no_wildcard(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "grants.db"
            store = CapabilityGrantStore(path)
            self.assertTrue(store.grant("screen.observe").active)
            with self.assertRaises(ValueError):
                store.grant("screen.*")
            store.close()
            store = CapabilityGrantStore(path)
            self.assertTrue(store.get("screen.observe").active)
            self.assertFalse(store.revoke("screen.observe").active)
            with self.assertRaises(ValueError):
                store.get("screen.observe")
            store.close()

    def test_tool_is_denied_until_exact_capability_is_granted(self):
        effects = []
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.registry.register(Tool("test.screen", "Inspect the screen.", Risk.OBSERVATION,
                lambda args, ctx: (effects.append(True) or ToolResult({}, Verification.PASS)),
                required_capability="screen.observe"))
            self.assertEqual(runtime.run("test.screen", {})["state"], "DENIED")
            self.assertFalse(effects)
            runtime.capability_grants.grant("screen.observe")
            self.assertEqual(runtime.run("test.screen", {})["state"], "COMPLETED")
            self.assertEqual(effects, [True])

    def test_revocation_invalidates_pending_high_risk_approval(self):
        effects = []
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("process.terminate")
            runtime.registry.register(Tool("test.terminate", "Terminate a process.", Risk.EXTERNAL_SIDE_EFFECT,
                lambda args, ctx: (effects.append(True) or ToolResult({}, Verification.PASS)),
                required_capability="process.terminate"))
            pending = runtime.run("test.terminate", {})
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            self.assertEqual(pending["approval"]["capability"]["capability"], "process.terminate")
            runtime.capability_grants.revoke("process.terminate")
            with self.assertRaises(ValueError):
                runtime.approve(pending["approval"]["token"])
            self.assertFalse(effects)


if __name__ == "__main__":
    unittest.main()
