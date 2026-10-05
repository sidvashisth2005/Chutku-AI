"""Routing fixes from the audit, written with the owner's real phrasing (master plan S7)."""
from datetime import datetime
import unittest
from unittest.mock import patch

from chutku import agent_loop
from chutku.dashboard import message_for_person
from chutku.quick_intents import quick_proposal

APPS = [{"name": "Spotify", "app_id": "spotify"}, {"name": "Notepad", "app_id": "notepad"}]


def tools(goal):
    proposal = quick_proposal(goal, apps=APPS)
    return None if proposal is None else [(s["tool"], s["arguments"]) for s in proposal["next_steps"]]


class RoutingFixTests(unittest.TestCase):
    def test_searching_a_named_folder_looks_in_that_folder(self):
        with patch.dict("os.environ", {"USERPROFILE": r"C:\Users\owner"}):
            self.assertEqual(tools("search my downloads for invoice"),
                             [("files.find", {"path": r"C:\Users\owner\Downloads", "query": "invoice"})])

    def test_cpu_temperature_is_not_weather(self):
        for goal in ("temperature of my cpu", "what is the cpu temperature", "laptop temperature kitna hai"):
            self.assertEqual(tools(goal), [("system.performance", {})], goal)
        self.assertEqual(tools("weather in Pune"), [("web.weather", {"city": "Pune"})])

    def test_call_it_a_day_is_not_a_phone_call(self):
        self.assertIsNone(tools("call it a day"))

    def test_remind_me_at_5_means_the_evening(self):
        steps = tools("remind me at 5 to call papa")
        self.assertEqual(steps[0][0], "reminder.set")
        self.assertEqual(datetime.fromisoformat(steps[0][1]["at"]).hour, 17)
        self.assertEqual(datetime.fromisoformat(tools("remind me at 9 am to study")[0][1]["at"]).hour, 9)

    def test_long_phrases_are_not_guessed_as_app_names(self):
        self.assertIsNone(tools("open the big blue app with icons"))
        self.assertEqual(tools("open spotify"), [("apps.launch", {"name": "Spotify"})])

    def test_hindi_open_words_count_as_actions(self):
        self.assertTrue(agent_loop._ACTION_WORDS.search("kya tum notepad khol sakti ho"))

    def test_say_to_a_person_is_not_spoken_aloud(self):
        self.assertTrue(message_for_person("voice.speak", "say good night to mammi"))
        self.assertTrue(message_for_person("voice.speak", "mammi ko bolo good night"))
        self.assertFalse(message_for_person("voice.speak", "say hello"))
        self.assertFalse(message_for_person("system.get_time", "say good night to mammi"))


if __name__ == "__main__":
    unittest.main()
