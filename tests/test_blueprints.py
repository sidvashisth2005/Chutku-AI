"""H23: blueprints create exactly the previewed task.schedule steps; shortcuts are checked routines."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import blueprints, routines
from chutku.quick_intents import quick_proposal

from tests.agent_fakes import real_registry

NOW = datetime(2026, 11, 6, 22, 15)   # a Friday night


class BlueprintTests(unittest.TestCase):
    def test_each_blueprint_builds_valid_schedule_steps(self):
        registry = real_registry()
        schedule = registry.get("task.schedule")
        for name, item in blueprints.CATALOG.items():
            slots = {slot: "cricket" for slot, value in item["slots"].items() if value is None}
            now = datetime.now()   # the real contract checks against the real clock
            steps = blueprints.build(name, slots)
            self.assertEqual([s["tool"] for s in steps], ["task.schedule"], name)
            schedule.validate_arguments(steps[0]["arguments"])   # the real contract, incl. "no time inside the goal"
            at = datetime.fromisoformat(steps[0]["arguments"]["at"])
            self.assertGreater(at, now.replace(second=0, microsecond=0), name)

    def test_times_and_days(self):
        step = blueprints.build("morning-briefing", {"time": "7:30"}, NOW)[0]["arguments"]
        self.assertEqual((step["at"], step["every_minutes"]), ("2026-11-07T07:30", 1440))
        step = blueprints.build("weekly-backup", {"day": "mon"}, NOW)[0]["arguments"]
        self.assertEqual((step["at"], step["every_minutes"]), ("2026-11-09T21:00", 10080))
        step = blueprints.build("weekly-insights", {"day": "friday", "time": "23:00"}, NOW)[0]["arguments"]
        self.assertEqual(step["at"], "2026-11-06T23:00")    # later today

    def test_slot_validation(self):
        for name, slots in (("nope", {}), ("news-digest", {}), ("morning-briefing", {"time": "25:00"}),
                            ("weekly-backup", {"day": "someday"}), ("news-digest", {"topic": "x;rm -rf /"}),
                            ("morning-briefing", {"colour": "red"})):
            with self.assertRaises(ValueError, msg=(name, slots)):
                blueprints.build(name, slots, NOW)

    def test_phrases_preview_exactly_what_is_created(self):
        with patch("chutku.blueprints.datetime") as clock:
            clock.now.return_value = NOW
            proposal = quick_proposal("subah ka briefing set karo 8 baje")
        self.assertEqual(proposal["next_steps"][0]["arguments"]["at"], "2026-11-07T08:00")
        self.assertEqual(proposal["declared_plan"], [proposal["next_steps"][0]["purpose"]])
        self.assertEqual(quick_proposal("automation news-digest")["status"], "clarify")
        self.assertEqual(quick_proposal("kaun si automations hain")["next_steps"][0]["tool"], "blueprint.list")
        self.assertEqual(quick_proposal("har roz cricket ki news batana")["next_steps"][0]["arguments"]["goal"],
                         "cricket ki latest news batao")

    def test_the_list_tool(self):
        out = real_registry_with_blueprints().get("blueprint.list").execute({}, None).output
        self.assertEqual(len(out["automations"]), len(blueprints.CATALOG))
        self.assertIn("morning-briefing", out["summary"])


def real_registry_with_blueprints():
    registry = real_registry()
    blueprints.register_blueprint_tools(registry)
    return registry


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(routines, "store_path", return_value=Path(self.temp.name) / "routines.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, text):
        proposal = quick_proposal(text)
        step = proposal["next_steps"][0]
        self.assertEqual(step["tool"], "routine.save")
        return real_registry().get("routine.save").execute(step["arguments"], None)

    def test_a_shortcut_is_saved_and_runs_by_its_name(self):
        result = self.save("jab main 'padhai time' bolun to volume 30 karo aur lock the pc")
        self.assertEqual(result.verification, "PASS", result.output)
        run = quick_proposal("padhai time")
        self.assertEqual([s["tool"] for s in run["next_steps"]], ["audio.volume", "system.lock"])
        self.assertTrue(run["finish"])

    def test_a_shortcut_with_an_unparsable_step_is_refused(self):
        result = self.save("when i say 'night mode', set volume to 10 and write my thesis introduction")
        self.assertEqual(result.verification, "FAIL")
        self.assertIn("write my thesis introduction", result.output["error"])
        self.assertIsNone(quick_proposal("night mode"))      # nothing was saved

    def test_saying_an_unknown_name_is_not_a_shortcut(self):
        self.assertIsNone(quick_proposal("padhai time"))


if __name__ == "__main__":
    unittest.main()
