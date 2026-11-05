"""Learning over time, suggestions and the mind map (owner, 2026-10-04)."""
from datetime import date, datetime
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import experience, learning, recall, suggest
from chutku.mind import Mind
from chutku.quick_intents import quick_proposal

TODAY = date(2026, 10, 4)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute).timestamp()


def steps(text):
    proposal = quick_proposal(text)
    return proposal and [(s["tool"], s["arguments"]) for s in proposal["next_steps"]]


class EventTests(unittest.TestCase):
    def test_dated_events_become_schedule_items_with_real_dates(self):
        cases = {"my exam is on 12 oct": "exam — Mon 12 Oct 2026",
                 "mera DBMS viva kal hai": "DBMS viva — Mon 05 Oct 2026",
                 "meeting friday ko hai": "meeting — Fri 09 Oct 2026",
                 "i have an interview tomorrow": "interview — Mon 05 Oct 2026",
                 "meri presentation parso hai": "presentation — Tue 06 Oct 2026",
                 "my birthday is 5 march": "birthday — Fri 05 Mar 2027"}
        for text, item in cases.items():
            self.assertEqual(learning.parse_event(text, TODAY), ("schedule", item), text)

    def test_questions_and_other_statements_are_not_events(self):
        for text in ("is my exam on monday?", "my city is Pune", "exam ho gaya", "send exam notes to mammi",
                     "open the meeting link"):
            self.assertIsNone(learning.parse_event(text, TODAY), text)

    def test_instant_phrases(self):
        self.assertEqual(steps("good job")[0], ("mind.feedback", {"rating": "good"}))
        self.assertEqual(steps("galat kiya chutku")[0], ("mind.feedback", {"rating": "bad"}))
        self.assertEqual(steps("mind map dikhao"), [("mind.map", {})])
        self.assertEqual(steps("mera exam 12 oct ko hai")[0][0], "mind.add")
        self.assertIsNone(learning.parse_feedback("good morning"))
        self.assertIsNone(learning.parse_feedback("wrong number"))


class Fake:
    def __init__(self, goal, status="done", tools=("apps.launch",), planner="local"):
        self.goal, self.status, self.tools, self.planner = goal, status, tools, planner

    def snapshot(self):
        return {"goal": self.goal, "status": self.status, "origin": "text", "reply": "ok",
                "steps": [{"tool": t, "purpose": t, "arguments": {}, "state": "COMPLETED"} for t in self.tools],
                "planners": [{"planner": self.planner}]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_feedback_marks_the_latest_task_and_bad_is_never_reused(self):
        session = Fake("open spotify and play lofi")
        experience.record(self.base, session)
        recall.log_session(session.snapshot(), base=self.base)
        recall.log_conversation("galat kiya", "Sorry", tools=["mind.feedback"], base=self.base)
        self.assertEqual(learning.rate_latest("bad", base=self.base), "open spotify and play lofi")
        self.assertEqual(experience.similar(self.base, "open spotify and play lofi"), [])
        learning.rate_latest("good", base=self.base)
        self.assertEqual(len(experience.similar(self.base, "open spotify and play lofi")), 1)

    def test_failed_wording_learns_the_plan_that_worked(self):
        recall.log_conversation("woh gaana lagao jo kal suna tha", "I couldn't.", status="failed", base=self.base)
        good = Fake("play lofi hip hop on youtube", tools=("youtube.play",))
        recall.log_session(good.snapshot(), base=self.base)
        self.assertEqual(learning.after_session(self.base, good), "woh gaana lagao jo kal suna tha")
        found = experience.similar(self.base, "woh gaana lagao jo kal suna tha")
        self.assertEqual(found[0]["steps"][0]["tool"], "youtube.play")

    def test_no_learning_after_a_success_or_a_long_gap(self):
        recall.log_conversation("open notepad", "Opened.", status="done", base=self.base)
        good = Fake("open calculator")
        recall.log_session(good.snapshot(), base=self.base)
        self.assertIsNone(learning.after_session(self.base, good))

    def test_habits_need_three_days_at_a_similar_hour(self):
        for day in (1, 2, 3):
            recall.log_conversation("play lofi on youtube", "Playing.", base=self.base, at=at(day, 22, 5))
            recall.log_conversation("what time is it", "It is…", base=self.base, at=at(day, 8 + day * 4))
        recall.log_conversation("open notepad", "Opened.", base=self.base, at=at(1, 10))
        habits = learning.refresh_habits(self.base, now=at(4, 12))
        self.assertEqual([h["said"] for h in habits.values()], ["play lofi on youtube"])
        self.assertEqual(next(iter(habits.values()))["hour"], 22)
        self.assertIn("habits", Mind(self.base).load())


class SuggestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        mind = Mind(self.base)
        mind.add("schedule", "DBMS viva — Mon 05 Oct 2026")
        mind.add("schedule", "old exam — Thu 01 Oct 2026")
        mind.add("assignments", "OS lab file")

    def test_tomorrows_event_and_open_assignment_are_suggested_with_runnable_commands(self):
        found = suggest.current(self.base, now=at(4, 15), free_c_gb=50)
        kinds = [s["kind"] for s in found]
        self.assertEqual(kinds, ["schedule", "assignments"])
        self.assertIn("DBMS viva is tomorrow", found[0]["text"])
        for s in found:   # Accept sends the command like a typed request: it must run instantly
            self.assertTrue(steps(s["command"]), s["command"])
        late = suggest.current(self.base, now=at(4, 21), free_c_gb=50)[0]
        self.assertIn("in 30 minutes", late["command"])

    def test_low_disk_and_habit_suggestions(self):
        Mind(self.base)._change(lambda d: d.__setitem__("habits", {"k": {
            "text": "play lofi (usually around 22:00)", "said": "play lofi on youtube", "hour": 22, "count": 3}}))
        kinds = [s["kind"] for s in suggest.current(self.base, now=at(4, 22, 10), free_c_gb=4.2)]
        self.assertIn("habit", kinds)
        self.assertIn("storage", kinds)
        recall.log_conversation("play lofi on youtube", "Playing.", base=self.base, at=at(4, 22, 1))
        kinds = [s["kind"] for s in suggest.current(self.base, now=at(4, 22, 10), free_c_gb=50)]
        self.assertNotIn("habit", kinds)          # already done today

    def test_dismissal_hides_for_a_week_and_three_stop_the_kind(self):
        first = suggest.current(self.base, now=at(4, 15), free_c_gb=50)[0]
        suggest.respond(self.base, first["id"], "dismiss", now=at(4, 15))
        self.assertNotIn(first["id"], [s["id"] for s in suggest.current(self.base, now=at(4, 16), free_c_gb=50)])
        state = suggest.load_state(self.base)
        state["dismissals"]["assignments"] = 3
        suggest._save_state(self.base, state)
        self.assertEqual(suggest.current(self.base, now=at(4, 16), free_c_gb=50), [])
        with self.assertRaises(ValueError):
            suggest.respond(self.base, "../../x", "accept")

    def test_at_most_one_popup_an_hour_and_never_at_night(self):
        sent = []
        send = lambda title, text: sent.append(text)
        self.assertIsNone(suggest.maybe_toast(self.base, now=at(4, 23, 30), send=send, free_c_gb=50))
        self.assertIsNone(suggest.maybe_toast(self.base, now=at(4, 7, 30), send=send, free_c_gb=50))
        self.assertIsNotNone(suggest.maybe_toast(self.base, now=at(4, 15), send=send, free_c_gb=50))
        self.assertIsNone(suggest.maybe_toast(self.base, now=at(4, 15, 40), send=send, free_c_gb=50))
        second = suggest.maybe_toast(self.base, now=at(4, 16, 1), send=send, free_c_gb=50)
        self.assertNotEqual(second["text"], sent[0])        # never the same one twice
        self.assertEqual(len(sent), 2)


class MindMapTests(unittest.TestCase):
    def test_map_data_and_recent_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Mind(base).remember_person("AK", aliases=["mammi"])
            for hour in (9, 10):
                recall.log_conversation("Latent season 2 episode chalao", "Playing.", base=base, at=at(4, hour))
            view = recall.mind_map(base, now=at(4, 12))
            self.assertEqual(view["people"][0]["name"], "AK")
            self.assertIn("latent", view["topics"])
            self.assertEqual(set(view["lists"]) >= {"assignments", "schedule"}, True)

    def test_meta_requests_are_not_topics_or_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for hour in (9, 10):
                recall.log_conversation("what did we talk about today", "…", base=base, at=at(4, hour))
                recall.log_conversation("good job", "Thanks", tools=["mind.feedback"], base=base, at=at(4, hour))
                recall.log_conversation("what time is it", "It's 9.", base=base, at=at(4, hour))
            self.assertEqual(recall.recent_topics(base, now=at(4, 12)), [])
            summary = recall.talked_about(date(2026, 10, 4), base)
            self.assertNotIn("talk about", summary)
            self.assertIn("what time is it", summary)

    def test_time_answer_uses_the_local_clock(self):
        from chutku.presentation import present
        text = present({"state": "COMPLETED", "output": {"local_time": "21:51", "utc_time": "2026-10-04T16:21:30"}})
        self.assertEqual(text, "It's 21:51.")

    def test_page_draws_svg_without_inline_markup(self):
        js = (Path(__file__).resolve().parents[1] / "chutku" / "web" / "app.js").read_text(encoding="utf-8")
        start = js.index("function renderMind")
        body = js[start:js.index("// ---- other tabs ----")]
        self.assertNotIn("innerHTML", body)
        self.assertIn("createElementNS", js)


if __name__ == "__main__":
    unittest.main()
