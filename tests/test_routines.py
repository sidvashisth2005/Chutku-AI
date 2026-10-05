from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import routines
from chutku.app import create_runtime
from chutku.quick_intents import quick_proposal

APPS = [{"name": "Spotify", "app_id": "Spotify.App"}, {"name": "Visual Studio Code", "app_id": "Microsoft.VSCode"}]


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.patcher = patch("chutku.routines.store_path", return_value=self.base / "data" / "routines.json")
        self.patcher.start()
        self.apps = patch("chutku.quick_intents._installed_apps", return_value=APPS)
        self.apps.start()
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.apps.stop()
        self.patcher.stop()
        self.temp.cleanup()

    def test_save_by_chat_then_start_runs_all_steps(self):
        save = quick_proposal("save routine work: open spotify, open visual studio code, set volume to 30", apps=APPS)
        step = save["next_steps"][0]
        self.assertEqual(step["tool"], "routine.save")
        result = self.runtime.run(step["tool"], step["arguments"])
        self.assertEqual(result["state"], "COMPLETED", result)
        started = quick_proposal("start work mode", apps=APPS)
        self.assertEqual([s["tool"] for s in started["next_steps"]], ["apps.launch", "apps.launch", "audio.volume"])
        self.assertEqual(quick_proposal("work mode on karo", apps=APPS)["next_steps"], started["next_steps"])

    def test_unknown_or_risky_commands_are_refused_at_save(self):
        result = self.runtime.run("routine.save", {"name": "bad", "commands": ["open spotify", "delete all my files"]})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("delete all my files", result["output"]["error"])
        self.assertNotIn("bad", routines.load())

    def test_limits_and_names(self):
        too_many = ["open spotify"] * 5
        self.assertEqual(self.runtime.run("routine.save", {"name": "x", "commands": too_many})["state"], "FAILED")
        self.assertEqual(self.runtime.run("routine.save", {"name": "../x", "commands": ["open spotify"]})["state"],
                         "FAILED")

    def test_unknown_routine_falls_through_and_list_forget(self):
        self.assertIsNone(quick_proposal("start party mode", apps=APPS))
        self.runtime.run("routine.save", {"name": "focus", "commands": ["mute"]})
        listed = self.runtime.run("routine.list", {})
        self.assertIn("focus", listed["output"]["routines"])
        waiting = self.runtime.run("routine.forget", {"name": "focus"})
        self.assertEqual(waiting["state"], "WAITING_CONFIRMATION")  # deleting always asks
        self.assertEqual(self.runtime.approve(waiting["approval"]["token"])["state"], "COMPLETED")
        self.assertNotIn("focus", routines.load())


if __name__ == "__main__":
    unittest.main()
