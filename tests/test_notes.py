from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import notes
from chutku.app import create_runtime
from chutku.quick_intents import quick_proposal


def step(text):
    proposal = quick_proposal(text, apps=[])
    return None if proposal is None else (proposal["next_steps"][0]["tool"], proposal["next_steps"][0]["arguments"])


class NoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch("chutku.notes.store_path", return_value=Path(self.temp.name) / "data" / "notes.json")
        self.patch.start()
        self.runtime = create_runtime(Path(self.temp.name))

    def tearDown(self):
        self.runtime.close()
        self.patch.stop()
        self.temp.cleanup()

    def test_add_list_done_and_reopen(self):
        for text in ("buy milk", "call mom"):
            self.assertEqual(self.runtime.run("note.add", {"text": text})["state"], "COMPLETED")
        listed = self.runtime.run("note.list", {})["output"]["items"]
        self.assertEqual([(i["id"], i["text"], i["done"]) for i in listed], [(1, "buy milk", False), (2, "call mom", False)])
        self.assertEqual(self.runtime.run("note.done", {"id": 1})["state"], "COMPLETED")
        self.assertTrue(self.runtime.run("note.list", {})["output"]["items"][-1]["done"])
        self.runtime.run("note.done", {"id": 1, "done": False})
        self.assertFalse(any(i["done"] for i in self.runtime.run("note.list", {})["output"]["items"]))
        self.assertEqual(self.runtime.run("note.done", {"id": 99})["state"], "FAILED")

    def test_old_finished_items_are_hidden(self):
        now = datetime(2026, 10, 3, 12, 0)
        items = [{"id": 1, "text": "old", "done": (now - timedelta(days=9)).isoformat(timespec="minutes")},
                 {"id": 2, "text": "recent", "done": (now - timedelta(days=1)).isoformat(timespec="minutes")},
                 {"id": 3, "text": "open", "done": None}]
        self.assertEqual([i["text"] for i in notes.visible(items, now)], ["open", "recent"])

    def test_phrases(self):
        self.assertEqual(step("note: buy milk"), ("note.add", {"text": "buy milk"}))
        self.assertEqual(step("note that the meeting is at 5"), ("note.add", {"text": "the meeting is at 5"}))
        self.assertEqual(step("add call mom to my list"), ("note.add", {"text": "call mom"}))
        self.assertEqual(step("likh lo: pay the bill"), ("note.add", {"text": "pay the bill"}))
        for text in ("show my list", "my todo list", "meri list dikhao"):
            self.assertEqual(step(text), ("note.list", {}), text)
        self.assertIsNone(step("show my list of bad ideas please explain"))
        self.assertEqual(step("mark 2 done"), ("note.done", {"id": 2, "done": True}))
        self.assertEqual(step("mark 3 as not done"), ("note.done", {"id": 3, "done": False}))
        self.assertEqual(step("2 ho gaya"), ("note.done", {"id": 2, "done": True}))


if __name__ == "__main__":
    unittest.main()
