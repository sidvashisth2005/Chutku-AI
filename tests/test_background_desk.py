"""Background Desk (owner 2026-11-10): Chutku works in apps behind the owner's window without taking his screen,
mouse or keyboard. Fakes stand in for Windows; the live measurement is scripts/background_probe.py."""
import time
import unittest
from unittest import mock

from chutku import background_desk as desk


class TypingPauseTests(unittest.TestCase):
    def test_waits_for_a_pause_in_the_owners_typing_and_never_forever(self):
        idle = iter([0.1, 0.2, 0.3, 0.9])
        slept = []
        self.assertTrue(desk.typing_pause(0.7, 8.0, idle=lambda: next(idle), sleep=slept.append))
        self.assertEqual(len(slept), 3)                                   # waited while he typed
        self.assertFalse(desk.typing_pause(0.7, 0.5, idle=lambda: 0.0, sleep=lambda s: None))   # gives up at the limit


class FocusGuardTests(unittest.TestCase):
    def test_a_window_that_jumps_forward_is_handed_back_to_the_owner(self):
        state = {"front": 100}
        given = []

        def give_back(hwnd):
            given.append(hwnd)
            state["front"] = hwnd
            return True
        with desk.FocusGuard(foreground=lambda: state["front"], give_back=give_back, interval=0.005,
                             ours=lambda hwnd: hwnd == 555) as guard:
            state["front"] = 555                                         # the app Chutku opened took focus
            time.sleep(0.05)
        self.assertEqual(given[0], 100)
        self.assertTrue(guard.steals and guard.steals[0][1])
        self.assertEqual(state["front"], 100)

    def test_the_owners_own_switch_is_never_undone(self):
        """Live 2026-11-10: the first guard pulled the owner back from Brave 9 times in 5 s."""
        state = {"front": 100}
        with desk.FocusGuard(foreground=lambda: state["front"], give_back=lambda h: self.fail("fought the owner"),
                             interval=0.005, ours=lambda hwnd: hwnd == 555) as guard:
            state["front"] = 200                                         # he clicked over to Brave himself
            time.sleep(0.05)
        self.assertEqual((guard.steals, state["front"], guard.owner), ([], 200, 200))

    def test_nothing_happens_when_focus_stays_with_the_owner(self):
        with desk.FocusGuard(foreground=lambda: 100, give_back=lambda h: self.fail("no give back"),
                             interval=0.005, ours=lambda hwnd: True) as guard:
            time.sleep(0.02)
        self.assertEqual(guard.steals, [])


class LaunchTests(unittest.TestCase):
    def test_opens_minimized_without_activation_then_parks_it_behind(self):
        shown = [{"window_id": 1, "title": "Brave"}]
        started, parked = [], []

        def popen(command, **kwargs):
            started.append((command, kwargs.get("startupinfo")))
            shown.append({"window_id": 2, "title": "Untitled - Notepad"})

        class Guard:
            steals = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass
        info, steals = desk.launch("Microsoft.WindowsNotepad!App", lambda: list(shown), popen=popen,
                                   pause=lambda: True, guard=Guard, park_window=parked.append, sleep=lambda s: None)
        self.assertEqual(info["window_id"], 2)
        self.assertEqual(parked, [2])                                    # behind the owner's window
        command, startup = started[0]
        self.assertTrue(command[1].startswith("shell:AppsFolder\\"))     # a Start-menu app, never a shell string
        if startup is not None:
            self.assertEqual(startup.wShowWindow, 7)                     # SW_SHOWMINNOACTIVE
        self.assertIn(2, desk.opened())                                  # the warm pool remembers it
        desk.OPENED.pop(2, None)

    def test_no_window_means_failure_not_a_guess(self):
        info, _ = desk.launch("X!App", lambda: [{"window_id": 1, "title": "Brave"}], popen=lambda *a, **k: None,
                              pause=lambda: True, park_window=lambda h: self.fail("nothing to park"),
                              sleep=lambda s: None, wait=0.01)
        self.assertIsNone(info)

    def test_another_tasks_new_window_is_never_taken_for_this_app(self):
        """Parallel lanes: Calculator opening in the same second must not be parked as Settings' window."""
        shown, clock = [{"window_id": 1, "title": "Brave"}], [0.0]

        def popen(command, **kwargs):
            shown.append({"window_id": 7, "title": "Calculator"})   # the other task's app
        with mock.patch.object(desk.time, "monotonic", lambda: clock[0]):
            def sleep(seconds):
                clock[0] += seconds
            info, _ = desk.launch("Settings!App", lambda: list(shown), popen=popen, pause=lambda: True,
                                  guard=_NoGuard, park_window=lambda h: self.fail("not ours"), sleep=sleep, wait=2,
                                  ours=lambda item: item["title"] == "Settings")
        self.assertIsNone(info)

    def test_a_suspended_store_app_is_started_once_more_halfway(self):
        """Settings left suspended after its window closed ignored the first start (live 2026-11-10)."""
        shown, starts, clock = [{"window_id": 1, "title": "Brave"}], [], [0.0]

        def popen(command, **kwargs):
            starts.append(clock[0])
            if len(starts) == 2:
                shown.append({"window_id": 9, "title": "Settings"})
        with mock.patch.object(desk.time, "monotonic", lambda: clock[0]):
            def sleep(seconds):
                clock[0] += seconds
            info, _ = desk.launch("Settings!App", lambda: list(shown), popen=popen, pause=lambda: True,
                                  guard=_NoGuard, park_window=lambda h: None, sleep=sleep, wait=4)
        self.assertEqual(info["window_id"], 9)
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1], 2.0)
        desk.OPENED.pop(9, None)

    def test_guarded_step_waits_for_a_pause_and_reports_steals(self):
        order = []

        class Guard:
            def __init__(self):
                self.steals = [(20, True)]

            def __enter__(self):
                order.append("guard on")
                return self

            def __exit__(self, *_):
                order.append("guard off")
        result, steals = desk.guarded(lambda: order.append("act") or "ok", pause=lambda: order.append("pause"),
                                      guard=Guard)
        self.assertEqual((result, steals), ("ok", [(20, True)]))
        self.assertEqual(order, ["pause", "guard on", "act", "guard off"])


class LaunchToolTests(unittest.TestCase):
    def test_background_is_an_option_of_apps_launch_and_is_validated(self):
        from chutku.tools import everyday
        everyday._validate_launch({"name": "Notepad", "background": True})
        for bad in ({"name": "Notepad", "background": "yes"}, {"background": True}, {"name": "a", "app_id": "b"}):
            with self.assertRaises(ValueError, msg=bad):
                everyday._validate_launch(bad)


if __name__ == "__main__":
    unittest.main()


class _NoGuard:
    steals = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

