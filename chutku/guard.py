"""Independent Windows supervisor for the dashboard and owned subprocesses.

The child waits for assignment to a kill-on-close Job Object before starting.
The guard watches heartbeats and bounded action duration. After a watchdog stop it
starts a fresh core (a few times per half hour) but never replays work. Existing/broker-launched desktop apps are not owned.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as w
from datetime import UTC, datetime
import json
import multiprocessing as mp
from pathlib import Path
import sys
import time

from chutku.app import PROJECT_ROOT
from chutku.core.action_control import ActionControl


class WindowsJob:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("The independent guard requires Windows.")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("active", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        for name, args, result in (
            ("CreateJobObjectW", [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            ("SetInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
            ("OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ("CloseHandle", [w.HANDLE], w.BOOL),
        ):
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        # KILL_ON_JOB_CLOSE ends Chutku's own processes on a stop; BREAKAWAY_OK lets the owner's apps (browser,
        # VS Code, a built app) be started outside the job (chutku/core/launch.py) so they survive it.
        info.basic.flags = 0x2000 | 0x0800  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, pid):
        process = self.kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class StopHotkey:
    """Owns Ctrl+Alt+F12 in the supervisor, independently of the core."""
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
        self.user.RegisterHotKey.restype = w.BOOL
        self.user.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        self.user.PeekMessageW.restype = w.BOOL
        self.user.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
        self.active = bool(self.user.RegisterHotKey(None, 1, 0x4003, 0x7B))

    def pressed(self):
        message = w.MSG()
        return bool(self.user.PeekMessageW(ctypes.byref(message), None, 0x312, 0x312, 1))

    def close(self):
        if self.active:
            self.user.UnregisterHotKey(None, 1)


def dashboard_child(connection, base, port, open_browser):
    try:
        if connection.recv() != "start":
            return
        from chutku.dashboard import serve
        try:
            serve(port, open_browser, base=base, heartbeat=connection)
        except BaseException:
            # 2026-11-01: the core once died at start-up with no trace (no orb, no tray). Never silently again.
            import traceback
            crash = Path(base) / "data" / "logs" / "core-crash.txt"
            try:
                crash.parent.mkdir(parents=True, exist_ok=True)
                crash.write_text(datetime.now().isoformat() + "\n" + traceback.format_exc(), encoding="utf-8")
                from chutku.health import notify
                notify("Chutku could not start", "Details: data\\logs\\core-crash.txt", wait=True)
            except Exception:
                pass
            raise
    finally:
        connection.close()


# A watchdog stop (hang, crash, slow start) used to end the guard: Chutku stayed off and paused until the next
# logon, which is how she sat dead from 2026-10-26 to 10-29. Now the guard starts a fresh core, at most
# `restarts` times in RESTART_WINDOW seconds; the owner's emergency stop still ends everything.
WATCHDOG_REASONS = frozenset({"heartbeat_timeout", "startup_timeout", "action_deadline", "core_exited",
                              "core_disconnected"})
RESTART_WINDOW = 1800.0
STARTUP_GRACE = 60.0   # 2026-11-11: the first core of the day was killed 15 s in while loading models offline


def supervise(base=PROJECT_ROOT, port=8765, open_browser=False, *, restarts=0, restart_delay=3.0, **options):
    from chutku.core.execution_lock import ExecutionLock
    with ExecutionLock(Path(base) / "data/guard.lock"):
        recent = []
        while True:
            report = _supervise(base, port, open_browser, **options)
            now = time.monotonic()
            recent = [at for at in recent if now - at < RESTART_WINDOW]
            if report.get("reason") not in WATCHDOG_REASONS or len(recent) >= restarts:
                return report
            recent.append(now)
            open_browser = False
            print(f"Restarting Chutku's core after {report['reason']} ({len(recent)} of {restarts}).", flush=True)
            time.sleep(restart_delay)


def _marker_says_quit(marker):
    try:
        return marker.read_text(encoding="utf-8").strip() == "quit"
    except OSError:
        return False


def _boot_time():
    """When Windows booted (seconds since the epoch, to within a minute)."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return round(time.time() - kernel32.GetTickCount64() / 1000)


def _same_boot(marker):
    try:
        recorded = int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True  # unreadable or old-format marker: be safe
    return abs(recorded - _boot_time()) <= 120


def _supervise(base=PROJECT_ROOT, port=8765, open_browser=False, *, child_target=dashboard_child,
              heartbeat_timeout=5.0, action_timeout=120.0, startup_timeout=20.0, hotkey=True,
              clock=time.monotonic, suspend_gap=2.0, resume_grace=20.0, startup_grace=0.0):
    base = Path(base)
    directory = base / "data"
    directory.mkdir(parents=True, exist_ok=True)
    stop_marker = directory / "guard.stop"
    running_marker = directory / "guard.running"
    if running_marker.exists() and _same_boot(running_marker):
        # Chutku stopped uncleanly during this Windows session: pause until the restarted core is healthy.
        # A marker left by a previous boot just means Windows shut down with Chutku running.
        ActionControl(base).pause("startup", "unclean_stop")
    running_marker.write_text(str(_boot_time()), encoding="utf-8")
    # A previous stop remains a persistent pause. Clear only the consumed signal.
    stop_marker.unlink(missing_ok=True)
    context = mp.get_context("spawn")
    parent, child_pipe = context.Pipe()
    child = context.Process(target=child_target, args=(child_pipe, base, port, open_browser))
    job = WindowsJob()
    keyboard = None
    reason = "startup_failure"
    started = last_beat = previous = clock()
    ready = False
    # Windows sleep/hibernate freezes every process but the monotonic clock keeps counting. A loop gap far
    # longer than its 50 ms poll means the whole system was suspended, not that the core hung: restart the
    # heartbeat timer with a wake-up grace, and keep slept time out of action deadlines.
    suspensions, grace_until = [], None
    try:
        keyboard = StopHotkey() if hotkey else None
        child.start()
        child_pipe.close()
        job.assign(child.pid)
        parent.send("start")
        print("Independent guard active. Ctrl+Alt+F12 stops Chutku." if keyboard and keyboard.active
              else "Independent guard active. Hotkey unavailable; use Stop-Chutku.cmd.", flush=True)
        while True:
            now = clock()
            if stop_marker.exists() or (keyboard and keyboard.pressed()):
                # "quit" (the owner closed Chutku from the taskbar, 2026-10-31): a clean shutdown, not a pause
                reason = "owner_quit" if _marker_says_quit(stop_marker) else "emergency_stop"
                break
            if now - previous > suspend_gap:
                suspensions.append((now, now - previous))
                last_beat, grace_until = now, now + resume_grace
            previous = now
            if not child.is_alive():
                reason = "core_exited"
                break
            if parent.poll(0.05):
                try:
                    message = parent.recv()
                except EOFError:
                    reason = "core_disconnected"
                    break
                if isinstance(message, dict) and message.get("type") == "heartbeat":
                    ready = True
                    last_beat = now
                    action_started = message.get("action_started")
                    slept = sum(gap for at, gap in suspensions if action_started is not None and at > action_started)
                    if action_started is not None and now - action_started - slept > action_timeout:
                        reason = "action_deadline"
                        break
            # A core still starting up (models loading from a cold disk, 2026-11-11) gets the start-up limit for
            # `startup_grace` seconds even after its first heartbeat; a real hang is still caught at that limit.
            limit = heartbeat_timeout if ready and now - started >= startup_grace else startup_timeout
            if grace_until is not None and now < grace_until:
                limit = max(limit, resume_grace)
            if now - last_beat > limit:
                reason = "heartbeat_timeout" if ready else "startup_timeout"
                break
    except KeyboardInterrupt:
        reason = "emergency_stop"
    finally:
        # Pause before killing. It survives restart; only a watchdog pause is lifted, by a restarted core that
        # stayed healthy, and the interrupted task itself is never run again.
        try:
            if reason != "owner_quit":
                ActionControl(base).pause("owner" if reason == "emergency_stop" else "guard", reason)
        finally:
            job.close()
            if child.pid is not None:
                child.join(5)
                if child.is_alive():
                    child.kill()
                    child.join(5)
            parent.close()
            child_pipe.close()
            if keyboard:
                keyboard.close()
        report = {"timestamp_utc": datetime.now(UTC).isoformat(), "reason": reason,
                  "core_pid": child.pid, "core_stopped": child.pid is None or not child.is_alive(),
                  "elapsed_seconds": round(time.monotonic() - started, 3), "actions_paused": True}
        from chutku.core.execution_lock import ExecutionLock, ExecutionBusy
        from chutku.core.event_log import EventLog
        try:
            with ExecutionLock(directory / "execution.lock"):
                log = EventLog(directory / "chutku.db")
                try:
                    report["interrupted_tasks"] = log.mark_interrupted()
                finally:
                    log.close()
        except (OSError, ExecutionBusy):
            report["audit_reconciliation"] = "Deferred: another runtime owns the execution lock or storage is unavailable."
        (directory / "guard-last-stop.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        running_marker.unlink(missing_ok=True)
        print("Guard stopped Chutku: " + reason + ". Inspect activity before explicitly resuming.", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description="Independent Chutku dashboard guard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    supervise(port=args.port, open_browser=args.open, restarts=3, startup_grace=STARTUP_GRACE)


if __name__ == "__main__":
    main()
