"""H26: the doctor repairs only what is safe, keeps what it replaces, and changes nothing without --fix."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku import doctor, history_index, recall
from chutku.core.action_control import ActionControl


def digest(folder):
    h = hashlib.sha256()
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(folder)).encode() + path.read_bytes())
    return h.hexdigest()


def states(report):
    return {row["name"]: row["state"] for row in report["checks"]}


class FakeBrain:
    def __init__(self, running):
        self.running, self.started = running, 0

    def status(self):
        return {"running": self.running, "backend": "vulkan"}

    def ensure_started(self):
        self.started += 1
        self.running = True


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        recall.log_conversation("DBMS notes kal banane hain", "Theek hai.", base=self.base, at=1000.0)
        recall.log_conversation("zebra secret", "Ok.", base=self.base, at=2000.0)
        recall.forget_last(self.base)                         # H29: hidden from search
        history_index.db_path(self.base).write_bytes(b"this is not sqlite" * 100)   # damaged index

    def test_read_only_mode_changes_nothing(self):
        ActionControl(self.base).pause("guard", "hang")
        before = digest(self.base / "data")
        report = doctor.repair(self.base, fix=False, brain=FakeBrain(False))
        self.assertEqual(digest(self.base / "data"), before)
        self.assertEqual(states(report)["History index"], "broken")
        self.assertEqual(states(report)["Pause"], "broken")

    def test_fix_rebuilds_the_index_keeps_the_damaged_copy_and_keeps_forgotten_turns_hidden(self):
        report = doctor.repair(self.base, fix=True)
        self.assertEqual(states(report)["History index"], "fixed")
        kept = list((self.base / "data").glob("history.db.broken-*"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(history_index.search(self.base, "DBMS")["matches"]), 1)
        self.assertEqual(history_index.search(self.base, "zebra")["matches"], [])   # still forgotten after rebuild
        again = doctor.repair(self.base, fix=True)                                  # idempotent
        self.assertEqual(states(again)["History index"], "ok")
        self.assertEqual(len(list((self.base / "data").glob("history.db.broken-*"))), 1)

    def test_the_owners_pause_is_never_lifted(self):
        ActionControl(self.base).pause("owner", "asked")
        report = doctor.repair(self.base, fix=True)
        self.assertEqual(states(report)["Pause"], "report")
        self.assertTrue(ActionControl(self.base).paused)

    def test_the_watchdog_pause_is_lifted(self):
        ActionControl(self.base).pause("guard", "hang")
        self.assertEqual(states(doctor.repair(self.base, fix=True))["Pause"], "fixed")
        self.assertFalse(ActionControl(self.base).paused)

    def test_the_local_model_is_started_once(self):
        brain = FakeBrain(False)
        self.assertEqual(states(doctor.repair(self.base, fix=True, brain=brain))["Local model"], "fixed")
        self.assertEqual(states(doctor.repair(self.base, fix=True, brain=brain))["Local model"], "ok")
        self.assertEqual(brain.started, 1)

    def test_a_damaged_embeddings_cache_is_moved_aside(self):
        (self.base / "data" / "embeddings.sqlite").write_bytes(b"x" * 500)
        self.assertEqual(states(doctor.repair(self.base, fix=True))["Embeddings cache"], "fixed")
        self.assertFalse((self.base / "data" / "embeddings.sqlite").exists())
        self.assertEqual(len(list((self.base / "data").glob("embeddings.sqlite.broken-*"))), 1)

    def test_summary_and_phrase(self):
        from chutku.daily_intent import parse_daily
        self.assertEqual(parse_daily("khud ko theek karo")[:2], ("system.self_repair", {"fix": True}))
        self.assertEqual(parse_daily("apna checkup karo")[:2], ("system.self_repair", {"fix": False}))
        report = doctor.repair(self.base, fix=True)
        self.assertIn("History index", doctor.summary(report))
        json.dumps(report)   # the dashboard and CLI print it


class ReindexTests(unittest.TestCase):
    def test_a_rotated_log_keeps_forgotten_turns_hidden(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            recall.log_conversation("zebra secret", "Ok.", base=base, at=2000.0)
            recall.forget_last(base)
            history_index.db_path(base).unlink()       # the index is rebuilt from scratch
            self.assertEqual(history_index.search(base, "zebra")["matches"], [])


if __name__ == "__main__":
    unittest.main()
