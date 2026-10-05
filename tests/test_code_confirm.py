"""Running code always asks first (owner decision 2026-10-06, master plan S1)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.policy.kernel import Decision, PolicyKernel, RUNS_CODE_REASON

CODE_TOOLS = ("code.run_python", "process.launch")


class CodeConfirmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "mind")
        self.mind_root.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")
        self.kernel = PolicyKernel()

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def decide(self, name, *, autonomy=None, provenance="delegated", confirmed=False):
        tool = self.runtime.registry.get(name)
        return self.kernel.authorize(tool, {}, confirmed, provenance=provenance,
                                     resource_access=frozenset({"observe", "modify"}), capability_allowed=True,
                                     autonomy=autonomy, tainted=False, exposed=False)

    def test_code_tools_declare_it(self):
        for name in CODE_TOOLS:
            tool = self.runtime.registry.get(name)
            self.assertTrue(tool.runs_code, name)
            self.assertTrue(tool.manifest()["runs_code"], name)
        self.assertNotIn("runs_code", self.runtime.registry.get("apps.launch").manifest())

    def test_asks_in_every_mode(self):
        for name in CODE_TOOLS:
            for mode in ("owner", "auto_edits", "auto_safe", "review"):
                result = self.decide(name, autonomy=mode)
                self.assertEqual(result.decision, Decision.CONFIRM, (name, mode))
            direct = self.decide(name, provenance="user_stated")
            self.assertEqual(direct.decision, Decision.CONFIRM, name)
            self.assertEqual(direct.reason, RUNS_CODE_REASON)

    def test_on_screen_confirmation_allows_it(self):
        for name in CODE_TOOLS:
            self.assertEqual(self.decide(name, autonomy="owner", confirmed=True).decision, Decision.ALLOW, name)
            self.assertEqual(self.decide(name, provenance="user_stated", confirmed=True).decision, Decision.ALLOW)

    def test_runtime_run_never_executes_without_the_click(self):
        script = Path(self.temp.name) / "state" / "sandbox" / "marker.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        marker = script.with_suffix(".txt")
        script.write_text(f"open(r'{marker}', 'w').write('ran')\n", encoding="utf-8")
        self.runtime.capability_grants.grant("process.launch")
        result = self.runtime.run("code.run_python", {"path": str(script)}, provenance="delegated",
                                  autonomy="owner", tainted=False, exposed=False)
        self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION")
        self.assertFalse(marker.exists())   # nothing ran before the owner's click


if __name__ == "__main__":
    unittest.main()
