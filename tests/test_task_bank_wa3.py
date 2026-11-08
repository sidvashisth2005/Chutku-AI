"""WA3: the task bank is well-formed, deterministic, split 80/20 by hash, about 10% damage, and names real tools."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_task_bank  # noqa: E402

BANK = ROOT / "tests" / "task_bank"


def rows():
    return [json.loads(line) for name in ("generated", "hard") for line in
            (BANK / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]


class TaskBankTests(unittest.TestCase):
    def test_every_line_has_the_shape_and_ids_are_unique(self):
        items = rows()
        self.assertGreater(len(items), 1400)
        for r in items:
            self.assertEqual(set(r), {"id", "say", "lang", "category", "expect", "risk", "needs", "multi_step", "split"}, r)
            self.assertEqual(len(r["expect"]), 1, r)
            self.assertIn(next(iter(r["expect"])), {"tools", "plan_shape", "refuse"}, r)
            self.assertIn(r["split"], {"train", "heldout"})
            self.assertEqual(r["split"], make_task_bank.split(r["say"]))       # the split is fixed by the text
        self.assertEqual(len({r["id"] for r in items}), len(items))
        heldout = sum(r["split"] == "heldout" for r in items) / len(items)
        damage = sum("refuse" in r["expect"] for r in items) / len(items)
        self.assertTrue(0.15 < heldout < 0.25 and 0.08 < damage < 0.15, (heldout, damage))
        self.assertTrue({"hi", "hinglish", "en"} <= {r["lang"] for r in items})
        self.assertTrue(any(r["multi_step"] and len(r["expect"]["plan_shape"]) >= 4 for r in items))

    def test_the_generator_is_deterministic(self):
        expected = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in make_task_bank.generate())
        self.assertEqual((BANK / "generated.jsonl").read_text(encoding="utf-8"), expected)

    def test_expected_tools_exist(self):
        from chutku.tools.builtin import register_builtin_tools
        from chutku.tools.registry import ToolRegistry
        registry = ToolRegistry()
        register_builtin_tools(registry)
        known = {t.name for t in registry.list()} | {"log.recent", "log.undo", "task.delegate"}   # runtime-registered
        for r in rows():
            for name in r["expect"].get("tools", []) + r["expect"].get("plan_shape", []):
                self.assertIn(name, known, r["say"])


if __name__ == "__main__":
    unittest.main()
