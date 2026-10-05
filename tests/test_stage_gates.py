import unittest
from unittest.mock import patch

from scripts.check_stages import STAGES, check_access, check_brain, evaluate


class StageGateTests(unittest.TestCase):
    def test_stage_order_is_locked(self):
        self.assertEqual(STAGES, ("foundation", "brain", "access", "llm", "voice"))

    def test_brain_gate_runs_real_disposable_path(self):
        report = check_brain(require_foundation=False)
        self.assertTrue(report["passed"], report)
        self.assertTrue(all(row["passed"] for row in report["checks"]))

    def test_evaluation_preserves_dependency_order(self):
        accepted = {"stage": "foundation", "passed": True, "checks": []}
        with patch("scripts.check_stages.check_foundation", return_value=accepted):
            results = evaluate("brain")
        self.assertEqual([row["stage"] for row in results], ["foundation", "brain"])

    def test_access_gate_runs_revocation_and_provenance_cases(self):
        with patch("scripts.check_stages.check_brain", return_value={"passed": True}):
            report = check_access()
        self.assertTrue(report["passed"], report)


if __name__ == "__main__":
    unittest.main()
