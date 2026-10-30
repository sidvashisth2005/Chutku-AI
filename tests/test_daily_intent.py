"""Everyday Hinglish from a 45-phrase real-life sweep (2026-10-04): 21 had missed or gone wrong."""
from datetime import datetime
import unittest

from chutku.daily_intent import _at, parse_daily
from chutku.quick_intents import quick_proposal

APPS = [{"name": n, "app_id": n} for n in ("Brave", "WhatsApp", "Spotify", "Calculator", "Notepad", "Settings")]


def steps(text):
    proposal = quick_proposal(text, apps=APPS)
    if proposal is None:
        return None
    return [(s["tool"], s["arguments"]) for s in proposal["next_steps"]] or ["reply"]


class DailyPhraseTests(unittest.TestCase):
    def test_media_volume_brightness_screenshot(self):
        self.assertEqual(steps("agla gaana"), [("media.control", {"action": "next"})])
        self.assertEqual(steps("pichla gaana"), [("media.control", {"action": "previous"})])
        self.assertEqual(steps("volume thoda badhao"), [("audio.volume", {"action": "up"})])
        self.assertEqual(steps("awaaz thodi kam karo"), [("audio.volume", {"action": "down"})])
        self.assertEqual(steps("brightness full karo"), [("display.brightness", {"action": "set", "level": 100})])
        self.assertEqual(steps("screen ki brightness 50 karo"), [("display.brightness", {"action": "set", "level": 50})])
        self.assertIsNone(steps("brightness 500 karo"))
        self.assertEqual(steps("screenshot lo"), [("keyboard.keys", {"keys": "win+printscreen"})])

    def test_timers_and_alarms(self):
        self.assertEqual(steps("10 minute ka timer lagao"),
                         [("reminder.set", {"message": "Timer done", "in_minutes": 10})])
        self.assertEqual(steps("2 ghante ka timer lagao")[0][1]["in_minutes"], 120)
        now = datetime(2026, 10, 4, 17, 30)
        tool, args, *_ = parse_daily("kal subah 7 baje ka alarm lagao", now)
        self.assertEqual((tool, args["at"]), ("reminder.set", "2026-10-05T07:00"))
        tool, args, *_ = parse_daily("mujhe 5 baje yaad dilana meeting hai", now)
        self.assertEqual((args["at"], args["message"]), ("2026-10-05T17:00", "meeting hai"))   # 5 PM passed today
        tool, args, *_ = parse_daily("raat 10 baje yaad dilana ki dawai leni hai", now)
        self.assertEqual((args["at"], args["message"]), ("2026-10-04T22:00", "dawai leni hai"))

    def test_time_convention(self):
        now = datetime(2026, 10, 4, 9, 0)
        self.assertEqual(_at(None, None, 5, 0, now).hour, 17)      # "5 baje" = 5 PM
        self.assertEqual(_at(None, None, 9, 30, now).hour, 9)      # "9:30 baje" = morning
        self.assertEqual(_at(None, "subah", 6, 0, now), datetime(2026, 10, 5, 6, 0))

    def test_spotify_score_screen_time(self):
        self.assertEqual(steps("spotify pe arijit singh chalao"), [("spotify.search", {"query": "arijit singh"})])
        self.assertEqual(steps("cricket score kya hai"), [("web.search", {"query": "cricket score live", "site": "google"})])
        self.assertEqual(steps("yeh kya hai")[0][0], "screen.ask")   # W5: the fast screen copilot
        self.assertEqual(steps("mujhe batao time kya hai"), [("system.get_time", {})])
        self.assertEqual(steps("instagram kholo brave mein"),
                         [("web.open", {"url": "https://www.instagram.com", "browser": "brave"})])

    def test_tell_someone_and_honest_answers(self):
        self.assertEqual(steps("pita shri ko bolo main late aaunga"),
                         [("message.send", {"app": "whatsapp", "to": "pita shri", "text": "main late aaunga"})])
        self.assertEqual(steps("mammi ko call karo"), ["reply"])
        self.assertIn("can't make calls", quick_proposal("mammi ko call karo", apps=APPS)["reply"])
        self.assertEqual(steps("recycle bin khali karo"), ["reply"])

    def test_never_the_wrong_thing(self):
        for text in ("wifi band karo", "bluetooth on karo", "close wifi", "internet band karo"):
            for tool, args in (steps(text) or []) if steps(text) != ["reply"] else []:
                self.assertNotIn(tool, ("apps.quit", "apps.launch"), text)     # wifi is not an app
        for text in ("mujhe yaad dilana 5 baje", "sabko bolo hi", "mujhe batao kya hua"):
            for item in steps(text) or []:
                self.assertFalse(isinstance(item, tuple) and item[0] == "message.send", text)


if __name__ == "__main__":
    unittest.main()
