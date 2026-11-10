import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.scoreboard import family, markdown, score, unbacked_promises


class DailyFamilyTests(unittest.TestCase):
    def test_a_finished_request_is_named_by_its_tool_and_an_unfinished_one_by_its_words(self):
        self.assertEqual(family("open whatsapp", ["apps.launch"]), "open_app")
        self.assertEqual(family("send hi to UB on whatsapp", ["message.send"]), "whatsapp_send")
        # cancelled after the launch step: the words say what was asked, not the one step that ran
        self.assertEqual(family('play "After Party" playlist in spotify', ["apps.launch"], "cancelled"), "music_play")
        self.assertEqual(family("open skills page in brave", [], "clarify"), "browser")
        self.assertEqual(family("write the text 'x' into the file D:\\a.txt", [], "failed"), "files_write")
        self.assertEqual(family("read the last message from pita shri on whatsapp", [], "cancelled"), "whatsapp_read")
        self.assertEqual(family("shutdown pc", [], "clarify"), "power")
        self.assertEqual(family("Watch out brother.", [], "clarify"), "other")

    def test_a_voice_promise_counts_only_when_no_task_backed_it(self):
        t = 1000.0
        turns = [  # conversation 1: two promises, one task row -> one unkept promise
            {"at": t - 40, "origin": "voice", "status": "done", "said": "open vlc", "tools": ["apps.launch"]},
            {"at": t, "origin": "voice", "status": "said", "said": "open vlc", "reply": "VLC khol rahi hoon."},
            {"at": t + 0.01, "origin": "voice", "status": "said", "said": "6 baje yaad dilana",
             "reply": "Main 6 baje yaad dila dungi. Ho jayega!"},
            {"at": t + 0.02, "origin": "voice", "status": "said", "said": "alarm", "reply": "Main alarm nahi set kar sakti."},
            {"at": t + 0.03, "origin": "voice", "status": "said", "said": "band karo", "reply": "Open kar deti hoon. Karoon?"},
            # conversation 2, an hour later: one promise, one task
            {"at": t + 3600, "origin": "voice", "status": "failed", "said": "send hi", "tools": []},
            {"at": t + 3650, "origin": "voice", "status": "said", "said": "send hi", "reply": "Bhej rahi hoon."},
            {"at": t + 3700, "origin": "text", "status": "said", "said": "x", "reply": "kar rahi hoon"}]   # typed: not voice
        count, examples = unbacked_promises(turns)
        self.assertEqual((count, examples), (1, ["Main 6 baje yaad dila dungi. Ho jayega!"]))


class ScoreboardTests(unittest.TestCase):
    def test_burden_counts_each_kind_once_and_ignores_chat_and_scripts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data" / "logs").mkdir(parents=True)
            now = time.time()
            turns = [{"at": now - 50, "said": "open notepad", "status": "done", "seconds": 1.0, "planners": ["quick"]},
                     {"at": now - 40, "said": "send hi to UB on whatsapp", "status": "failed", "seconds": 15.0},
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
        self.assertEqual(s["lies"], 0)
        self.assertEqual([f[:3] for f in s["families"]],
                         [("whatsapp_send", 0, 1), ("whatsapp_open_chat", 0, 1), ("open_app", 1, 1)])
        text = markdown(s)
        self.assertIn("B100 = ", text)
        self.assertIn("The Daily 30: 1/3 requests finished (33%", text)


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
