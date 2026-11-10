"""The task table (owner 2026-11-10): synthetic workflows for every kind of user, looked up by the normalised sentence.
Every ready plan must name real tools with arguments those tools accept, and an app action is used only once the
Action Lab verified it."""
from pathlib import Path
import tempfile
import unittest

from chutku import task_table
from chutku.app import create_runtime


class TaskTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.runtime = create_runtime(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()
        cls.temp.cleanup()

    def test_every_plan_uses_real_tools_with_valid_arguments(self):
        rows = task_table.rows()
        self.assertGreaterEqual(len(rows), 120)
        self.assertGreaterEqual({p for r in rows for p in r["personas"]}, {"genz", "office", "student", "elder"})
        self.assertEqual({r["lang"] for r in rows}, {"en", "hinglish", "hi"})
        tools = self.runtime.registry._tools
        for row in rows:
            for step in row.get("steps", []):
                self.assertIn(step["tool"], tools, row["id"])
                tools[step["tool"]].validate_arguments(step["arguments"])

    def test_one_sentence_one_plan(self):
        keys = [task_table.key(r["say"]) for r in task_table.rows()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_known_request_is_one_lookup_in_any_wording_style(self):
        for said in ("aaj ka mausam", "Aaj ka mausam?", "मौसम कैसा है"):
            proposal = task_table.lookup(said, verified={})
            self.assertEqual([s["tool"] for s in proposal["next_steps"]], ["web.weather"], said)
        self.assertIsNone(task_table.lookup("aaj ka mausam aur kal ka bhi", verified={}))

    def test_an_app_action_waits_for_the_lab(self):
        self.assertIsNone(task_table.lookup("open scientific calculator", verified={}))
        proposal = task_table.lookup("open scientific calculator", verified={"calculator": {"scientific"}})
        self.assertEqual(proposal["next_steps"][0]["tool"], "app.calculator.scientific")

    def test_the_instant_router_uses_the_table_for_gaps_only_and_damage_is_still_refused(self):
        from chutku.quick_intents import quick_proposal
        self.assertEqual(quick_proposal("start my work day")["task_table"], "start_day-0")
        self.assertNotIn("task_table", quick_proposal("show my recent files"))   # the hand-written route wins
        # live bug 2026-11-10: the fuzzy app match opened Word for "start my work day"
        self.assertEqual(quick_proposal("start word")["next_steps"][0]["arguments"], {"name": "Word"})
        self.assertNotIn({"name": "Word"}, [st["arguments"] for st in quick_proposal("start my work day")["next_steps"]])
        # persona exam 2026-11-10: "gmail kholo" opened the Mail app; "awaaz band karo" closed an app named "awaaz"
        self.assertEqual(quick_proposal("gmail kholo")["next_steps"][0]["tool"], "web.open")
        self.assertEqual(quick_proposal("awaaz band karo")["next_steps"][0], {**quick_proposal("awaaz band karo")[
            "next_steps"][0], "tool": "audio.volume", "arguments": {"action": "mute"}})
        self.assertEqual(quick_proposal("Open sport")["next_steps"][0]["arguments"], {"name": "Spotify"})   # still fuzzy
        refused = quick_proposal(r"delete C:\Windows\System32")
        self.assertNotIn("task_table", refused or {})


if __name__ == "__main__":
    unittest.main()
