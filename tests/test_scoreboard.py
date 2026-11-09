import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.scoreboard import markdown, score


class ScoreboardTests(unittest.TestCase):
    def test_burden_counts_each_kind_once_and_ignores_chat_and_scripts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data" / "logs").mkdir(parents=True)
            now = time.time()
            turns = [{"at": now - 50, "said": "open notepad", "status": "done", "seconds": 1.0, "planners": ["quick"]},
                     {"at": now - 40, "said": "send hi to UB", "status": "failed", "seconds": 15.0},
                     {"at": now - 30, "said": "galat chat hai", "status": "clarify"},
                     {"at": now - 20, "said": "kaisi ho", "status": "said"},                  # chat, not a request
                     {"at": now - 10, "said": "x", "status": "failed", "origin": "script"},   # a test script
                     {"at": now - 9 * 86400, "said": "old", "status": "failed"}]             # outside the window
            (base / "data" / "conversations.jsonl").write_text("\n".join(json.dumps(t) for t in turns), "utf-8")
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - 30))
            log = [{"time": stamp, "tool": "message.send", "state": "WAITING_CONFIRMATION"},
                   {"time": stamp, "tool": "message.send", "state": "FAILED"},
                   {"time": stamp, "tool": "message.send", "state": "COMPLETED"},
                   {"time": stamp, "tool": "filesystem.move", "state": "WAITING_CONFIRMATION",   # a test script
                    "arguments": {"source": r"D:\ChutkuScratch\a.txt"}}]
            (base / "data" / "actions.log.jsonl").write_text("\n".join(json.dumps(r) for r in log), "utf-8")
            (base / "data" / "logs" / "hang-1.txt").write_text("stalled", "utf-8")
            s = score(base, days=7)
        self.assertEqual((s["requests"], s["failed"], s["clarify"], s["complaints"], s["approvals"], len(s["hangs"])),
                         (3, 1, 1, 1, 1, 1))
        # 5 failed + 3 complaint + 2*(1 clarify + 1 approval) + (15-5)/5 = 2 waited + 20 hang = 34 over 3 requests
        self.assertEqual(s["B100"], round(100 * 34 / 3, 1))
        self.assertEqual(s["worst_tools"][0][:3], ("message.send", 1, 3))
        self.assertIn("B100 = ", markdown(s))


class RealBankTests(unittest.TestCase):
    def test_owner_requests_become_practice_items_and_failures_a_fix_list(self):
        from chutku import practice
        from scripts import make_real_bank
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data").mkdir()
            turns = [{"at": 1, "said": "open notepad", "status": "failed"},
                     {"at": 2, "said": "Open  Notepad", "status": "done", "tools": ["apps.launch"]},   # newest wins
                     {"at": 3, "said": "cajana ka mausam", "status": "clarify", "reply": "Which city?"},
                     {"at": 4, "said": "kaisi ho", "status": "said"},
                     {"at": 5, "said": "test goal", "status": "done", "tools": ["x"], "origin": "script"}]
            (base / "data" / "conversations.jsonl").write_text("\n".join(json.dumps(t) for t in turns), "utf-8")
            make_real_bank.main(["--base", str(base)])
            real = base / "data" / "task_bank" / "real.jsonl"
            bank = [json.loads(line) for line in real.read_text("utf-8").splitlines()]
            failures = (base / "data" / "task_bank" / "real_failures.jsonl").read_text("utf-8")
            self.assertEqual([(i["say"], i["expect"]) for i in bank], [("Open Notepad", {"tools": ["apps.launch"]})])
            self.assertIn("cajana", failures)
            self.assertNotIn("notepad", failures.casefold())     # its newest outcome was a success
            self.assertIn("Open Notepad", [i["say"] for i in practice.load_bank(real=real)])
            self.assertNotIn("Open Notepad", [i["say"] for i in practice.load_bank()])  # tests never see private data


if __name__ == "__main__":
    unittest.main()
