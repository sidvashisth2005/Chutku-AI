from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.tools import reminders


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.runtime.capability_grants.grant("reminders.manage")
        self.tasks = {}
        store = Path(self.temp.name) / "data" / "reminders.json"
        self.patches = [patch.object(reminders, "store_path", return_value=store),
                        patch.object(reminders, "scheduler", side_effect=self.fake_scheduler)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.runtime.close()
        self.temp.cleanup()

    def fake_scheduler(self, request):
        if request["action"] == "register":
            self.tasks[request["id"]] = request["at"]
            self.assertNotIn("message", request)  # the message never reaches the task command line
        if request["action"] == "unregister":
            self.tasks.pop(request["id"], None)
        return dict(self.tasks)

    def test_set_list_cancel(self):
        created = self.runtime.run("reminder.set", {"message": "drink water", "in_minutes": 10})
        self.assertEqual(str(created["state"]), "COMPLETED", created)
        rid = created["output"]["id"]
        listed = self.runtime.run("reminder.list", {})["output"]["upcoming"]
        self.assertEqual([(r["id"], r["message"]) for r in listed], [(rid, "drink water")])
        cancelled = self.runtime.run("reminder.cancel", {"id": rid})
        self.assertTrue(cancelled["output"]["cancelled"])
        self.assertEqual(self.runtime.run("reminder.list", {})["output"]["upcoming"], [])

    def test_in_minutes_rounds_up_never_early(self):
        now = datetime(2026, 9, 30, 20, 50, 55)
        self.assertEqual(reminders._parse_when({"in_minutes": 1}, now), datetime(2026, 9, 30, 20, 52))
        self.assertEqual(reminders._parse_when({"in_minutes": 1}, datetime(2026, 9, 30, 20, 50)),
                         datetime(2026, 9, 30, 20, 51))

    def test_validation(self):
        validate = self.runtime.registry.get("reminder.set").validate_arguments
        past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        far = (datetime.now() + timedelta(days=400)).strftime("%Y-%m-%dT%H:%M")
        for bad in ({"message": "x"}, {"message": "x", "in_minutes": 5, "at": "2026-10-01T10:00"},
                    {"message": "", "in_minutes": 5}, {"message": "x", "in_minutes": 0},
                    {"message": "x", "at": past}, {"message": "x", "at": far}, {"message": "x", "at": "tomorrow 9am"}):
            with self.assertRaises(ValueError, msg=bad):
                validate(bad)
        with self.assertRaises(ValueError):
            self.runtime.registry.get("reminder.cancel").validate_arguments({"id": "../../x"})

    def test_scheduler_failure_leaves_no_orphan(self):
        with patch.object(reminders, "scheduler", side_effect=OSError("denied")):
            result = self.runtime.run("reminder.set", {"message": "x", "in_minutes": 3})
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertEqual(reminders.load(), {})

    def test_capability_required(self):
        self.runtime.capability_grants.revoke("reminders.manage")
        self.assertEqual(str(self.runtime.run("reminder.set", {"message": "x", "in_minutes": 3})["state"]), "DENIED")


if __name__ == "__main__":
    unittest.main()
