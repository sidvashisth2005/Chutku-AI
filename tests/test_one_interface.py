"""Never two Chutku windows, and never the old one (owner 2026-11-11: "pressing the hotkey activates two Chutku: the
previous interface and the current one ... remove"). The old Tk HUD started whenever the presence window had not
appeared within 8 s, while the presence process kept running and showed its window later (log: "did not appear (exit
code None); using the HUD", 5 times 2026-11-05..10)."""
import types
import unittest
from unittest.mock import patch

from chutku import presence
from chutku.dashboard_presence import DashboardPresence


class FakeProcess:
    def __init__(self, alive=True):
        self.alive, self.pid, self.killed = alive, 4242, False

    def poll(self):
        return None if self.alive else 1


def server(process, restart_ok=False):
    fake = types.SimpleNamespace(presence_process=process, hud=None, started=[], restarts=[])
    fake.start_hud = lambda: fake.started.append("hud")
    fake.start_presence = lambda retries=1: (fake.restarts.append(retries), restart_ok)[1]
    return fake


class OneInterfaceTests(unittest.TestCase):
    def watch(self, fake, windows, **kwargs):
        notes = []
        with patch.object(presence, "window_exists", side_effect=lambda title=presence.TITLE: title in windows), \
                patch("chutku.dashboard_presence._end_process_tree",
                      side_effect=lambda process: setattr(process, "killed", True)), \
                patch("chutku.health.notify", side_effect=lambda title, text: notes.append(text)):
            DashboardPresence.watch_presence(fake, wait=0.3, poll=0.05, **kwargs).join(2)
        return notes

    def test_the_bar_window_counts_as_the_presence_window(self):
        fake = server(FakeProcess())
        self.watch(fake, {presence.BAR_TITLE})
        self.assertEqual((fake.started, fake.restarts), ([], []))

    def test_a_presence_that_never_shows_is_ended_and_started_again_never_the_old_hud(self):
        process = FakeProcess()
        fake = server(process)
        self.watch(fake, set())
        self.assertTrue(process.killed)                          # its late window can never pop up beside another
        self.assertEqual(fake.restarts, [0])                     # one more try
        self.assertEqual(fake.started, [])                       # the old HUD never opens

    def test_a_second_failure_says_where_chutku_is(self):
        fake = server(FakeProcess(alive=False))
        notes = self.watch(fake, set(), retries=0)
        self.assertEqual((fake.started, fake.restarts), ([], []))
        self.assertIn("tray icon", notes[0])

    def test_the_default_wait_allows_a_slow_cold_start(self):
        import inspect
        self.assertGreaterEqual(inspect.signature(DashboardPresence.watch_presence).parameters["wait"].default, 30)


if __name__ == "__main__":
    unittest.main()
