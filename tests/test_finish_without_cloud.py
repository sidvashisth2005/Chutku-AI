"""Verified work is never reported as failed because the cloud brain could not write the reply (plan slice E, live
2026-11-10: "aaj ka weather, news aur meri reminders batao" ran all 4 steps, then said "I couldn't work on that: the
free AI limit is used up", status failed)."""
import json
import unittest
from types import SimpleNamespace

from chutku.quick_intents import quick_answer

WEATHER = {"place": "Indore, Madhya Pradesh, India", "source": "open-meteo.com",
           "now": {"temperature_c": 24.5, "feels_like_c": 25.1, "humidity_percent": 60, "wind_kmh": 7, "sky": "clear sky"},
           "next_days": [{"date": "2026-11-10", "max_c": 29.0, "min_c": 15.2, "rain_chance_percent": 0, "sky": "clear sky"}]}
NEWS = {"untrusted_data": {"topic": "top stories", "provenance": "external_untrusted",
                           "headlines": [{"title": "First headline - NDTV", "source": "NDTV", "published": "", "url": "u"},
                                         {"title": "Second headline", "source": "", "published": "", "url": "u"}]},
        "source": "web.news"}
REMINDERS = {"upcoming": [{"id": "r1", "at": "2026-11-10T18:00", "message": "stretch"}], "count": 1}


def step(tool, output, state="COMPLETED"):
    return {"tool": tool, "state": state, "purpose": tool, "observation": json.dumps(output)}


class FinishWithoutCloudTests(unittest.TestCase):
    def test_the_daily_briefing_answers_from_its_own_steps(self):
        session = SimpleNamespace(goal="aaj ka weather, news aur meri reminders batao", steps=[
            step("system.get_time", {"local_time": "Tuesday, 10 November 2026, 07:31 PM"}),
            step("web.weather", WEATHER), step("reminder.list", REMINDERS), step("web.news", NEWS)])
        reply = quick_answer(session)
        self.assertIsNotNone(reply)
        for part in ("07:31 PM", "Indore", "24.5", "clear sky", "stretch", "6:00 PM", "First headline"):
            self.assertIn(part, reply)

    def test_each_part_alone_and_empty_lists(self):
        self.assertIn("No reminders", quick_answer(SimpleNamespace(goal="show my reminders", steps=[
            step("reminder.list", {"upcoming": [], "count": 0})])))
        self.assertIn("Second headline", quick_answer(SimpleNamespace(goal="news batao", steps=[step("web.news", NEWS)])))
        self.assertIn("Indore", quick_answer(SimpleNamespace(goal="weather in indore", steps=[
            step("web.weather", WEATHER)])))

    def test_every_instant_lookup_that_can_be_worded_locally_is(self):
        largest = {"files": [{"full_path": r"C:\Users\o\Downloads\movie.mkv", "size_mib": 1830.4},
                             {"full_path": r"C:\Users\o\Downloads\setup.exe", "size_mib": 96.0}],
                   "scanned": 412, "complete": True}
        reply = quick_answer(SimpleNamespace(goal="downloads mein sabse badi file kaunsi hai",
                                             steps=[step("filesystem.largest", largest)]))
        self.assertIn("movie.mkv", reply)
        self.assertIn("1.8 GB", reply)
        rules = {"rules": ["[a1b2c3] D:\\Private — kabhi nahi chhoona"], "count": 1}
        self.assertIn("D:\\Private", quick_answer(SimpleNamespace(goal="mere never rules dikhao",
                                                                  steps=[step("never.list", rules)])))
        self.assertIn("No never-rules", quick_answer(SimpleNamespace(goal="mere never rules dikhao",
                                                                     steps=[step("never.list", {"rules": [], "count": 0})])))

    def test_a_headline_with_a_claim_word_is_shown_but_a_model_claim_is_still_withheld(self):
        # A briefing must not be withheld because a headline says "deleted"; the guard is for what a model writes.
        from chutku.agent_loop import AgentSession
        session = AgentSession("news batao", mode="owner")
        session._finish("done", "Headlines: Files deleted in a data leak - NDTV.", worded_by_code=True)
        self.assertEqual(session.reply, "Headlines: Files deleted in a data leak - NDTV.")
        model = AgentSession("news batao", mode="owner")
        model._finish("done", "I deleted the old files for you.")            # negative: a model's claim, no step
        self.assertIn("withheld", model.reply)

    def test_an_unexpected_shape_still_leaves_it_to_the_model(self):
        # strict builders: a wrong fixed reply is worse than the model's
        self.assertIsNone(quick_answer(SimpleNamespace(goal="weather in indore", steps=[
            step("web.weather", {"place": "X"})])))


if __name__ == "__main__":
    unittest.main()
