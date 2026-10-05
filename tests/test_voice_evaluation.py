import unittest

from scripts.evaluate_human_voice import CONDITIONS, GROUPS, summarize


class VoiceEvaluationTests(unittest.TestCase):
    def row(self, group, condition="quiet-1m", passed=True, source="source", executed=False):
        return {"group": group, "passed": passed, "source_sha256": source,
                "condition": condition, "latency_seconds": 1.0,
                "participant": group, "executed": executed}

    def test_gate_requires_both_groups_and_threshold(self):
        rows = [self.row(group, condition) for group in GROUPS for condition in CONDITIONS for _ in range(20)]
        report = summarize(rows, "source")
        self.assertTrue(report["passed"])
        self.assertEqual(report["recordings"], 200)
        rows[0]["executed"] = True
        self.assertFalse(summarize(rows, "source")["passed"])

    def test_stale_and_low_accuracy_trials_do_not_pass(self):
        stale = [self.row(group, condition, source="old") for group in GROUPS for condition in CONDITIONS for _ in range(20)]
        self.assertFalse(summarize(stale, "source")["passed"])
        low = [self.row(group, CONDITIONS[index % len(CONDITIONS)], passed=index < 84)
               for group in GROUPS for index in range(100)]
        self.assertFalse(summarize(low, "source")["passed"])


if __name__ == "__main__":
    unittest.main()
