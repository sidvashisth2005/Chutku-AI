"""Weekly insights (Phase 3b H7): exact counts from a fixture week, and the phrases that ask for them."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from chutku import insights
from chutku.quick_intents import QUICK_ANSWERS, quick_proposal

NOW = datetime(2026, 10, 7, 12, 0, 0)


def turn(days_ago, origin="text", planners=("quick",), tools=("system.get_time",), status="done"):
    return {"at": (NOW - timedelta(days=days_ago)).timestamp(), "origin": origin, "said": "x", "reply": "y",
            "status": status, "tools": list(tools), "planners": list(planners) if planners else None}


def action(days_ago, tool, state, approved=False):
    when = (NOW - timedelta(days=days_ago)).astimezone().isoformat(timespec="seconds")
    return {"time": when, "tool": tool, "state": state, "approved_on_screen": approved}


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        turns = [turn(1), turn(2, origin="voice", planners=("local",), tools=("apps.launch",)),
                 turn(3, planners=("gemini",), tools=("web.news",)), turn(3, planners=("reflex",)),
                 turn(4, planners=None, tools=(), status="said"),              # a voice-chat line, not a request
                 turn(5, planners=("quick", "local"), tools=("apps.launch",), status="failed"),
                 turn(9), turn(10, origin="voice")]                             # last week
        (self.base / "data" / "conversations.jsonl").write_text("".join(json.dumps(t) + "\n" for t in turns),
                                                                encoding="utf-8")
        actions = [action(1, "system.get_time", "COMPLETED"), action(2, "apps.launch", "FAILED"),
                   action(2, "apps.launch", "FAILED"), action(3, "filesystem.move", "WAITING_CONFIRMATION"),
                   action(3, "filesystem.move", "COMPLETED", approved=True), action(4, "x.y", "DENIED"),
                   action(12, "old.tool", "FAILED")]
        (self.base / "data" / "actions.log.jsonl").write_text("".join(json.dumps(a) + "\n" for a in actions),
                                                              encoding="utf-8")
        (self.base / "data" / "reflexes.json").write_text(json.dumps([
            {"id": "a", "template": "open {app}", "created": (NOW - timedelta(days=2)).isoformat()},
            {"id": "b", "template": "old one", "created": (NOW - timedelta(days=20)).isoformat()}]), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_counts(self):
        out = insights.week(self.base, now=NOW)
        this = out["this_week"]
        self.assertEqual((this["requests"], this["voice"], this["typed"]), (5, 1, 4))
        self.assertEqual((this["instant"], this["by_model"], this["gemini"]), (2, 3, 1))
        self.assertEqual(this["instant_share"], 0.4)
        self.assertEqual((this["voice_chat_lines"], this["not_done"]), (1, 1))
        self.assertEqual(out["last_week"]["requests"], 2)
        self.assertEqual(set(out["top_actions"][:2]), {("apps.launch", 2), ("system.get_time", 2)})   # a tie
        self.assertEqual((out["completed"], out["failed"], out["refused"]), (2, 2, 1))
        self.assertEqual((out["asked_you"], out["you_approved"]), (1, 1))
        self.assertEqual(out["most_failed"], [("apps.launch", 2)])
        self.assertEqual(out["new_skills"], ["open {app}"])
        text = QUICK_ANSWERS["insights.week"](out)
        for fact in ("5 requests", "1 by voice", "last week 2", "Instant answers: 40%", "3 needed a model",
                     "1 of them Gemini", "2 failed", "approved 1", "New learned skills: 1"):
            self.assertIn(fact, text)

    def test_empty_logs(self):
        with tempfile.TemporaryDirectory() as empty:
            out = insights.week(Path(empty), now=NOW)
        self.assertEqual(out["this_week"]["requests"], 0)
        self.assertIn("0 requests", insights.say(out))

    def test_phrases(self):
        for text in ("is hafte kya kiya", "is hafte kya kya hua", "weekly report", "what did you do this week",
                     "hafte ki report", "is week ka report dikhao"):
            self.assertEqual(quick_proposal(text)["next_steps"][0]["tool"], "insights.week", text)
        self.assertEqual(quick_proposal("aaj kya kiya")["next_steps"][0]["tool"], "log.recent")


if __name__ == "__main__":
    unittest.main()
