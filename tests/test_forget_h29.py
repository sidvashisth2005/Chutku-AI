"""H29: "ye baat bhool jao" hides the last exchange from memory and search (the log keeps it); "wapas yaad karo"
brings it back."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku import history_index, recall


class ForgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        recall.log_conversation("mera favourite colour neela hai", "Yaad rakha.", base=self.base, at=1000.0)
        recall.log_conversation("zebra crossing ka secret plan", "Theek hai.", base=self.base, at=2000.0)

    def test_a_forgotten_turn_leaves_memory_and_search_but_not_the_log(self):
        self.assertEqual(len(history_index.search(self.base, "zebra")["matches"]), 1)
        forgotten = recall.forget_last(self.base)
        self.assertEqual(forgotten["said"], "zebra crossing ka secret plan")
        self.assertEqual([t["said"] for t in recall.turns(self.base)], ["mera favourite colour neela hai"])
        self.assertEqual(history_index.search(self.base, "zebra")["matches"], [])
        raw = recall.conversations_path(self.base).read_text(encoding="utf-8")
        self.assertIn("zebra", raw)                                       # independent check: still in the log
        self.assertEqual(len(recall.turns(self.base, include_hidden=True)), 2)

    def test_wapas_yaad_karo_brings_it_back(self):
        recall.forget_last(self.base)
        self.assertEqual(recall.unforget_last(self.base)["said"], "zebra crossing ka secret plan")
        self.assertEqual(len(recall.turns(self.base)), 2)
        self.assertEqual(len(history_index.search(self.base, "zebra")["matches"]), 1)
        self.assertIsNone(recall.unforget_last(self.base))                # nothing left to bring back
        self.assertEqual(json.loads((self.base / "data" / "hidden-turns.json").read_text()), [])


class ContextGaugeTests(unittest.TestCase):
    def test_the_gauge_measures_each_part_the_brain_reads(self):
        from chutku.agent_loop import AgentSession
        session = AgentSession("what time is it", mode="owner", context={"user_facts": "x" * 40, "about_you": {}})
        sizes = session.snapshot()["context_chars"]
        self.assertEqual(sizes["GOAL"], len("what time is it"))
        self.assertEqual(sizes["user_facts"], 42)                         # the JSON string with its quotes
        before = sizes["STEPS"]
        session.steps.append({"tool": "system.get_time", "arguments": {}, "state": "COMPLETED", "observation": "y" * 500,
                              "purpose": "p"})
        self.assertGreater(session.context_sizes()["STEPS"], before + 500)


if __name__ == "__main__":
    unittest.main()
