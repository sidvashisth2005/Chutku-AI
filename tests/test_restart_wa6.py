"""WA6: a clean restart never leaves Chutku paused; the emergency stop still does (on purpose)."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from chutku import control_intent, restart
from chutku.core.action_control import ActionControl


class RestartTests(unittest.TestCase):
    def test_a_restart_asks_the_guard_to_quit_and_starts_a_helper(self):
        with TemporaryDirectory() as temp:
            spawned = []
            message = restart.request(temp, spawn=lambda argv, base: spawned.append(argv))
            self.assertEqual((Path(temp) / "data" / "guard.stop").read_text(encoding="utf-8"), "quit")
            self.assertFalse(ActionControl(Path(temp)).paused)
            self.assertEqual(spawned[0][1:3], ["-m", "chutku.restart"])
            self.assertIn("restart", message)

    def test_the_emergency_stop_still_pauses(self):   # negative case: stop is not a restart
        with TemporaryDirectory() as temp:
            ActionControl(Path(temp)).stop()
            self.assertTrue(ActionControl(Path(temp)).paused)
            self.assertNotEqual((Path(temp) / "data" / "guard.stop").read_text(encoding="utf-8"), "quit")

    def test_the_helper_waits_for_the_guard_then_starts_once(self):
        with TemporaryDirectory() as temp:
            running = Path(temp) / "data" / "guard.running"
            running.parent.mkdir()
            running.write_text("1")
            started, ticks = [], [0]

            def sleep(_):
                ticks[0] += 1
                if ticks[0] == 3:
                    running.unlink()
            self.assertTrue(restart.wait_and_start(temp, start=lambda: started.append(1), sleep=sleep))
            self.assertEqual((started, ticks[0]), ([1], 3))
            running.write_text("1")   # the old Chutku never finished: do not start a second one
            now = [0.0]
            self.assertFalse(restart.wait_and_start(temp, start=lambda: started.append(2), sleep=lambda s: None,
                                                    clock=lambda: now.__setitem__(0, now[0] + 1) or now[0]))
            self.assertEqual(started, [1])

    def test_the_phrase(self):
        for said in ("chutku restart karo", "restart chutku", "khud ko restart karo"):
            self.assertEqual(control_intent.kind(said), "restart", said)
        for said in ("restart karo", "restart the pc", "laptop restart karo"):   # the PC, not Chutku
            self.assertNotEqual(control_intent.kind(said), "restart", said)

    @unittest.skipUnless(sys.platform == "win32", "the tray module is Windows-only")
    def test_the_tray_has_restart(self):
        from chutku.tray import RESTART, STOP, menu_items
        items = [i for i in menu_items(False, True) if i]
        self.assertIn((RESTART, "Restart Chutku", True), items)
        self.assertEqual([i[2] for i in menu_items(False, False) if i and i[0] in (RESTART, STOP)], [False, False])

    def test_the_dashboard_says_why_it_cannot_restart_without_the_guard(self):
        from test_setup_page_w5 import Server
        with TemporaryDirectory() as temp:
            web = Server(temp)
            try:
                status, body = web.call("POST", "/api/control", {"action": "restart"})
                self.assertEqual(status, 409)
                self.assertIn("Start menu", body["error"])
                self.assertFalse((Path(temp) / "data" / "guard.stop").exists())
            finally:
                web.close()


if __name__ == "__main__":
    unittest.main()
