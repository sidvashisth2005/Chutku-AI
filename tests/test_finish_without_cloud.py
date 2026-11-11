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

    def test_a_planned_multi_part_answer_keeps_every_result(self):
        # live 2026-11-11: "aaj ki date batao, C drive mein kitni jagah hai aur internet chal raha hai kya" ran all 3
        # checks, then the cloud model (which never sees private results) said "C drive ki details nahi mili"
        from chutku.agent_loop import AgentSession
        from tests.agent_fakes import FakeRuntime, ScriptedPlanner, continue_with
        outputs = {"system.get_time": {"local_time": "Wednesday, 11 November 2026, 01:36 AM"},
                   "system.disk_space": {"drives": [{"drive": "C:\\", "free_gb": 41.2, "total_gb": 475.0,
                                                     "free_percent": 8.7}]},
                   "net.check": {"verdict": "Internet is working.", "local_ip": "192.168.1.5"}}
        runtime = FakeRuntime(outputs)
        session = AgentSession("aaj ki date batao, C drive mein kitni jagah hai aur internet chal raha hai kya",
                               mode="owner")
        planner = ScriptedPlanner(
            continue_with({"tool": "system.get_time", "arguments": {}}, {"tool": "system.disk_space", "arguments": {}},
                          {"tool": "net.check", "arguments": {}}),
            {"status": "done", "reply": "Date mil gayi; C drive aur internet ki details results mein nahi mili.",
             "declared_plan": [], "next_steps": [], "finish": True})
        session.advance(runtime, planner)
        self.assertEqual(session.status, "done")
        for part in ("01:36 AM", "41.2 GB free", "Internet is working"):
            self.assertIn(part, session.reply)
        self.assertNotIn("nahi mili", session.reply)

    def test_a_file_search_is_counted_honestly(self):
        found = {"matches": [{"full_path": rf"C:\Users\o\Desktop\f{i}.txt", "kind": "file"} for i in range(7)]
                 + [{"full_path": r"C:\Users\o\Desktop\Work", "kind": "directory"}],
                 "count": 8, "truncated": False, "complete": True}
        reply = quick_answer(SimpleNamespace(goal="desktop pe kitni files hain", steps=[step("filesystem.search", found)]))
        if reply is not None:   # only when the router owns this sentence; the planner path is covered below
            self.assertIn("7 files and 1 folder", reply)
        from chutku.quick_intents import worded
        self.assertIn("7 files and 1 folder", worded([step("filesystem.search", found)]))
        cut = dict(found, truncated=True)
        self.assertIn("7+ files", worded([step("filesystem.search", cut)]))
        self.assertIn("Nothing matched", worded([step("filesystem.search", {"matches": [], "count": 0,
                                                                            "truncated": False, "complete": True})]))

    def test_offline_briefing_still_gives_the_parts_that_work(self):
        # live 2026-11-11 10:42 (offline): the scheduled briefing's weather failed, then "please specify the city"
        # and no reminders at all
        from chutku.agent_loop import AgentSession
        from chutku.quick_intents import QuickPlanner
        from tests.agent_fakes import FakeRuntime
        runtime = FakeRuntime({"system.get_time": {"local_time": "Wednesday, 11 November 2026, 10:42 AM"},
                               "reminder.list": REMINDERS, "web.news": NEWS}, fail={"web.weather", "web.news"})
        session = AgentSession("aaj ka weather, news aur meri reminders batao", mode="owner")
        session.advance(runtime, QuickPlanner())
        self.assertEqual([s["tool"] for s in session.steps],
                         ["system.get_time", "web.weather", "reminder.list", "web.news"])   # nothing skipped
        self.assertEqual(session.status, "done")
        for part in ("10:42 AM", "stretch", "Check the weather: not done", "not done"):
            self.assertIn(part, session.reply)

    def test_a_failed_action_still_stops_the_plan(self):
        # negative: only lookups continue after a failure; an action re-plans as before
        from chutku.agent_loop import AgentSession
        from tests.agent_fakes import FakeRuntime, ScriptedPlanner, continue_with
        runtime = FakeRuntime(fail={"apps.launch"})
        session = AgentSession("spotify kholo aur volume 30 karo", mode="owner")
        session.advance(runtime, ScriptedPlanner(
            continue_with({"tool": "apps.launch", "arguments": {"name": "Spotify"}},
                          {"tool": "audio.volume", "arguments": {"level": 30}}),
            {"status": "clarify", "reply": "Spotify did not open.", "declared_plan": [], "next_steps": [],
             "finish": False}))
        self.assertEqual([s["tool"] for s in session.steps], ["apps.launch"])

    def test_the_weather_says_no_internet_instead_of_asking_for_a_city(self):
        from unittest.mock import patch
        from chutku.tools import internet
        context = SimpleNamespace(memory=None)
        with patch.object(internet, "fetch", side_effect=OSError("no route")):
            result = internet._weather({}, context)
        self.assertIn("No internet", result.output["error"])
        self.assertNotIn("Which city", result.output["error"])

    def test_research_still_gets_the_models_answer(self):
        # a step without a builder (web.results): the model's synthesis is kept
        from chutku.agent_loop import AgentSession
        from tests.agent_fakes import FakeRuntime, ScriptedPlanner, continue_with
        runtime = FakeRuntime({"web.results": {"results": [{"title": "Python 3.14", "url": "u"}]}})
        session = AgentSession("python ka latest version kya hai", mode="owner")
        session.advance(runtime, ScriptedPlanner(
            continue_with({"tool": "web.results", "arguments": {"query": "python latest version"}}),
            {"status": "done", "reply": "Python 3.14 latest hai.", "declared_plan": [], "next_steps": [],
             "finish": True}))
        self.assertTrue(session.reply.startswith("Python 3.14 latest hai."), session.reply)

    def test_an_unexpected_shape_still_leaves_it_to_the_model(self):
        # strict builders: a wrong fixed reply is worse than the model's
        self.assertIsNone(quick_answer(SimpleNamespace(goal="weather in indore", steps=[
            step("web.weather", {"place": "X"})])))


if __name__ == "__main__":
    unittest.main()
