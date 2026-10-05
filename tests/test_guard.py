"""Real Windows fault injection: these tests spawn and kill owned processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from chutku.guard import supervise


def hung_child(connection, base, port, open_browser):
    connection.recv()
    from chutku.core.event_log import EventLog
    log = EventLog(base / "data/chutku.db")
    log.append("fault-task", "task_received", {"tool": "fixture.hang", "arguments": {}})
    log.append("fault-task", "task_state", {"from": "RECEIVED", "to": "EXECUTING"})
    log.close()
    descendant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (base / "descendant.json").write_text(json.dumps({"pid": descendant.pid, "core_pid": os.getpid()}))
    connection.send({"type": "heartbeat", "action_started": None})
    time.sleep(60)


def stuck_action(connection, base, port, open_browser):
    connection.recv()
    started = time.monotonic()
    while True:
        connection.send({"type": "heartbeat", "action_started": started})
        time.sleep(0.05)


def request_stop(connection, base, port, open_browser):
    connection.recv()
    (base / "data/guard.stop").touch()
    time.sleep(60)


def beating_through_an_action(connection, base, port, open_browser):
    """A healthy core mid-action: heartbeats every 50 ms for 3 s, then asks for a stop."""
    connection.recv()
    started = time.monotonic()
    while time.monotonic() - started < 3:
        connection.send({"type": "heartbeat", "action_started": started})
        time.sleep(0.05)
    (base / "data/guard.stop").touch()
    time.sleep(60)


class SleepingClock:
    """time.monotonic, but the whole PC 'sleeps' for an hour once, `after` seconds in."""
    def __init__(self, after, jump=3600.0):
        self.start, self.after, self.jump = time.monotonic(), after, jump

    def __call__(self):
        now = time.monotonic()
        return now + (self.jump if now - self.start > self.after else 0.0)


def process_exited(pid):
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return True
    try:
        return kernel.WaitForSingleObject(handle, 3000) == 0
    finally:
        kernel.CloseHandle(handle)


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object integration")
class GuardTests(unittest.TestCase):
    def test_guard_crash_closes_job_and_kills_owned_tree(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            command = ("import sys; from pathlib import Path; sys.path.insert(0, " + repr(str(Path(__file__).parent)) + "); "
                       "from test_guard import hung_child; from chutku.guard import supervise; "
                       "supervise(Path(" + repr(temp) + "), child_target=hung_child, heartbeat_timeout=30, hotkey=False)")
            parent = subprocess.Popen([sys.executable, "-c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + 15
                while not (base / "descendant.json").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue((base / "descendant.json").exists())
                identities = json.loads((base / "descendant.json").read_text())
                parent.kill()
                parent.wait(5)
                self.assertTrue(process_exited(identities["core_pid"]))
                self.assertTrue(process_exited(identities["pid"]))
                self.assertTrue((base / "data/guard.running").exists())
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(5)

    def test_hung_core_and_descendant_are_killed_and_pause_persists(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            result = supervise(base, child_target=hung_child, heartbeat_timeout=0.4, hotkey=False)
            self.assertEqual(result["reason"], "heartbeat_timeout")
            self.assertTrue(result["core_stopped"])
            pid = json.loads((base / "descendant.json").read_text())["pid"]
            self.assertTrue(process_exited(pid))
            self.assertTrue((base / "data/actions.paused").exists())
            self.assertEqual(result["interrupted_tasks"], 1)
            self.assertEqual(json.loads((base / "data/guard-last-stop.json").read_text())["reason"], "heartbeat_timeout")

    def test_heartbeat_cannot_hide_a_stuck_action(self):
        with TemporaryDirectory() as temp:
            result = supervise(Path(temp), child_target=stuck_action, action_timeout=0.4, hotkey=False)
            self.assertEqual(result["reason"], "action_deadline")
            self.assertTrue(result["core_stopped"])

    def test_windows_sleep_is_not_mistaken_for_a_hang(self):
        with TemporaryDirectory() as temp:
            result = supervise(Path(temp), child_target=beating_through_an_action, heartbeat_timeout=0.5,
                               action_timeout=10, hotkey=False, clock=SleepingClock(after=1.0))
            self.assertEqual(result["reason"], "emergency_stop")  # the core's own stop request, not a timeout

    def test_a_real_hang_after_waking_is_still_caught(self):
        with TemporaryDirectory() as temp:
            result = supervise(Path(temp), child_target=hung_child, heartbeat_timeout=0.4, resume_grace=1.0,
                               hotkey=False, clock=SleepingClock(after=1.5))
            self.assertEqual(result["reason"], "heartbeat_timeout")
            self.assertTrue(result["core_stopped"])

    def test_external_stop_does_not_need_core_cooperation(self):
        with TemporaryDirectory() as temp:
            result = supervise(Path(temp), child_target=request_stop, hotkey=False)
            self.assertEqual(result["reason"], "emergency_stop")
            self.assertTrue(result["core_stopped"])

    def test_unclean_guard_restart_pauses_before_child_work(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data").mkdir()
            (base / "data/guard.running").touch()
            result = supervise(base, child_target=request_stop, hotkey=False)
            self.assertTrue((base / "data/actions.paused").exists())
            self.assertFalse((base / "data/guard.running").exists())
            self.assertTrue(result["core_stopped"])

    def test_only_a_marker_from_this_windows_boot_counts_as_a_crash(self):
        from chutku.guard import _boot_time, _same_boot
        with TemporaryDirectory() as temp:
            marker = Path(temp) / "guard.running"
            marker.write_text(str(_boot_time() - 86400), encoding="utf-8")  # Windows shut down yesterday
            self.assertFalse(_same_boot(marker))
            marker.write_text(str(_boot_time()), encoding="utf-8")  # killed during this session
            self.assertTrue(_same_boot(marker))
            marker.write_text("", encoding="utf-8")  # old-format marker: stay safe
            self.assertTrue(_same_boot(marker))

if __name__ == "__main__":
    unittest.main()
