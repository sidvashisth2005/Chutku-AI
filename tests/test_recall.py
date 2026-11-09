"""One memory for every planner and the voice model; every conversation remembered (owner, 2026-10-04)."""
from datetime import date, datetime
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import recall
from chutku.mind import Mind
from chutku.quick_intents import quick_proposal


def at(day, hour):
    return datetime(2026, 10, day, hour, 0).timestamp()


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        mind = Mind(self.base)
        mind.remember_person("AK", aliases=["mammi"])
        mind.remember_person("Rahul Sharma", aliases=["DL sir"], relation="teacher")
        mind.set_fact("home", "Pune")
        mind.set_fact("college", "MIT WPU")
        mind.add("assignments", "DBMS report by Friday")
        mind.add("goals", "learn guitar")

    def test_slice_puts_the_goal_related_parts_first_and_fits_the_budget(self):
        view = recall.about_you("DL sir ko DBMS report bhejo", base=self.base, budget=1200)
        self.assertEqual(view["people"][0]["name"], "Rahul Sharma")
        self.assertEqual(view["open"][0], "assignments: DBMS report by Friday")
        small = recall.about_you("DL sir ko DBMS report bhejo", base=self.base, budget=150)
        self.assertLessEqual(len(json.dumps(small, ensure_ascii=False)), 150)
        self.assertEqual(small["people"][0]["name"], "Rahul Sharma")   # the relevant person survives the cut

    def test_old_memory_notes_are_included(self):
        view = recall.about_you("weather", base=self.base, notes=[{"key": "city", "value": "Pune"}])
        self.assertEqual(view["facts"]["city"], "Pune")

    def test_conversation_log_and_earlier_turns(self):
        recall.log_conversation("Latent season 2 kab aaya", "It came out in June.", base=self.base, at=at(1, 20))
        recall.log_conversation("weather kaisa hai", "Sunny.", base=self.base, at=at(2, 9))
        for i in range(4):
            recall.log_conversation(f"task {i}", "ok [Verified: 1 of 1 steps completed.]", base=self.base,
                                    at=at(4, 10 + i))
        found = recall.earlier("Latent season 2 ka next episode", self.base, now=at(4, 18))
        said = [t["you"] for t in found]
        self.assertIn("Latent season 2 kab aaya", said)          # older and related
        self.assertNotIn("weather kaisa hai", said)              # older and unrelated
        self.assertEqual(said[:3], ["task 3", "task 2", "task 1"])   # today's last three, newest first
        self.assertEqual(found[0]["chutku"], "ok")               # verification tail stripped

    def test_voice_conversation_turns_skip_noise(self):
        recall.log_voice([("you", "Thank you."), ("chutku", "Welcome!"), ("you", "agla gaana chalao"),
                          ("chutku", "Chala diya.")], base=self.base)
        rows = recall.turns(self.base)
        self.assertEqual([(r["said"], r["reply"], r["origin"]) for r in rows],
                         [("agla gaana chalao", "Chala diya.", "voice")])

    def test_session_logged_only_when_finished(self):
        recall.log_session({"goal": "open spotify", "status": "running"}, base=self.base)
        recall.log_session({"goal": "open spotify", "status": "done", "reply": "Opened Spotify.", "origin": "hotkey",
                            "steps": [{"tool": "apps.launch", "state": "COMPLETED"}]}, base=self.base)
        rows = recall.turns(self.base)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["origin"], rows[0]["tools"]), ("hotkey", ["apps.launch"]))
        self.assertNotIn("asks", rows[0])
        # 20x plan: the scoreboard reads each turn's time and the approvals the owner had to answer
        recall.log_session({"goal": "move it", "status": "done", "reply": "Moved.", "seconds": 3.456, "asks": 1,
                            "planners": [{"planner": "gemini"}]}, base=self.base)
        last = recall.turns(self.base)[-1]
        self.assertEqual((last["seconds"], last["asks"], last["planners"]), (3.46, 1, ["gemini"]))

    def test_what_did_we_talk_about_yesterday(self):
        yesterday = date.today().toordinal() - 1
        when = datetime.combine(date.fromordinal(yesterday), datetime.min.time()).timestamp() + 15 * 3600
        recall.log_conversation("mammi ko good night bhejo", "Sent.", base=self.base, at=when)
        with patch.object(recall, "PROJECT_ROOT", self.base):
            for phrase in ("what did we talk about yesterday", "kal humne kya baat ki",
                           "pichli baar maine kya pucha tha"):
                proposal = quick_proposal(phrase)
                self.assertIsNotNone(proposal, phrase)
            reply = quick_proposal("what did we talk about yesterday")["reply"]
            self.assertIn("mammi ko good night bhejo", reply)
            self.assertIn("no saved conversation", quick_proposal("what did we talk about today")["reply"])

    def test_busy_day_history_still_fits_an_instant_reply(self):
        from chutku.agent_loop import validate_proposal
        when = datetime.combine(date.today(), datetime.min.time()).timestamp() + 8 * 3600
        for i in range(40):
            recall.log_conversation(f"request number {i} " + "x" * 120, "reply " + "y" * 200, base=self.base,
                                    at=when + i * 60)
        with patch.object(recall, "PROJECT_ROOT", self.base):
            proposal = quick_proposal("what did we talk about today")
        self.assertLessEqual(len(proposal["reply"]), 600)
        self.assertIn("request number 39", proposal["reply"])          # the newest is always shown
        runtime = types.SimpleNamespace(registry=types.SimpleNamespace(list=lambda: []))
        validate_proposal(proposal, runtime, set())                     # what the live path checks

    def test_cloud_planner_gets_a_small_slice_only(self):
        from chutku.cloud_planner import cloud_view
        view = recall.about_you("DL sir ko DBMS report bhejo", base=self.base, budget=1200)
        session = types.SimpleNamespace(goal="DL sir ko DBMS report bhejo", steps=[], feedback=None,
                                        context={"about_you": view, "accessible_roots": []})
        sent = json.loads(cloud_view(session, None))["CONTEXT"]
        self.assertLessEqual(len(json.dumps(sent["about_you"], ensure_ascii=False)), 800)
        self.assertEqual(sent["about_you"]["people"][0]["name"], "Rahul Sharma")


if __name__ == "__main__":
    unittest.main()
