"""H24: standing goals, checked from the PC without a model; removing one asks first."""
from datetime import datetime
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku import goals
from chutku.daily_intent import parse_daily


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.folder = self.base / "goal"
        self.folder.mkdir()

    def test_a_folder_goal_counts_files_and_finishes_by_itself(self):
        monday = datetime(2026, 11, 2, 10, 0)
        goal = goals.add(self.base, f"is hafte 3 notes banane hain, {self.folder} mein", now=monday)
        self.assertEqual(goal["criterion"], {"kind": "folder_count", "path": str(self.folder), "count": 3})
        self.assertEqual(goal["due"], "2026-11-08T23:59")                  # Sunday night
        for name in ("a.txt", "b.txt"):
            (self.folder / name).write_text("x", encoding="utf-8")
        rows = goals.check(self.base, now=monday)
        self.assertEqual((rows[0]["done"], rows[0]["needed"], rows[0]["status"]), (2, 3, "open"))
        self.assertIn("2/3, 6 din bache", goals.describe(rows))
        (self.folder / "c.txt").write_text("x", encoding="utf-8")
        rows = goals.check(self.base, now=monday)
        self.assertEqual(len(os.listdir(self.folder)), 3)                 # independent check
        self.assertEqual(rows[0]["status"], "done")
        self.assertIn("pura!", goals.describe(rows))

    def test_said_done_overdue_and_devanagari(self):
        goal = goals.add(self.base, "viva ki taiyari 2 din mein", now=datetime(2026, 11, 2, 10, 0))
        self.assertEqual(goal["criterion"], {"kind": "said_done"})
        rows = goals.check(self.base, now=datetime(2026, 11, 6, 10, 0))
        self.assertTrue(rows[0]["overdue"])
        self.assertIn("aage badhaun ya hata dun?", goals.describe(rows))
        self.assertEqual(goals.mark_done(self.base, goal["id"])[0]["status"], "done")
        hindi = goals.add(self.base, "हर दिन 30 मिनट पढ़ाई")
        self.assertEqual(goals.load(self.base)[-1]["text"], hindi["text"])
        with self.assertRaises(ValueError):
            goals.mark_done(self.base, 99)
        with self.assertRaises(ValueError):
            goals.add(self.base, "x")

    def test_phrases_and_removal_asks_first(self):
        self.assertEqual(parse_daily("goal: 5 chapter notes D:\\Study mein")[:2],
                         ("goals.add", {"text": "5 chapter notes D:\\Study mein"}))
        self.assertEqual(parse_daily("mere goals")[:2], ("goals.list", {}))
        self.assertEqual(parse_daily("goal 2 ho gaya")[:2], ("goals.done", {"id": 2}))
        self.assertEqual(parse_daily("goal 2 hatao")[:2], ("goals.remove", {"id": 2}))
        from chutku.app import create_runtime
        with create_runtime(self.base / "install") as runtime:
            goals.add(self.base / "install", "viva ki taiyari")
            result = runtime.run("goals.remove", {"id": 1}, provenance="delegated", autonomy="owner")
            self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION")       # a delete always asks
            self.assertEqual(len(goals.load(self.base / "install")), 1)
            listed = runtime.run("goals.list", {}, provenance="delegated", autonomy="owner")
            self.assertEqual(str(listed["state"]), "COMPLETED")


class AnswerTests(unittest.TestCase):
    def test_goals_and_backups_answer_from_the_tool_output_not_a_model(self):
        """Live 2026-11-07: "mere goals" got "I don't have the list visible" from the cloud model."""
        from chutku.quick_intents import QUICK_ANSWERS
        self.assertEqual(QUICK_ANSWERS["goals.list"]({"summary": "1. notes: 2/3"}), "1. notes: 2/3")
        self.assertIn("Abhi koi backup nahi hai", QUICK_ANSWERS["backup.list"]({"backups": [], "folder": "D:/B"}))
        self.assertIn("2 KB", QUICK_ANSWERS["backup.list"]({"backups": [{"name": "a.zip", "bytes": 2048}], "folder": "D:/B"}))


if __name__ == "__main__":
    unittest.main()
