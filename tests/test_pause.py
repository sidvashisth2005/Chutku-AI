"""Background pause (Phase 3b H2): scheduled tasks and the Night Shift wait; the owner's own requests still work;
the pause fails safe (an empty, damaged or unreadable pause file still counts as paused)."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind, nightshift, pause, scheduled
from chutku.app import create_runtime
from chutku.quick_intents import quick_proposal
from chutku.router.catalog import CommandCatalog


class OneTick:
    """A stop event whose wait() lets the watcher loop run exactly once."""
    def __init__(self):
        self.calls = 0

    def wait(self, _seconds):
        self.calls += 1
        return self.calls > 1


class FakeServer:
    def __init__(self, base):
        self.base, self.started = base, []

    def begin_session(self, goal, *args, **kwargs):
        self.started.append(goal)

        class Session:
            id = "s1"
        return Session()


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        (self.base / "data").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_fails_safe(self):
        self.assertFalse(pause.engaged(self.base))
        pause.path(self.base).write_bytes(b"")
        self.assertTrue(pause.engaged(self.base))            # empty file
        pause.path(self.base).write_bytes(b"\x00garbage{")
        self.assertTrue(pause.engaged(self.base))            # damaged file
        self.assertTrue(pause.info(self.base)["paused"])
        pause.release(self.base)
        with patch("chutku.pause.os.stat", side_effect=PermissionError("denied")):
            self.assertTrue(pause.engaged(self.base))        # cannot check -> paused

    def test_engage_and_release(self):
        state = pause.engage(self.base, "test")
        self.assertTrue(state["paused"])
        self.assertEqual(state["reason"], "test")
        self.assertFalse(pause.release(self.base)["paused"])

    def due_job(self):
        scheduled.add(self.base, "set volume to 25", datetime.now() - timedelta(seconds=30))

    def test_scheduled_tasks_wait_and_stay_due(self):
        self.due_job()
        pause.engage(self.base)
        server = FakeServer(self.base)
        with patch.object(scheduled, "_announce"):
            scheduled.watch(server, OneTick(), tick=0)
        self.assertEqual(server.started, [])
        self.assertEqual(len(scheduled.active(self.base)), 1)   # still waiting, not consumed
        pause.release(self.base)
        with patch.object(scheduled, "_announce"):
            scheduled.watch(server, OneTick(), tick=0)
        self.assertEqual(server.started, ["set volume to 25"])

    def test_night_shift_skips_while_paused(self):
        pause.engage(self.base)
        with patch.object(nightshift, "on_ac_power", return_value=True), \
                patch.object(nightshift, "_run_jobs", side_effect=AssertionError("must not run")):
            report = nightshift.run_once(self.base)
        self.assertEqual(report["skipped"], "background work is paused")
        self.assertEqual(list(nightshift.report_dir(self.base).glob("report-*.json")), [])


class PauseToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.mind_root = patch.object(mind, "PROJECT_ROOT", self.base)
        self.mind_root.start()
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def test_anyone_may_pause_only_the_owner_resumes_and_own_requests_still_run(self):
        paused = self.runtime.run("background.pause", {}, provenance="delegated", autonomy="owner", tainted=False,
                                  exposed=False)
        self.assertEqual(str(paused["state"]), "COMPLETED", paused)
        self.assertTrue(pause.engaged(self.base))
        mine = self.runtime.run("system.get_time", {})
        self.assertEqual(str(mine["state"]), "COMPLETED")        # the owner's own request is not paused
        agent = self.runtime.run("background.resume", {}, provenance="delegated", autonomy="owner", tainted=False,
                                 exposed=False)
        self.assertEqual(str(agent["state"]), "DENIED")
        self.assertTrue(pause.engaged(self.base))
        typed = self.runtime.run("background.resume", {})
        self.assertEqual(str(typed["state"]), "COMPLETED", typed)
        self.assertFalse(pause.engaged(self.base))

    def test_phrases(self):
        catalog = CommandCatalog()
        for text, tool in (("background kaam roko", "background.pause"), ("pause background work", "background.pause"),
                           ("resume background work", "background.resume"),
                           ("background kaam shuru karo", "background.resume"),
                           ("is background paused?", "background.status")):
            self.assertEqual(catalog.route(text).tool_name, tool, text)
        self.assertEqual(quick_proposal("background kaam roko")["next_steps"][0]["tool"], "background.pause")
        self.assertIsNone(quick_proposal("resume background work"))   # resume is typed only, never by voice
        for text in ("pause", "stop", "scheduled tasks roko"):        # media pause / task cancel keep their meaning
            proposal = quick_proposal(text)
            tools = [s["tool"] for s in proposal.get("next_steps", [])] if proposal else []
            self.assertNotIn("background.pause", tools, text)


if __name__ == "__main__":
    unittest.main()
