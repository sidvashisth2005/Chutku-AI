"""The safety documents shown to the owner and the planner must match the code (master plan S4)."""
from collections import Counter
from pathlib import Path
import tempfile
import unittest

from chutku.app import create_runtime
from chutku.tools.assistant import LIMITS

ROOT = Path(__file__).resolve().parents[1]


class DocsTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.runtime = create_runtime(Path(cls.temp.name) / "state")
        cls.tools = cls.runtime.registry.list()

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()
        cls.temp.cleanup()

    def test_security_doc_lists_every_high_risk_tool_and_the_counts(self):
        text = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        apps = [tool for tool in self.tools if tool.name.startswith("app.")]   # atlas actions, counted on their own
        core = [tool for tool in self.tools if not tool.name.startswith("app.")]
        self.assertIn(f"{len(core)} registered", text)
        self.assertIn(f"plus {len(apps)} app actions", text)
        counts = Counter(int(tool.base_risk) for tool in core)
        for level, name in ((0, "R0 observation"), (1, "R1 reversible"), (2, "R2 data modification"),
                            (3, "R3 external side effect"), (4, "R4 destructive / privileged")):
            self.assertIn(f"| {name} | {counts[level]} |", text, name)
        for tool in core:
            if tool.base_risk >= 3:
                self.assertIn(tool.name, text, tool.name)

    def test_limits_do_not_repeat_old_claims(self):
        joined = " ".join(LIMITS)
        for stale in ("limited to Notepad and Calculator", "arbitrary typing/clicking is unavailable",
                      "small English phrase list"):
            self.assertNotIn(stale, joined)
        self.assertIn("always asks first", joined)

    def test_every_code_running_tool_is_flagged(self):
        flagged = {tool.name for tool in self.tools if tool.runs_code}
        self.assertEqual(flagged, {"code.run_python", "process.launch", "system.powershell", "skill.approve",
                                   "skill.create", "evolve.approve", "skill.import"})


if __name__ == "__main__":
    unittest.main()
