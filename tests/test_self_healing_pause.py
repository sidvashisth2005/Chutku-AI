"""F1 (2026-10-29): a guard stop heals itself, the owner's pause never does, and a paused Chutku always answers."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from chutku.control_intent import kind
from chutku.core.action_control import ActionControl
from chutku.dashboard import DashboardServer, paused_explanation, paused_spoken


def counting_hung_child(connection, base, port, open_browser):
    """Records each start, beats once, then hangs: the guard must stop it (and restart it when allowed)."""
    connection.recv()
    with open(base / "runs.txt", "a", encoding="utf-8") as stream:
        stream.write("run\n")
    connection.send({"type": "heartbeat", "action_started": None})
    time.sleep(60)


def stop_request_child(connection, base, port, open_browser):
    connection.recv()
    with open(base / "runs.txt", "a", encoding="utf-8") as stream:
        stream.write("run\n")
    (base / "data/guard.stop").touch()
    time.sleep(60)


class FakePipe:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append((time.monotonic(), message))


class PauseMarkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.control = ActionControl(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_marker_records_who_paused_and_why(self):
        self.assertEqual(self.control.info(), {})
        self.control.pause("guard", "heartbeat_timeout")
        info = self.control.info()
        self.assertEqual((info["source"], info["reason"]), ("guard", "heartbeat_timeout"))
        self.assertIsInstance(info["at"], float)

    def test_guard_and_startup_pauses_heal_but_the_owners_never_does(self):
        for source in ("guard", "startup"):
            self.control.pause(source, "x")
            self.assertEqual(self.control.heal()["source"], source)
            self.assertFalse(self.control.paused)
        self.control.pause()                       # the owner (dashboard button, tray, "pause chutku")
        self.assertIsNone(self.control.heal())
        self.assertTrue(self.control.paused)

    def test_old_text_marker_is_unknown_and_never_heals(self):
        (self.base / "data").mkdir(exist_ok=True)
        self.control.marker.write_text("Actions paused by the user. Resume explicitly.\n", encoding="utf-8")
        self.assertEqual(self.control.info()["source"], "unknown")
        self.assertIsNone(self.control.heal())
        self.assertTrue(self.control.paused)

    def test_owner_pause_wins_over_a_guard_pause_and_is_not_overwritten_back(self):
        self.control.pause("guard", "heartbeat_timeout")
        self.control.pause("owner", "asked")        # now only the owner can lift it
        self.assertEqual(self.control.info()["source"], "owner")
        self.control.pause("guard", "action_deadline")
        self.assertEqual(self.control.info()["source"], "owner")
        self.assertIsNone(self.control.heal())

    def test_emergency_stop_is_the_owners(self):
        self.control.stop()
        self.assertEqual(self.control.info(), self.control.info() | {"source": "owner", "reason": "emergency_stop"})
        self.assertIsNone(self.control.heal())

    def test_explanations_name_the_real_cause(self):
        self.control.pause("owner", "asked")
        self.assertIn("You paused me", paused_explanation(self.base))
        self.assertIn("Aapne mujhe pause", paused_spoken(self.base))
        self.control.resume()
        self.control.pause("guard", "heartbeat_timeout")
        (self.base / "data" / "guard-last-stop.json").write_text(json.dumps(
            {"timestamp_utc": "2026-10-28T01:28:53+00:00", "reason": "heartbeat_timeout"}), encoding="utf-8")
        self.assertIn("resume by myself", paused_explanation(self.base))
        self.assertIn("atak gayi", paused_spoken(self.base))

    def test_resume_phrases(self):
        for said in ("resume", "Resume actions please", "chalu ho jao", "wapas chalu karo bhai", "unpause"):
            self.assertEqual(kind(said), "resume", said)
        for said in ("fan chalu karo", "spotify chalu karo", "resume my download", "resume the video"):
            self.assertNotEqual(kind(said), "resume", said)


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object integration")
class GuardRestartTests(unittest.TestCase):
    def test_a_hung_core_is_restarted_then_the_guard_gives_up(self):
        from chutku.guard import supervise
        with TemporaryDirectory() as temp:
            base = Path(temp)
            result = supervise(base, child_target=counting_hung_child, heartbeat_timeout=0.4, hotkey=False,
                               restarts=1, restart_delay=0)
            self.assertEqual(result["reason"], "heartbeat_timeout")
            self.assertEqual((base / "runs.txt").read_text().count("run"), 2)   # first core + one restart
            self.assertEqual(ActionControl(base).info()["source"], "guard")       # heals in the next healthy core

    def test_the_owners_emergency_stop_is_never_restarted(self):
        from chutku.guard import supervise
        with TemporaryDirectory() as temp:
            base = Path(temp)
            result = supervise(base, child_target=stop_request_child, hotkey=False, restarts=3, restart_delay=0)
            self.assertEqual(result["reason"], "emergency_stop")
            self.assertEqual((base / "runs.txt").read_text().count("run"), 1)
            self.assertEqual(ActionControl(base).info()["source"], "owner")
            self.assertIsNone(ActionControl(base).heal())


class CoreHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.pipe = FakePipe()
        self.server = DashboardServer(self.base, port=0, heartbeat=self.pipe)

    def tearDown(self):
        self.server.server_close()
        self.temp.cleanup()

    def test_heartbeat_comes_from_its_own_thread_and_stops_on_a_real_stall(self):
        self.server.LOOP_STALL, self.server.HANG_DUMP_AFTER = 0.6, 0.3
        thread = self.server.start_heartbeat(interval=0.05)
        time.sleep(0.25)
        self.assertGreaterEqual(len(self.pipe.sent), 3)   # beats although the HTTP loop is not even running
        time.sleep(0.9)                                    # the loop has now been "stuck" past LOOP_STALL
        count = len(self.pipe.sent)
        time.sleep(0.3)
        self.assertEqual(len(self.pipe.sent), count)       # silent: the guard will see the hang
        dumps = list((self.base / "data" / "logs").glob("hang-*.txt"))
        self.assertEqual(len(dumps), 1)
        self.assertIn("chutku-heartbeat", dumps[0].read_text(encoding="utf-8"))
        self.server.service_actions()                      # the loop moves again
        time.sleep(0.2)
        self.assertGreater(len(self.pipe.sent), count)
        self.server.closing.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_windows_sleep_is_not_a_hang(self):
        """2026-11-09: a 2898.9 s 'hang' was the laptop asleep; time.monotonic counts sleep, so the core was restarted."""
        from unittest.mock import patch
        from chutku import dashboard
        clock = {"awake": 100.0}
        with patch.object(dashboard, "awake_clock", side_effect=lambda: clock["awake"]):
            self.server.service_actions()
            thread = self.server.start_heartbeat(interval=0.05)
            time.sleep(0.3)                                     # wall time passes, awake time does not (asleep)
            self.assertEqual(list((self.base / "data" / "logs").glob("hang-*.txt")), [])
            clock["awake"] += 9.0                               # awake and the loop really did not move: a hang
            time.sleep(0.2)
            self.assertEqual(len(list((self.base / "data" / "logs").glob("hang-*.txt"))), 1)
            self.server.closing.set()
            thread.join(2)
        self.assertGreater(dashboard.awake_clock(), 0)          # the real clock works on this machine

    def test_restarted_core_lifts_the_guards_pause_but_not_the_owners(self):
        ActionControl(self.base).pause("guard", "heartbeat_timeout")
        self.server.heal_when_healthy(healthy_for=0.1).join(5)
        self.assertFalse(ActionControl(self.base).paused)
        self.assertEqual(self.server.healed["reason"], "heartbeat_timeout")
        self.assertIn("restart", self.server.hud_state["message"])
        ActionControl(self.base).pause()
        self.server.healed = None
        self.server.heal_when_healthy(healthy_for=0.1).join(5)
        self.assertTrue(ActionControl(self.base).paused)
        self.assertIsNone(self.server.healed)

    def test_no_healing_without_the_guard(self):
        server = DashboardServer(self.base, port=0)
        try:
            ActionControl(self.base).pause("guard", "heartbeat_timeout")
            self.assertIsNone(server.heal_when_healthy(healthy_for=0.01))
            self.assertTrue(ActionControl(self.base).paused)
        finally:
            server.server_close()


class PausedVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.server = DashboardServer(self.base, port=0)
        self.said = []
        self.heard = ""
        self.server._say = self.said.append
        self.server._listen_paused = lambda: self.heard
        self.started = []
        self.server.begin_session = lambda *a, **k: self.started.append(a)
        ActionControl(self.base).pause("owner", "asked")

    def tearDown(self):
        self.server.server_close()
        self.temp.cleanup()

    def test_hotkey_then_resume_lifts_the_pause_out_loud(self):
        self.heard = "resume"
        self.server.handsfree_request()
        self.assertFalse(ActionControl(self.base).paused)
        self.assertIn("Aapne mujhe pause", self.said[0])
        self.assertIn("Chalu ho gayi", self.said[-1])
        self.assertEqual(self.started, [])

    def test_hotkey_then_anything_else_keeps_the_pause_and_runs_nothing(self):
        self.heard = "notepad kholo"
        self.server.handsfree_request()
        self.assertTrue(ActionControl(self.base).paused)
        self.assertEqual(self.started, [])
        self.assertEqual(len(self.said), 1)              # only the explanation

    def test_a_wake_phrase_only_hears_why(self):
        self.server.handsfree_request("resume", source="wake")
        self.assertTrue(ActionControl(self.base).paused)
        self.assertIn("Ctrl+Alt+Space", self.said[0])
        self.assertEqual(self.started, [])

    def test_resume_by_voice_session_is_refused_but_typed_resume_works(self):
        server = DashboardServer(self.base, port=0)
        try:
            session = server.begin_session("resume", "owner", "voice")
            self.assertTrue(ActionControl(self.base).paused)
            self.assertIn("Ctrl+Alt+Space", session.snapshot()["reply"])
            session = server.begin_session("resume", "owner", "text")
            self.assertFalse(ActionControl(self.base).paused)
            self.assertIn("Chalu ho gayi", session.snapshot()["reply"])
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()


def quit_request_child(connection, base, port, open_browser):
    connection.recv()
    (base / "data/guard.stop").write_text("quit", encoding="utf-8")
    time.sleep(60)


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object integration")
class TaskbarQuitTests(unittest.TestCase):
    def test_closing_from_the_taskbar_ends_everything_without_a_pause(self):
        from chutku.guard import supervise
        with TemporaryDirectory() as temp:
            base = Path(temp)
            result = supervise(base, child_target=quit_request_child, hotkey=False, restarts=3, restart_delay=0)
            self.assertEqual(result["reason"], "owner_quit")
            self.assertTrue(result["core_stopped"])
            self.assertFalse(ActionControl(base).paused)          # the next start is not paused
            self.assertFalse((base / "data/guard.running").exists())
